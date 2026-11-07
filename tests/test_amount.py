"""Hvordan et skrevet beløp tolkes.

Dette er sjekken hele demoen hviler paa: et menneske maa skrive beloepet for aa
godkjenne en stor overfoering. Da maa "skrev beloepet" bety at tallet faktisk er
det samme - ikke at sifrene tilfeldigvis staar i samme rekkefoelge.

Funn F1 i docs/REDTEAM.md: den gamle regelen kastet alle tegn som ikke var 0-9,
saa "100000,00" (hundre tusen kroner og null oere) ble lest som 10 000 000.
"""

from __future__ import annotations

import json
import pathlib
import shutil
import subprocess

import pytest

from ui.amount import amount_matches, parse_amount

CASES_PATH = pathlib.Path(__file__).with_name("amount_cases.json")
CASES = json.loads(CASES_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# F1: beloep som IKKE er beloepet
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "skrevet",
    [
        "100000,00",      # hundre tusen kroner og null oere
        "100000.00",
        "1000000,0",      # én million
        "1000000,00",
        "-10000000",      # negativt
        "+10000000",
        "abc10000000xyz",  # bokstaver rundt
        "10000000kroner ekstra",
        "10 000 000,01",  # én oere for mye
        "9999999,99",
    ],
)
def test_et_annet_beloep_blir_aldri_godtatt(skrevet):
    assert amount_matches(skrevet, 10_000_000) is False


@pytest.mark.parametrize(
    "skrevet",
    ["10000000", "10 000 000", "10 000 000 kr", "10.000.000", " 10000000 ", "0010000000",
     "10000000,00", "10 000 000 NOK", "10000000 kroner"],
)
def test_det_riktige_beloepet_kan_skrives_som_folk_skriver_beloep(skrevet):
    assert amount_matches(skrevet, 10_000_000) is True


# ---------------------------------------------------------------------------
# desimaler
# ---------------------------------------------------------------------------


def test_desimalbeloep_kan_bekreftes():
    """Den gamle regelen kunne ALDRI bekrefte et beloep med oere."""
    assert amount_matches("1234,56", 1234.56) is True
    assert amount_matches("1 234,56", 1234.56) is True
    assert amount_matches("1234,56 kr", 1234.56) is True


def test_feil_oere_blir_avvist():
    assert amount_matches("1234,57", 1234.56) is False
    assert amount_matches("1234,5", 1234.56) is False
    assert amount_matches("1234", 1234.56) is False
    assert amount_matches("123456", 1234.56) is False


def test_oere_regnes_eksakt_uten_flyttallsstoey():
    for kroner in (0.01, 0.1, 1.05, 19.99, 1234.56, 49999.5, 70.07):
        tekst = f"{kroner:.2f}".replace(".", ",")
        assert amount_matches(tekst, kroner) is True, kroner


# ---------------------------------------------------------------------------
# F3: lang streng skal gi et pent nei, ikke en krasj
# ---------------------------------------------------------------------------


def test_en_svaert_lang_streng_gir_et_pent_nei():
    assert parse_amount("1" * 5000) is None
    assert amount_matches("1" * 5000, 10_000_000) is False


def test_for_mange_sifre_avvises_uten_aa_regne_paa_dem():
    """Grensen er 13 siffer. Over det kan nettleseren ikke regne eksakt."""
    assert parse_amount("9" * 14) is None
    assert parse_amount("9" * 13) == 999999999999900


# ---------------------------------------------------------------------------
# tusenskille maa gruppere riktig
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "skrevet",
    ["1 0000000", "10.00.000", "10 000 00", "1.0000.000", "10,000,000"],
)
def test_feil_gruppering_avvises(skrevet):
    assert parse_amount(skrevet) is None


def test_uendelig_eller_manglende_forventet_beloep_gir_aldri_treff():
    assert amount_matches("10000000", None) is False
    assert amount_matches("10000000", float("inf")) is False
    assert amount_matches("0", float("nan")) is False


# ---------------------------------------------------------------------------
# samme regel i Python og i nettleseren
# ---------------------------------------------------------------------------


def test_alle_felles_tilfeller_stemmer_i_python():
    for case in CASES:
        got = parse_amount(case["typed"])
        assert got == case["ore"], case


@pytest.mark.skipif(shutil.which("node") is None, reason="node er ikke installert")
def test_nettleseren_tolker_beloep_noeyaktig_som_python():
    """app.js og state.py maa aldri kunne bli uenige om hva et beloep er.

    Er de uenige, blir knappen i nettleseren gronn for noe tjeneren avviser
    (eller motsatt), og "skriv beloepet" betyr ikke lenger det samme de to
    stedene. Derfor kjoerer vi NOEYAKTIG samme tilfeller gjennom begge.
    """
    amount_js = pathlib.Path(__file__).resolve().parents[1] / "ui" / "static" / "amount.js"
    skript = (
        f"require({str(amount_js)!r});"
        f"const cases = require({str(CASES_PATH)!r});"
        "const out = cases.map((c) => LonewatchAmount.parseAmountOre(c.typed));"
        "process.stdout.write(JSON.stringify(out));"
    )
    res = subprocess.run(
        ["node", "-e", skript], capture_output=True, text=True, timeout=30
    )
    assert res.returncode == 0, res.stderr
    fra_js = json.loads(res.stdout)

    uenige = [
        (c["typed"], c["ore"], js)
        for c, js in zip(CASES, fra_js)
        if c["ore"] != js
    ]
    assert not uenige, f"python og js er uenige om: {uenige}"
