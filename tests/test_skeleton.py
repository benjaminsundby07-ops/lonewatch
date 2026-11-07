"""Røyktest for skjelettet: hele flyten én gang gjennom."""

from __future__ import annotations

from agents.scenarios import all_scenarios, dangerous_scenarios
from contracts import ActionType, Verdict
from gateway import evaluate
from run_demo import run
from vault import Vault, pseudonymize


def _big_transfer_id() -> str:
    """Id-en til overfoeringen paa 10 000 000 kr til ukjent konto."""
    hits = [
        r.id
        for r in dangerous_scenarios()
        if r.action_type is ActionType.TRANSFER_MONEY and not r.recipient_known
    ]
    assert len(hits) == 1, hits
    return hits[0]


def test_full_flow_transfer_is_red_and_log_verifies():
    vault = run(Vault())

    decisions = [e.payload for e in vault.entries() if e.kind == "decision"]
    by_id = {d["request_id"]: d for d in decisions}

    # Hver forespoersel skal ha fatt en avgjoerelse.
    assert set(by_id) == {r.id for r in all_scenarios()}

    # Kalender og dokumentlesing er hverdagsarbeid og skal ikke forstyrre noen.
    calm = [
        r.id
        for r in all_scenarios()
        if r.action_type in (ActionType.UPDATE_CALENDAR, ActionType.READ_DOCUMENT)
    ]
    assert calm, "demodata skal inneholde harmloese forespoersler"
    for request_id in calm:
        assert by_id[request_id]["verdict"] == Verdict.ALLOW.value

    # Den store overfoeringen til ukjent konto maa stoppes og krever at et
    # menneske skriver beloepet.
    big = by_id[_big_transfer_id()]
    assert big["verdict"] == Verdict.RED.value
    assert "unknown_recipient" in big["reasons"]
    assert big["requires_typed_amount"] is True

    assert vault.verify() is None


def test_every_scenario_gets_a_decision():
    reqs = all_scenarios()
    assert len(reqs) >= 3
    for req in reqs:
        assert evaluate(req).request_id == req.id


def test_tampering_with_the_log_is_caught():
    vault = run(Vault())
    entries = vault._entries
    entries[1] = entries[1].model_copy(update={"payload": {"verdict": "allow"}})
    assert vault.verify() == 1


def test_pseudonymize_is_stable_and_hides_the_name():
    first = pseudonymize("ansatt-007")
    assert first == pseudonymize("ansatt-007")
    assert first.startswith("emp_")
    assert "ansatt" not in first
    assert first != pseudonymize("ansatt-008")
