"""Tillegg som aldri kom i gang: verdiktet `not_tested`.

Foer var svaret `clean`, og det betyr "vi saa etter og fant ingenting". Her
fikk vi aldri sett etter. Det er den eneste endringen som er gjort i den
ellers laaste contracts.py.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

import sandbox
from contracts import ActionRequest, ActionType, SandboxReport, Verdict
from gateway import consequence, evaluate, rules
from ui.overview import build_overview
from ui.state import DemoState

TS = datetime(2026, 11, 7, 9, 0, tzinfo=timezone.utc)

KRASJER = "def run():\n    raise RuntimeError('noe gikk galt')\n"
UTEN_RUN = "x = 1\n"
VIRKER = "def run():\n    return 1\n"


def rapport(verdict: str = "not_tested", **felt) -> SandboxReport:
    base = dict(
        ts=TS, package_name="noe-tillegg", attempted_network=False,
        destinations=[], verdict=verdict, notes="",
    )
    base.update(felt)
    return SandboxReport(**base)


def install(package_name: str = "noe-tillegg") -> ActionRequest:
    return ActionRequest(
        id="req_x", ts=TS, agent_id="it_helper",
        action_type=ActionType.INSTALL_PACKAGE, summary="", package_name=package_name,
    )


# ---------------------------------------------------------------------------
# sandkassen produserer det
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("kilde", [KRASJER, UTEN_RUN])
def test_et_tillegg_som_aldri_kom_i_gang_er_not_tested_og_aldri_clean(kilde):
    kjoring = sandbox.run_in_box("proeve", kilde, timeout_s=6)
    assert kjoring.report.verdict == "not_tested"
    assert kjoring.report.verdict != "clean"
    assert kjoring.inconclusive is True
    assert kjoring.report.notes.startswith("IKKE TESTET")


def test_et_tillegg_som_kjoerer_ferdig_er_clean():
    kjoring = sandbox.run_in_box("virker", VIRKER, timeout_s=6)
    assert kjoring.report.verdict == "clean"
    assert kjoring.inconclusive is False


def test_et_funn_slaar_en_krasj():
    """Krasjer tillegget ETTER at det proevde seg paa nettet, er det et funn.

    "Vi fikk ikke testet det" ville vaert loegn: vi saa noe, og det vi saa var
    nok.
    """
    kilde = (
        "import socket\n"
        "def run():\n"
        "    try:\n"
        "        socket.create_connection(('x.invalid', 80), timeout=1)\n"
        "    except OSError:\n"
        "        pass\n"
        "    raise RuntimeError('krasj etterpaa')\n"
    )
    kjoring = sandbox.run_in_box("funn_foerst", kilde, timeout_s=6)
    assert kjoring.report.verdict == "blocked"
    assert kjoring.inconclusive is True  # den krasjet, men funnet veier mer


def test_tidsgrensen_er_fortsatt_blocked():
    """Et tillegg som henger har gjort noe vi SAA: det nektet aa gi seg."""
    r = sandbox.scan(sandbox.HANGING_PACKAGE, timeout_s=1.5)
    assert r.verdict == "blocked"


def test_alle_demotilleggene_blir_faktisk_testet():
    for navn in sandbox.DEMO_PACKAGES:
        assert sandbox.scan_cached(navn).verdict != "not_tested", navn


# ---------------------------------------------------------------------------
# gateway
# ---------------------------------------------------------------------------


def test_not_tested_blokkerer_ikke():
    """"Vi fikk ikke testet det" er ikke det samme som "nei"."""
    assert rules.sandbox_blocked(install(), rapport("not_tested")) is False
    d = evaluate(install(), sandbox_report=rapport("not_tested"))
    assert d.verdict is Verdict.RED
    assert "sandbox_blocked" not in d.reasons


def test_new_package_gjelder_fortsatt():
    d = evaluate(install(), sandbox_report=rapport("not_tested"))
    assert "new_package" in d.reasons


def test_klarteksten_sier_at_vi_ikke_fikk_testet_det():
    d = evaluate(install(), sandbox_report=rapport("not_tested"))
    assert consequence.SANDBOX_INCONCLUSIVE in d.consequence_text
    assert "fikk ikke testet" in d.consequence_text
    # Og den maa ALDRI lese som en klarering.
    assert "ingenting mistenkelig" not in d.consequence_text
    assert "fant ikke noe" not in d.consequence_text
    assert consequence.SANDBOX_CLEAN not in d.consequence_text


def test_de_tre_utfallene_sier_tre_forskjellige_ting():
    tekster = {
        v: evaluate(install(), sandbox_report=rapport(v)).consequence_text
        for v in ("clean", "blocked", "not_tested")
    }
    assert len(set(tekster.values())) == 3
    assert "ingenting mistenkelig" in tekster["clean"]
    assert "stoppet" in tekster["blocked"]
    assert "fikk ikke testet" in tekster["not_tested"]


def test_et_godkjent_tillegg_som_ikke_ble_testet_er_fortsatt_allow():
    """not_tested legger ikke til risiko av seg selv."""
    d = evaluate(install("nordlys-core"), sandbox_report=rapport("not_tested",
                                                                package_name="nordlys-core"))
    assert d.verdict is Verdict.ALLOW


# ---------------------------------------------------------------------------
# gamle rapporter
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("gammel", ["clean", "blocked"])
def test_gamle_rapporter_leses_fortsatt(gammel):
    r = rapport(gammel)
    assert SandboxReport.model_validate(r.model_dump(mode="json")).verdict == gammel


def test_en_gammel_loggfil_med_clean_kan_fortsatt_leses(tmp_path):
    """Loggen lagrer payload som dict. En linje fra foer skal fortsatt gaa."""
    from vault import Vault
    from vault.after import build_after_actions

    v = Vault(path=tmp_path / "gammel.jsonl")
    v.append("sandbox", rapport("clean", package_name="gammelt").model_dump(mode="json"))
    v.append("sandbox", rapport("blocked", package_name="gammelt2",
                                attempted_network=True,
                                destinations=["x.invalid:1"]).model_dump(mode="json"))
    assert v.verify() is None
    paa_disk = Vault(path=v.path).entries()
    assert [e.payload["verdict"] for e in paa_disk] == ["clean", "blocked"]
    # Etter-listen taaler dem.
    assert build_after_actions(paa_disk)


# ---------------------------------------------------------------------------
# UI-tellingen
# ---------------------------------------------------------------------------


@pytest.fixture()
def state() -> DemoState:
    s = DemoState()
    yield s
    s.close()


def test_foer_listen_teller_ikke_not_tested_som_clean(state):
    state._record_sandbox(rapport("not_tested", package_name="krasjet"))
    state._record_sandbox(rapport("clean", package_name="rent"))
    state._record_sandbox(rapport("blocked", package_name="stoppet"))

    foer = state.before_list()
    assert foer["clean"] == 1
    assert foer["blocked"] == 1
    assert foer["not_tested"] == 1
    assert len(foer["scanned"]) == 3


def test_dashbordet_teller_bare_det_som_faktisk_ble_testet(state):
    state._record_sandbox(rapport("not_tested", package_name="krasjet"))
    state._record_sandbox(rapport("clean", package_name="rent"))
    state._record_sandbox(rapport("blocked", package_name="stoppet"))

    o = build_overview(cards=[], before=state.before_list())
    # To ble testet, ikke tre: det som aldri kom i gang teller ikke med.
    assert o["sandbox"]["tested"] == 2
    assert o["sandbox"]["blocked"] == 1


def test_demoen_har_ingen_not_tested(state):
    while state.step_feed() is not None:
        pass
    assert state.before_list()["not_tested"] == 0


# ---------------------------------------------------------------------------
# UI-tekster
# ---------------------------------------------------------------------------


def test_alle_regelnavn_har_norsk_tekst_i_ui():
    """Et regelnavn uten tekst vises raatt som `destructive_change` i brikken."""
    import pathlib
    import re

    js = (pathlib.Path(__file__).resolve().parents[1] / "ui" / "static" / "app.js").read_text(
        encoding="utf-8"
    )
    blokk = js.split("const RULE_TEXT = {", 1)[1].split("};", 1)[0]
    i_ui = set(re.findall(r"^\s*(\w+):", blokk, re.M))

    alle = {n for n, _ in rules.RISK_RULES} | {n for n, _ in rules.BLOCK_RULES}
    alle |= {"sandbox_blocked", "recipient_total_over_limit"}
    assert alle <= i_ui, sorted(alle - i_ui)


def test_foer_listen_i_ui_viser_ikke_testet_som_egen_tilstand():
    """«Ikke testet» maa vaere en tredje tilstand, ikke en variant av «rent».

    Testen spoer etter innholdet, ikke etter en bestemt formulering: Foer-
    visningen er skrevet om, og en test som laaser teksten ville stoppet enhver
    omskriving uten aa si noe om det som faktisk betyr noe.
    """
    import pathlib
    import re

    js = (pathlib.Path(__file__).resolve().parents[1] / "ui" / "static" / "app.js").read_text(
        encoding="utf-8"
    )

    # Alle tre verdiktene har sin egen tilstand i UI.
    tilstander = re.search(r"const BEFORE_STATE = \{(.+?)\n\};", js, re.S)
    assert tilstander, "Foer-visningen maa ha en tabell over tilstandene"
    blokk = tilstander.group(1)
    for verdict in ("blocked", "clean", "not_tested"):
        assert f"{verdict}:" in blokk, verdict

    # Og de tre skal ha hver sin etikett - ikke samme ord to ganger.
    etiketter = re.findall(r'tekst: "([^"]+)"', blokk)
    assert len(etiketter) == 3 and len(set(etiketter)) == 3, etiketter

    # «Rent» skal si hva det IKKE betyr, paa stedet der det staar.
    assert "ikke det samme som at tillegget er trygt" in js
    # «Ikke testet» skal ikke kunne leses som en klarering.
    assert "Vi vet ikke hva tillegget ville gjort" in js


def test_loggsjekken_kjoeres_automatisk_i_ui():
    """Ringen skal vise OK uten at noen trykker, men aldri foer sjekken er kjoert."""
    import pathlib

    js = (pathlib.Path(__file__).resolve().parents[1] / "ui" / "static" / "app.js").read_text(
        encoding="utf-8"
    )
    assert "async function verifyQuietly()" in js
    # Ved oppstart, naar stroemmen er ferdig, og etter Nullstill.
    assert js.count("verifyQuietly()") >= 3
    # Den bruker den ekte ruten, ikke en snarvei.
    etter = js.split("async function verifyQuietly()", 1)[1][:400]
    assert '/api/verify' in etter
