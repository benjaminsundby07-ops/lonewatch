"""Det som bare kan gaa galt NAAR grenene staar sammen.

Hver gren er testet for seg. Denne filen tester det ingen av dem kunne teste
alene: at designrundens UI, regelsettet fra falske-alarmer, den laaste loggen
fra bryt-loggen og broen mot en ekte agent fortsatt henger sammen etter
sammenslaaingen.

Det er ikke kopier av testene fra grenene. Alt her er noe som var RIKTIG paa
hver gren og likevel kunne bli feil i samme tre.
"""

from __future__ import annotations

import pathlib

import pytest

from contracts import ActionType
from gateway import config, evaluate, rules
from ui.state import SANNTIDS_PREFIKS, TID_SANNTID, TID_SIMULERT, DemoState

ROT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture()
def state() -> DemoState:
    """`conftest.py` gir hver test ferske noekler og en loggfil i tmp."""
    return DemoState()


# ---------------------------------------------------------------------------
# design-runde x ekte-agent: tidskolonnen og en ny kilde
# ---------------------------------------------------------------------------


def test_agentens_kort_staar_som_sanntid_ikke_som_simulert(state):
    """Kjernen i den ene semantiske konflikten i sammenslaaingen.

    `submit_agent()` gaar gjennom `submit_custom()` og faar `datetime.now()`.
    Tidskolonnen i Etter sier hvilken klokke tallet kommer fra, og den ble
    skrevet da `custom_` var den eneste kilden med ekte klokke. Et agentkort
    stemplet med ekte klokke, men merket "simulert", er en loegn i den ene
    kolonnen hele funksjonen finnes for.
    """
    ut = state.submit_agent(
        action_type="transfer_money",
        summary="agentens egen",
        amount="4 000",
        recipient="NO93 8601 1117 947",
    )
    assert ut["ok"] is True
    rid = ut["card"]["request"]["id"]
    assert rid.startswith("agent_")

    rad = next(r for r in state.log_rows()["rows"] if r["request_id"] == rid)
    assert rad["tidsbase"] == TID_SANNTID


def test_demoens_kort_staar_fortsatt_som_simulert(state):
    """Motstykket: rettingen skal ikke gjoere alt til sanntid."""
    while state.step_feed() is not None:
        pass
    demo = [
        r for r in state.log_rows()["rows"]
        if r["request_id"] and not r["request_id"].startswith(SANNTIDS_PREFIKS)
    ]
    assert demo
    for r in demo:
        assert r["tidsbase"] == TID_SIMULERT


def test_sanntidskildene_er_en_liste_noen_har_bestemt():
    """En ny kilde skal legges inn med vilje, ikke fordi navnet ligner."""
    assert SANNTIDS_PREFIKS == ("custom_", "agent_")


# ---------------------------------------------------------------------------
# design-runde x ekte-agent: begge sider lever i de samme filene
# ---------------------------------------------------------------------------


def test_nettsiden_har_bade_designrundens_fem_visninger_og_agentbroen():
    app_js = (ROT / "ui" / "static" / "app.js").read_text(encoding="utf-8")
    index = (ROT / "ui" / "static" / "index.html").read_text(encoding="utf-8")

    # design-runde: sidemenyen er eneste navigasjon, og den har fem visninger.
    for tab in ("overview", "before", "queue", "after", "custom"):
        assert f'tab: "{tab}"' in app_js, tab
    assert 'el("app-nav").innerHTML' in app_js

    # ekte-agent: egen fil, lastet av nettsiden, og de to stedene den hekter
    # seg paa i app.js.
    assert "/static/agent_live.js" in index
    assert (ROT / "ui" / "static" / "agent_live.js").is_file()
    assert "agent: 8" in app_js
    assert 'card.source === "agent"' in app_js


def test_agentendepunktene_staar_i_ui_app():
    app_py = (ROT / "ui" / "app.py").read_text(encoding="utf-8")
    for rute in (
        "/api/agent/ping",
        "/api/agent/submit",
        "/api/agent/status/{request_id}",
        "/api/agent/abandon/{request_id}",
    ):
        assert rute in app_py, rute


def test_ui_state_har_begge_sider():
    import ui.state as s

    # ekte-agent
    assert hasattr(s.DemoState, "submit_agent")
    assert hasattr(s.DemoState, "agent_status")
    # design-runde
    assert hasattr(s.DemoState, "log_rows")
    assert s.TID_SANNTID != s.TID_SIMULERT


# ---------------------------------------------------------------------------
# falske-alarmer x ekte-agent: reglene gjelder ogsaa en ekte agent
# ---------------------------------------------------------------------------


def test_en_ekte_agent_kan_ikke_sende_en_utbetaling_uten_beloep(state):
    """Regelen fra falske-alarmer maa gjelde den nye veien inn ogsaa.

    `submit_agent` tar `amount` som streng. Tom streng avvises i skjemaet
    (`ui/state.py`), saa en agent kan ikke i det hele tatt faa inn en
    utbetaling uten beloep - og kommer den noen gang forbi skjemaet, staar
    `incomplete_request` i reglene bak.
    """
    ut = state.submit_agent(action_type="transfer_money", amount="", recipient="x")
    assert ut["ok"] is False
    assert "beløp" in ut["error"].lower()


def test_regelen_bak_skjemaet_staar_uansett_hvem_som_spoer():
    """Samme forespoersel, to ulike agent-id-er: samme svar.

    Reglene ser ikke hvem som spoer. En ekte agent faar ikke mildere
    behandling enn demoens agenter, og ikke strengere heller.
    """
    from datetime import datetime, timezone

    from contracts import ActionRequest

    def be(agent_id: str):
        return ActionRequest(
            id="x1",
            ts=datetime(2026, 11, 16, 9, 0, tzinfo=timezone.utc),
            agent_id=agent_id,
            action_type=ActionType.TRANSFER_MONEY,
            summary="s",
            amount=None,
            recipient="kjent konto",
            recipient_known=True,
        )

    demo = evaluate(be("oppgjor-agent"))
    ekte = evaluate(be("claude_code"))
    assert demo.reasons == ekte.reasons == ["incomplete_request"]
    assert demo.verdict is ekte.verdict
    assert rules.no_usable_transfer_amount(be("claude_code")) is True


def test_en_agent_kan_ikke_oppgi_de_to_feltene_vi_setter_selv(state):
    """Fra ekte-agent, men verdt aa holde fast ved i samlet.

    `recipient_known` og `reversible` settes av `submit_custom`, ikke av den
    som spoer. Ellers kunne en agent krysset av for at en ukjent konto er
    kjent. Se "Et prinsipp som ikke kan brytes" i gateway/LIMITS.md.
    """
    ut = state.submit_agent(
        action_type="transfer_money",
        amount=str(int(config.AMOUNT_LIMIT_NOK) + 1),
        recipient="konto ingen har sett foer",
    )
    assert ut["ok"] is True
    req = ut["card"]["request"]
    assert req["recipient_known"] is False
    assert {"amount_over_limit", "unknown_recipient"} <= set(ut["card"]["decision"]["reasons"])


# ---------------------------------------------------------------------------
# bryt-loggen x resten: loggen er fortsatt laast
# ---------------------------------------------------------------------------


def test_bryt_loggen_er_med_og_kjoerer_mot_det_samlede_treet():
    from vault import tamper_demo

    assert hasattr(tamper_demo, "main") or hasattr(tamper_demo, "run")


def test_loggen_holder_ogsaa_naar_en_agent_har_skrevet_i_den(state):
    """Sjekk-av-logg skal gi OK paa en logg som inneholder agentkort."""
    state.submit_agent(
        action_type="send_email",
        summary="agentens egen",
        recipient="post@nordrebilpleie.no",
    )
    while state.step_feed() is not None:
        pass
    assert state.vault.verify() is None
