"""Angrep 8: agentverktoeyene (MCP).

`agent_gateway/` FINNES IKKE i denne grenen. Angrepet kan derfor ikke
gjennomfoeres slik det var tenkt, og det sies rett ut her i stedet for aa bli
borte i stillhet.

Det som KAN testes er invarianten angrepet egentlig handler om: finnes det noe
kall - et verktoey, et felt, et endepunkt - som godkjenner noe uten aa gaa
gjennom `DemoState.respond()`? Det er testet under, og svaret er nei.

Testen over `agent_gateway` er skrudd paa automatisk hvis mappen dukker opp
senere, slik at angrepet ikke blir glemt naar grenen vokser.
"""

from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path

import pytest

PROSJEKT = Path(__file__).resolve().parents[2]


def _har_agent_gateway() -> bool:
    return (PROSJEKT / "agent_gateway").is_dir()


# ---------------------------------------------------------------------------
# selve angrepet: hoppet over, med begrunnelse
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not _har_agent_gateway(),
    reason=(
        "HOPPET OVER: agent_gateway/ finnes ikke i grenen 'angrep'. Det finnes "
        "heller ingen MCP-flate noe sted i prosjektet (ingen treff paa 'mcp', "
        "'tool_call' eller 'list_tools' i noen .py- eller .md-fil). Angrep 8 "
        "er derfor ikke utfoert, og vi kan ikke si noe om det. Lages "
        "agent_gateway/ senere, slaar denne testen seg paa av seg selv."
    ),
)
def test_no_agent_tool_can_approve_anything():
    import agent_gateway  # noqa: PLC0415 - finnes bare hvis mappen finnes

    mistenkelige = []
    for navn, obj in inspect.getmembers(agent_gateway):
        if navn.startswith("_") or not callable(obj):
            continue
        kilde = ""
        try:
            kilde = inspect.getsource(obj)
        except (OSError, TypeError):
            continue
        if "approved" in kilde or "HumanResponse" in kilde:
            mistenkelige.append(navn)
    assert not mistenkelige, (
        "disse i agent_gateway roerer godkjenning: " + ", ".join(mistenkelige)
    )


def test_the_branch_really_has_no_agent_gateway_and_no_mcp_surface():
    """Fester hvorfor angrep 8 er hoppet over, slik at det ikke blir en paastand."""
    assert not _har_agent_gateway()
    assert importlib.util.find_spec("agent_gateway") is None

    # Bare kode teller. docs/ANGREP.md nevner MCP fordi den forklarer nettopp
    # at flaten ikke finnes.
    treff = []
    for sti in PROSJEKT.rglob("*.py"):
        if any(del_ in sti.parts for del_ in (".git", ".venv", "tests")):
            continue
        tekst = sti.read_text(encoding="utf-8", errors="replace").lower()
        for noekkelord in ("list_tools", "tool_call", "import mcp", "from mcp"):
            if noekkelord in tekst:
                treff.append(f"{sti.relative_to(PROSJEKT)}: {noekkelord}")
    assert not treff, f"MCP-liknende flate funnet: {treff}"


# ---------------------------------------------------------------------------
# invarianten angrepet handler om
# ---------------------------------------------------------------------------


def test_only_one_place_in_the_whole_app_can_approve_a_card():
    """`STATUS_APPROVED` settes paa noeyaktig ett sted: `DemoState.respond()`."""
    kilde = (PROSJEKT / "ui" / "state.py").read_text(encoding="utf-8")
    tilordninger = [
        linje.strip()
        for linje in kilde.splitlines()
        if 'card["status"] =' in linje and "!=" not in linje
    ]
    assert tilordninger == ['card["status"] = STATUS_APPROVED if approved else STATUS_REJECTED']

    respond = inspect.getsource(__import__("ui.state", fromlist=["DemoState"]).DemoState.respond)
    assert "STATUS_WAITING" in respond, "respond maa kreve at kortet venter"
    assert "requires_typed_amount" in respond, "respond maa sjekke beloepsporten"
    assert "amount_matches" in respond


def test_no_other_http_endpoint_writes_a_human_response():
    """Bare /api/respond kan legge en `HumanResponse` i loggen."""
    from ui.app import app

    poster = sorted(
        rute.path
        for rute in app.routes
        if "POST" in getattr(rute, "methods", set())
    )
    assert poster == [
        "/api/custom",
        "/api/feed/step",
        "/api/reset",
        "/api/respond",
        "/api/story/start",
        "/api/story/step",
    ], f"ny POST-rute uten angrepsdekning: {poster}"

    state_kilde = (PROSJEKT / "ui" / "state.py").read_text(encoding="utf-8")
    assert state_kilde.count("HumanResponse(") == 1, (
        "HumanResponse lages paa mer enn ett sted"
    )


def test_a_request_field_cannot_carry_an_approval():
    """`ActionRequest` har ingen vei til aa be om sin egen godkjenning."""
    from contracts import ActionRequest

    felt = set(ActionRequest.model_fields)
    for forbudt in ("approved", "verdict", "risk", "pre_approved", "requires_typed_amount"):
        assert forbudt not in felt, f"ActionRequest har feltet {forbudt}"

    # Og et ukjent felt avvises med én gang (`Strict` / extra='forbid').
    with pytest.raises(Exception):
        ActionRequest.model_validate(
            {
                "id": "x",
                "ts": "2026-11-08T12:00:00+00:00",
                "agent_id": "a",
                "action_type": "transfer_money",
                "summary": "s",
                "approved": True,
            }
        )
