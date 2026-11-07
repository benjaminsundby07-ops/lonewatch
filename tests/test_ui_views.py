"""De nye aggregeringene bak Oversikt, Godkjenning og Etter.

Alle tre skissene krevde tall og lister appen ikke hadde fra før. Testene her
handler om én ting: at det som vises er **regnet ut av ekte tilstand**, og at
det ikke står noe på skjermen vi ikke har dekning for.
"""

from __future__ import annotations

import pytest

from ui.after_view import HASTER, VIKTIG, build_after_view
from ui.state import STATUS_WAITING, DemoState


@pytest.fixture()
def kjort() -> DemoState:
    """En demo som har gått hele veien gjennom alle 40 scenarioene."""
    state = DemoState()
    while state.step_feed() is not None:
        pass
    return state


# ---------------------------------------------------------------------------
# «Venter paa deg» paa Oversikt
# ---------------------------------------------------------------------------


def test_nothing_waiting_gives_nothing_to_show():
    """Tom kø skal gi None, ikke et tomt kort som ser ut som en sak."""
    assert DemoState().waiting_for_you() is None


def test_waiting_picks_the_most_pressing_red_alert(kjort):
    w = kjort.waiting_for_you()
    assert w is not None

    venter = [kjort.cards[r] for r in kjort.order if kjort.cards[r]["status"] == STATUS_WAITING]
    assert w["waiting_total"] == len(venter)

    # Høyest risiko først. Er det flere med samme risiko, det største beløpet.
    risiko = [c["decision"]["risk"] for c in venter]
    assert w["risk"] == min(risiko, key=lambda r: {"high": 0, "medium": 1, "low": 2}[r])

    samme = [c for c in venter if c["decision"]["risk"] == w["risk"]]
    storst = max(float(c["request"].get("amount") or 0) for c in samme)
    assert float(w["amount"] or 0) == storst


def test_waiting_only_shows_what_the_card_really_has(kjort):
    w = kjort.waiting_for_you()
    card = kjort.cards[w["request_id"]]
    assert w["consequence_text"] == card["decision"]["consequence_text"]
    assert w["requires_typed_amount"] == card["decision"]["requires_typed_amount"]
    assert w["recipient"] == card["request"].get("recipient")


def test_waiting_disappears_when_the_human_answers(kjort):
    w = kjort.waiting_for_you()
    forste = w["request_id"]
    kjort.respond(forste, approved=False, typed_amount=None, seconds_to_decide=1.0)
    etterpa = kjort.waiting_for_you()
    assert etterpa is None or etterpa["request_id"] != forste


def test_overview_carries_the_waiting_card(kjort):
    assert kjort.overview()["waiting"]["request_id"] == kjort.waiting_for_you()["request_id"]


# ---------------------------------------------------------------------------
# logglinjene bak «Hendelser»
# ---------------------------------------------------------------------------


def test_log_rows_are_newest_first_and_counted_honestly(kjort):
    data = kjort.log_rows()
    rader = data["rows"]
    assert rader, "demoen skal ha skrevet logglinjer"

    seq = [r["seq"] for r in rader]
    assert seq == sorted(seq, reverse=True)

    # Tallene paa filterknappene maa stemme med radene de filtrerer.
    assert data["counts"]["alle"] == len(rader) or data["truncated"]
    assert data["counts"]["menneske"] == len([r for r in rader if r["utfall"] == "red"])


def test_every_log_row_has_the_columns_the_table_shows(kjort):
    for r in kjort.log_rows()["rows"]:
        for felt in ("seq", "ts", "agent", "kall", "maal", "utfall", "regler", "hash"):
            assert felt in r, felt
        assert isinstance(r["regler"], list)
        # Hashen forkortes for aa faa plass, men den skal vaere ekte.
        assert r["hash"] is None or len(r["hash"]) <= 16


def test_log_rows_are_capped_and_say_so(kjort):
    data = kjort.log_rows(limit=5)
    assert len(data["rows"]) == 5
    assert data["truncated"] is True


# ---------------------------------------------------------------------------
# fellene
# ---------------------------------------------------------------------------


def test_traps_show_whether_they_actually_fired(kjort):
    feller = kjort.traps_overview()
    assert feller, "demoen har plantede feller"
    assert any(f["sist"] for f in feller), "minst én felle skal ha gått av"
    for f in feller:
        assert f["doc_id"] and f["type"] and f["intent"]
        if f["sist"]:
            assert f["sist"]["ts"] and f["sist"]["agent"]


# ---------------------------------------------------------------------------
# «Dette ledet hit»
# ---------------------------------------------------------------------------


def test_the_trail_is_only_the_same_agent_and_ends_on_this_request(kjort):
    rid = kjort.waiting_for_you()["request_id"]
    agent = kjort.cards[rid]["request"]["agent_id"]
    spor = kjort.agent_trail(rid)

    assert spor, "det skal staa noe foer en roed forespoersel"
    assert spor[-1]["er_denne"] is True
    assert spor[-1]["request_id"] == rid
    for steg in spor:
        assert kjort.cards[steg["request_id"]]["request"]["agent_id"] == agent


def test_the_trail_names_the_trap_instead_of_just_saying_yes(kjort):
    """«felle: true» er ikke noe man kan slaa opp. Navnet er det."""
    for rid in kjort.order:
        felle = kjort.cards[rid].get("trap")
        if not felle:
            continue
        steg = [s for s in kjort.agent_trail(rid) if s["er_denne"]][0]
        assert steg["felle"] == felle["trap_id"]
        return
    pytest.skip("ingen feller gikk av i denne kjoeringen")


def test_an_unknown_request_has_no_trail(kjort):
    assert kjort.agent_trail("finnes_ikke") == []


# ---------------------------------------------------------------------------
# Etter-visningen
# ---------------------------------------------------------------------------


def test_one_request_gives_one_case_not_one_per_task(kjort):
    """req_0021 fikk to kort foer fordi den utloeste to oppgaver."""
    view = build_after_view(kjort.vault.entries())
    ider = [s["topp"]["id"] for s in _alle_saker(view) if s["topp"]["id"]]
    assert len(ider) == len(set(ider)), "samme forespørsel skal bare stå én gang"


def test_the_urgent_bucket_comes_first(kjort):
    view = build_after_view(kjort.vault.entries())
    nivaaer = [b["nivaa"] for b in view["bolker"]]
    assert nivaaer == sorted(nivaaer)
    assert nivaaer[0] == HASTER


def test_a_blocked_package_is_urgent_and_an_approval_is_not(kjort):
    view = build_after_view(kjort.vault.entries())
    for bolk in view["bolker"]:
        for sak in bolk["saker"]:
            if "Installerer tillegg" in sak["topp"]["handling"]:
                assert bolk["nivaa"] == HASTER
            if sak["topp"]["handling"] == "Overfører penger" and bolk["nivaa"] != HASTER:
                assert bolk["nivaa"] == VIKTIG


def test_the_view_speaks_norwegian_and_has_no_double_periods(kjort):
    view = build_after_view(kjort.vault.entries())
    for sak in _alle_saker(view):
        for felt in (sak["topp"]["agent"], sak["topp"]["handling"]):
            assert "_" not in felt, f"raa kode lekket ut: {felt}"
        for rolle in sak["roller"]:
            assert rolle in ("Sikkerhet", "Økonomi", "Den ansatte", "IT"), rolle
        for o in sak["oppgaver"]:
            assert ".." not in o["tekst"]
            assert "paa " not in o["tekst"]
            assert " aa " not in o["tekst"]


def test_the_same_package_tested_twice_is_one_job(kjort):
    """Maskert og umaskert adresse er to tekster, men samme oppgave."""
    view = build_after_view(kjort.vault.entries())
    for sak in _alle_saker(view):
        if sak["topp"]["agent"] != "Sandkassen":
            continue
        tekster = [o["tekst"] for o in sak["oppgaver"]]
        nettverk = [t for t in tekster if "forsøkte å kontakte" in t]
        assert len(nettverk) <= 1, tekster


def test_the_counts_match_what_is_in_the_buckets(kjort):
    view = build_after_view(kjort.vault.entries())
    saker = _alle_saker(view)
    assert view["antall"] == len(saker)
    assert view["antall_oppgaver"] == sum(len(s["oppgaver"]) for s in saker)


def test_an_empty_log_gives_an_empty_view():
    view = build_after_view([])
    assert view == {"bolker": [], "antall": 0, "antall_oppgaver": 0}


def test_the_after_api_carries_the_view(kjort):
    data = kjort.after_actions()
    assert data["view"]["antall"] == build_after_view(kjort.vault.entries())["antall"]


def _alle_saker(view):
    return [s for b in view["bolker"] for s in b["saker"]]
