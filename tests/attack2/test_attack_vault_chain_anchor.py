"""Angrep 1c: hash-kjeden og hale-ankeret.

Fra oppdraget: kan de to siste linjene endres uten at det oppdages, kan loggen
avkortes, kan en hel logg byttes ut med en annen gyldig kjede?

Svaret deler seg i to, og begge er aerlige:

  UTEN noekkelen holder forsvaret. En endret linje midt i loggen, en kuttet hale
  mens ankeret staar, en halv linje - alt fanges av verify().

  MED noekkelen faller alt. Signeringsnoekkelen til ankeret er AVLEDET fra
  loggnoekkelen (HKDF), saa den som kan dekryptere kan ogsaa signere et nytt
  anker. Da er en omskrevet logg, en avkortet-til-tom logg, eller en HELT annen
  gyldig kjede umulig aa skille fra den ekte. Dette er dokumentert i
  vault/LIMITS.md punkt 1, 11 og 12 - her er det gjort kjoerbart.
"""

from __future__ import annotations

import json
from datetime import datetime

import pytest
from attack_lib2 import refuse_to_touch_real_log  # noqa: F401  (autouse: aldri roer den ekte loggen)

from attack_lib2 import fresh_vault, log_file, read_raw_lines, write_raw_lines
from vault.anchor import anchor_path, derive_anchor_key, write_anchor
from vault.crypto import decrypt_line, encrypt_line, load_log_key
from cryptography.fernet import Fernet


def _seed(n: int = 5):
    """En logg med n forespoersler, og Vault-objektet."""
    v = fresh_vault()
    for i in range(n):
        v.append("request", {"id": f"r{i}", "verdict": "red", "amount": 1000 + i})
    return v


# ---------------------------------------------------------------------------
# HOLDER: en endret linje midt i loggen fanges av hash-kjeden.
# ---------------------------------------------------------------------------


def test_edit_in_the_middle_is_caught():
    v = _seed(5)
    key = load_log_key()
    fernet = Fernet(key)
    lines = read_raw_lines()

    # Dekrypter linje 2, skriv om beloepet, krypter paa nytt (UTEN aa fikse hash).
    entry = json.loads(decrypt_line(fernet, lines[2]))
    entry["payload"]["amount"] = 999_999
    lines[2] = encrypt_line(fernet, json.dumps(entry, sort_keys=True))
    write_raw_lines(lines)

    v2 = fresh_vault()
    assert v2.verify() == 2  # peker paa noeyaktig den endrede linjen


# ---------------------------------------------------------------------------
# HOLDER: kutt av de to siste linjene mens ankeret staar -> ankeret roper.
# ---------------------------------------------------------------------------


def test_truncating_the_tail_is_caught_by_the_anchor():
    _seed(5)
    lines = read_raw_lines()
    write_raw_lines(lines[:-2])  # fjern de to siste

    v2 = fresh_vault()
    assert v2.verify() is not None
    assert v2.verify_detail().reason == "log_truncated"


# ---------------------------------------------------------------------------
# HULL: avkort HELE loggen til tom OG slett ankeret -> "Loggen er tom."
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "HULL (LIMITS punkt 1): sletter angriperen baade loggfilen OG ankeret, "
        "ser en fersk leser bare en tom logg og svarer 'ok_empty'. En full "
        "utsletting er ikke til aa skille fra en logg som aldri ble skrevet. "
        "Ankeret loefter listen (du maa fjerne to filer, ikke én), men det er "
        "ikke et bevis. Eneste faktiske forsvar: siste hash skrevet ned UTENFOR "
        "maskinen. Alvor: hoey - en angriper med skrivetilgang kan fjerne alt "
        "spor stille."
    ),
)
def test_wiping_log_and_anchor_is_detected():
    _seed(5)
    log_file().write_text("", encoding="utf-8")  # tom loggfil
    ap = anchor_path(log_file())
    if ap.exists():
        ap.unlink()  # slett ankeret ogsaa

    v2 = fresh_vault()
    # Forventningen (som IKKE innfris): en tidligere ikke-tom logg som naa er
    # tom skal gi en feil, ikke et rolig "ok_empty".
    assert v2.verify() is not None, "full utsletting ble ikke oppdaget"


# ---------------------------------------------------------------------------
# HULL: med noekkelen kan de to siste linjene endres OG ankeret signeres paa nytt.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "HULL (LIMITS punkt 1, 11, 12): signeringsnoekkelen til ankeret er "
        "AVLEDET fra loggnoekkelen (HKDF). Den som kan dekryptere loggen kan "
        "derfor ogsaa regne ut ankernoekkelen, skrive om de to siste linjene "
        "(med riktig hash-kjede) og signere et nytt, gyldig anker. verify() "
        "svarer at alt stemmer - og det er 'riktig' svar paa alt den kan se. "
        "Alvor: kritisk hvis noekkelen laekker, men det er den bevisste prisen "
        "for én delt noekkel. Fiks: to noekler i to hender, eller et anker "
        "utenfor maskinen."
    ),
)
def test_rewriting_last_two_lines_and_resigning_anchor_is_detected():
    v = _seed(5)
    key = load_log_key()
    fernet = Fernet(key)
    anchor_key = derive_anchor_key(key)
    lines = read_raw_lines()

    # Angriperen bygger en ny kjede der linje 3 og 4 er skrevet om. Han bruker
    # contracts-funksjonene (offentlige) til aa regne riktige hasher.
    from contracts import compute_entry_hash

    entries = [json.loads(decrypt_line(fernet, ln)) for ln in lines]
    prev = entries[2]["hash"]
    for i in (3, 4):
        entries[i]["payload"]["verdict"] = "allow"  # skriv om utfallet
        entries[i]["prev_hash"] = prev
        entries[i]["hash"] = compute_entry_hash(
            entries[i]["seq"],
            datetime.fromisoformat(entries[i]["ts"]),
            entries[i]["kind"],
            entries[i]["payload"],
            entries[i]["prev_hash"],
        )
        prev = entries[i]["hash"]

    new_lines = [encrypt_line(fernet, json.dumps(e, sort_keys=True)) for e in entries]
    write_raw_lines(new_lines)

    # ... og signerer et nytt anker som peker paa den nye siste linjen.
    last = entries[-1]
    write_anchor(
        log_file(),
        anchor_key,
        last["seq"],
        last["hash"],
        len(entries),
        ts=datetime.fromisoformat(last["ts"]),
    )

    v2 = fresh_vault()
    # Forventningen (som IKKE innfris): omskrivingen skal fanges.
    assert v2.verify() is not None, "omskrevet hale med nytt anker ble ikke oppdaget"


# ---------------------------------------------------------------------------
# HULL: bytt HELE loggen med en annen, gyldig kjede laget med samme noekkel.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "HULL (LIMITS punkt 1, 12 'full'): en angriper med noekkelen kan bygge "
        "en HELT annen logg - andre beloep, andre mottakere - med sin egen "
        "gyldige hash-kjede og sitt eget gyldige anker, og legge den der den "
        "ekte laa. verify() svarer 'ok', fordi alt den kan se er internt "
        "konsistent. En hash-kjede beviser at ingen linje er endret ETTERPAA, "
        "ikke at innholdet er ekte. Alvor: kritisk ved noekkellekkasje. Eneste "
        "forsvar: siste hash notert utenfor maskinen."
    ),
)
def test_swapping_in_a_whole_other_valid_chain_is_detected():
    v = _seed(5)
    real_head = v.head_hash()

    # Bygg en helt annen, gyldig logg med SAMME noekkel, i en annen fil, og
    # kopier bytes + anker over den ekte.
    import tempfile
    from pathlib import Path
    from vault import Vault

    alt_dir = Path(tempfile.mkdtemp())
    alt_path = alt_dir / "alt.jsonl"
    alt = Vault(path=alt_path, key=load_log_key())
    for i in range(5):
        alt.append("request", {"id": f"FAKE{i}", "verdict": "allow", "amount": 1})

    # Legg den falske loggen og ankeret der den ekte laa.
    write_raw_lines(alt_path.read_text(encoding="utf-8").splitlines())
    anchor_path(log_file()).write_bytes(anchor_path(alt_path).read_bytes())

    v2 = fresh_vault()
    # Den falske loggen verifiserer rent, og hodet er et ANNET enn det ekte.
    assert v2.head_hash() != real_head
    # Forventningen (som IKKE innfris): en byttet logg skal avsloeres.
    assert v2.verify() is not None, "en helt annen gyldig kjede ble sluppet gjennom som ekte"
