"""Angrep 2: komme seg ut av sandkassen fra et tillegg.

sandbox/LIMITS.md er uvanlig aerlig: "Dette er ikke ekte isolasjon." Sperrene er
Python-funksjoner i samme prosess som tillegget. Runde en hoppet over sandkassen
helt. Her kjoerer vi angrepene og rapporterer ARLIG hva boksen faktisk isolerer
og hva den bare later som.

  HOLDER (ekte isolasjon):
    - Lonewatch-noeklene laekker IKKE inn i delprosessen. Miljoeet bygges fra null.
    - `import vault` / `import gateway` naar ikke fram.
    - Et naivt filskriv/-lese utenfor boksen avvises.
    - Nettverk, prosess-spawn og ctypes er sperret for den som ikke bryter ut.
    - Tidsgrensen dreper et tillegg som henger.

  LUKKET I RUNDE 3 (herd-e), men ikke med ekte isolasjon:
    - `open.__globals__["_REAL_BUILTINS_OPEN"]` avvises naa FOER kjoering av den
      statiske sjekken i `sandbox/static_check.py`, og rapporten sier `blocked`.
    - Samme for veien til hendelsesfilen: et tillegg kan ikke lenger skrive
      falske hendelser inn i rapporten om seg selv.
    - Naar et tillegg likevel naar den globale ordboken (f.eks. uten at kilden
      nevner noe sperret), ligger det en SNARE der de ekte funksjonene laa.
      Snaren skriver ned forsoeket (`guard_bypass`) og nekter.
    - `clean` krever naa et BEVIS: harness-et maa ha bekreftet at sperrene sto
      igjen etterpaa (`guards_intact`). Uten beviset er svaret `not_tested`.

  FORTSATT AAPENT (og kan ikke lukkes her):
    - Python-sandboxing i samme prosess kan ikke gjoeres sikker. Den statiske
      sjekken avviser MOENSTRE vi kjenner; en streng satt sammen under
      kjoeringen, dekodet fra base64 eller hentet fra en fil gaar gjennom den.
      Ekte loesning: prosessisolasjon (container/VM/seccomp) eller en etablert
      sandkasse. Se sandbox/LIMITS.md.
"""

from __future__ import annotations

import pytest
from attack_lib2 import refuse_to_touch_real_log  # noqa: F401  (autouse: aldri roer den ekte loggen)

from sandbox import static_check
from sandbox.runner import run_in_box


# ---------------------------------------------------------------------------
# HOLDER: noeklene foelger ikke med inn i delprosessen.
# ---------------------------------------------------------------------------


def test_lonewatch_keys_do_not_leak_into_the_box(monkeypatch):
    monkeypatch.setenv("LONEWATCH_LOG_KEY", "hemmelig-loggnoekkel-xyz")
    monkeypatch.setenv("LONEWATCH_PSEUDONYM_KEY", "hemmelig-pseudonymnoekkel-xyz")
    src = '''
import os
def run():
    leaked = [k for k in os.environ if "LONEWATCH" in k]
    return "LEAKED=" + repr(leaked)
'''
    run = run_in_box("pdf-helper", src, timeout_s=6)
    assert "LEAKED=[]" in run.result_value()


def test_cannot_import_vault_or_gateway():
    src = '''
def run():
    out = []
    for mod in ("vault", "gateway", "contracts"):
        try:
            __import__(mod)
            out.append(mod + ":IMPORTED")
        except Exception as e:
            out.append(mod + ":" + type(e).__name__)
    return " ".join(out)
'''
    run = run_in_box("pdf-helper", src, timeout_s=6)
    assert "IMPORTED" not in run.result_value()


def test_naive_file_read_outside_box_is_blocked():
    src = '''
def run():
    try:
        return "READ:" + open("/etc/passwd").read()[:10]
    except Exception as e:
        return "blocked:" + type(e).__name__
'''
    run = run_in_box("pdf-helper", src, timeout_s=6)
    assert "blocked:" in run.result_value()
    assert "READ:" not in run.result_value()
    assert run.report.verdict == "blocked"


def test_process_spawn_is_blocked():
    src = '''
import os
def run():
    try:
        os.system("echo hi")
        return "RAN"
    except Exception as e:
        return "blocked:" + type(e).__name__
'''
    run = run_in_box("pdf-helper", src, timeout_s=6)
    assert "RAN" not in run.result_value()


def test_hanging_plugin_is_killed_by_the_timeout():
    src = '''
def run():
    while True:
        pass
'''
    run = run_in_box("slow-plugin", src, timeout_s=1)
    assert run.report.verdict == "blocked"


# ---------------------------------------------------------------------------
# LUKKET: bryt ut via open.__globals__ og les en fil utenfor boksen.
#
# Dette var HULLET i runde 2: angrepet virket, OG rapporten sa `clean`. Begge
# delene er rettet - men med en bom og en snare, ikke med ekte isolasjon.
# ---------------------------------------------------------------------------


def test_globals_escape_cannot_read_outside_the_box():
    """Den klassiske roemningen. Avvises FOER kjoering, og gir `blocked`."""
    src = '''
def run():
    real_open = open.__globals__["_REAL_BUILTINS_OPEN"]
    with real_open("/etc/passwd") as f:
        return "ESCAPED:" + f.read()[:8]
'''
    run = run_in_box("pdf-helper", src, timeout_s=6)
    assert "ESCAPED:" not in run.result_value(), "tillegget leste en fil utenfor boksen"
    assert run.report.verdict != "clean", "boksen sa 'clean' om et tillegg som brot ut"
    assert run.report.verdict == "blocked"
    # Avvist av den statiske sjekken: det ble ikke startet noen delprosess.
    assert "static_reject" in run.kinds()
    assert "AVVIST FOER KJOERING" in run.report.notes
    assert "dunder_attributt" in run.report.notes


def test_plugin_cannot_forge_events_in_its_own_report():
    """Skrive falske hendelser inn i sin egen rapport. Samme vei, samme svar."""
    src = '''
import json
def run():
    ev = open.__globals__["_events"]
    ev.write(json.dumps({"kind": "fabricated_by_attacker", "data": {}}) + "\\n")
    ev.flush()
    return "forged"
'''
    run = run_in_box("pdf-helper", src, timeout_s=6)
    assert "fabricated_by_attacker" not in run.kinds(), "tillegget forfalsket sin egen rapport"
    assert run.report.verdict == "blocked"


@pytest.mark.parametrize(
    "uttrykk",
    [
        'open.__globals__["_REAL_BUILTINS_OPEN"]',
        'open.__builtins__["open"]',
        '(0).__class__.__mro__[1].__subclasses__()',
        'type("x", (), {}).__class__',
        'run.__code__',
        'run.__closure__',
        'open.__getattribute__("__globals__")',
        'getattr(open, "__globals__")',
        'eval("1+1")',
        'exec("x=1")',
        'compile("1", "<s>", "eval")',
        '__import__("os")',
    ],
)
def test_known_escape_patterns_are_refused_before_the_plugin_runs(uttrykk):
    """Hvert moenster avvises paa kilden, uten at en prosess startes."""
    src = f"def run():\n    return {uttrykk}\n"
    assert static_check.check_source(src), f"ikke avvist: {uttrykk}"
    run = run_in_box("moenster", src, timeout_s=6)
    assert run.report.verdict == "blocked", run.report.notes
    assert "static_reject" in run.kinds()
    # Ingen prosess ble startet, saa tillegget fikk aldri returnert noe.
    assert run.result_value() == ""


def test_a_string_that_names_a_dunder_is_refused_too():
    """`getattr` er den aapenbare veien rundt sjekken paa attributtnavn."""
    src = '''
def run():
    navn = "__globals__"
    return navn
'''
    funn = static_check.check_source(src)
    assert [f.rule for f in funn] == ["dunder_i_streng"]


def test_a_concatenated_name_slips_past_the_static_check_but_hits_the_tripwire():
    """AERLIG: den statiske sjekken ser ikke en streng satt sammen under kjoering.

    `"__glob" + "als__"` staar ikke i kilden som et sperret navn, saa sjekken
    slipper den gjennom. Da er det snaren som maa gi seg til kjenne: der de ekte
    funksjonene laa ligger det naa et objekt som skriver ned forsoeket og
    nekter. Snaren er ingen vegg - men forsoeket blir SETT, og rapporten sier
    `blocked` i stedet for `clean`.
    """
    src = '''
import operator
def run():
    hent = operator.attrgetter("__glob" + "als__")
    g = hent(open)
    try:
        ekte = g["_REAL" + "_BUILTINS" + "_OPEN"]
        with ekte("/etc/passwd") as f:
            return "ESCAPED:" + f.read()[:8]
    except Exception as e:
        return "snare:" + type(e).__name__
'''
    # Den statiske sjekken ser ikke dette. Det er den aerlige grensen.
    assert static_check.check_source(src) == []

    run = run_in_box("sammensatt", src, timeout_s=6)
    assert "ESCAPED:" not in run.result_value(), "tillegget leste en fil utenfor boksen"
    assert "guard_bypass" in run.kinds(), "snaren ga seg ikke til kjenne"
    assert run.report.verdict == "blocked", run.report.notes
    assert "strakk seg etter" in run.report.notes


def test_the_event_file_is_no_longer_in_the_global_dict_at_all():
    """Hendelsesfilen laa i `_events` i den globale ordboken. Naa er den en snare."""
    src = '''
import operator
def run():
    g = operator.attrgetter("__glob" + "als__")(open)
    return "events=" + type(g.get("_events", None)).__name__
'''
    assert static_check.check_source(src) == []
    run = run_in_box("hendelsesfil", src, timeout_s=6)
    # Navnet finnes ikke lenger som et filobjekt. Skriveren ligger i en lukning.
    assert "TextIOWrapper" not in run.result_value(), run.result_value()


def test_a_plugin_that_swaps_out_a_guard_is_caught_afterwards():
    """Sperrene sjekkes ETTER kjoeringen. Byttes en ut, er alt annet usikkert."""
    src = '''
import builtins
def run():
    builtins.open = lambda *a, **k: None
    return "byttet"
'''
    run = run_in_box("sperrebytte", src, timeout_s=6)
    # Kilden skriver til builtins.open, saa den statiske sjekken tar den foerst.
    assert run.report.verdict == "blocked", run.report.notes
    assert "sperre_overskriving" in run.report.notes


def test_clearing_meta_path_is_reported_as_tampering():
    """`sys.meta_path.clear()` naevner ingen sperret ting - men sees etterpaa."""
    src = '''
import sys
def run():
    sys.meta_path.clear()
    return "tomt"
'''
    run = run_in_box("metapath", src, timeout_s=6)
    assert "guard_tampered" in run.kinds(), run.report.notes
    assert run.report.verdict == "blocked"
    assert "sto ikke igjen" in run.report.notes


# ---------------------------------------------------------------------------
# `clean` krever bevis, ikke bare stillhet.
# ---------------------------------------------------------------------------


def test_clean_requires_the_guards_to_have_been_checked():
    """Et harmlost tillegg blir fortsatt `clean` - men naa med et bevis bak."""
    src = "def run():\n    return 1 + 1\n"
    run = run_in_box("harmlos", src, timeout_s=6)
    assert run.report.verdict == "clean", run.report.notes
    assert "guards_intact" in run.kinds(), "clean uten bevis for at sperrene sto igjen"


def test_a_report_without_the_proof_is_never_clean():
    """Uten `guards_intact` i hendelsene skal rapporten aldri si `clean`."""
    from sandbox.report import build_report

    hendelser = [
        {"kind": "start", "data": {}},
        {"kind": "result", "data": {"value": "1"}},
        {"kind": "done", "data": {}},
    ]
    rapport = build_report(
        "uten-bevis", hendelser, timed_out=False, timeout_s=6.0, returncode=0
    )
    assert rapport.verdict == "not_tested"
    assert rapport.verdict != "clean"
    assert "IKKE TESTET" in rapport.notes


# ---------------------------------------------------------------------------
# FALSKE POSITIVER: vanlige tillegg skal ikke bli avvist.
# ---------------------------------------------------------------------------


VANLIGE_TILLEGG = {
    "leser-en-fil": (
        "import os\n"
        "from pathlib import Path\n"
        "def run():\n"
        "    p = Path(os.path.expanduser('~')) / 'Dokumenter' / 'faktura-demo.txt'\n"
        "    return len(p.read_text(encoding='utf-8'))\n"
    ),
    "regner-paa-datoer": (
        "from datetime import date, timedelta\n"
        "def run():\n"
        "    d = date(2026, 11, 7)\n"
        "    return str(d + timedelta(days=7))\n"
    ),
    "bruker-standardbiblioteket": (
        "import json, pathlib, uuid, re\n"
        "def run():\n"
        "    return json.dumps({'navn': str(pathlib.Path('.').name)})\n"
    ),
    "egen-klasse-og-dekorator": (
        "import functools\n"
        "class Teller:\n"
        "    def __init__(self):\n"
        "        self.n = 0\n"
        "    def tikk(self):\n"
        "        self.n += 1\n"
        "        return self.n\n"
        "@functools.lru_cache(maxsize=4)\n"
        "def kvadrat(x):\n"
        "    return x * x\n"
        "def run():\n"
        "    t = Teller()\n"
        "    t.tikk()\n"
        "    return kvadrat(t.n)\n"
    ),
    "henter-ut-felt-med-oppslag": (
        "def run():\n"
        "    rad = {'belop': 10, 'valuta': 'NOK'}\n"
        "    return '%s %s' % (rad['belop'], rad['valuta'])\n"
    ),
}


@pytest.mark.parametrize("kilde", list(VANLIGE_TILLEGG.values()), ids=list(VANLIGE_TILLEGG))
def test_an_ordinary_plugin_is_not_refused_by_the_static_check(kilde):
    assert static_check.check_source(kilde) == [], "vanlig tillegg ble avvist"


def test_the_harmless_demo_packages_still_run():
    """De to harmlose demotilleggene skal fortsatt bli `clean`."""
    import sandbox

    for navn in ("pdf-helper", "date-utils"):
        rapport = sandbox.scan(navn)
        assert rapport.verdict == "clean", f"{navn}: {rapport.notes}"


def test_the_stealing_demo_packages_are_still_blocked_by_what_they_DO():
    """De mistenkelige tilleggene skal stoppes paa handling, ikke paa kilden.

    Det er en ekte forskjell: blir de avvist statisk, mister vi beviset for at
    nettsperren og agnfilene virker. Derfor skal kilden deres vaere ren.
    """
    import sandbox

    for navn in ("nordlys-mail-connector-patch", "free-ai-boost", "env-sync-helper"):
        kilde = sandbox.package_path(navn).read_text(encoding="utf-8")
        assert static_check.check_source(kilde) == [], f"{navn} ble avvist statisk"
        rapport = sandbox.scan(navn)
        assert rapport.verdict == "blocked", f"{navn}: {rapport.notes}"
        assert "static_reject" not in rapport.notes
