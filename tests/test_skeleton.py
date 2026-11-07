"""Røyktest for skjelettet: hele flyten én gang gjennom."""

from __future__ import annotations

from agents.scenarios import all_scenarios
from contracts import Verdict
from gateway import evaluate
from run_demo import run
from vault import Vault, pseudonymize


def test_full_flow_transfer_is_red_and_log_verifies():
    vault = run(Vault())

    decisions = [e.payload for e in vault.entries() if e.kind == "decision"]
    by_id = {d["request_id"]: d for d in decisions}

    assert by_id["req_0001"]["verdict"] == Verdict.ALLOW.value
    assert by_id["req_0002"]["verdict"] == Verdict.ALLOW.value
    assert by_id["req_0003"]["verdict"] == Verdict.RED.value
    assert "unknown_recipient" in by_id["req_0003"]["reasons"]
    assert by_id["req_0003"]["requires_typed_amount"] is True

    assert vault.verify() is None


def test_every_scenario_gets_a_decision():
    reqs = all_scenarios()
    assert len(reqs) == 3
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
