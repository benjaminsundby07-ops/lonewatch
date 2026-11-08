"""Angrep 1a: noekkelhaandtering i vault.

Spoersmaalet: hva skjer ved manglende, tom, kort eller feil noekkel? Loeftet er
at loggen aldri aapnes uten en gyldig noekkel, og at en feil noekkel aldri gir
en stille "alt er fint". Alt her er forsoek paa aa faa vault til aa svikte aapent
(bruke en daarlig noekkel, lese noe den ikke burde). Holder forsvaret, bestaar
testen.
"""

from __future__ import annotations

import pytest

from attack_lib2 import fresh_vault
from vault.crypto import (
    ENV_LOG_KEY,
    ENV_PSEUDONYM_KEY,
    VaultKeyError,
    load_log_key,
    load_pseudonym_key,
    new_log_key,
)


# ---------------------------------------------------------------------------
# HOLDER: ingen noekkel -> ingen logg. Fail closed.
# ---------------------------------------------------------------------------


def test_missing_log_key_is_refused(monkeypatch):
    monkeypatch.delenv(ENV_LOG_KEY, raising=False)
    with pytest.raises(VaultKeyError):
        load_log_key()


def test_empty_log_key_is_refused(monkeypatch):
    monkeypatch.setenv(ENV_LOG_KEY, "")
    with pytest.raises(VaultKeyError):
        load_log_key()


def test_whitespace_only_log_key_is_refused(monkeypatch):
    monkeypatch.setenv(ENV_LOG_KEY, "   \t  ")
    with pytest.raises(VaultKeyError):
        load_log_key()


@pytest.mark.parametrize(
    "bad",
    [
        "x",  # for kort
        "kort-tull",
        "a" * 43,  # feil lengde for en Fernet-noekkel
        "a" * 45,  # ogsaa feil lengde
        "!" * 44,  # riktig lengde, men ikke gyldig base64
    ],
)
def test_malformed_log_key_is_refused(monkeypatch, bad):
    monkeypatch.setenv(ENV_LOG_KEY, bad)
    with pytest.raises(VaultKeyError):
        load_log_key()


def test_pseudonym_key_too_short_is_refused(monkeypatch):
    monkeypatch.setenv(ENV_PSEUDONYM_KEY, "kortnoekkel")  # < 16 tegn
    with pytest.raises(VaultKeyError):
        load_pseudonym_key()


def test_pseudonym_key_exactly_16_is_accepted(monkeypatch):
    monkeypatch.setenv(ENV_PSEUDONYM_KEY, "0123456789abcdef")  # 16 tegn
    assert load_pseudonym_key() == b"0123456789abcdef"


# ---------------------------------------------------------------------------
# HOLDER: en FEIL (men gyldig) Fernet-noekkel gir aldri "alt er fint".
# ---------------------------------------------------------------------------


def test_wrong_key_cannot_read_an_existing_log(monkeypatch):
    """En gyldig, men gal, noekkel ser INGEN linjer og verifiserer ikke.

    Den som aapner loggen med feil noekkel skal ikke faa en stille klarering.
    Linjene kan ikke dekrypteres, saa de telles ikke med, og verify() peker paa
    den foerste uleselige linjen i stedet for aa svare None.
    """
    v = fresh_vault()
    v.append("request", {"id": "r1", "recipient": "NO93 8601 1117 947"})
    v.append("decision", {"request_id": "r1", "verdict": "red"})
    assert len(v) == 2

    wrong = new_log_key()
    monkeypatch.setenv(ENV_LOG_KEY, wrong)
    from vault import Vault

    v2 = Vault(key=wrong)
    # Ingen linjer leses ut (alt feiler dekryptering), og verify roper fra.
    assert len(v2) == 0
    assert v2.verify() == 0
    assert v2.verify_detail().reason in ("unreadable_line", "chain")


def test_wrong_key_never_reports_ok(monkeypatch):
    """Det farlige utfallet - verify() == None (alt stemmer) - skjer aldri med feil noekkel."""
    v = fresh_vault()
    for i in range(3):
        v.append("request", {"id": f"r{i}"})

    wrong = new_log_key()
    from vault import Vault

    v2 = Vault(key=wrong)
    assert v2.verify() is not None  # aldri en stille "ok"
