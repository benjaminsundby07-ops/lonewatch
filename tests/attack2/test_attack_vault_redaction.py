"""Angrep 1d: roemmer persondata inn i loggen i klartekst?

Loggen er kryptert paa disk, saa "klartekst" betyr her: det en gransker med
noekkelen ser etter dekryptering. Demoen kjoerer med dataminimering paa
(Vault(redact=True)). Spoersmaalet er om minimeringen holder det den lover.

To ting er verdt aa holde fra hverandre:
  HOLDER: agentens frie tekst (summary) og den fulle mottakeren forsvinner naar
          minimeringen er paa, og en allow-avgjoerelse krympes til nesten
          ingenting.
  HULL / DELVIS (dokumentert i vault/LIMITS.md punkt 7): minimeringen maskerer
          BARE feltene `recipient` og `destinations`. Fellenes `what_happened`
          og sandkassens `notes` staar i klartekst, og mottakeren maskeres bare
          til de siste fire tegnene.
"""

from __future__ import annotations

import pytest

from vault.redaction import redact_payload


# ---------------------------------------------------------------------------
# HOLDER: summary og full mottaker fjernes naar minimeringen er paa.
# ---------------------------------------------------------------------------


def test_summary_is_dropped_from_a_request():
    out = redact_payload(
        "request",
        {
            "id": "r1",
            "agent_id": "a",
            "action_type": "send_email",
            "recipient": "kari.nordmann@example.com",
            "summary": "HEMMELIG: kundens fulle personnummer staar her",
        },
    )
    assert "summary" not in out
    # Mottakeren er maskert, ikke full.
    assert out["recipient"] != "kari.nordmann@example.com"
    assert "kari" not in out["recipient"]


def test_consequence_text_is_dropped_from_a_red_decision():
    out = redact_payload(
        "decision",
        {
            "request_id": "r1",
            "verdict": "red",
            "reasons": ["unknown_recipient"],
            "risk": "high",
            "consequence_text": "Overfoerer 112 500 kr til NO55 1122 3344 556.",
        },
    )
    assert "consequence_text" not in out
    assert "NO55" not in str(out)


def test_allow_decision_is_shrunk_to_almost_nothing():
    out = redact_payload(
        "decision",
        {
            "request_id": "r1",
            "verdict": "allow",
            "action_type": "transfer_money",
            "risk": "low",
            "recipient": "NO55 1122 3344 556",
            "consequence_text": "Overfoerer 1 000 kr til NO55 1122 3344 556.",
        },
    )
    assert "recipient" not in out
    assert "consequence_text" not in out
    assert "NO55" not in str(out)


# ---------------------------------------------------------------------------
# DELVIS (dokumentert): mottakeren maskeres bare til de siste fire tegnene.
# ---------------------------------------------------------------------------


def test_recipient_mask_still_shows_the_last_four_characters():
    """Siste fire tegn av kontonummeret staar igjen. Dokumentert, men det ER
    persondata i klartekst - sammen med beloep og tid peker det ofte paa én
    transaksjon (LIMITS punkt 7). Testen fester at dette er valget som er tatt."""
    out = redact_payload(
        "request", {"id": "r", "action_type": "transfer_money", "recipient": "NO93 8601 1117 947"}
    )
    assert out["recipient"].endswith(" 947")  # siste fire tegn laekker


# ---------------------------------------------------------------------------
# HULL (dokumentert LIMITS punkt 7): what_happened og notes maskeres ALDRI.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "HULL (LIMITS punkt 7): redact_payload() maskerer BARE feltene "
        "'recipient' og 'destinations'. En felle sin 'what_happened' er fri "
        "tekst og kan inneholde en e-postadresse eller et kontonummer fra den "
        "skjulte teksten i dokumentet - det staar da i klartekst i loggen. "
        "Demoens egne feller er ufarlige her (intent inneholder ingen adresse), "
        "men mekanismen beskytter ingenting. Alvor: lav i demoen, men det er en "
        "ekte lekkasjevei om feltet brukes slik det kan. Fiks: vask fri tekst, "
        "eller maskér kjente moenstre (e-post, IBAN) i alle felt."
    ),
)
def test_trap_what_happened_is_masked():
    out = redact_payload(
        "trap",
        {
            "ts": "t",
            "doc_id": "d",
            "agent_id": "a",
            "trap_id": "t1",
            "what_happened": "Agenten sendte kundelisten til arkiv-backup@nordlys-arkiv-eu.net.",
        },
    )
    # Forventningen (som IKKE innfris): adressen skal vaere maskert.
    assert "arkiv-backup@nordlys-arkiv-eu.net" not in str(out)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "HULL (LIMITS punkt 7): sandkasserapportens 'destinations' maskeres, "
        "men den SAMME adressen staar uendret i 'notes', fordi notes er fri "
        "tekst. Maskeringen av destinations gir et falskt inntrykk av at "
        "adressen er borte. Alvor: lav (adressen er tilleggets egen, ikke "
        "persondata), men det er klartekst minimeringen utgir seg for aa ha "
        "fjernet."
    ),
)
def test_sandbox_notes_do_not_leak_the_raw_destination():
    out = redact_payload(
        "sandbox",
        {
            "ts": "t",
            "package_name": "p",
            "attempted_network": True,
            "destinations": ["evil.example:80"],
            "verdict": "blocked",
            "notes": "Tillegget proevde aa koble til evil.example:80.",
        },
    )
    # destinations ble maskert ...
    assert "evil.example:80" not in str(out["destinations"])
    # ... men forventningen (som IKKE innfris) er at adressen da er helt borte.
    assert "evil.example:80" not in out["notes"]


# ---------------------------------------------------------------------------
# HULL: uten minimering (Vault-standard) logges ALT i klartekst.
# ---------------------------------------------------------------------------


def test_direct_vault_defaults_to_no_redaction(monkeypatch):
    """Vault() har minimering AV som standard. Lager en integrasjon en Vault
    direkte uten redact=True, havner summary og full mottaker i loggen. Demoen
    slaar den paa, men standarden er den farlige. Dokumentert (LIMITS punkt 7),
    her gjort synlig."""
    from attack_lib2 import fresh_vault

    v = fresh_vault(redact=False)
    v.append(
        "request",
        {"id": "r1", "action_type": "send_email", "recipient": "kari@example.com", "summary": "personnr 01010101010"},
    )
    payload = v.entries()[0].payload
    assert payload["summary"] == "personnr 01010101010"  # full klartekst
    assert payload["recipient"] == "kari@example.com"  # full mottaker
