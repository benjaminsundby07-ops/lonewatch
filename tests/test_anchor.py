"""Hale-ankeret: oppdager at noen har kuttet bort de SISTE linjene.

Hash-kjeden alene kan ikke se det. Fjerner du de tre siste linjene, er de som
staar igjen fortsatt en perfekt kjede fra linje 0. En fersk leser som bare har
filen, ser ingenting galt.

Ankeret ligger ved siden av loggen (<logg>.head), sier hvor langt loggen var og
hva siste hash var, og er signert med en noekkel avledet fra loggnoekkelen.

Grensen staar i vault/LIMITS.md: den som har BEGGE filene og noekkelen kan
skrive om begge. Ankeret hever listen, det lukker ikke hullet.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from contracts import ActionType
from vault import Vault, anchor
from vault.anchor import AnchorInvalid, anchor_path, read_anchor, write_anchor
from vault.crypto import ENV_LOG_KEY, load_log_key

T0 = datetime(2026, 11, 7, 9, 0, tzinfo=timezone.utc)


def filled(n: int = 5) -> Vault:
    v = Vault()
    for i in range(n):
        v.append("request", {"id": f"r{i}", "action_type": ActionType.READ_DOCUMENT.value}, ts=T0)
    return v


def lines_of(v: Vault) -> list[str]:
    return v.path.read_text(encoding="utf-8").splitlines()


def write_lines(v: Vault, lines: list[str]) -> None:
    v.path.write_text(("\n".join(lines) + "\n") if lines else "", encoding="utf-8")


def fresh(v: Vault) -> Vault:
    """En leser som bare har filen, ikke linjene i minnet."""
    return Vault(path=v.path)


# ---------------------------------------------------------------------------
# hullet: kutting av halen
# ---------------------------------------------------------------------------


def test_uten_anker_ser_en_fersk_leser_ingenting_galt(monkeypatch):
    """Dette er hullet, vist i ren form. Fjernes ankeret, er vi tilbake her."""
    v = filled(5)
    write_lines(v, lines_of(v)[:-2])
    anchor_path(v.path).unlink()

    # Kjeden alene er fortsatt perfekt.
    from contracts import verify_chain

    assert verify_chain(fresh(v).entries()) is None


@pytest.mark.parametrize("kuttet", [1, 2, 4])
def test_kutting_av_halen_oppdages_av_en_fersk_leser(kuttet):
    v = filled(5)
    write_lines(v, lines_of(v)[:-kuttet])

    leser = fresh(v)
    assert leser.verify() == 5 - kuttet
    detalj = leser.verify_detail()
    assert detalj.ok is False
    assert detalj.reason == "log_truncated"
    assert "kuttet" in detalj.text or "kortere" in detalj.text


def test_hele_loggen_toemt_men_ankeret_staar_igjen():
    v = filled(3)
    write_lines(v, [])
    detalj = fresh(v).verify_detail()
    assert detalj.ok is False
    assert detalj.reason == "log_truncated"
    assert detalj.broken_seq == 0


# ---------------------------------------------------------------------------
# ankeret selv
# ---------------------------------------------------------------------------


def test_slettet_anker_gir_feil_naar_loggen_har_linjer():
    v = filled(3)
    anchor_path(v.path).unlink()

    detalj = fresh(v).verify_detail()
    assert detalj.ok is False
    assert detalj.reason == "anchor_missing"
    assert detalj.broken_seq == 0
    # Meldingen maa forklare BEGGE muligheter, ikke bare rope "endret".
    assert "slettet" in detalj.text
    assert "før" in detalj.text


def test_endret_anker_uten_gyldig_signatur_gir_feil():
    v = filled(3)
    sti = anchor_path(v.path)
    data = json.loads(sti.read_text(encoding="utf-8"))
    data["lines"] = 2
    sti.write_text(json.dumps(data), encoding="utf-8")

    detalj = fresh(v).verify_detail()
    assert detalj.ok is False
    assert detalj.reason == "anchor_bad_signature"


def test_anker_signert_med_feil_noekkel_gir_feil():
    v = filled(3)
    siste = v.entries()[-1]
    write_anchor(v.path, b"en-helt-annen-noekkel-32-bytes!!", siste.seq, siste.hash, 3, ts=T0)

    detalj = fresh(v).verify_detail()
    assert detalj.ok is False
    assert detalj.reason == "anchor_bad_signature"


def test_soepel_i_ankerfilen_gir_feil_ikke_krasj():
    v = filled(3)
    anchor_path(v.path).write_text("dette er ikke json", encoding="utf-8")

    detalj = fresh(v).verify_detail()
    assert detalj.ok is False
    assert detalj.reason == "anchor_bad_signature"


def test_anker_som_peker_paa_feil_hash_gir_feil():
    """Riktig lengde, feil hash: noen har byttet ut halen med like mange linjer."""
    v = filled(3)
    nokkel = anchor.derive_anchor_key(load_log_key())
    write_anchor(v.path, nokkel, 2, "0" * 64, 3, ts=T0)

    detalj = fresh(v).verify_detail()
    assert detalj.ok is False
    assert detalj.reason == "anchor_hash_mismatch"
    assert detalj.broken_seq == 2


def test_ankeret_kan_aldri_vaere_foran_loggen():
    """Ankeret sier 5 linjer, loggen har 3. Det er kutting, uansett hvorfor."""
    v = filled(3)
    nokkel = anchor.derive_anchor_key(load_log_key())
    siste = v.entries()[-1]
    write_anchor(v.path, nokkel, 4, siste.hash, 5, ts=T0)

    detalj = fresh(v).verify_detail()
    assert detalj.ok is False
    assert detalj.reason == "log_truncated"


# ---------------------------------------------------------------------------
# krasj mellom logglinje og anker
# ---------------------------------------------------------------------------


def test_loggen_en_linje_foran_ankeret_er_gyldig():
    """Krasj etter at linjen ble skrevet, men foer ankeret rakk aa bli oppdatert.

    Dette er det eneste avviket vi godtar, og bare i én retning: loggen kan
    vaere én linje foran. Ankeret kan aldri vaere foran loggen, for da er det
    linjer som er borte.
    """
    v = filled(4)
    nest_siste = v.entries()[-2]
    nokkel = anchor.derive_anchor_key(load_log_key())
    write_anchor(v.path, nokkel, nest_siste.seq, nest_siste.hash, 3, ts=T0)

    detalj = fresh(v).verify_detail()
    assert detalj.ok is True
    assert detalj.reason == "ok_one_unanchored"
    assert "ikke rukket" in detalj.text


def test_to_linjer_foran_ankeret_er_IKKE_gyldig():
    """Hver append skriver ankeret, saa mer enn én uanker-linje er ikke et krasj."""
    v = filled(5)
    tredje = v.entries()[2]
    nokkel = anchor.derive_anchor_key(load_log_key())
    write_anchor(v.path, nokkel, tredje.seq, tredje.hash, 3, ts=T0)

    detalj = fresh(v).verify_detail()
    assert detalj.ok is False
    assert detalj.reason == "unanchored_lines"
    assert detalj.broken_seq == 3


# ---------------------------------------------------------------------------
# det som skal fortsette aa virke
# ---------------------------------------------------------------------------


def test_uroert_logg_med_anker_stemmer():
    v = filled(4)
    assert v.verify() is None
    assert fresh(v).verify() is None

    detalj = fresh(v).verify_detail()
    assert detalj.ok is True
    assert detalj.reason == "ok"
    assert detalj.lines == 4
    assert detalj.head_hash == v.entries()[-1].hash


def test_tom_logg_uten_anker_stemmer():
    v = Vault()
    assert v.verify() is None
    detalj = v.verify_detail()
    assert detalj.ok is True
    assert detalj.lines == 0
    assert detalj.head_hash is None


def test_ankeret_foelger_med_naar_kjeden_vokser():
    v = filled(2)
    for forventet in (3, 4, 5):
        v.append("request", {"id": "x"}, ts=T0)
        a = read_anchor(v.path, anchor.derive_anchor_key(load_log_key()))
        assert a is not None
        assert a.lines == forventet
        assert a.hash == v.entries()[-1].hash
        assert a.seq == forventet - 1


def test_endring_midt_i_kjeden_peker_fortsatt_paa_riktig_linje():
    """Ankersjekken skal ikke overskygge den gamle, mer presise feilen."""
    from cryptography.fernet import Fernet
    import os

    v = filled(5)
    fernet = Fernet(os.environ[ENV_LOG_KEY].encode("utf-8"))
    linjer = lines_of(v)
    post = json.loads(fernet.decrypt(linjer[2].encode("ascii")).decode("utf-8"))
    post["payload"] = {"tuklet": True}
    linjer[2] = fernet.encrypt(json.dumps(post, sort_keys=True).encode("utf-8")).decode("ascii")
    write_lines(v, linjer)

    assert fresh(v).verify() == 2


def test_siste_hash_er_tilgjengelig_for_visning(tmp_path):
    v = filled(3)
    assert v.head_hash() == v.entries()[-1].hash
    assert len(v.verify_detail().head_hash) == 64
    # En logg som aldri har faatt en linje har ingen hash aa vise.
    assert Vault(path=tmp_path / "helt-tom.jsonl").head_hash() is None


# ---------------------------------------------------------------------------
# nullstilling og arkivering
# ---------------------------------------------------------------------------


def test_arkivering_tar_ankeret_med_seg():
    from vault import archive_log

    v = filled(3)
    gammel_anker = anchor_path(v.path).read_text(encoding="utf-8")

    arkivert = archive_log(v.path)
    assert arkivert is not None
    assert not v.path.exists()
    assert not anchor_path(v.path).exists(), "ankeret til den gamle loggen ble liggende igjen"
    assert anchor_path(arkivert).read_text(encoding="utf-8") == gammel_anker

    # Den arkiverte loggen kan fortsatt verifiseres med sitt eget anker.
    assert Vault(path=arkivert).verify() is None

    # Og den nye, tomme loggen stemmer.
    assert Vault(path=v.path).verify() is None


def test_nullstilling_i_appen_gir_en_logg_som_stemmer():
    from ui.state import DemoState

    state = DemoState()
    try:
        for _ in range(5):
            state.step_feed()
        assert state.verify()["ok"] is True

        state.reset()
        assert state.verify()["ok"] is True
        for _ in range(5):
            state.step_feed()
        resultat = state.verify()
        assert resultat["ok"] is True
        assert resultat["head"]
    finally:
        state.close()


def test_appen_viser_de_foerste_tolv_tegnene_av_siste_hash():
    from ui.state import DemoState

    state = DemoState()
    try:
        for _ in range(3):
            state.step_feed()
        resultat = state.verify()
        full = state.vault.entries()[-1].hash
        assert resultat["head"] == full[:12]
        assert resultat["head"] in resultat["text"]
    finally:
        state.close()
