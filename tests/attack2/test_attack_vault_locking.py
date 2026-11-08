"""Angrep 1e + 3: fil-laasing ved samtidig skriving.

Vault regner `seq` ut fra det den har i minnet. To skrivere mot samme fil
skriver derfor over hverandres sekvensnummer og knekker kjeden. Nettappen tar
en flock-laas (acquire_log_lock) og nekter en app nr. 2 aa starte - men Vault
SELV tar ingen laas.

  HOLDER: flock-laasen stopper en andre innehaver (det vanlige uhellet: to apper).
  HULL (dokumentert LIMITS punkt 6): to Vault-objekter mot samme fil knekker
          kjeden. verify() oppdager det etterpaa, men skaden er gjort - det
          finnes ingen transaksjon.
"""

from __future__ import annotations

import threading

import pytest

from attack_lib2 import fresh_vault, log_file
from vault.store import acquire_log_lock, LogLocked


# ---------------------------------------------------------------------------
# HOLDER: flock stopper en andre innehaver av loggen.
# ---------------------------------------------------------------------------


def test_second_lock_holder_is_refused():
    lock = acquire_log_lock()
    try:
        with pytest.raises(LogLocked):
            acquire_log_lock()
    finally:
        lock.release()


def test_lock_is_released_and_can_be_retaken():
    lock = acquire_log_lock()
    lock.release()
    again = acquire_log_lock()  # skal gaa fint naa
    again.release()


# ---------------------------------------------------------------------------
# HULL (dokumentert): to Vault paa samme fil - Vault tar ingen laas.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "HULL (LIMITS punkt 6): Vault SELV tar ingen laas. To Vault-objekter "
        "mot samme fil regner begge `seq` fra sitt eget minne og skriver begge "
        "en linje med seq 0. Kjeden knekker. Flock-laasen beskytter bare "
        "nettappen (DemoState), ikke run_demo.py, testene eller enhver annen "
        "integrasjon som lager en Vault direkte. verify() oppdager bruddet, men "
        "det finnes ingen transaksjon som HINDRER det. Alvor: middels - krever "
        "to skrivere mot samme fil, men da er skaden gjort foer noen sjekker."
    ),
)
def test_two_vaults_on_the_same_file_keep_the_chain_intact():
    a = fresh_vault()
    b = fresh_vault()  # ingen laas hindrer dette
    a.append("request", {"id": "a1"})
    b.append("request", {"id": "b1"})  # ogsaa seq 0
    a.append("request", {"id": "a2"})

    fresh = fresh_vault()
    # Forventningen (som IKKE innfris): kjeden skal fortsatt stemme.
    assert fresh.verify() is None, "to samtidige Vault-skrivere knakk kjeden"


def test_the_corruption_from_two_vaults_is_at_least_detected():
    """HOLDER (trøst): selv om bruddet ikke HINDRES, SER verify() det."""
    a = fresh_vault()
    b = fresh_vault()
    a.append("request", {"id": "a1"})
    b.append("request", {"id": "b1"})
    fresh = fresh_vault()
    assert fresh.verify() is not None  # minst oppdaget
