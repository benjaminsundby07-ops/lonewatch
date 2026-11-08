"""Angrep 8: agentverktoeyene (MCP) og de to skriverutene agenten eier.

Forrige runde ble dette angrepet **hoppet over**: `agent_gateway/` fantes ikke
i grenen, og det fantes ingen MCP-flate noe sted. Naa finnes begge, og
`/api/agent/submit` og `/api/agent/abandon/{request_id}` er to skriveruter som
en agent kan naa med en noekkel som ligger i `.mcp.json` - altsaa i en fil
agenten selv leser. Da maa de angripes.

Angrepene her er delt i tre:

1. **Kan agenten, via submit, faa et kort til aa se godkjent ut?**
2. **Kan abandon brukes til aa lukke - eller lyve om - en annens kort?**
3. Invarianten angrepet egentlig handler om: finnes det noen vei til en
   godkjenning som ikke gaar gjennom `DemoState.respond()`?

Det som ble FUNNET og FIKSET i denne runden staar i docs/ANGREP.md: abandon og
status svarte paa kort agenten aldri hadde sendt, og abandon kunne skrive
samme notis saa mange ganger den ville. Det som fortsatt er aapent staar som
`xfail(strict=True)` nederst.
"""

from __future__ import annotations

import importlib.util
import inspect
import json
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from attack_lib import live_app
from conftest import HUMAN_KEY

from ui.human_key import HUMAN_KEY_HEADER

PROSJEKT = Path(__file__).resolve().parents[2]

AGENT_KEY_HEADER = "X-Lonewatch-Agent-Key"
AGENTNOEKKEL = "angrep-agentnoekkel-" + "z" * 16

UKJENT_KONTO = "NO93 8601 1117 947"


def _har_agent_gateway() -> bool:
    return (PROSJEKT / "agent_gateway").is_dir()


@pytest.fixture()
def agent(live_app, monkeypatch):
    """Appen med agentbroen slaatt paa, og en klient som snakker som agenten.

    Noekkelen settes i miljoeet her. Det er nettopp slik den ligger i
    virkeligheten: en streng i terminalen som kjoerer appen, og den samme
    strengen i `.mcp.json`.
    """
    monkeypatch.setenv("LONEWATCH_AGENT_KEY", AGENTNOEKKEL)
    live_app.post("/api/reset")
    return live_app


def _agent_call(klient, path, body=None, method=None, noekkel=AGENTNOEKKEL, ekstra=None):
    """Raatt kall mot agentbroen. Gir (status, json-eller-tekst)."""
    data = None if body is None else json.dumps(body).encode()
    headers = {}
    if noekkel is not None:
        headers[AGENT_KEY_HEADER] = noekkel
    if data is not None:
        headers["Content-Type"] = "application/json"
    headers.update(ekstra or {})
    req = urllib.request.Request(
        klient.base + path,
        data=data,
        headers=headers,
        method=method or ("POST" if data is not None else "GET"),
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            return res.status, json.loads(res.read() or b"{}")
    except urllib.error.HTTPError as exc:
        kropp = exc.read()[:400].decode("utf-8", "replace")
        try:
            return exc.code, json.loads(kropp or "{}")
        except json.JSONDecodeError:
            return exc.code, kropp


def _submit(klient, **felt):
    kropp = {
        "action_type": felt.pop("action_type", "transfer_money"),
        "summary": felt.pop("summary", "Faktura 8841"),
        "amount": felt.pop("amount", "450000"),
        "recipient": felt.pop("recipient", UKJENT_KONTO),
        "package_name": felt.pop("package_name", ""),
        "contains_personal_data": felt.pop("contains_personal_data", False),
    }
    kropp.update(felt)
    return _agent_call(klient, "/api/agent/submit", kropp)


# ---------------------------------------------------------------------------
# 0. flaten finnes naa, og noekkelen er paakrevd
# ---------------------------------------------------------------------------


def test_the_mcp_surface_exists_in_this_branch():
    """Fester at angrep 8 KAN kjoeres naa. Forrige runde var det hoppet over."""
    assert _har_agent_gateway()
    assert importlib.util.find_spec("agent_gateway") is not None

    flate = []
    for sti in (PROSJEKT / "agent_gateway").rglob("*.py"):
        tekst = sti.read_text(encoding="utf-8", errors="replace").lower()
        for noekkelord in ("list_tools", "tool_call", "import mcp", "from mcp"):
            if noekkelord in tekst:
                flate.append(f"{sti.relative_to(PROSJEKT)}: {noekkelord}")
    assert flate, "agent_gateway/ finnes, men har ingen MCP-flate - sjekk angrepet"


def test_the_agent_routes_are_off_without_the_key(agent, monkeypatch):
    """Ingen noekkel i miljoeet: 503. Feil noekkel i kallet: 403."""
    monkeypatch.delenv("LONEWATCH_AGENT_KEY", raising=False)
    status, _ = _agent_call(agent, "/api/agent/ping")
    assert status == 503

    monkeypatch.setenv("LONEWATCH_AGENT_KEY", AGENTNOEKKEL)
    for feil in (None, "", "feil-noekkel-helt-feil"):
        status, _ = _agent_call(agent, "/api/agent/ping", noekkel=feil)
        assert status == 403, feil


# ---------------------------------------------------------------------------
# 1. kan agenten, via submit, faa et kort til aa se godkjent ut?
# ---------------------------------------------------------------------------


def test_submit_can_never_produce_an_approved_card(agent):
    """Alle utfallene submit kan gi, og ingen av dem er «godkjent».

    Vi proever de fire veiene gjennom: en groenn, en roed, en blokkert og en
    som ikke holder formelt. Ingen av dem gir `approved`, og ingen av dem
    skriver en `human`-linje i loggen.
    """
    forsoek = [
        # groenn: kjent mottaker, lite beloep
        dict(action_type="read_document", amount="", recipient="rapport.pdf"),
        # roed: ukjent konto
        dict(action_type="transfer_money", amount="450000", recipient=UKJENT_KONTO),
        # blokkert: over den harde grensen
        dict(action_type="transfer_money", amount="99000000", recipient=UKJENT_KONTO),
        # holder ikke formelt: overfoering uten beloep
        dict(action_type="transfer_money", amount="", recipient=UKJENT_KONTO),
    ]
    sett = []
    for felt in forsoek:
        status, svar = _submit(agent, **felt)
        assert status == 200, (felt, svar)
        sett.append(svar)
        assert svar.get("status") != "approved", svar
        assert svar.get("approved") is not True, svar
        assert "human" not in svar

    utfall = {s.get("status") for s in sett}
    assert utfall <= {"allow", "waiting", "blocked", None}, utfall

    # Og ingenting i loggen sier at et menneske svarte.
    _, logg = agent.get("/api/log")
    assert all(rad["utfall"] != "approved" for rad in logg["log"]["rows"])


@pytest.mark.parametrize(
    "forbudt",
    [
        {"approved": True},
        {"status": "approved"},
        {"verdict": "allow"},
        {"risk": "low"},
        {"requires_typed_amount": False},
        {"typed_amount": "450000"},
        {"employee_pseudonym": "emp_0000"},
        {"seconds_to_decide": 30.0},
        {"human": {"approved": True}},
        {"recipient_known": True},
        {"reversible": True},
        {"agent_id": "finance"},
        {"id": "req_0001"},
        {"source": "feed"},
        {"approval": "noe"},
        {"execution": {"executed": True}},
    ],
)
def test_submit_refuses_every_field_that_would_decide_something(agent, forbudt):
    """Et felt som avgjoer noe finnes ikke i modellen, og blir 422 - ikke ignorert.

    Forskjellen betyr noe: et felt som ble stilltiende kastet ville sett ut som
    om agenten kunne sende det, og neste versjon kunne ha begynt aa lese det.
    """
    status, svar = _submit(agent, **forbudt)
    assert status == 422, (forbudt, svar)


def test_submit_cannot_choose_its_own_identity_or_id(agent):
    """`agent_id` og `id` settes av tjeneren. Agenten kan ikke utgi seg for noen."""
    status, svar = _submit(agent, action_type="read_document", amount="", recipient="a.pdf")
    assert status == 200 and svar["ok"] is True
    request_id = svar["request_id"]
    assert request_id.startswith("agent_")

    _, snap = agent.get("/api/state")
    kort = [
        c
        for c in snap["waiting"] + snap["blocked"] + snap["answered"] + snap["calm"]
        if c["request"]["id"] == request_id
    ]
    assert kort, request_id
    assert kort[0]["request"]["agent_id"] == "claude_code"
    assert kort[0]["source"] == "agent"


def test_a_blocked_submit_does_not_hand_out_the_rule_names(agent):
    """Regelnavnene ville vaert en oppskrift paa hva som maa endres neste gang."""
    status, svar = _submit(agent, amount="99000000")
    assert status == 200
    assert svar["verdict"] == "block"
    assert "reasons" not in svar
    assert svar["consequence_text"] is None


def test_submit_cannot_read_the_seal_or_the_execution_of_another_card(agent):
    """Svaret til agenten inneholder ingen forsegling og ingen utfoeringslinje.

    Avtrykket (`Approval.request_fingerprint`) er det eneste som binder en
    godkjenning til NOEYAKTIG den forespoerselen mennesket saa. Faar agenten
    se det, kan den lage en godkjenning som ser riktig ut.
    """
    status, svar = _submit(agent, action_type="read_document", amount="", recipient="a.pdf")
    assert status == 200
    tekst = json.dumps(svar)
    for ord_ in ("approval", "fingerprint", "request_fingerprint"):
        assert ord_ not in tekst, (ord_, svar)


# ---------------------------------------------------------------------------
# 2. kan abandon brukes til aa lukke - eller lyve om - en annens kort?
# ---------------------------------------------------------------------------


def test_abandon_cannot_touch_a_card_the_agent_did_not_send(agent):
    """FUNNET OG FIKSET: abandon svarte paa alle kort, ikke bare agentens egne.

    Foer fiksen kunne agenten kalle abandon paa et vilkaarlig `req_0012` og
    faa dashbordet til aa skrive «Den ekte agenten ventet 120 s paa svar paa
    req_0012». Det er en notis om noe som ikke skjedde, paa en sak agenten
    aldri hadde sendt.
    """
    agent.drain_feed()
    fremmede = [c["request"]["id"] for c in agent.waiting()]
    assert fremmede, "koen skal ha roede kort fra demoen"

    _, foer = agent.get("/api/state")
    notiser_foer = len(foer["notices"])

    for request_id in fremmede:
        status, svar = _agent_call(
            agent, f"/api/agent/abandon/{request_id}", {"waited_seconds": 120.0}
        )
        assert status == 200
        assert svar["noted"] is False, request_id

    _, etter = agent.get("/api/state")
    assert len(etter["notices"]) == notiser_foer, "abandon skrev en notis om en annens kort"
    # Og kortene staar fortsatt og venter.
    assert {c["request"]["id"] for c in agent.waiting()} >= set(fremmede)


def test_abandon_cannot_close_or_decide_anything(agent):
    """Abandon er ikke et nei. Kortet skal staa noeyaktig som foer."""
    status, svar = _submit(agent)
    assert svar["verdict"] == "red"
    request_id = svar["request_id"]

    status, ut = _agent_call(
        agent, f"/api/agent/abandon/{request_id}", {"waited_seconds": 120.0}
    )
    assert status == 200 and ut["noted"] is True

    _, status_svar = _agent_call(agent, f"/api/agent/status/{request_id}")
    assert status_svar["status"] == "waiting"
    assert status_svar["approved"] is None
    assert any(c["request"]["id"] == request_id for c in agent.waiting())

    # Og ingenting i loggen: ingen HumanResponse har skjedd.
    _, logg = agent.get("/api/log")
    assert not [r for r in logg["log"]["rows"] if r["utfall"] in ("approved", "rejected")]


def test_abandon_cannot_be_used_to_flood_the_notices(agent):
    """FUNNET OG FIKSET: én notis per kort, uansett hvor mange ganger den kalles.

    `snapshot()` viser de tolv siste notisene. Uten denne sperren kunne
    agenten kalt abandon i en loekke og skjoevet sandkasserapporter og feller
    ut av listen - altsaa skjult det den som sitter der skulle sett.
    """
    status, svar = _submit(agent)
    request_id = svar["request_id"]

    for _ in range(25):
        status, ut = _agent_call(
            agent, f"/api/agent/abandon/{request_id}", {"waited_seconds": 1.0}
        )
        assert status == 200 and ut["noted"] is True

    _, snap = agent.get("/api/state")
    agentnotiser = [n for n in snap["notices"] if n["kind"] == "agent"]
    assert len(agentnotiser) == 1, len(agentnotiser)


def test_abandon_on_an_unknown_id_writes_nothing(agent):
    """En id som ikke finnes skal ikke kunne smugle tekst inn i en notis."""
    for rusk in ("req_9999", "agent_9999", "../../etc/passwd", "x" * 300, "<b>hei</b>"):
        status, svar = _agent_call(
            agent, f"/api/agent/abandon/{rusk}", {"waited_seconds": 1.0}
        )
        assert status in (200, 404), (rusk, status)
        if status == 200:
            assert svar["noted"] is False, rusk

    _, snap = agent.get("/api/state")
    assert not [n for n in snap["notices"] if n["kind"] == "agent"]


def test_abandon_refuses_a_nonsense_wait(agent):
    """Ventetiden er tall, og den har en oevre grense. Ukjente felt avvises."""
    status, svar = _submit(agent)
    request_id = svar["request_id"]
    for kropp in (
        {"waited_seconds": -1},
        {"waited_seconds": 10**9},
        {"waited_seconds": "evig"},
        {"waited_seconds": 1.0, "approved": True},
        {"approved": True},
    ):
        status, _ = _agent_call(agent, f"/api/agent/abandon/{request_id}", kropp)
        assert status == 422, kropp


def test_status_cannot_read_a_card_the_agent_did_not_send(agent):
    """FUNNET OG FIKSET: status svarte paa alle kort.

    Et kort i menneskets godkjenningskoe inneholder beloep, mottaker og
    konsekvenstekst. Agenten fikk lese alt det paa saker den ikke hadde sendt,
    altsaa lese ut av koeen til mennesket.
    """
    agent.drain_feed()
    fremmede = [c["request"]["id"] for c in agent.waiting()]
    assert fremmede

    for request_id in fremmede:
        status, svar = _agent_call(agent, f"/api/agent/status/{request_id}")
        assert status == 200
        assert svar["ok"] is False, request_id
        assert "consequence_text" not in svar
        assert "amount" not in json.dumps(svar)


# ---------------------------------------------------------------------------
# 3. invarianten: finnes det noen vei til en godkjenning utenom respond()?
# ---------------------------------------------------------------------------


def test_no_agent_tool_can_approve_anything():
    """Ingenting i `agent_gateway` roerer en godkjenning.

    `tools.py` LESER status for aa vite om den skal slutte aa vente. Den
    skriver aldri én. Vi skiller de to ved aa se etter det som ville vaert en
    skriving: at noen lager en `HumanResponse`, eller kaller `respond`.
    """
    import agent_gateway

    mistenkelige = []
    for navn, obj in inspect.getmembers(agent_gateway):
        if navn.startswith("_") or not callable(obj):
            continue
        try:
            kilde = inspect.getsource(obj)
        except (OSError, TypeError):
            continue
        for forbudt in ("HumanResponse", "respond(", "/api/respond", "approved="):
            if forbudt in kilde:
                mistenkelige.append(f"{navn}: {forbudt}")
    assert not mistenkelige, (
        "disse i agent_gateway roerer godkjenning: " + ", ".join(mistenkelige)
    )


def test_the_agent_client_has_no_way_to_reach_the_human_endpoint():
    """`LonewatchClient` er hele agentens vei inn. Den har tre kall, og ingen av
    dem er godkjenningen - og den kjenner ikke menneskenoekkelen."""
    from agent_gateway import client as klient_modul

    kilde = inspect.getsource(klient_modul)
    assert "/api/respond" not in kilde
    assert "Human-Key" not in kilde
    assert HUMAN_KEY_HEADER not in kilde

    from agent_gateway.client import LonewatchClient

    kall = {n for n, _ in inspect.getmembers(LonewatchClient, inspect.isfunction)}
    assert kall == {"__init__", "_call", "_explain", "submit", "status", "abandon"}


def test_the_human_key_is_never_written_into_the_mcp_config():
    """Oppsettet skriver agentnoekkelen i `.mcp.json`. Ikke menneskenoekkelen.

    `.mcp.json` leses av Claude Code. Laa menneskenoekkelen der, ville
    agenten faatt godkjenningsnoekkelen utlevert.
    """
    from agent_gateway.oppsett import MCP_KEYS, build_mcp_config

    assert "LONEWATCH_HUMAN_KEY" not in MCP_KEYS
    config = build_mcp_config(
        None, agent_key="agent-hemmelighet", python="/usr/bin/python3", root=PROSJEKT
    )
    tekst = json.dumps(config)
    assert "LONEWATCH_HUMAN_KEY" not in tekst
    assert "agent-hemmelighet" in tekst  # agentnoekkelen SKAL staa der


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
    """Bare /api/respond kan legge en `HumanResponse` i loggen.

    Listen er med vilje uttoemmende: en ny POST-rute skal gi en feilende test,
    slik at den blir angrepet foer den blir sluppet.
    """
    from ui.app import app

    poster = sorted(
        rute.path for rute in app.routes if "POST" in getattr(rute, "methods", set())
    )
    assert poster == [
        "/api/agent/abandon/{request_id}",
        "/api/agent/submit",
        "/api/custom",
        "/api/feed/step",
        "/api/human/check",
        "/api/reset",
        "/api/respond",
        "/api/story/start",
        "/api/story/step",
    ], f"ny POST-rute uten angrepsdekning: {poster}"

    state_kilde = (PROSJEKT / "ui" / "state.py").read_text(encoding="utf-8")
    assert state_kilde.count("HumanResponse(") == 1, (
        "HumanResponse lages paa mer enn ett sted"
    )


def test_the_approval_route_is_the_only_one_behind_the_human_key():
    """Og den ene ruten som godkjenner er den ene som krever menneskenoekkelen."""
    from ui import app as app_modul

    kilde = inspect.getsource(app_modul)
    assert kilde.count("_human_guard") == 3, "menneskevakten skal staa paa to ruter"
    assert "def api_respond(body: RespondIn, operator: str = Depends(_human_guard))" in kilde


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


# ---------------------------------------------------------------------------
# hullet som staar
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "HULL (kjent fra agent_gateway/LIMITS.md punkt 4, her gjort "
        "kjoerbart): det finnes ingen grense paa hvor mange forespoersler en "
        "agent kan sende. 40 kall fyller godkjenningskoeen med 40 roede kort, "
        "og den som sitter i dashbordet maa gaa gjennom alle for aa finne den "
        "ene som betyr noe. Det er en tjenestenekt mot MENNESKET, ikke mot "
        "appen. En ekte versjon maatte hatt et tak per agent per minutt, og "
        "en maate aa slaa sammen like forespoersler."
    ),
)
def test_an_agent_cannot_fill_the_queue(agent):
    for _ in range(40):
        status, svar = _submit(agent)
        assert status == 200 and svar["verdict"] == "red"
    assert len(agent.waiting()) < 40, "koeen ble fylt av én agent i en loekke"
