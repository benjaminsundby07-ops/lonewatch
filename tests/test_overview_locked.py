"""Oversikt uten menneskenoekkel, og faktura-scenarioet i hendelsen.

To ting pinnes her:

1. `/api/overview` var AAPEN. Den svarte med hele `waiting_for_you()`, saa en
   side ingen hadde laast opp viste hele kontonummeret, konsekvensteksten som
   navngir mottakeren, og regelnavnene. Samme lekkasje `minimized_snapshot`
   lukket for `/api/state`, bare gjennom en annen doer.

2. Hendelsen («Spill av hendelsen») skal vise bedrageriet: en skjult instruksjon
   i faktura 8841 bytter kontonummer, og agenten proever aa overfoere dit.
   Utfallet skal komme fra de EKSISTERENDE reglene - testen spoer gateway, den
   paastaar ikke noe selv.
"""

from __future__ import annotations

import pytest

from agents import doc_scan, story, traps
from ui.state import CLOSED_OVERVIEW_KEYS, DemoState, minimized_overview

# Kontoen og beloepet den skriptede agentdemoen og docs/EKTE_AGENT.md bruker:
# «Betal faktura 8841: 450 000 kr til NO93 8601 1117 947».
UKJENT_KONTO = "NO93 8601 1117 947"
BELOP = 450_000


@pytest.fixture()
def state() -> DemoState:
    s = DemoState()
    yield s
    s.close()


def _spill_hele(s: DemoState) -> None:
    s.story_start()
    for _ in range(len(story.binance_inspired().steps)):
        s.story_step()


# ---------------------------------------------------------------------------
# 1. den laaste Oversikt
# ---------------------------------------------------------------------------


def test_laast_oversikt_viser_ikke_konsekvenstekst_eller_regelnavn(state):
    _spill_hele(state)
    aapen = state.overview()
    assert aapen["waiting"] is not None, "hendelsen skal ha latt et roedt kort staa"
    assert aapen["waiting"]["consequence_text"]
    assert aapen["waiting"]["reasons"]

    laast = minimized_overview(aapen)
    assert laast["locked"] is True
    assert "consequence_text" not in laast["waiting"]
    assert "reasons" not in laast["waiting"]
    assert "summary" not in laast["waiting"]


def test_laast_oversikt_maskerer_mottakeren(state):
    _spill_hele(state)
    laast = minimized_overview(state.overview())
    mottaker = laast["waiting"]["recipient"]
    assert mottaker != UKJENT_KONTO
    # Samme maskering loggen bruker: bare halen staar igjen.
    assert "8601" not in mottaker
    assert mottaker.endswith("947")


def test_laast_oversikt_beholder_tallene_og_statusen(state):
    """En laast forside som ikke kan tegne noe, viser ikke at Lonewatch finnes."""
    _spill_hele(state)
    laast = minimized_overview(state.overview())
    assert laast["counts"]["evaluated"] > 0
    assert laast["agents"]
    assert "logChain" in laast
    assert "lines" in laast["log"]
    # AT noe venter er en teller, ikke en lekkasje.
    assert laast["waiting"]["waiting_total"] >= 1


def test_minimized_overview_er_en_allowliste_ikke_en_denyliste(state):
    """Et nytt felt i `build_overview` skal mangle paa den laaste siden.

    Mangler det, ser noen det. Med en denyliste ville det lekket i stillhet.
    """
    full = dict(state.overview())
    full["et_helt_nytt_felt"] = "hemmelig"
    laast = minimized_overview(full)
    assert "et_helt_nytt_felt" not in laast
    assert set(laast) <= set(CLOSED_OVERVIEW_KEYS) | {"locked", "waiting"}


def test_api_overview_ruten_minimerer_uten_noekkel():
    """Gjennom den ekte ruten, ikke bare funksjonen under.

    Ingen `state`-fikstur her: `ui.app` lager sin EGEN `DemoState` naar den
    importeres, og to av dem i samme test slaass om laasen paa loggfilen.
    """
    pytest.importorskip("fastapi")
    from starlette.requests import Request

    import ui.app as app_mod

    def _req(headers: list[tuple[bytes, bytes]]) -> Request:
        return Request({"type": "http", "method": "GET", "path": "/api/overview",
                        "headers": headers})

    laast = app_mod.api_overview(_req([]))
    assert laast["locked"] is True
    venter = laast.get("waiting")
    if isinstance(venter, dict):
        assert "consequence_text" not in venter
        assert "reasons" not in venter

    from ui.app import HUMAN_KEY_HEADER
    from tests.conftest import HUMAN_KEY

    aapen = app_mod.api_overview(
        _req([(HUMAN_KEY_HEADER.lower().encode(), HUMAN_KEY.encode())])
    )
    assert aapen["locked"] is False


# ---------------------------------------------------------------------------
# 2. faktura-scenarioet
# ---------------------------------------------------------------------------


def test_fakturaen_bruker_samme_beloep_og_konto_som_agentdemoen():
    overforing = [
        r for r in story.story_requests() if r.action_type.value == "transfer_money"
    ]
    assert len(overforing) == 1
    req = overforing[0]
    assert req.amount == BELOP
    assert req.recipient == UKJENT_KONTO
    assert req.source_doc_id == "doc_invoice_8841"
    assert req.recipient_known is False


def test_den_skjulte_teksten_oppgir_kontoen_og_ber_om_taushet():
    doc = traps.find_doc("doc_invoice_8841")
    skjult = doc.hidden_text
    assert UKJENT_KONTO in skjult
    assert "varsle" in skjult.lower()
    # Kontoen et menneske ser er en ANNEN. Det er hele bedrageriet.
    assert UKJENT_KONTO not in doc.visible_to_human()
    assert "450 000 kr" in doc.visible_to_human()


def test_felleskanneren_gaar_av_paa_den_skjulte_teksten():
    doc = traps.find_doc("doc_invoice_8841")
    funn = doc_scan.scan_document(
        visible_text=doc.visible_text,
        hidden_text=doc.hidden_text,
        metadata=doc.metadata,
    )
    assert funn, "skanneren maa se den skjulte teksten, ellers er hendelsen tom"
    navn = {f.label for f in funn}
    assert "hvit-paa-hvit" in navn
    assert "instruksjonsfrase" in navn


def test_reglene_selv_gjoer_overforingen_roed(state):
    """Ikke hardkodet: svaret kommer fra gateway.evaluate gjennom hendelsen."""
    _spill_hele(state)
    kort = state.snapshot()
    roede = [
        c
        for c in kort["waiting"]
        if c["request"]["id"] == "story_0004"
    ]
    assert len(roede) == 1
    besluttet = roede[0]["decision"]
    assert besluttet["verdict"] == "red"
    assert besluttet["risk"] == "high"
    assert set(besluttet["reasons"]) == {
        "amount_over_limit",
        "unknown_recipient",
        "irreversible",
    }
    # Menneskets steg: beloepet maa skrives inn.
    assert besluttet["requires_typed_amount"] is True
    assert "450 000 kr" in besluttet["consequence_text"]


def test_fella_blir_en_logglinje_og_et_varsel(state):
    _spill_hele(state)
    rader = state.log_rows()["rows"]
    feller = [
        r
        for r in rader
        if r["utfall"] == "trap" and r["maal"] == "doc_invoice_8841"
    ]
    assert len(feller) == 1, "fella i faktura 8841 maa staa i loggen"

    varsler = [
        n
        for n in state.snapshot()["notices"]
        if n["kind"] == "trap" and "doc_invoice_8841" in n["detail"]
    ]
    assert len(varsler) == 1, "fella maa ogsaa gi et varsel paa skjermen"


def test_feil_beloep_avvises_og_riktig_beloep_godkjennes(state):
    _spill_hele(state)
    feil = state.respond("story_0004", approved=True, typed_amount="400000")
    assert feil["ok"] is False

    riktig = state.respond("story_0004", approved=True, typed_amount="450 000")
    assert riktig["ok"] is True
    assert riktig["card"]["human"]["typed_amount"] == BELOP
