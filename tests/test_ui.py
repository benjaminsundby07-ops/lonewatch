"""Tester for ui/: tilstanden bak nettsiden, og at HTTP-endepunktene svarer.

Logikken testes direkte mot DemoState. Det er der alt skjer: app.py er bare et
tynt lag med ruter over den.

Testene kjoerer mot den ekte gatewayen og den ekte vaulten. De sjekker flyten
gjennom UI, ikke hvor gode reglene er: det hoerer til tests/test_gateway.py.
"""

from __future__ import annotations

import json
import socket
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pytest

from contracts import ActionRequest, ActionType, Verdict
from ui.state import (
    STATUS_ALLOW,
    STATUS_APPROVED,
    STATUS_BLOCKED,
    STATUS_REJECTED,
    STATUS_WAITING,
    DemoState,
    amount_matches,
)

# ---------------------------------------------------------------------------
# beloepet mennesket maa skrive
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "written",
    ["10000000", "10 000 000", "10 000 000 kr", "10.000.000", " 10000000 "],
)
def test_the_amount_can_be_written_the_way_people_write_amounts(written):
    assert amount_matches(written, 10_000_000) is True


@pytest.mark.parametrize("written", ["", "   ", "1000000", "100000000", "kr", "ti millioner"])
def test_a_different_or_empty_amount_is_not_accepted(written):
    assert amount_matches(written, 10_000_000) is False


def test_no_expected_amount_means_nothing_matches():
    assert amount_matches("0", None) is False


# ---------------------------------------------------------------------------
# den rolige stroemmen
# ---------------------------------------------------------------------------


@pytest.fixture()
def state() -> DemoState:
    return DemoState()


def _drain(state: DemoState) -> int:
    count = 0
    while state.step_feed() is not None:
        count += 1
    return count


def test_the_feed_runs_through_every_scenario_once_and_then_stops(state):
    from agents.scenarios import all_scenarios

    assert state.feed_done is False
    assert _drain(state) == len(all_scenarios())
    assert state.feed_done is True
    assert state.step_feed() is None


def test_each_card_gets_a_decision_and_a_norwegian_label(state):
    card = state.step_feed()
    assert card is not None
    assert card["decision"]["request_id"] == card["request"]["id"]
    assert card["agent_label"]
    assert card["action_label"]
    assert card["status"] in (STATUS_ALLOW, STATUS_WAITING, STATUS_BLOCKED)


def test_allow_goes_to_the_calm_list_and_red_goes_to_the_queue(state):
    _drain(state)
    snap = state.snapshot()
    assert snap["calm_total"] > 0
    for card in snap["calm"]:
        assert card["decision"]["verdict"] == Verdict.ALLOW.value
    for card in snap["waiting"]:
        assert card["decision"]["verdict"] == Verdict.RED.value
    for card in snap["blocked"]:
        assert card["decision"]["verdict"] == Verdict.BLOCK.value


def test_most_requests_pass_quietly(state):
    """Roedt skal vaere sjeldent, ellers slaar folk av varselet."""
    _drain(state)
    snap = state.snapshot()
    total = snap["feed"]["total"]
    loud = len(snap["waiting"]) + len(snap["blocked"])
    assert loud / total <= 0.25


def test_reading_a_trapped_document_shows_up_as_a_notice(state):
    _drain(state)
    notices = state.snapshot()["notices"]
    assert any(n["kind"] == "trap" for n in notices)


def test_everything_is_written_to_the_log(state):
    _drain(state)
    snap = state.snapshot()
    # minst én linje for forespoerselen og én for avgjoerelsen, per forespoersel
    assert snap["log"]["lines"] >= 2 * snap["feed"]["total"]
    kinds = {e.kind for e in state.vault.entries()}
    assert {"request", "decision"} <= kinds
    assert "trap" in kinds


# ---------------------------------------------------------------------------
# svaret fra mennesket
# ---------------------------------------------------------------------------


def _first_waiting(state: DemoState) -> dict:
    _drain(state)
    waiting = state.snapshot()["waiting"]
    assert waiting, "demoen skal gi minst én roed forespoersel"
    return waiting[0]


# Beloepet paa demoens store overfoering. Det er dette mennesket maa skrive.
BIG_TRANSFER_NOK = 10_000_000


def _big_transfer(state: DemoState) -> dict:
    """Kortet for pengeoverfoeringen paa 10 000 000 kr.

    Med det ekte regelsettet er flere forespoersler roede (ukjent mottaker,
    nytt tillegg, personopplysninger ut av huset), og koeen viser nyeste
    foerst. Foerste kort i koeen er derfor ikke overfoeringen. Testene under
    handler om beloepet som maa skrives inn, saa de plukker overfoeringen med
    vilje i stedet for aa gjette paa rekkefoelgen.
    """
    _drain(state)
    for card in state.snapshot()["waiting"]:
        if card["request"]["amount"] == BIG_TRANSFER_NOK:
            return card
    raise AssertionError("demoen skal ha en roed overfoering paa 10 000 000 kr")


def test_the_big_transfer_is_red_and_cannot_be_approved_without_typing_the_amount(state):
    """Hovedpoenget i demoen: 10 000 000 kr slipper ikke gjennom av seg selv."""
    card = _big_transfer(state)
    assert card["decision"]["verdict"] == Verdict.RED.value
    assert card["decision"]["requires_typed_amount"] is True
    assert card["status"] == STATUS_WAITING


def test_a_typed_amount_request_cannot_be_approved_with_the_wrong_amount(state):
    card = _big_transfer(state)
    assert card["decision"]["requires_typed_amount"] is True
    out = state.respond(card["request"]["id"], approved=True, typed_amount="1")
    assert out["ok"] is False
    assert "stemmer ikke" in out["error"]
    # Den staar fortsatt i koeen.
    assert state.cards[card["request"]["id"]]["status"] == STATUS_WAITING


def test_an_empty_amount_is_also_refused(state):
    card = _big_transfer(state)
    assert state.respond(card["request"]["id"], approved=True, typed_amount="")["ok"] is False
    assert state.respond(card["request"]["id"], approved=True, typed_amount=None)["ok"] is False


def test_the_right_amount_approves_it_and_lands_in_the_log(state):
    card = _big_transfer(state)
    request_id = card["request"]["id"]
    before = len(state.vault.entries())

    out = state.respond(request_id, approved=True, typed_amount="10 000 000", seconds_to_decide=9.5)
    assert out["ok"] is True
    assert state.cards[request_id]["status"] == STATUS_APPROVED
    assert len(state.vault.entries()) == before + 1

    human = state.vault.entries()[-1]
    assert human.kind == "human"
    assert human.payload["approved"] is True
    assert human.payload["typed_amount"] == BIG_TRANSFER_NOK
    assert human.payload["seconds_to_decide"] == pytest.approx(9.5)


def test_the_log_never_contains_the_employee_name_only_the_pseudonym(state):
    card = _first_waiting(state)
    state.respond(card["request"]["id"], approved=False)
    human = state.vault.entries()[-1]
    assert human.payload["employee_pseudonym"].startswith("emp_")
    assert "ansatt" not in json.dumps(human.payload)


def test_rejecting_needs_no_amount(state):
    card = _first_waiting(state)
    out = state.respond(card["request"]["id"], approved=False)
    assert out["ok"] is True
    assert state.cards[card["request"]["id"]]["status"] == STATUS_REJECTED


def test_the_same_request_cannot_be_answered_twice(state):
    card = _first_waiting(state)
    request_id = card["request"]["id"]
    assert state.respond(request_id, approved=False)["ok"] is True
    again = state.respond(request_id, approved=False)
    assert again["ok"] is False
    assert "allerede" in again["error"]


def test_an_unknown_request_id_is_handled_without_crashing(state):
    out = state.respond("finnes_ikke", approved=True, typed_amount="1")
    assert out["ok"] is False
    assert out["error"]


def test_answered_requests_leave_the_queue(state):
    card = _first_waiting(state)
    request_id = card["request"]["id"]
    state.respond(request_id, approved=False)
    snap = state.snapshot()
    assert request_id not in [c["request"]["id"] for c in snap["waiting"]]
    assert request_id in [c["request"]["id"] for c in snap["answered"]]


# ---------------------------------------------------------------------------
# "Foer": sandkassen
# ---------------------------------------------------------------------------


def _install_card(state: DemoState, package_name: str) -> dict:
    _drain(state)
    for request_id in state.order:
        card = state.cards[request_id]
        if card["request"].get("package_name") == package_name:
            return card
    raise AssertionError(f"fant ingen forespoersel om {package_name}")


def test_the_sandbox_runs_before_the_decision_and_lands_in_the_log(state):
    """Rekkefoelgen i loggen skal vaere request -> sandbox -> decision."""
    card = _install_card(state, "nordlys-mail-connector-patch")
    kinds = [(e.kind, e.payload.get("id") or e.payload.get("request_id") or e.payload.get("package_name"))
             for e in state.vault.entries()]
    i_req = kinds.index(("request", card["request"]["id"]))
    i_box = kinds.index(("sandbox", "nordlys-mail-connector-patch"))
    i_dec = kinds.index(("decision", card["request"]["id"]))
    assert i_req < i_box < i_dec


def test_a_blocked_plugin_is_stopped_and_never_queued_for_a_human(state):
    card = _install_card(state, "nordlys-mail-connector-patch")
    assert card["decision"]["verdict"] == Verdict.BLOCK.value
    assert "sandbox_blocked" in card["decision"]["reasons"]
    assert card["status"] == STATUS_BLOCKED
    assert card["request"]["id"] not in [c["request"]["id"] for c in state.snapshot()["waiting"]]


def test_a_clean_plugin_is_still_red_because_it_is_new(state):
    card = _install_card(state, "pdf-helper")
    assert card["decision"]["verdict"] == Verdict.RED.value
    assert card["decision"]["reasons"] == ["new_package"]
    assert card["sandbox"]["verdict"] == "clean"
    assert "ikke at tillegget er trygt" in card["decision"]["consequence_text"]


def test_the_before_list_shows_one_clean_and_one_blocked(state):
    _drain(state)
    before = state.snapshot()["before"]
    assert before["clean"] >= 1
    assert before["blocked"] >= 1
    assert {r["package_name"] for r in before["scanned"]} >= {"pdf-helper", "nordlys-mail-connector-patch"}
    assert before["error"] is None


def test_each_plugin_is_scanned_once_even_if_asked_for_twice(state):
    """Koeen og historien ber om det samme tillegget. Det skal kjoeres én gang."""
    _drain(state)
    state.story_start()
    while not state.story_step()["done"]:
        pass
    kinds = [e.kind for e in state.vault.entries()]
    names = [e.payload["package_name"] for e in state.vault.entries() if e.kind == "sandbox"]
    assert kinds.count("sandbox") == len(set(names))
    assert names.count("nordlys-mail-connector-patch") == 1


def test_a_plugin_the_sandbox_does_not_have_is_not_run(state, monkeypatch):
    """Et navn vi ikke har en fil for skal gi "ikke testet", ikke en kjoering."""
    import sandbox

    def eksploder(*args, **kwargs):  # pragma: no cover - skal aldri kalles
        raise AssertionError("sandkassen startet en prosess for et ukjent navn")

    monkeypatch.setattr(sandbox.runner.subprocess, "Popen", eksploder)

    req = ActionRequest(
        id="req_ukjent",
        ts=datetime(2026, 11, 7, 9, 0, tzinfo=timezone.utc),
        agent_id="it_helper",
        action_type=ActionType.INSTALL_PACKAGE,
        summary="",
        # Et navn sandkassen ikke har en fil for. Det er normaltilfellet:
        # de fleste tillegg i verden ligger ikke i sandbox/packages/.
        package_name="nordlys-pdf-reader",
    )
    card = state._handle(req, source="feed")

    assert card["sandbox"] is None
    assert card["decision"]["verdict"] == Verdict.RED.value
    assert "sandbox_blocked" not in card["decision"]["reasons"]
    assert "ikke testet i sandkassen" in card["decision"]["consequence_text"]
    untested = state.snapshot()["before"]["untested"]
    assert [u["package_name"] for u in untested] == ["nordlys-pdf-reader"]


def test_reset_empties_the_before_list(state):
    _drain(state)
    assert state.snapshot()["before"]["scanned"]
    state.reset()
    before = state.snapshot()["before"]
    assert before["scanned"] == []
    assert before["untested"] == []


# ---------------------------------------------------------------------------
# sjekk loggen
# ---------------------------------------------------------------------------


def test_verify_is_green_on_an_untouched_log(state):
    _drain(state)
    result = state.verify()
    assert result["ok"] is True
    assert result["seq"] is None
    assert result["lines"] > 0
    assert "stemmer" in result["text"]


def test_verify_points_at_the_changed_line(state):
    _drain(state)
    entries = state.vault._entries  # vi roerer loggen med vilje for aa teste sjekken
    entries[3] = entries[3].model_copy(update={"payload": {"tuklet": True}})
    result = state.verify()
    assert result["ok"] is False
    assert result["seq"] == 3
    assert "seq=3" in result["text"]


def test_the_last_verify_is_remembered_in_the_snapshot(state):
    assert state.snapshot()["log"]["last_verify"] is None
    state.verify()
    assert state.snapshot()["log"]["last_verify"]["ok"] is True


# ---------------------------------------------------------------------------
# Etter-listen
# ---------------------------------------------------------------------------


def test_after_list_says_kommer_until_vault_after_exists(state):
    """Oekt C eier vault/after.py. Finnes den ikke, skal UI si 'kommer', ikke krasje."""
    data = state.after_actions()
    assert isinstance(data["items"], list)
    assert isinstance(data["available"], bool)
    if not data["available"]:
        assert data["items"] == []
        assert data["note"]
    else:
        for item in data["items"]:
            assert {"title", "detail", "owner_role", "done"} <= set(item)


# ---------------------------------------------------------------------------
# hendelsen
# ---------------------------------------------------------------------------


def test_the_story_plays_every_step_and_then_says_done(state):
    snap = state.story_start()
    assert snap["running"] is True
    assert snap["index"] == 0
    total = snap["total_steps"]

    for _ in range(total):
        snap = state.story_step()

    assert snap["done"] is True
    assert snap["running"] is False
    assert snap["index"] == total
    assert len(snap["log"]) == total
    # Ett steg for mye skal ikke krasje.
    assert state.story_step()["done"] is True


def test_the_story_writes_traps_and_the_sandbox_to_the_log(state):
    state.story_start()
    while not state.story_step()["done"]:
        pass
    kinds = [e.kind for e in state.vault.entries()]
    assert kinds.count("trap") == 2
    assert kinds.count("sandbox") == 1
    assert state.verify() is not None
    assert state.verify()["ok"] is True


def test_the_story_ends_with_a_transfer_waiting_for_a_human(state):
    state.story_start()
    while not state.story_step()["done"]:
        pass
    waiting = state.snapshot()["waiting"]
    assert waiting, "overfoeringen i historien skal vente paa et menneske"
    assert any(c["decision"]["requires_typed_amount"] for c in waiting)
    assert all(c["source"] == "story" for c in waiting)


def test_the_story_clock_never_passes_ninety_seconds(state):
    state.story_start()
    seconds = []
    snap = state.story_snapshot()
    while not snap["done"]:
        snap = state.story_step()
        seconds.append(snap["current_second"])
    assert seconds == sorted(seconds)
    assert max(seconds) <= 90


def test_starting_the_story_again_replays_it_from_the_top(state):
    state.story_start()
    state.story_step()
    snap = state.story_start()
    assert snap["index"] == 0
    assert snap["log"] == []


# ---------------------------------------------------------------------------
# nullstilling
# ---------------------------------------------------------------------------


def test_reset_empties_the_queue_the_log_and_the_story(state):
    _drain(state)
    state.story_start()
    state.story_step()
    state.verify()

    state.reset()
    snap = state.snapshot()
    assert snap["waiting"] == []
    assert snap["calm"] == []
    assert snap["calm_total"] == 0
    assert snap["notices"] == []
    assert snap["log"]["lines"] == 0
    assert snap["log"]["last_verify"] is None
    assert snap["story"]["index"] == 0
    assert snap["feed"]["seen"] == 0


def test_reset_starts_a_new_log_file_and_keeps_the_old_one(state):
    """Nullstilling skal gi en fersk logg, men aldri slette den gamle i det skjulte."""
    _drain(state)
    old_path = state.vault.path
    lines_before = len(state.vault.entries())
    assert lines_before > 0

    state.reset()

    assert state.vault.entries() == []
    assert state.snapshot()["log"]["lines"] == 0

    archived = state.snapshot()["log"]["archived"]
    assert archived, "UI maa si hvor den gamle loggen ble lagt"
    archived_path = Path(archived)
    assert archived_path.exists()
    assert archived_path != old_path
    # Den gamle loggen er flyttet, ikke slettet: alle linjene er fortsatt der.
    assert len(archived_path.read_text(encoding="utf-8").splitlines()) == lines_before


def test_the_log_after_a_reset_verifies_from_scratch(state):
    """Den nye loggen skal ha sin egen hash-kjede, ikke henge etter den gamle."""
    _drain(state)
    state.reset()
    _drain(state)
    result = state.verify()
    assert result["ok"] is True
    assert state.vault.entries()[0].seq == 0


def test_the_snapshot_has_everything_the_page_needs(state):
    snap = state.snapshot()
    assert {
        "company",
        "waiting",
        "blocked",
        "answered",
        "calm",
        "calm_total",
        "notices",
        "feed",
        "story",
        "log",
    } <= set(snap)
    assert snap["company"] == "Nordlys Forsikring"
    # Snapshot maa kunne sendes som JSON uten videre behandling.
    json.dumps(snap)


# ---------------------------------------------------------------------------
# HTTP: appen svarer faktisk
# ---------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server() -> str:
    """Starter den ekte appen paa en ledig port. Hopper over testen hvis den ikke kommer opp."""
    uvicorn = pytest.importorskip("uvicorn")
    from ui.app import app

    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    srv = uvicorn.Server(config)
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()

    base = f"http://127.0.0.1:{port}"
    for _ in range(100):
        if srv.started:
            break
        threading.Event().wait(0.05)
    else:
        srv.should_exit = True
        pytest.skip("appen kom ikke opp")

    yield base

    srv.should_exit = True
    thread.join(timeout=5)


def _get(base: str, path: str):
    with urllib.request.urlopen(base + path, timeout=5) as res:
        return res.status, json.loads(res.read())


def _post(base: str, path: str, body: dict | None = None):
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(
        base + path, data=data, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=5) as res:
        return res.status, json.loads(res.read())


def test_the_page_and_its_files_are_served(server):
    for path in ("/", "/static/style.css", "/static/app.js"):
        with urllib.request.urlopen(server + path, timeout=5) as res:
            assert res.status == 200
            assert res.read()


def test_the_endpoints_answer(server):
    _post(server, "/api/reset")

    status, snap = _get(server, "/api/state")
    assert status == 200 and snap["company"] == "Nordlys Forsikring"

    status, out = _post(server, "/api/feed/step")
    assert status == 200 and out["card"] is not None

    status, result = _get(server, "/api/verify")
    assert status == 200 and result["ok"] is True

    status, after = _get(server, "/api/after")
    assert status == 200 and isinstance(after["items"], list)

    status, story = _post(server, "/api/story/start")
    assert status == 200 and story["story"]["index"] == 0

    status, story = _post(server, "/api/story/step")
    assert status == 200 and story["story"]["index"] == 1

    status, story = _get(server, "/api/story")
    assert status == 200 and story["story_id"] == "binance_inspired"

    _post(server, "/api/reset")


def test_approving_over_http_needs_the_right_amount(server):
    _post(server, "/api/reset")
    while _post(server, "/api/feed/step")[1]["card"] is not None:
        pass

    snap = _get(server, "/api/state")[1]
    transfers = [
        c for c in snap["waiting"] if c["request"]["amount"] == BIG_TRANSFER_NOK
    ]
    assert transfers, "demoen skal ha en roed overfoering paa 10 000 000 kr"
    card = transfers[0]
    assert card["decision"]["requires_typed_amount"] is True
    request_id = card["request"]["id"]

    status, out = _post(
        server,
        "/api/respond",
        {"request_id": request_id, "approved": True, "typed_amount": "42"},
    )
    assert status == 200 and out["ok"] is False

    status, out = _post(
        server,
        "/api/respond",
        {
            "request_id": request_id,
            "approved": True,
            "typed_amount": "10 000 000",
            "seconds_to_decide": 4.0,
        },
    )
    assert status == 200 and out["ok"] is True

    _post(server, "/api/reset")


def _waiting_transfer_id(server: str) -> str:
    while _post(server, "/api/feed/step")[1]["card"] is not None:
        pass
    snap = _get(server, "/api/state")[1]
    cards = [c for c in snap["waiting"] if c["request"]["amount"] == BIG_TRANSFER_NOK]
    assert cards, "demoen skal ha en roed overfoering paa 10 000 000 kr"
    return cards[0]["request"]["id"]


@pytest.mark.parametrize(
    "juks",
    ["100000,00", "100000.00", "1000000,0", "-10000000", "+10000000", "abc10000000xyz"],
)
def test_the_amount_gate_cannot_be_bypassed_over_http(server, juks):
    """F1 i docs/REDTEAM.md: disse ble alle godtatt mot 10 000 000.

    Verre enn ingen sjekk: loggen ville etterpaa vist at operatoeren bekreftet
    ti millioner, selv om det de skrev var et helt annet beloep.
    """
    _post(server, "/api/reset")
    request_id = _waiting_transfer_id(server)

    status, out = _post(
        server, "/api/respond", {"request_id": request_id, "approved": True, "typed_amount": juks}
    )
    assert status == 200
    assert out["ok"] is False
    assert "stemmer ikke" in out["error"]
    # Og den staar fortsatt og venter paa et menneske.
    assert request_id in [c["request"]["id"] for c in out["state"]["waiting"]]

    _post(server, "/api/reset")


def test_a_very_long_amount_gives_a_clean_no_not_a_500(server):
    """F3: mer enn 4300 siffer sprengte Pythons int() og ga HTTP 500."""
    _post(server, "/api/reset")
    request_id = _waiting_transfer_id(server)

    status, out = _post(
        server,
        "/api/respond",
        {"request_id": request_id, "approved": True, "typed_amount": "1" * 5000},
    )
    assert status == 200
    assert out["ok"] is False
    assert "stemmer ikke" in out["error"]

    _post(server, "/api/reset")


def test_the_log_records_the_amount_we_parsed_not_the_raw_text(server):
    """Loggen skal vise tallet som faktisk ble vurdert."""
    _post(server, "/api/reset")
    request_id = _waiting_transfer_id(server)

    status, out = _post(
        server,
        "/api/respond",
        {"request_id": request_id, "approved": True, "typed_amount": "10.000.000 kr"},
    )
    assert status == 200 and out["ok"] is True
    assert out["card"]["human"]["typed_amount"] == BIG_TRANSFER_NOK

    _post(server, "/api/reset")
