"""Den statiske sjekken i sandbox/static_check.py, for seg selv.

Tre krav: den er deterministisk, den sier HVA den fant, og den sier ærlig fra
om hva den ikke ser. Angrepene mot hele boksen står i
tests/attack2/test_attack_sandbox_escape.py.
"""

from __future__ import annotations

import pytest

from sandbox import static_check
from sandbox.static_check import check_source


def _regler(kilde: str) -> list[str]:
    return static_check.rules_in(check_source(kilde))


# ---------------------------------------------------------------------------
# det den skal ta
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("attributt", sorted(static_check.DENIED_ATTRIBUTES))
def test_hvert_sperret_attributt_blir_avvist(attributt):
    funn = check_source(f"def run():\n    return open.{attributt}\n")
    assert funn, attributt
    assert "dunder_attributt" in static_check.rules_in(funn)
    # Funnet sier hvilket attributt det var, ikke bare at noe var galt.
    assert attributt in funn[0].detail


@pytest.mark.parametrize("navn", sorted(static_check.DENIED_NAMES))
def test_hvert_sperret_navn_blir_avvist(navn):
    assert "sperret_navn" in _regler(f"def run():\n    return {navn}\n")


def test_open_er_tillatt():
    """`open` er sperret inne i boksen, ikke forbudt. Agnfilene SKAL leses."""
    assert check_source("def run():\n    return open('fil.txt').read()\n") == []
    assert "open" in static_check.ALLOWED_NAMES


@pytest.mark.parametrize("kall", ["getattr", "setattr", "delattr"])
def test_oppslag_av_attributt_ved_navn_blir_avvist(kall):
    med_streng = _regler(f"def run():\n    return {kall}(open, 'x')\n")
    assert "getattr_med_streng" in med_streng
    med_uttrykk = _regler(f"def run():\n    n = 'x'\n    return {kall}(open, n)\n")
    assert "getattr_med_uttrykk" in med_uttrykk


def test_en_streng_som_nevner_et_sperret_attributt_blir_avvist():
    assert "dunder_i_streng" in _regler("def run():\n    return '__globals__'\n")


@pytest.mark.parametrize(
    "modul", ["builtins", "io", "_io", "os", "socket", "subprocess"]
)
def test_skriving_til_en_sperremodul_blir_avvist(modul):
    kilde = f"import {modul}\ndef run():\n    {modul}.open = None\n"
    assert "sperre_overskriving" in _regler(kilde)


def test_kilde_som_ikke_kan_leses_er_ogsaa_et_funn():
    """Kan vi ikke lese kilden, vet vi ikke hva den gjør. Da kjøres den ikke."""
    funn = check_source("def run(:\n")
    assert [f.rule for f in funn] == ["kilden_kan_ikke_leses"]


# ---------------------------------------------------------------------------
# determinisme og form
# ---------------------------------------------------------------------------


def test_samme_kilde_gir_noeyaktig_samme_svar():
    kilde = (
        "def run():\n"
        "    a = open.__globals__\n"
        "    b = getattr(open, '__class__')\n"
        "    return eval('1')\n"
    )
    foerste = check_source(kilde)
    for _ in range(5):
        assert check_source(kilde) == foerste


def test_funnet_sier_hvilken_linje():
    kilde = "def run():\n    x = 1\n    return open.__globals__\n"
    funn = check_source(kilde)
    assert funn[0].lineno == 3
    assert "linje 3" in funn[0].text()


def test_tom_kilde_gir_ingen_funn():
    assert check_source("") == []
    assert check_source("   \n\n") == []


# ---------------------------------------------------------------------------
# ÆRLIG: det den ikke ser
# ---------------------------------------------------------------------------


def test_en_streng_satt_sammen_under_kjoeringen_gaar_gjennom():
    """Dokumentert grense (sandbox/LIMITS.md). Da er det snaren som fanger det."""
    kilde = (
        "import operator\n"
        "def run():\n"
        "    return operator.attrgetter('__glob' + 'als__')(open)\n"
    )
    assert check_source(kilde) == []


def test_en_kodet_streng_gaar_gjennom():
    kilde = (
        "import base64\n"
        "def run():\n"
        "    return base64.b64decode('X19nbG9iYWxzX18=').decode()\n"
    )
    assert check_source(kilde) == []
