"""FastAPI-appen. Én nettside, ingen byggesteg, ren HTML/CSS/JS.

Appen inneholder ingen regler. Den spoer gateway og vault, og viser svaret.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ui.state import DemoState

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Lonewatch", docs_url=None, redoc_url=None)
state = DemoState()

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


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
