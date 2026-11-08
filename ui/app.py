"""FastAPI-appen. Én nettside, ingen byggesteg, ren HTML/CSS/JS.

Appen inneholder ingen regler. Den spoer gateway og vault, og viser svaret.
"""

from __future__ import annotations

import hmac
import os
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from ui.state import (
    MAX_PACKAGE_CHARS,
    MAX_RECIPIENT_CHARS,
    MAX_SUMMARY_CHARS,
    DemoState,
)

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Lonewatch", docs_url=None, redoc_url=None)
state = DemoState()

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class CustomIn(BaseModel):
    """En forespørsel juryen har skrevet i "Prøv selv".

    Lengdegrensene staar her OG i ui/state.py: her for aa avvise det som er
    aapenbart for stort foer vi gjoer noe, der fordi state.py ogsaa kalles
    direkte fra tester og kan ikke stole paa at noen har validert foerst.

    Merk hva som IKKE staar her: `recipient_known` og `reversible`. De regnes
    ut i integrasjonslaget. Den som skriver en forespørsel skal ikke kunne
    paastaa at en ukjent konto er kjent.
    """

    action_type: str = Field(max_length=40)
    summary: str = Field(default="", max_length=MAX_SUMMARY_CHARS)
    amount: str = Field(default="", max_length=64)
    recipient: str = Field(default="", max_length=MAX_RECIPIENT_CHARS)
    package_name: str = Field(default="", max_length=MAX_PACKAGE_CHARS)
    contains_personal_data: bool = False


class RespondIn(BaseModel):
    request_id: str
    approved: bool
    typed_amount: str | None = None
    seconds_to_decide: float = 0.0


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/state")
def api_state() -> dict:
    return state.snapshot()


@app.post("/api/feed/step")
def api_feed_step() -> dict:
    """Slipper neste forespoersel fra demodataene gjennom mellomstasjonen."""
    card = state.step_feed()
    return {"card": card, "state": state.snapshot()}


@app.post("/api/respond")
def api_respond(body: RespondIn) -> dict:
    """Mennesket godkjenner eller avviser en roed forespoersel."""
    result = state.respond(
        request_id=body.request_id,
        approved=body.approved,
        typed_amount=body.typed_amount,
        seconds_to_decide=body.seconds_to_decide,
    )
    return {**result, "state": state.snapshot()}


@app.post("/api/custom")
def api_custom(body: CustomIn) -> dict:
    """"Prøv selv": juryens egen forespørsel gjennom samme vei som de 40."""
    result = state.submit_custom(
        action_type=body.action_type,
        summary=body.summary,
        amount=body.amount,
        recipient=body.recipient,
        package_name=body.package_name,
        contains_personal_data=body.contains_personal_data,
    )
    return {**result, "state": state.snapshot()}


@app.get("/api/custom/help")
def api_custom_help() -> dict:
    """Handlingstyper og eksempler paa kjente mottakere, til skjemaet."""
    return state.custom_help()


@app.get("/api/log")
def api_log() -> dict:
    """Logglinjene som tabell, pluss fellene i dokumentene.

    Alt kommer fra loggen og fra agents/traps.py. Ingenting er regnet ut for
    aa se pent ut.
    """
    return {"log": state.log_rows(), "traps": state.traps_overview()}


@app.get("/api/trail/{request_id}")
def api_trail(request_id: str) -> dict:
    """«Dette ledet hit»: hva samme agent gjorde rett foer."""
    return {"trail": state.agent_trail(request_id)}


@app.get("/api/overview")
def api_overview() -> dict:
    """Tallene til dashbordet, regnet fra tilstanden og loggen.

    Samme form som LONEWATCH_DATA i design-handoff/, saa svaret kan sendes
    rett inn i Lonewatch.setData(...).
    """
    return state.overview()


@app.get("/api/verify")
def api_verify() -> dict:
    """Sjekk loggen: kaller vault.verify()."""
    return state.verify()


@app.get("/api/after")
def api_after() -> dict:
    """Etter-listen fra vault.after.build_after_actions, hvis den finnes."""
    return state.after_actions()


@app.post("/api/story/start")
def api_story_start() -> dict:
    return {"story": state.story_start(), "state": state.snapshot()}


@app.post("/api/story/step")
def api_story_step() -> dict:
    return {"story": state.story_step(), "state": state.snapshot()}


@app.get("/api/story")
def api_story() -> dict:
    return state.story_snapshot()


@app.post("/api/reset")
def api_reset() -> dict:
    """Nullstiller demoen: tom logg, tom koe, historien ikke spilt."""
    state.reset()
    return state.snapshot()


# -- den ekte agenten (MCP) -------------------------------------------------
#
# ALT som gjelder broen mot en agent som faktisk kjører, står i denne blokken,
# samlet med vilje: resten av filen skal se ut som før, og dette skal være
# enkelt å lese, flytte eller fjerne. Se docs/EKTE_AGENT.md og
# agent_gateway/LIMITS.md.
#
# Tre valg som ikke er pyntet på:
#
# 1. Endepunktene er AV uten en delt hemmelighet. `LONEWATCH_AGENT_KEY` må
#    være satt i terminalen som kjører appen, ellers svarer de 503. Da kan
#    ingen annen prosess på maskinen legge noe i godkjenningskøen ved et uhell.
# 2. Bare kall fra 127.0.0.1 slipper inn, uansett hva appen er bundet til.
#    Setter noen LONEWATCH_HOST=0.0.0.0, er dette siste skanse.
# 3. Agenten får ikke regelnavnene tilbake. De ville vært en oppskrift på hva
#    som må endres for å slippe gjennom neste gang.

ENV_AGENT_KEY = "LONEWATCH_AGENT_KEY"
AGENT_KEY_HEADER = "X-Lonewatch-Agent-Key"

# Adresser vi regner som "denne maskinen".
LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost"})


class AgentSubmitIn(BaseModel):
    """Et verktøykall fra en agent som faktisk kjører.

    `extra="forbid"` er poenget her: sender agenten med `recipient_known`,
    `reversible`, `agent_id` eller `id`, får den 422 i stedet for at feltet blir
    stilltiende brukt eller stilltiende ignorert. De fire feltene finnes ikke i
    modellen, og de regnes ut i ui/state.py.
    """

    model_config = ConfigDict(extra="forbid")

    action_type: str = Field(max_length=40)
    summary: str = Field(default="", max_length=MAX_SUMMARY_CHARS)
    amount: str = Field(default="", max_length=64)
    recipient: str = Field(default="", max_length=MAX_RECIPIENT_CHARS)
    package_name: str = Field(default="", max_length=MAX_PACKAGE_CHARS)
    contains_personal_data: bool = False


class AgentAbandonIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    waited_seconds: float = Field(default=0.0, ge=0, le=86400)


def _agent_guard(request: Request) -> None:
    """Slipper bare inn lokale kall med riktig delt hemmelighet."""
    expected = (os.environ.get(ENV_AGENT_KEY) or "").strip()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail=(
                "Broen mot en ekte agent er av. Sett LONEWATCH_AGENT_KEY i "
                "terminalen som kjører appen, og start den på nytt."
            ),
        )

    host = request.client.host if request.client else ""
    if host not in LOOPBACK:
        raise HTTPException(
            status_code=403,
            detail="Broen svarer bare på kall fra denne maskinen (127.0.0.1).",
        )

    given = request.headers.get(AGENT_KEY_HEADER) or ""
    if not hmac.compare_digest(given.encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(status_code=403, detail="Feil eller manglende nøkkel.")


def _lw_name(request_id: str) -> str:
    """Samme visningsnavn som nettsiden bruker, slik at agenten og mennesket
    snakker om det samme kortet. Serie 8 er den ekte agenten."""
    prefix, _, number = str(request_id).partition("_")
    serie = {"req": 1, "story": 2, "agent": 8, "custom": 9}.get(prefix)
    if serie is None or not number.isdigit():
        return str(request_id)
    return f"LW-{serie}{number.zfill(3)[-3:]}"


def _agent_view(request_id: str, card_or_status: dict) -> dict:
    """Det agenten får se. Regelnavnene (`reasons`) er ikke med."""
    verdict = card_or_status.get("verdict")
    ut = {
        "ok": True,
        "request_id": request_id,
        "name": _lw_name(request_id),
        "status": card_or_status.get("status"),
        "verdict": verdict,
        "risk": card_or_status.get("risk"),
        "requires_typed_amount": card_or_status.get("requires_typed_amount", False),
    }
    if verdict == "block":
        # Kort avvisning. Konsekvensteksten navngir hva som slo til, og det
        # ville vært et tips om hvordan den kan omgås.
        ut["consequence_text"] = None
    else:
        ut["consequence_text"] = card_or_status.get("consequence_text")
    return ut


@app.get("/api/agent/ping")
def api_agent_ping(_: None = Depends(_agent_guard)) -> dict:
    """Kommer MCP-tjeneren inn? Brukes til å feilsøke oppsettet, gjør ingenting."""
    return {"ok": True, "app": "lonewatch"}


@app.post("/api/agent/submit")
def api_agent_submit(body: AgentSubmitIn, _: None = Depends(_agent_guard)) -> dict:
    """Et verktøykall fra en ekte agent, inn samme vei som "Prøv selv"."""
    result = state.submit_agent(
        action_type=body.action_type,
        summary=body.summary,
        amount=body.amount,
        recipient=body.recipient,
        package_name=body.package_name,
        contains_personal_data=body.contains_personal_data,
    )
    if not result.get("ok"):
        # Forespørselen holdt ikke formelt. Den er ikke vurdert, og det sier vi.
        return {"ok": False, "error": result.get("error")}

    card = result["card"]
    request_id = card["request"]["id"]
    return _agent_view(request_id, {**card["decision"], "status": card["status"]})


@app.get("/api/agent/status/{request_id}")
def api_agent_status(request_id: str, _: None = Depends(_agent_guard)) -> dict:
    """Hvor står en rød forespørsel nå? Svarer med en gang, venter aldri."""
    status = state.agent_status(request_id)
    if status is None:
        return {"ok": False, "error": "Finner ikke forespørselen."}
    ut = _agent_view(request_id, status)
    ut["approved"] = status.get("approved")
    ut["typed_amount"] = status.get("typed_amount")
    return ut


@app.post("/api/agent/abandon/{request_id}")
def api_agent_abandon(
    request_id: str, body: AgentAbandonIn, _: None = Depends(_agent_guard)
) -> dict:
    """Agenten sluttet å vente. Blir en notis i UI - ingenting i loggen.

    Ingen `HumanResponse` har skjedd, så loggen skal ikke si at noen svarte.
    Kortet blir liggende i køen og venter fortsatt på et menneske.
    """
    noted = state.agent_gave_up(request_id, body.waited_seconds)
    return {"ok": True, "noted": noted}
