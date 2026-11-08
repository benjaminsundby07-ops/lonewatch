"""Angriperens verktoeykasse. Importeres av testene i tests/attack/.

Alt her er hjelpemidler for angrepene, ikke forsvar. Ingenting i denne mappen
roerer kode utenfor tests/attack/ og docs/ANGREP.md.

Noekler og loggfil kommer fra `tests/conftest.py` (fiksturen `lonewatch_env`),
som gir hver test ferske, tilfeldige noekler og en loggfil i tmp. Ingen angrep
her skriver til prosjektets ekte logg, og ingen noekkel skrives ut.

Ingen sonde peker ut mot internett: oppdiktede adresser bruker
`.example`/`.invalid` eller RFC 5737-nettet 192.0.2.0/24, som ikke rutes.
"""

from __future__ import annotations

import json
import socket
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from contracts import ActionRequest, ActionType

# Fast tidspunkt, slik at angrepene gir samme svar hver gang.
T0 = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)


def req(**kw: Any) -> ActionRequest:
    """En ActionRequest angriperen kan vri paa. Standard: en liten, lovlig overfoering."""
    base: dict[str, Any] = dict(
        id="atk_0001",
        ts=T0,
        agent_id="agent_angrep",
        action_type=ActionType.TRANSFER_MONEY,
        summary="rutinemessig oppgjoer",
        amount=1_000.0,
        recipient="NO93 8601 1117 947",
        recipient_known=True,
    )
    base.update(kw)
    return ActionRequest(**base)


def minutes(n: int) -> datetime:
    return T0 + timedelta(minutes=n)


def human_headers() -> dict[str, str]:
    """Menneskenoekkelen testmiljoeet har satt (foerste av flere).

    Staar her og ikke som en fikstur, slik at `Client` kan bruke den uten at
    hver test maa ta imot noe.
    """
    import os

    keys = (os.environ.get("LONEWATCH_HUMAN_KEY") or "").split(",")
    return {"X-Lonewatch-Human-Key": keys[0].strip()}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class Client:
    """Minimal HTTP-klient. Ingen nettleser, ingen informasjonskapsel, ingen token."""

    def __init__(self, base: str) -> None:
        self.base = base

    def get(self, path: str, headers: dict[str, str] | None = None) -> tuple[int, Any]:
        request = urllib.request.Request(self.base + path, headers=headers or {}, method="GET")
        with urllib.request.urlopen(request, timeout=10) as res:
            return res.status, json.loads(res.read())

    def post(
        self,
        path: str,
        body: dict | None = None,
        content_type: str = "application/json",
        headers: dict[str, str] | None = None,
    ) -> tuple[int, Any]:
        data = json.dumps(body or {}).encode()
        head = {"Content-Type": content_type}
        head.update(headers or {})
        request = urllib.request.Request(self.base + path, data=data, headers=head, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=10) as res:
                return res.status, json.loads(res.read())
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()[:400].decode("utf-8", "replace")

    # -- hjelpere for angrepene ------------------------------------------

    def drain_feed(self) -> None:
        """Slipper alle demoforespoerslene gjennom, slik at koen fylles.

        Sender menneskenoekkelen. /api/feed/step er en SKRIVENDE rute og ligger
        bak den (den var aapen til runde to; se H25 i docs/ANGREP.md). Dette er
        oppsettet et angrep gjoer FOER angrepet, ikke angrepet - at ruten
        krever noekkelen maales av `test_demo_write_routes_require_the_human_key`.
        """
        for _ in range(500):
            _, body = self.post("/api/feed/step", headers=human_headers())
            if not isinstance(body, dict) or body.get("card") is None:
                return
        raise AssertionError("stroemmen stoppet ikke")

    def waiting(self) -> list[dict]:
        """Koeen slik et INNLOGGET menneske ser den (hele kortet).

        Uten noekkelen gir /api/state et minimert syn (maskert mottaker, ingen
        summary, ingen regelnavn - A1 i docs/ANGREP2.md). Angrepene maaler paa
        hele kortet, saa de leser som mennesket.
        """
        _, snap = self.get("/api/state", headers=human_headers())
        return list(snap["waiting"])

    def cards_with_amount_gate(self) -> list[dict]:
        return [c for c in self.waiting() if c["decision"]["requires_typed_amount"]]


# ---------------------------------------------------------------------------
# serverfiksturen
# ---------------------------------------------------------------------------
#
# Fiksturen ligger HER og ikke i conftest.py med vilje: da kan hver
# angrepsmodul importere den selv (`from attack_lib import live_app`), og den
# er ikke avhengig av at en delt conftest.py ser ut paa én bestemt maate.


@pytest.fixture()
def live_app():
    """Den ekte appen, startet paa en ledig port paa 127.0.0.1, stoppet etterpaa."""
    uvicorn = pytest.importorskip("uvicorn")
    from ui.app import app

    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        threading.Event().wait(0.05)
    else:
        server.should_exit = True
        thread.join(timeout=5)
        pytest.skip("appen kom ikke opp")

    try:
        yield Client(f"http://127.0.0.1:{port}")
    finally:
        server.should_exit = True
        thread.join(timeout=5)
