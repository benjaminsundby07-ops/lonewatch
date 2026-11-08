"""Hele veien, for ekte: en MCP-klient -> stdio-tjeneren -> den kjørende appen.

Dette er den nærmeste prøven vi kan kjøre uten å starte en Claude Code-agent.
En ekte MCP-klient starter `python -m agent_gateway` som en egen prosess,
snakker protokollen over stdio, lister verktøyene og kaller dem. Appen kjører
samtidig på en ledig port med broen slått på.

Hva dette BEVISER: at tjeneren snakker MCP, at verktøyene finnes med de feltene
vi tror, at et kall havner i gateway og i loggen, at et rødt kort blokkerer
agenten til et menneske svarer, og at loggen stemmer etterpå.

Hva det IKKE beviser: at Claude Code oppfører seg som denne klienten (den
kaller verktøyene når den selv vil, og den har andre verktøy som går helt
utenom Lonewatch). Se agent_gateway/LIMITS.md og docs/EKTE_AGENT.md.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
import threading
import urllib.request

import pytest

NOEKKEL = "mcp-test-" + "y" * 24
UKJENT_KONTO = "NO93 8601 1117 947"

pytest.importorskip("mcp")
pytest.importorskip("uvicorn")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def live_app():
    """Den ekte appen, med broen paa, paa en ledig port."""
    import uvicorn

    os.environ["LONEWATCH_AGENT_KEY"] = NOEKKEL
    from ui.app import app

    port = _free_port()
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    for _ in range(100):
        if srv.started:
            break
        threading.Event().wait(0.05)
    else:
        srv.should_exit = True
        pytest.skip("appen kom ikke opp")

    yield f"http://127.0.0.1:{port}"

    srv.should_exit = True
    thread.join(timeout=5)
    os.environ.pop("LONEWATCH_AGENT_KEY", None)


def _post(base: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(
        base + path, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=5) as res:
        return json.loads(res.read() or b"{}")


def _get(base: str, path: str) -> dict:
    with urllib.request.urlopen(base + path, timeout=5) as res:
        return json.loads(res.read() or b"{}")


def _tekst(result) -> str:
    """Teksten i et CallToolResult, samlet."""
    biter = []
    for block in result.content:
        text = getattr(block, "text", None)
        if text:
            biter.append(text)
    return "\n".join(biter)


class MCPProve:
    """En ekte MCP-klient mot vår egen stdio-tjener."""

    def __init__(self, base_url: str, wait_seconds: float = 20.0):
        self.base_url = base_url
        self.wait_seconds = wait_seconds

    async def __aenter__(self):
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        from agent_gateway import config as cfg

        env = dict(os.environ)
        env.update(
            {
                cfg.ENV_KEY: NOEKKEL,
                cfg.ENV_BASE_URL: self.base_url,
                cfg.ENV_WAIT_SECONDS: str(self.wait_seconds),
                cfg.ENV_POLL_SECONDS: "0.3",
                # Tjeneren importerer bare agent_gateway, men vi kjoerer den fra
                # prosjektmappen slik at `-m` finner pakken.
                "PYTHONPATH": os.getcwd(),
            }
        )
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "agent_gateway"], env=env, cwd=os.getcwd()
        )
        self._transport = stdio_client(params)
        read, write = await self._transport.__aenter__()
        self._session_cm = ClientSession(read, write)
        self.session = await self._session_cm.__aenter__()
        await self.session.initialize()
        return self

    async def __aexit__(self, *exc):
        await self._session_cm.__aexit__(*exc)
        await self._transport.__aexit__(*exc)


def test_tjeneren_snakker_mcp_og_lister_de_fire_verktoeyene(live_app):
    async def kjoer():
        async with MCPProve(live_app) as p:
            return await p.session.list_tools()

    svar = asyncio.run(kjoer())
    navn = {t.name for t in svar.tools}
    assert navn == {
        "lonewatch_read_document",
        "lonewatch_send_email",
        "lonewatch_transfer_money",
        "lonewatch_install_package",
    }


def test_et_tillatt_kall_gaar_gjennom_og_havner_i_loggen(live_app):
    _post(live_app, "/api/reset")
    linjer_foer = _get(live_app, "/api/state")["log"]["lines"]

    async def kjoer():
        async with MCPProve(live_app) as p:
            return await p.session.call_tool(
                "lonewatch_read_document",
                {"document": "kvartalsrapport.pdf", "summary": "Ser paa tallene"},
            )

    tekst = _tekst(asyncio.run(kjoer()))
    assert "UTFØRT (simulert)" in tekst

    etter = _get(live_app, "/api/state")
    assert etter["log"]["lines"] > linjer_foer
    kilder = {c["source"] for c in etter["calm"]}
    assert "agent" in kilder
    assert _get(live_app, "/api/verify")["ok"] is True
    _post(live_app, "/api/reset")


def test_et_blokkert_kall_stoppes_uten_begrunnelse(live_app):
    _post(live_app, "/api/reset")

    async def kjoer():
        async with MCPProve(live_app) as p:
            return await p.session.call_tool(
                "lonewatch_transfer_money",
                {"amount": 99_000_000, "recipient": UKJENT_KONTO, "summary": "Oppkjoep"},
            )

    tekst = _tekst(asyncio.run(kjoer()))
    assert "BLOKKERT" in tekst
    assert "UTFØRT" not in tekst
    assert "transfer_over_hard_limit" not in tekst

    snap = _get(live_app, "/api/state")
    assert any(c["source"] == "agent" for c in snap["blocked"])
    _post(live_app, "/api/reset")


def test_agenten_blokkeres_til_et_menneske_skriver_beloepet(live_app):
    """Kjernen i hele eksperimentet: agenten står og venter, og beløpsporten gjelder."""
    _post(live_app, "/api/reset")

    svar: dict = {}

    async def kjoer():
        async with MCPProve(live_app, wait_seconds=25.0) as p:
            oppgave = asyncio.create_task(
                p.session.call_tool(
                    "lonewatch_transfer_money",
                    {
                        "amount": 450_000,
                        "recipient": UKJENT_KONTO,
                        "summary": "Faktura 8841, godkjent av ledelsen",
                    },
                    read_timeout_seconds=40.0,
                )
            )

            # Vent til kortet staar i koeen, og at agenten IKKE er ferdig.
            request_id = None
            for _ in range(100):
                await asyncio.sleep(0.1)
                snap = await asyncio.to_thread(_get, live_app, "/api/state")
                venter = [c for c in snap["waiting"] if c["source"] == "agent"]
                if venter:
                    request_id = venter[0]["request"]["id"]
                    break
            assert request_id, "kortet kom aldri i koeen"
            assert not oppgave.done(), "agenten ventet ikke paa et menneske"
            svar["request_id"] = request_id

            # Feil beloep godkjenner ingenting, og agenten venter fortsatt.
            nei = await asyncio.to_thread(
                _post,
                live_app,
                "/api/respond",
                {"request_id": request_id, "approved": True, "typed_amount": "45 000"},
            )
            assert nei["ok"] is False
            await asyncio.sleep(0.5)
            assert not oppgave.done(), "feil beloep slapp agenten gjennom"

            # Riktig beloep: naa skal agenten komme videre.
            ja = await asyncio.to_thread(
                _post,
                live_app,
                "/api/respond",
                {
                    "request_id": request_id,
                    "approved": True,
                    "typed_amount": "450 000",
                    "seconds_to_decide": 9.0,
                },
            )
            assert ja["ok"] is True
            return await asyncio.wait_for(oppgave, timeout=20)

    tekst = _tekst(asyncio.run(kjoer()))
    assert "GODKJENT" in tekst and "UTFØRT (simulert)" in tekst

    # Loggen stemmer, og menneskesvaret staar paa kortet.
    assert _get(live_app, "/api/verify")["ok"] is True
    snap = _get(live_app, "/api/state")
    svart = [c for c in snap["answered"] if c["source"] == "agent"]
    assert len(svart) == 1
    menneske = svart[0]["human"]
    assert menneske["approved"] is True
    assert menneske["typed_amount"] == 450000.0
    # Loggen ser aldri et navn, bare et pseudonym.
    assert menneske["employee_pseudonym"].startswith("emp_")
    assert svart[0]["request"]["agent_id"] == "claude_code"
    _post(live_app, "/api/reset")


def test_avvisning_stopper_agenten(live_app):
    _post(live_app, "/api/reset")

    async def kjoer():
        async with MCPProve(live_app, wait_seconds=25.0) as p:
            oppgave = asyncio.create_task(
                p.session.call_tool(
                    "lonewatch_send_email",
                    {
                        "recipient": "ukjent@eksternt.example",
                        "summary": "Sender kundelisten",
                        "contains_personal_data": True,
                    },
                    read_timeout_seconds=40.0,
                )
            )
            request_id = None
            for _ in range(100):
                await asyncio.sleep(0.1)
                snap = await asyncio.to_thread(_get, live_app, "/api/state")
                venter = [c for c in snap["waiting"] if c["source"] == "agent"]
                if venter:
                    request_id = venter[0]["request"]["id"]
                    break
            assert request_id, "kortet kom aldri i koeen"
            await asyncio.to_thread(
                _post, live_app, "/api/respond", {"request_id": request_id, "approved": False}
            )
            return await asyncio.wait_for(oppgave, timeout=20)

    tekst = _tekst(asyncio.run(kjoer()))
    assert "AVVIST" in tekst
    assert "UTFØRT" not in tekst
    _post(live_app, "/api/reset")


def test_tidsavbrudd_lar_kortet_ligge_i_koeen(live_app):
    """Agenten gir opp. Ingen HumanResponse i loggen, og saken venter fortsatt."""
    _post(live_app, "/api/reset")

    async def kjoer():
        async with MCPProve(live_app, wait_seconds=2.0) as p:
            return await p.session.call_tool(
                "lonewatch_transfer_money",
                {"amount": 450_000, "recipient": UKJENT_KONTO, "summary": "Faktura 8841"},
                read_timeout_seconds=40.0,
            )

    tekst = _tekst(asyncio.run(kjoer()))
    assert "INGEN SVARTE" in tekst
    assert "IKKE utført" in tekst

    snap = _get(live_app, "/api/state")
    # Kortet venter fortsatt paa et menneske.
    assert any(c["source"] == "agent" for c in snap["waiting"])
    # Og det staar en notis om at agenten ga opp.
    assert any(n.get("kind") == "agent" for n in snap["notices"])
    # Ingen har svart, saa ingen kort er besvart.
    assert not [c for c in snap["answered"] if c["source"] == "agent"]
    assert _get(live_app, "/api/verify")["ok"] is True
    _post(live_app, "/api/reset")


def test_tjeneren_starter_ikke_uten_noekkel():
    """Uten delt hemmelighet skal prosessen dø med en setning paa stderr."""
    import subprocess

    env = {k: v for k, v in os.environ.items()}
    env.pop("LONEWATCH_AGENT_KEY", None)
    env["PYTHONPATH"] = os.getcwd()
    p = subprocess.run(
        [sys.executable, "-m", "agent_gateway"],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        input="",
    )
    assert p.returncode == 1
    assert "LONEWATCH_AGENT_KEY" in p.stderr
    assert p.stdout == ""  # stdout er MCP-kanalen og skal vaere helt stille
