"""Tallene dashbordet tegnes fra.

Regelen i ui/overview.py er at vi bare viser tall vi faktisk har. Testene her
sjekker at summene gaar opp, at formen er den design-handoff/DATASHAPE.md
beskriver, og at en tom logg gir "–" (None) i stedet for et oppdiktet tall.
"""

from __future__ import annotations

import json
import pathlib
import re

import pytest

from contracts import ActionType
from ui.overview import CHART_BUCKETS, TEXT, build_overview, empty_overview
from ui.state import DemoState


@pytest.fixture()
def state() -> DemoState:
    s = DemoState()
    yield s
    s.close()


def drained(state: DemoState) -> dict:
    while state.step_feed() is not None:
        pass
    return state.overview()


# ---------------------------------------------------------------------------
# summene
# ---------------------------------------------------------------------------


def test_demoens_tall_summerer_seg_til_40(state):
    c = drained(state)["counts"]
    assert c["allowed"] == 32
    assert c["red"] == 7
    assert c["blocked"] == 1
    assert c["allowed"] + c["red"] + c["blocked"] == c["evaluated"] == 40


def test_ventende_og_fulgt_opp_summerer_seg_til_roede(state):
    """waitingForHuman + followedUp maa vaere noeyaktig red.

    Ellers er broeken "x av y" under kortene en paastand, ikke en maaling.
    """
    c = drained(state)["counts"]
    assert c["waitingForHuman"] + c["followedUp"] == c["red"]
    assert c["waitingForHuman"] == 7
    assert c["followedUp"] == 0


def test_et_svar_fra_et_menneske_flytter_fra_ventende_til_fulgt_opp(state):
    drained(state)
    roedt = state.snapshot()["waiting"][0]["request"]["id"]
    state.respond(roedt, approved=False)

    c = state.overview()["counts"]
    assert c["waitingForHuman"] == 6
    assert c["followedUp"] == 1
    assert c["waitingForHuman"] + c["followedUp"] == c["red"] == 7


def test_per_agent_summene_er_lik_totalen(state):
    o = drained(state)
    agents = o["agents"]
    c = o["counts"]

    assert sum(a["actions"] for a in agents) == c["evaluated"]
    assert sum(a["red"] for a in agents) == c["red"]
    assert sum(a["blocked"] for a in agents) == c["blocked"]
    assert sum(a["allowed"] for a in agents) == c["allowed"]
    # Og hver rad gaar opp for seg selv.
    for a in agents:
        assert a["red"] + a["blocked"] + a["allowed"] == a["actions"], a["id"]


def test_agentene_har_navn_paa_begge_spraak(state):
    for a in drained(state)["agents"]:
        assert a["name"]["no"]
        assert a["name"]["en"]
        assert a["id"]


def test_egne_forespoersler_telles_med(state):
    foer = drained(state)["counts"]["evaluated"]
    state.submit_custom(action_type="update_calendar", summary="min egen")

    o = state.overview()
    assert o["counts"]["evaluated"] == foer + 1
    assert any(a["id"] == "jury" for a in o["agents"])
    assert sum(a["actions"] for a in o["agents"]) == o["counts"]["evaluated"]


# ---------------------------------------------------------------------------
# tom logg
# ---------------------------------------------------------------------------


def test_tom_logg_gir_nuller_uten_krasj(state):
    o = state.overview()
    c = o["counts"]
    assert c == {
        "evaluated": 0, "red": 0, "blocked": 0,
        "allowed": 0, "waitingForHuman": 0, "followedUp": 0,
    }
    assert o["agents"] == []
    # Ingen har sjekket loggen ennaa: ringen skal staa tom, ikke si "OK".
    assert o["logChain"] == {"status": None, "checkedAt": None}
    assert o["sandbox"] == {"tested": 0, "blocked": 0}
    assert len(o["chartShapes"]) == 3
    json.dumps(o)


def test_helt_uten_kort_gir_flate_kurver_som_fortsatt_kan_tegnes():
    o = build_overview(cards=[])
    for kurve in o["chartShapes"]:
        assert len(kurve["data"]) == CHART_BUCKETS
        assert set(kurve["data"]) == {0}
    assert o["chartShapes"][1]["marks"] == []


def test_tomt_datasett_gir_strek_overalt():
    o = empty_overview("ingen forbindelse")
    assert all(v is None for v in o["counts"].values())
    assert o["isExample"] is False
    assert o["logChain"]["status"] is None
    assert o["sandbox"] == {"tested": None, "blocked": None}
    json.dumps(o)


def test_nullstilling_setter_tallene_tilbake(state):
    drained(state)
    state.reset()
    assert state.overview()["counts"]["evaluated"] == 0


# ---------------------------------------------------------------------------
# formen DATASHAPE beskriver
# ---------------------------------------------------------------------------


def test_svaret_har_formen_dashbordet_forventer(state):
    o = drained(state)
    assert {
        "isExample", "defaultLang", "counts", "agents",
        "logChain", "sandbox", "log", "chartShapes", "text",
    } <= set(o)
    assert o["isExample"] is False, "eksempelmerkelappen skal vaere borte"
    assert o["defaultLang"] == "no"
    assert set(o["text"]) == {"no", "en"}
    for lang in ("no", "en"):
        t = o["text"][lang]
        # DATASHAPE: mangler status, stats, cols eller nav tegnes ikke dashbordet.
        assert len(t["nav"]) == 5
        assert len(t["stats"]) == 3
        assert len(t["cols"]) == 5
        assert set(t["status"]) == {"ok", "broken", "none"}
    json.dumps(o)


def test_kurvene_er_ekte_tall_og_marks_er_gyldige_indekser(state):
    o = drained(state)
    vurdert, roede, blokkert = o["chartShapes"]

    # Summen av boettene er totalen: dette er et forloep, ikke pynt.
    assert sum(vurdert["data"]) == o["counts"]["evaluated"]
    assert sum(roede["data"]) == o["counts"]["red"]
    assert sum(blokkert["data"]) == o["counts"]["blocked"]

    # DATASHAPE: en marks-indeks utenfor data gjoer at dashbordet ikke tegnes.
    for i in roede["marks"]:
        assert 0 <= i < len(roede["data"])
        assert roede["data"][i] > 0

    # Ingen ghost: vi har ingen andre serie, og en pen kurve uten tall bak er
    # en paastand vi ikke kan staa for.
    for kurve in o["chartShapes"]:
        assert "ghost" not in kurve


def test_loggkjeden_sier_ikke_ok_foer_noen_har_sjekket(state):
    drained(state)
    assert state.overview()["logChain"]["status"] is None

    state.verify()
    lc = state.overview()["logChain"]
    assert lc["status"] == "ok"
    assert lc["checkedAt"]


def test_sandkassen_kommer_fra_ekte_skanninger(state):
    o = drained(state)
    foer = state.snapshot()["before"]
    assert o["sandbox"]["tested"] == len(foer["scanned"])
    assert o["sandbox"]["blocked"] == foer["blocked"]
    assert o["sandbox"]["tested"] == 2
    assert o["sandbox"]["blocked"] == 1


def test_fanenavnet_er_godkjenning_ikke_under():
    assert TEXT["no"]["nav"][2] == "Godkjenning"
    assert TEXT["en"]["nav"][2] == "Approval"


def test_tidsetiketten_lover_ikke_et_filter_som_ikke_finnes():
    """"I dag" ville paastaatt et doegnfilter. Det finnes ikke."""
    assert TEXT["no"]["range"] == "Denne økten"
    assert TEXT["en"]["range"] == "This session"


# ---------------------------------------------------------------------------
# ruten
# ---------------------------------------------------------------------------


def test_ruten_finnes():
    """Uten `state`-fiksturen: aa importere ui.app lager sin egen DemoState,
    og den ville kollidert med laasen fiksturen holder."""
    import ui.app as app_modul

    assert any(r.path == "/api/overview" for r in app_modul.app.routes)
    assert hasattr(app_modul, "api_overview")


# ---------------------------------------------------------------------------
# offline: ingen fil i ui/ skal hente noe fra nettet
# ---------------------------------------------------------------------------

UI = pathlib.Path(__file__).resolve().parents[1] / "ui"

# Det som faktisk HENTER noe naar siden lastes. Vi leter ikke etter "http" i
# ren tekst: lisensfiler og XML-navnerom inneholder adresser som aldri brukes.
HENTER_EKSTERNT = re.compile(
    r"""(?:src|href)\s*=\s*["']https?://|url\(\s*["']?https?://|@import\s+url\(\s*["']?https?://""",
    re.IGNORECASE,
)

# Tredjeparts biblioteksfiler. De er lastet ned én gang, ligger lokalt, og
# endres aldri. React-DOM har adresser inne i feilmeldinger og XML-navnerom.
UNNTAK = {"vendor"}


def _ui_filer() -> list[pathlib.Path]:
    ut = []
    for f in UI.rglob("*"):
        if not f.is_file() or f.suffix not in {".html", ".css", ".js", ".py"}:
            continue
        if UNNTAK & set(f.relative_to(UI).parts):
            continue
        ut.append(f)
    return ut


def test_ingen_fil_i_ui_henter_noe_fra_nettet():
    """Hele appen skal virke uten internett.

    Dashbordet hentet React fra jsDelivr og skriften fra Google Fonts. Begge
    ligger naa lokalt. Denne testen er det som hindrer at de sniker seg inn
    igjen ved neste kopiering fra design-handoff/.
    """
    syndere = []
    for f in _ui_filer():
        tekst = f.read_text(encoding="utf-8", errors="replace")
        for treff in HENTER_EKSTERNT.findall(tekst):
            syndere.append(f"{f.relative_to(UI)}: {treff}")
    assert syndere == [], "eksterne adresser i ui/: " + "; ".join(syndere)


def test_filene_dashbordet_trenger_ligger_lokalt():
    for sti in [
        "static/vendor/react.production.min.js",
        "static/vendor/react-dom.production.min.js",
        "static/vendor/NOTICE.md",
        "static/vendor/LICENSE-react.txt",
        "static/dashboard/bundle.js",
        "static/dashboard/bundle.css",
        "static/dashboard/tokens.css",
        "static/dashboard/fonts/LICENSE-plus-jakarta-sans.txt",
    ]:
        assert (UI / sti).is_file(), sti
    for vekt in (400, 500, 600):
        assert (UI / f"static/dashboard/fonts/plus-jakarta-sans-latin-{vekt}-normal.woff2").is_file()


def test_react_er_noeyaktig_18_3_1():
    tekst = (UI / "static/vendor/react.production.min.js").read_text(encoding="utf-8")
    assert "18.3.1" in tekst


def test_spraakvalget_er_skjult_men_tekstene_er_beholdt():
    css = (UI / "static/dashboard/bundle.css").read_text(encoding="utf-8")
    assert ".lw-lang { display: none !important; }" in css
    # Begge spraak staar urørt i datasettet.
    assert TEXT["en"]["stats"] == ["Actions evaluated", "Red alerts", "Blocked"]


def test_dashbordet_tegnes_aldri_uten_egne_data():
    """Uten `data`-prop faller React tilbake paa eksempeldataene i bundle.js."""
    app_js = (UI / "static/app.js").read_text(encoding="utf-8")
    assert "Lonewatch.Dashboard, {" in app_js
    kall = app_js.split("Lonewatch.Dashboard, {", 1)[1][:200]
    assert "data: dashboardData" in kall
    assert "if (!dashboardReady() || !dashboardData) return;" in app_js
