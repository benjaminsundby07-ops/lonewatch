"""Tester for broen mot en ekte agent: MCP-tjeneren og det nye endepunktet.

Ingen Claude Code kjøres her. Det som testes er alt som ligger MELLOM agenten
og Lonewatch, og det er der feilene kan gjøre skade:

- at allow, rødt og block gir riktig svar til agenten
- at tidsavbruddet behandles som et nei, og ikke som en godkjenning
- at feil beløp ikke kan godkjenne et rødt kort
- at agenten ikke kan oppgi `recipient_known`, `reversible`, `agent_id` eller `id`
- at et blokkert kall ikke får vite hvilke regler som slo til
- at loggen og loggsjekken stemmer etter at agenten har vært innom

Det som IKKE testes her: at Claude Code faktisk snakker protokollen riktig. Se
docs/EKTE_AGENT.md for hva som må prøves for hånd.
"""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import urllib.error
import urllib.request

import pytest

from agent_gateway import config as agent_config
from agent_gateway import tools
from agent_gateway.client import LonewatchClient, LonewatchRefused, LonewatchUnavailable
from agent_gateway.config import ConfigError, load_config
from ui.state import (
    AGENT_AGENT_ID,
    AGENT_SOURCE,
    STATUS_APPROVED,
    STATUS_BLOCKED,
    STATUS_REJECTED,
    STATUS_WAITING,
    DemoState,
)

NOEKKEL = "x" * 32

# En konto som IKKE staar paa demoens liste over kjente mottakere.
UKJENT_KONTO = "NO93 8601 1117 947"


@pytest.fixture
def state():
    s = DemoState()
    yield s
    s.close()


# ---------------------------------------------------------------------------
# oppsettet: nøkkel påkrevd, bare 127.0.0.1
# ---------------------------------------------------------------------------


def test_uten_noekkel_starter_ikke_tjeneren():
    with pytest.raises(ConfigError) as feil:
        load_config({})
    assert agent_config.ENV_KEY in str(feil.value)


def test_for_kort_noekkel_avvises():
    with pytest.raises(ConfigError):
        load_config({agent_config.ENV_KEY: "kort"})


@pytest.mark.parametrize(
    "adresse",
    [
        "http://10.0.0.5:8000",
        "http://lonewatch.example",
        "http://169.254.169.254",
        "file:///etc/passwd",
    ],
)
def test_tjeneren_nekter_aa_snakke_ut_av_maskinen(adresse):
    """En MCP-tjener som kunne pekt hvor som helst, ville vært en kanal ut."""
    with pytest.raises(ConfigError):
        load_config({agent_config.ENV_KEY: NOEKKEL, agent_config.ENV_BASE_URL: adresse})


def test_standardoppsettet_er_lokalt():
    cfg = load_config({agent_config.ENV_KEY: NOEKKEL})
    assert cfg.base_url == "http://127.0.0.1:8000"
    assert cfg.wait_seconds == 120.0


@pytest.mark.parametrize("raar", ["null", "-5", "ikke-et-tall"])
def test_ugyldig_ventetid_avvises(raar):
    with pytest.raises(ConfigError):
        load_config({agent_config.ENV_KEY: NOEKKEL, agent_config.ENV_WAIT_SECONDS: raar})


# ---------------------------------------------------------------------------
# beløpet: det agenten sender må tolkes likt av ui/amount.py
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "tall,tekst",
    [
        (450000, "450000"),
        (450000.0, "450000"),
        (10_000_000, "10000000"),
        (1234.56, "1234,56"),
        (1234.5, "1234,50"),
        (0, "0"),
        (None, ""),
    ],
)
def test_beloepet_formateres_slik_lonewatch_leser_det(tall, tekst):
    assert tools.format_amount(tall) == tekst


def test_punktum_som_desimalskille_sendes_aldri():
    """ui/amount.py avviser "450000.00" med vilje. Da skal vi ikke sende det."""
    from ui.amount import parse_amount

    for tall in (450000, 1234.56, 99.9, 1):
        assert parse_amount(tools.format_amount(tall)) == int(round(tall * 100))


# ---------------------------------------------------------------------------
# en falsk klient, slik at flyten kan prøves uten HTTP
# ---------------------------------------------------------------------------


class FalskKlient:
    """Later som den er appen. Svarene er satt opp av testen."""

    def __init__(self, submit_svar, status_svar=()):
        self.submit_svar = submit_svar
        self.status_svar = list(status_svar)
        self.sendt: list[dict] = []
        self.status_kall = 0
        self.ga_opp: list[tuple[str, float]] = []

    def submit(self, payload):
        self.sendt.append(payload)
        if isinstance(self.submit_svar, Exception):
            raise self.submit_svar
        return self.submit_svar

    def status(self, request_id):
        self.status_kall += 1
        if self.status_svar:
            return self.status_svar.pop(0)
        return {"ok": True, "status": STATUS_WAITING, "request_id": request_id}

    def abandon(self, request_id, waited_seconds):
        self.ga_opp.append((request_id, waited_seconds))
        return {"ok": True}


class FalskKlokke:
    """En klokke som bare går når noen sover. Da kan tidsavbruddet testes uten å vente."""

    def __init__(self):
        self.naa = 0.0

    def sov(self, sekunder):
        self.naa += sekunder

    def tid(self):
        return self.naa


def _kjoer(klient, **felt):
    klokke = FalskKlokke()
    tekst = tools.run_action(
        klient,
        tool_name=felt.pop("tool_name", "lonewatch_transfer_money"),
        sleep=klokke.sov,
        clock=klokke.tid,
        **felt,
    )
    return tekst, klokke


# ---------------------------------------------------------------------------
# de tre veiene: allow, rødt, block
# ---------------------------------------------------------------------------


def test_allow_gir_simulert_utfoert():
    klient = FalskKlient(
        {
            "ok": True,
            "request_id": "agent_0001",
            "name": "LW-8001",
            "status": "allow",
            "verdict": "allow",
            "risk": "low",
            "consequence_text": "Dokumentet blir lest.",
        }
    )
    tekst, _ = _kjoer(klient, tool_name="lonewatch_read_document", recipient="rapport.pdf")
    assert "UTFØRT (simulert)" in tekst
    assert "simulering" in tekst
    assert klient.status_kall == 0


def test_block_gir_kort_avvisning_uten_regelnavn():
    klient = FalskKlient(
        {
            "ok": True,
            "request_id": "agent_0001",
            "name": "LW-8001",
            "status": "blocked",
            "verdict": "block",
            "risk": "high",
            "consequence_text": None,
        }
    )
    tekst, _ = _kjoer(klient, amount=99_000_000, recipient=UKJENT_KONTO)
    assert "BLOKKERT" in tekst
    assert "UTFØRT" not in tekst
    # Ingen oppskrift paa hvordan den kan omgaas.
    for hint in ("transfer_over_hard_limit", "unknown_recipient", "grensen", "mindre"):
        assert hint not in tekst


def test_roedt_som_godkjennes_blir_utfoert():
    klient = FalskKlient(
        {
            "ok": True,
            "request_id": "agent_0001",
            "name": "LW-8001",
            "status": "waiting",
            "verdict": "red",
            "risk": "high",
            "consequence_text": "450 000 kr til en ukjent konto.",
        },
        status_svar=[
            {"ok": True, "status": STATUS_WAITING},
            {"ok": True, "status": STATUS_WAITING},
            {"ok": True, "status": STATUS_APPROVED, "approved": True, "typed_amount": 450000.0},
        ],
    )
    tekst, klokke = _kjoer(klient, amount=450000, recipient=UKJENT_KONTO)
    assert "GODKJENT" in tekst and "UTFØRT (simulert)" in tekst
    assert "450000 kr" in tekst
    assert klokke.naa == pytest.approx(4.0)  # to runder a 2 s


def test_roedt_som_avvises_blir_ikke_utfoert():
    klient = FalskKlient(
        {
            "ok": True,
            "request_id": "agent_0001",
            "name": "LW-8001",
            "status": "waiting",
            "verdict": "red",
            "risk": "high",
            "consequence_text": "...",
        },
        status_svar=[{"ok": True, "status": STATUS_REJECTED, "approved": False}],
    )
    tekst, _ = _kjoer(klient, amount=450000, recipient=UKJENT_KONTO)
    assert "AVVIST" in tekst
    assert "UTFØRT" not in tekst


def test_tidsavbrudd_er_et_nei_og_sier_fra_til_appen():
    klient = FalskKlient(
        {
            "ok": True,
            "request_id": "agent_0001",
            "name": "LW-8001",
            "status": "waiting",
            "verdict": "red",
            "risk": "high",
            "consequence_text": "...",
        }
    )
    tekst, klokke = _kjoer(
        klient, amount=450000, recipient=UKJENT_KONTO, wait_seconds=10.0, poll_seconds=2.0
    )
    assert "INGEN SVARTE" in tekst
    assert "IKKE utført" in tekst
    assert "UTFØRT (simulert)" not in tekst
    # Den ga opp etter ventetiden, ikke foer og ikke etter.
    assert klokke.naa == pytest.approx(10.0)
    assert klient.ga_opp and klient.ga_opp[0][0] == "agent_0001"


def test_mistet_kontakt_mens_vi_venter_behandles_som_ikke_utfoert():
    klient = FalskKlient(
        {
            "ok": True,
            "request_id": "agent_0001",
            "name": "LW-8001",
            "status": "waiting",
            "verdict": "red",
            "risk": "high",
        }
    )

    def doed_status(request_id):
        raise LonewatchUnavailable("appen svarer ikke")

    klient.status = doed_status
    tekst, _ = _kjoer(klient, amount=450000, recipient=UKJENT_KONTO)
    assert "IKKE ble utført" in tekst
    assert "GODKJENT" not in tekst


def test_uten_mellomstasjon_skjer_ingenting():
    klient = FalskKlient(LonewatchUnavailable("Kjører appen?"))
    tekst, _ = _kjoer(klient, amount=450000, recipient=UKJENT_KONTO)
    assert "ikke tilgjengelig" in tekst
    assert "IKKE utført" in tekst


def test_feil_noekkel_gir_ingen_handling():
    klient = FalskKlient(LonewatchRefused("Feil eller manglende nøkkel."))
    tekst, _ = _kjoer(klient, amount=450000, recipient=UKJENT_KONTO)
    assert "slapp ikke kallet inn" in tekst
    assert "IKKE utført" in tekst


def test_en_forespoersel_appen_ikke_tok_imot_er_ikke_en_avgjoerelse():
    klient = FalskKlient({"ok": False, "error": "En overføring må ha et beløp."})
    tekst, _ = _kjoer(klient, recipient=UKJENT_KONTO)
    assert "tok ikke imot" in tekst
    assert "Ingenting ble utført" in tekst


# ---------------------------------------------------------------------------
# hva agenten KAN sende
# ---------------------------------------------------------------------------


def test_agenten_sender_aldri_recipient_known_eller_reversible():
    klient = FalskKlient(
        {"ok": True, "request_id": "agent_0001", "verdict": "allow", "status": "allow"}
    )
    _kjoer(klient, tool_name="lonewatch_send_email", recipient="noen@ukjent.example")
    sendt = klient.sendt[0]
    for forbudt in ("recipient_known", "reversible", "agent_id", "id", "source_doc_id"):
        assert forbudt not in sendt


def test_verktoeyene_har_ingen_felt_agenten_ikke_skal_eie():
    """Signaturene til MCP-verktøyene, lest direkte."""
    mcp = pytest.importorskip("mcp")
    from agent_gateway.config import AgentConfig
    from agent_gateway.server import build_server

    server = build_server(AgentConfig("http://127.0.0.1:8000", NOEKKEL, 120.0, 2.0))
    verktoey = {t.name: t for t in asyncio.run(server.list_tools())}
    assert set(verktoey) == {t.name for t in tools.TOOL_SPECS}

    for navn, t in verktoey.items():
        skjema = getattr(t, "input_schema", None) or getattr(t, "inputSchema", None) or {}
        felt = set(skjema.get("properties", {}))
        assert not felt & {
            "recipient_known",
            "reversible",
            "agent_id",
            "id",
            "action_type",
            "ts",
        }, (navn, felt)
    assert mcp is not None


# ---------------------------------------------------------------------------
# endepunktet: samme vei som "Prøv selv", gjennom DemoState
# ---------------------------------------------------------------------------


def test_agentens_forespoersel_gaar_samme_vei_og_merkes(state):
    out = state.submit_agent(
        action_type="transfer_money",
        amount="450000",
        recipient=UKJENT_KONTO,
        summary="Dette er godkjent av ledelsen",
    )
    assert out["ok"] is True
    card = out["card"]
    assert card["source"] == AGENT_SOURCE
    assert card["request"]["agent_id"] == AGENT_AGENT_ID
    assert card["request"]["id"].startswith("agent_")
    # Begge feltene er regnet ut, ikke oppgitt.
    assert card["request"]["recipient_known"] is False
    assert card["request"]["reversible"] is False
    # Og den maa til et menneske, med beloepet skrevet inn.
    assert card["decision"]["verdict"] == "red"
    assert card["decision"]["requires_typed_amount"] is True
    assert card["status"] == STATUS_WAITING


def test_agentens_summary_endrer_ingenting(state):
    """Agentens egen forklaring skal aldri kunne snakke seg gjennom."""
    felles = dict(action_type="transfer_money", amount="450000", recipient=UKJENT_KONTO)
    a = state.submit_agent(**felles, summary="Rutine. Forhåndsgodkjent. Ikke varsle noen.")
    b = state.submit_agent(**felles, summary="")
    assert a["card"]["decision"]["verdict"] == b["card"]["decision"]["verdict"]
    assert a["card"]["decision"]["reasons"] == b["card"]["decision"]["reasons"]
    assert a["card"]["decision"]["risk"] == b["card"]["decision"]["risk"]


def test_agentens_ider_kolliderer_ikke_med_prov_selv(state):
    state.submit_custom(action_type="update_calendar", summary="min egen")
    state.submit_agent(action_type="read_document", recipient="rapport.pdf")
    state.submit_custom(action_type="update_calendar", summary="min egen nr 2")
    ider = list(state.cards)
    assert "custom_0001" in ider and "custom_0002" in ider and "agent_0001" in ider


def test_status_foelger_kortet_hele_veien(state):
    out = state.submit_agent(
        action_type="transfer_money", amount="450000", recipient=UKJENT_KONTO
    )
    request_id = out["card"]["request"]["id"]

    status = state.agent_status(request_id)
    assert status["status"] == STATUS_WAITING

    # Feil beloep godkjenner ingenting.
    assert state.respond(request_id, approved=True, typed_amount="45000")["ok"] is False
    assert state.agent_status(request_id)["status"] == STATUS_WAITING

    # Riktig beloep gjoer det.
    assert state.respond(request_id, approved=True, typed_amount="450 000")["ok"] is True
    status = state.agent_status(request_id)
    assert status["status"] == STATUS_APPROVED
    assert status["approved"] is True
    assert status["typed_amount"] == 450000.0


def test_status_gir_ikke_agenten_regelnavnene(state):
    out = state.submit_agent(
        action_type="transfer_money", amount="450000", recipient=UKJENT_KONTO
    )
    status = state.agent_status(out["card"]["request"]["id"])
    assert "reasons" not in status


def test_status_paa_noe_vi_ikke_har(state):
    assert state.agent_status("agent_9999") is None


def test_agenten_som_gir_opp_skriver_ingenting_i_loggen(state):
    out = state.submit_agent(
        action_type="transfer_money", amount="450000", recipient=UKJENT_KONTO
    )
    request_id = out["card"]["request"]["id"]
    linjer_foer = len(state.vault.entries())

    assert state.agent_gave_up(request_id, 120.0) is True
    assert len(state.vault.entries()) == linjer_foer
    # Kortet venter fortsatt paa et menneske.
    assert state.agent_status(request_id)["status"] == STATUS_WAITING
    # Men den som sitter der skal se at agenten ga opp.
    assert any(n["kind"] == "agent" for n in state.notices)

    # Og mennesket kan fortsatt svare etterpaa.
    assert state.respond(request_id, approved=False)["ok"] is True
    assert state.agent_status(request_id)["status"] == STATUS_REJECTED
    # Naa er den ikke lenger noe aa gi opp.
    assert state.agent_gave_up(request_id, 10.0) is False


def test_loggen_og_loggsjekken_stemmer_etter_agenten(state):
    state.submit_agent(action_type="read_document", recipient="rapport.pdf")
    out = state.submit_agent(
        action_type="transfer_money", amount="450000", recipient=UKJENT_KONTO
    )
    request_id = out["card"]["request"]["id"]
    state.respond(request_id, approved=True, typed_amount="450000", seconds_to_decide=7.0)
    state.submit_agent(action_type="transfer_money", amount="99000000", recipient=UKJENT_KONTO)

    sjekk = state.verify()
    assert sjekk["ok"] is True, sjekk

    slag = [e.kind for e in state.vault.entries()]
    # To request+decision per forespoersel, og én human for den som ble godkjent.
    assert slag.count("request") == 3
    assert slag.count("decision") == 3
    assert slag.count("human") == 1


def test_den_harde_grensen_gjelder_ogsaa_agenten(state):
    out = state.submit_agent(
        action_type="transfer_money", amount="99000000", recipient=UKJENT_KONTO
    )
    assert out["card"]["decision"]["verdict"] == "block"
    assert out["card"]["status"] == STATUS_BLOCKED
    # Og ingen kan klikke den gjennom.
    assert state.respond(out["card"]["request"]["id"], approved=True)["ok"] is False


# ---------------------------------------------------------------------------
# HTTP: den ekte appen, den ekte nøkkelen
# ---------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def agent_server(request):
    """Den ekte appen med broen slått på."""
    uvicorn = pytest.importorskip("uvicorn")
    import os

    os.environ["LONEWATCH_AGENT_KEY"] = NOEKKEL
    from ui.app import app

    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    srv = uvicorn.Server(config)
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


def _raa(base, path, body=None, noekkel=NOEKKEL, method=None):
    """Kaller endepunktet direkte, uten klienten. Gir (status, json)."""
    data = None if body is None else json.dumps(body).encode()
    headers = {}
    if noekkel is not None:
        headers["X-Lonewatch-Agent-Key"] = noekkel
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        base + path, data=data, headers=headers, method=method or ("POST" if data else "GET")
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as res:
            return res.status, json.loads(res.read() or b"{}")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read() or b"{}")
        except Exception:
            return exc.code, {}


def test_uten_noekkel_slipper_ingen_inn(agent_server):
    kode, _ = _raa(agent_server, "/api/agent/ping", noekkel=None)
    assert kode == 403
    kode, _ = _raa(agent_server, "/api/agent/ping", noekkel="feil-noekkel-helt-feil")
    assert kode == 403
    kode, svar = _raa(agent_server, "/api/agent/ping")
    assert kode == 200 and svar["ok"] is True


def test_endepunktet_nekter_felt_agenten_ikke_skal_eie(agent_server):
    for forbudt in ("recipient_known", "reversible", "agent_id", "id"):
        kode, _ = _raa(
            agent_server,
            "/api/agent/submit",
            {"action_type": "send_email", "recipient": "noen@ukjent.example", forbudt: True},
        )
        assert kode == 422, forbudt


def test_hele_veien_over_http_med_den_ekte_klienten(agent_server):
    _raa(agent_server, "/api/reset")
    klient = LonewatchClient(agent_server, NOEKKEL)

    # Rødt: sendt inn, men ingen har svart.
    svar = klient.submit(
        {
            "action_type": "transfer_money",
            "amount": "450000",
            "recipient": UKJENT_KONTO,
            "summary": "Faktura 8841",
        }
    )
    assert svar["ok"] is True
    assert svar["verdict"] == "red"
    assert svar["name"].startswith("LW-8")
    assert "reasons" not in svar
    request_id = svar["request_id"]

    assert klient.status(request_id)["status"] == STATUS_WAITING

    # Et menneske godkjenner, men maa skrive beloepet. Feil tall gaar ikke.
    kode, nei = _raa(
        agent_server,
        "/api/respond",
        {"request_id": request_id, "approved": True, "typed_amount": "45000"},
    )
    assert kode == 200 and nei["ok"] is False
    assert klient.status(request_id)["status"] == STATUS_WAITING

    kode, ja = _raa(
        agent_server,
        "/api/respond",
        {"request_id": request_id, "approved": True, "typed_amount": "450 000"},
    )
    assert kode == 200 and ja["ok"] is True
    status = klient.status(request_id)
    assert status["status"] == STATUS_APPROVED and status["typed_amount"] == 450000.0

    # Blokk: ingen begrunnelse ut til agenten.
    blokk = klient.submit(
        {"action_type": "transfer_money", "amount": "99000000", "recipient": UKJENT_KONTO}
    )
    assert blokk["verdict"] == "block"
    assert blokk["consequence_text"] is None
    assert "reasons" not in blokk

    # Loggen stemmer fortsatt.
    kode, sjekk = _raa(agent_server, "/api/verify")
    assert kode == 200 and sjekk["ok"] is True

    # Og kortene staar i dashbordets egen tilstand, merket som ekte agent.
    kode, snap = _raa(agent_server, "/api/state")
    kilder = {
        c["source"]
        for c in snap["waiting"] + snap["blocked"] + snap["answered"] + snap["calm"]
    }
    assert AGENT_SOURCE in kilder
    _raa(agent_server, "/api/reset")


def test_status_paa_noe_som_ikke_finnes_over_http(agent_server):
    klient = LonewatchClient(agent_server, NOEKKEL)
    svar = klient.status("agent_9999")
    assert svar["ok"] is False


def test_klienten_sier_fra_naar_appen_ikke_svarer():
    klient = LonewatchClient(f"http://127.0.0.1:{_free_port()}", NOEKKEL, timeout=1.0)
    with pytest.raises(LonewatchUnavailable):
        klient.submit({"action_type": "read_document"})


def test_klienten_skiller_avvist_fra_nede(agent_server):
    klient = LonewatchClient(agent_server, "helt-feil-noekkel-her")
    with pytest.raises(LonewatchRefused):
        klient.submit({"action_type": "read_document", "recipient": "x"})
