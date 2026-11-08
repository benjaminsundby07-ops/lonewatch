"""Angrep 2: komme seg ut av sandkassen fra et tillegg.

sandbox/LIMITS.md er uvanlig aerlig: "Dette er ikke ekte isolasjon." Sperrene er
Python-funksjoner i samme prosess som tillegget, og et tillegg kan naa de ekte
funksjonene gjennom `open.__globals__`. Runde en hoppet over sandkassen helt.
Her kjoerer vi angrepene og rapporterer ARLIG hva boksen faktisk isolerer og hva
den bare later som.

  HOLDER (ekte isolasjon):
    - Lonewatch-noeklene laekker IKKE inn i delprosessen. Miljoeet bygges fra null.
    - `import vault` / `import gateway` naar ikke fram.
    - Et naivt filskriv/-lese utenfor boksen avvises.
    - Nettverk, prosess-spawn og ctypes er sperret for den som ikke bryter ut.
    - Tidsgrensen dreper et tillegg som henger.

  HULL (boksen bare later som - dokumentert):
    - `open.__globals__["_REAL_BUILTINS_OPEN"]` leser en vilkaarlig fil utenfor
      boksen, og rapporten sier likevel `clean`.
    - Samme vei naar hendelsesfilen, saa et tillegg kan skrive falske hendelser
      inn i rapporten om seg selv.
"""

from __future__ import annotations

import pytest

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
# HULL (dokumentert): bryt ut via open.__globals__ og les en fil utenfor boksen.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "HULL (sandbox/LIMITS.md 'Sperrene kan brytes fra innsiden'): sperrene "
        "er funksjoner i SAMME Python-prosess som tillegget. `open.__globals__` "
        "gir tilgang til de ekte funksjonene harness-et tok vare paa "
        "(_REAL_BUILTINS_OPEN), og da kan tillegget lese en vilkaarlig fil "
        "utenfor boksen. Verre: rapporten sier `clean` mens det skjer - boksen "
        "ser ingenting. Alvor: kritisk for en ekte sandkasse, men dette er en "
        "bom og ikke en vegg, og det kan ikke lukkes saa lenge tillegget "
        "kjoerer i samme prosess. Fiks: ekte OS-isolasjon (container/VM/seccomp)."
    ),
)
def test_globals_escape_cannot_read_outside_the_box():
    src = '''
def run():
    real_open = open.__globals__["_REAL_BUILTINS_OPEN"]
    with real_open("/etc/passwd") as f:
        return "ESCAPED:" + f.read()[:8]
'''
    run = run_in_box("pdf-helper", src, timeout_s=6)
    # Forventningen (som IKKE innfris): utbrudd skal vaere umulig ELLER gi blocked.
    assert "ESCAPED:" not in run.result_value(), "tillegget leste en fil utenfor boksen"
    assert run.report.verdict != "clean", "boksen sa 'clean' om et tillegg som brot ut"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "HULL (sandbox/LIMITS.md): samme vei naar hendelsesfilen. Via "
        "`open.__globals__['_events']` kan tillegget skrive hendelser inn i sin "
        "EGEN rapport. Et tillegg kan altsaa pynte paa beviset mot seg selv. "
        "Alvor: kritisk - det undergraver at rapporten er et uavhengig vitne. "
        "Fiks: samme som over, ekte isolasjon utenfor prosessen."
    ),
)
def test_plugin_cannot_forge_events_in_its_own_report():
    src = '''
import json
def run():
    ev = open.__globals__["_events"]
    ev.write(json.dumps({"kind": "fabricated_by_attacker", "data": {}}) + "\\n")
    ev.flush()
    return "forged"
'''
    run = run_in_box("pdf-helper", src, timeout_s=6)
    # Forventningen (som IKKE innfris): tillegget skal ikke naa hendelsesstroemmen.
    assert "fabricated_by_attacker" not in run.kinds(), "tillegget forfalsket sin egen rapport"
