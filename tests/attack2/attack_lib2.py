"""Angriperens verktoeykasse for ANDRE runde (tests/attack2/).

Egen fil med vilje: tests/attack2/ laaner ingenting fra tests/attack/ og roerer
ingen kode utenfor tests/attack2/ og docs/ANGREP2.md. Noekler og loggfil kommer
fra den autouse-fiksturen `lonewatch_env` i tests/conftest.py (fersk, tilfeldig
noekkel og en loggfil i tmp for hver test). Ingen test her skriver til
prosjektets ekte logg, og ingen noekkel skrives ut.

Runde to tar for seg det runde en (tests/attack/, docs/ANGREP.md) ikke rakk:
vault i dybden, sandkassen, kapploep, last, de oevrige rutene, kjeding og
informasjonslekkasje.

Ingen sonde peker ut mot internett. Oppdiktede adresser bruker
`.example`/`.invalid` eller RFC 5737-nettet 192.0.2.0/24, som ikke rutes. Alle
servere angrepene starter blir stoppet igjen.
"""

from __future__ import annotations

import json
import os
import socket
import tempfile
import threading
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from contracts import ActionRequest, ActionType

# Fast tidspunkt, slik at angrepene gir samme svar hver gang.
T0 = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)

# Et oppdiktet kontonummer. Ikke en ekte konto, ikke en ekte mottaker.
FAKE_IBAN = "NO93 8601 1117 947"


def req(**kw: Any) -> ActionRequest:
    """En liten, lovlig overfoering angriperen kan vri paa."""
    base: dict[str, Any] = dict(
        id="atk2_0001",
        ts=T0,
        agent_id="agent_angrep2",
        action_type=ActionType.TRANSFER_MONEY,
        summary="rutinemessig oppgjoer",
        amount=1_000.0,
        recipient=FAKE_IBAN,
        recipient_known=True,
    )
    base.update(kw)
    return ActionRequest(**base)


def minutes(n: int) -> datetime:
    return T0 + timedelta(minutes=n)


def fresh_vault(redact: bool = False):
    """En Vault paa tmp-loggen fiksturen satte opp. redact=True = som demoen."""
    from vault import Vault

    return Vault(redact=redact)


def log_file() -> Path:
    """Loggfilen fiksturen peker paa (alltid under tmp)."""
    from vault.store import log_path

    return log_path()


def read_raw_lines() -> list[str]:
    """De krypterte linjene paa disk, slik de ligger der."""
    path = log_file()
    if not path.exists():
        return []
    return [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def write_raw_lines(lines: list[str]) -> None:
    """Skriver raa krypterte linjer tilbake (angriperens redigering av filen)."""
    log_file().write_text("".join(ln + "\n" for ln in lines), encoding="utf-8")


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
        try:
            with urllib.request.urlopen(request, timeout=15) as res:
                return res.status, json.loads(res.read())
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()[:800].decode("utf-8", "replace")

    def get_resp(self, path: str, headers: dict[str, str] | None = None):
        """Hele svaret, slik at hodene kan inspiseres."""
        request = urllib.request.Request(self.base + path, headers=headers or {}, method="GET")
        return urllib.request.urlopen(request, timeout=15)

    def post(
        self,
        path: str,
        body: dict | bytes | None = None,
        content_type: str = "application/json",
        headers: dict[str, str] | None = None,
    ) -> tuple[int, Any]:
        if isinstance(body, bytes):
            data = body
        else:
            data = json.dumps(body or {}).encode()
        head = {"Content-Type": content_type}
        head.update(headers or {})
        request = urllib.request.Request(self.base + path, data=data, headers=head, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=30) as res:
                return res.status, json.loads(res.read())
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()[:800].decode("utf-8", "replace")

    # -- hjelpere -------------------------------------------------------
    def drain_feed(self) -> None:
        """Fyller koeen. Menneskenoekkelen er med fordi /api/feed/step SKRIVER
        og ligger bak den (A12/H25). Oppsett, ikke angrep."""
        for _ in range(500):
            _, body = self.post("/api/feed/step", headers=human_headers())
            if not isinstance(body, dict) or body.get("card") is None:
                return
        raise AssertionError("stroemmen stoppet ikke")

    def waiting(self) -> list[dict]:
        """Koeen slik et INNLOGGET menneske ser den - hele kortet. Uten
        noekkelen gir /api/state det minimerte synet (A1)."""
        _, snap = self.get("/api/state", headers=human_headers())
        return list(snap["waiting"])

    def custom(self, body: dict) -> tuple[int, Any]:
        """"Prøv selv" med menneskenoekkelen. /api/custom ligger bak den (H25:
        en allow herfra utfoeres paa ekte)."""
        return self.post("/api/custom", body, headers=human_headers())


# Delt hemmelighet for den ekte agenten (MCP). Settes i prosessen foer appen
# leses, aldri skrevet til disk.
AGENT_KEY = "attack2-agent-key-local-only"
AGENT_KEY_HEADER = "X-Lonewatch-Agent-Key"


@pytest.fixture()
def live_app():
    """Den ekte appen paa en ledig port paa 127.0.0.1, stoppet etterpaa.

    Egen kopi av fiksturen (ikke den i tests/attack/). Setter ogsaa
    LONEWATCH_AGENT_KEY i prosessen, slik at /api/agent/* kan naas i
    kapploeps- og lasttestene.
    """
    uvicorn = pytest.importorskip("uvicorn")
    os.environ["LONEWATCH_AGENT_KEY"] = AGENT_KEY
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

    client = Client(f"http://127.0.0.1:{port}")
    # ui.app.state er en singleton som deles mellom tester. Nullstill foer hver
    # test, slik at ett angrep ikke arver kort fra det forrige. Noekkelen maa
    # med: /api/reset ligger bak menneskenoekkelen etter runde to (A12).
    client.post("/api/reset", headers=human_headers())
    try:
        yield client
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        os.environ.pop("LONEWATCH_AGENT_KEY", None)


from vault.store import ENV_LOG_PATH  # noqa: E402


@pytest.fixture(autouse=True)
def refuse_to_touch_real_log():
    """Stopper testen om LONEWATCH_LOG_PATH ikke ligger i et tmp-omraade."""
    path = os.environ.get(ENV_LOG_PATH, "")
    tmp_root = os.path.realpath(tempfile.gettempdir())
    resolved = os.path.realpath(path) if path else ""
    # pytest sine tmp_path ligger under tempdir (eller /private/var/... paa mac,
    # som realpath normaliserer). Godta ogsaa "pytest-of-" i stien.
    ok = bool(resolved) and (
        resolved.startswith(tmp_root)
        or "pytest-of-" in resolved
        or "/pytest-" in resolved
        or resolved.startswith("/private/")
    )
    assert ok, (
        f"NEKTER aa kjoere: LONEWATCH_LOG_PATH={path!r} peker ikke paa en "
        "tmp-fil. Et angrep skal aldri roere den ekte loggen."
    )
    yield


def human_headers() -> dict[str, str]:
    """Menneskenoekkelen testmiljoeet har satt (foerste av flere). Uten den avvises /api/respond."""
    keys = os.environ.get("LONEWATCH_HUMAN_KEY", "").split(",")
    return {"X-Lonewatch-Human-Key": keys[0].strip()}
