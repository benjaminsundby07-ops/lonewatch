"""Tester for agents/: demodata, hovedscenarioet og dokumentfellene.

Dette er tester paa SIMULERTE data. De sier ingenting om hvor gode reglene i
gateway er, bare at demodataene er sammenhengende og deterministiske.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from agents import scenarios, story, traps
from contracts import ActionRequest, ActionType, SandboxReport, TrapEvent

# ---------------------------------------------------------------------------
# scenarios.py
# ---------------------------------------------------------------------------


def test_about_forty_requests_and_nine_of_ten_are_harmless():
    reqs = scenarios.all_scenarios()
    assert 35 <= len(reqs) <= 45
    harmless = scenarios.harmless_scenarios()
    assert len(harmless) / len(reqs) >= 0.85


def test_all_five_agents_are_represented():
    used = {r.agent_id for r in scenarios.all_scenarios()}
    assert used == set(scenarios.AGENT_IDS)


def test_ids_are_unique_and_timeline_only_moves_forward():
    reqs = scenarios.all_scenarios()
    assert len({r.id for r in reqs}) == len(reqs)
    stamps = [r.ts for r in reqs]
    assert stamps == sorted(stamps)
    assert all(r.ts.tzinfo is not None for r in reqs)


def test_same_seed_gives_the_exact_same_list_every_time():
    first = [r.model_dump(mode="json") for r in scenarios.all_scenarios()]
    second = [r.model_dump(mode="json") for r in scenarios.all_scenarios()]
    assert first == second


def test_harmless_and_dangerous_together_are_the_whole_set():
    reqs = scenarios.all_scenarios()
    split = scenarios.harmless_scenarios() + scenarios.dangerous_scenarios()
    assert {r.id for r in split} == {r.id for r in reqs}
    assert len(split) == len(reqs)


def test_the_dangerous_ones_are_the_three_we_promised():
    danger = {r.action_type for r in scenarios.dangerous_scenarios()}
    assert ActionType.TRANSFER_MONEY in danger
    assert ActionType.SHARE_DATA in danger
    assert ActionType.INSTALL_PACKAGE in danger


def test_the_big_transfer_has_the_fields_the_rules_need():
    hits = [
        r
        for r in scenarios.dangerous_scenarios()
        if r.action_type is ActionType.TRANSFER_MONEY
    ]
    assert len(hits) == 1
    big = hits[0]
    assert big.amount == 10_000_000
    assert big.recipient_known is False
    assert big.reversible is False
    assert big.recipient


def test_customer_list_is_personal_data_to_an_unknown_recipient():
    hits = [
        r
        for r in scenarios.dangerous_scenarios()
        if r.action_type is ActionType.SHARE_DATA
    ]
    assert len(hits) == 1
    assert hits[0].contains_personal_data is True
    assert hits[0].recipient_known is False


def test_the_suspicious_package_has_a_name():
    hits = [
        r
        for r in scenarios.dangerous_scenarios()
        if r.action_type is ActionType.INSTALL_PACKAGE
    ]
    assert len(hits) == 1
    assert hits[0].package_name
    assert hits[0].recipient_known is False


def test_harmless_requests_never_combine_unknown_recipient_with_no_undo():
    """Vaar egen merking skal vaere aerlig: ingen skjult bombe blant de harmloese."""
    for req in scenarios.harmless_scenarios():
        assert not (req.recipient_known is False and req.reversible is False), req.id


def test_every_referenced_document_actually_exists():
    for req in scenarios.all_scenarios():
        if req.source_doc_id:
            assert traps.find_doc(req.source_doc_id) is not None, req.source_doc_id


def test_find_scenario_and_labels():
    first = scenarios.all_scenarios()[0]
    assert scenarios.find_scenario(first.id) == first
    assert scenarios.find_scenario("finnes_ikke") is None
    assert scenarios.agent_label("hr") == "HR"
    assert scenarios.agent_label("ukjent_agent") == "ukjent_agent"
    assert scenarios.action_label(ActionType.TRANSFER_MONEY) == "Overfoerer penger"
    assert scenarios.action_label("transfer_money") == "Overfoerer penger"


# ---------------------------------------------------------------------------
# traps.py
# ---------------------------------------------------------------------------


def test_there_are_both_clean_and_trapped_documents():
    assert traps.trapped_docs()
    assert traps.clean_docs()
    assert len(traps.all_docs()) == len(traps.trapped_docs()) + len(traps.clean_docs())
    assert all(d.is_trapped for d in traps.trapped_docs())
    assert not any(d.is_trapped for d in traps.clean_docs())


def test_document_ids_are_unique():
    ids = [d.doc_id for d in traps.all_docs()]
    assert len(set(ids)) == len(ids)


def test_the_trap_is_invisible_to_a_human_but_visible_to_an_agent():
    for doc in traps.trapped_docs():
        human = doc.visible_to_human()
        agent = doc.raw_for_agent()
        hidden = doc.hidden_text + "".join(doc.metadata.values())
        assert hidden, doc.doc_id
        # Det menneskelige laget skal vaere kortere og ikke inneholde fella.
        assert len(agent) > len(human)
        for marker in traps.found_markers(doc):
            assert marker not in human


def test_every_trapped_document_has_at_least_one_known_marker():
    for doc in traps.trapped_docs():
        assert traps.found_markers(doc), doc.doc_id


def test_clean_documents_have_no_markers():
    for doc in traps.clean_docs():
        assert traps.found_markers(doc) == []


def test_reading_a_trapped_document_gives_a_trap_event():
    ts = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)
    event = traps.trap_triggered(
        "doc_invoice_8841", "finance", access=traps.ACCESS_READ, ts=ts
    )
    assert isinstance(event, TrapEvent)
    assert event.doc_id == "doc_invoice_8841"
    assert event.agent_id == "finance"
    assert event.trap_id == "trap_invoice_rewrite"
    assert event.ts == ts
    assert "leste" in event.what_happened


def test_sending_out_a_trapped_document_says_sent_not_read():
    event = traps.trap_triggered(
        "doc_claim_4412", "customer_service", access=traps.ACCESS_SEND
    )
    assert event is not None
    assert "sendte ut" in event.what_happened


def test_clean_and_unknown_documents_give_no_event():
    assert traps.trap_triggered("doc_policy_terms_v12", "hr") is None
    assert traps.trap_triggered("finnes_ikke", "hr") is None


def test_unknown_access_mode_is_an_error():
    with pytest.raises(ValueError):
        traps.trap_triggered("doc_invoice_8841", "finance", access="delete")


def test_is_trapped_matches_the_documents():
    assert traps.is_trapped("doc_invoice_8841") is True
    assert traps.is_trapped("doc_policy_terms_v12") is False
    assert traps.is_trapped("finnes_ikke") is False


# ---------------------------------------------------------------------------
# story.py
# ---------------------------------------------------------------------------


def test_the_story_fits_in_ninety_seconds_and_moves_forward():
    s = story.binance_inspired()
    assert s.story_id == "binance_inspired"
    assert s.duration_seconds == 90
    seconds = [step.at_second for step in s.steps]
    assert seconds == sorted(seconds)
    assert seconds[0] == 0
    assert seconds[-1] <= 90


def test_the_chain_is_install_then_trapped_document_then_transfer():
    requests = story.story_requests()
    order = [r.action_type for r in requests]
    install = order.index(ActionType.INSTALL_PACKAGE)
    transfer = order.index(ActionType.TRANSFER_MONEY)
    reads = [i for i, a in enumerate(order) if a is ActionType.READ_DOCUMENT]
    assert install < transfer
    # Minst én dokumentlesing ligger mellom installasjonen og overfoeringen.
    assert any(install < i < transfer for i in reads)


def test_the_story_has_two_traps_and_one_sandbox_report():
    s = story.binance_inspired()
    trap_steps = [step for step in s.steps if step.trap is not None]
    sandbox_steps = [step for step in s.steps if step.sandbox is not None]
    assert len(trap_steps) == 2
    assert len(sandbox_steps) == 1
    assert all(isinstance(step.trap, TrapEvent) for step in trap_steps)
    assert isinstance(sandbox_steps[0].sandbox, SandboxReport)


def test_the_sandbox_report_is_marked_as_blocked_and_simulated():
    report = next(
        step.sandbox for step in story.binance_inspired().steps if step.sandbox
    )
    assert report.verdict == "blocked"
    assert report.attempted_network is True
    assert report.destinations
    assert "imulert" in report.notes  # "Simulert" / "simulert"


def test_story_requests_are_action_requests_with_their_own_ids():
    requests = story.story_requests()
    assert requests
    assert all(isinstance(r, ActionRequest) for r in requests)
    assert all(r.id.startswith("story_") for r in requests)
    # Ingen kollisjon med de 40 i scenarios.py.
    scenario_ids = {r.id for r in scenarios.all_scenarios()}
    assert not scenario_ids & {r.id for r in requests}


def test_story_step_timestamps_follow_at_second():
    for step in story.binance_inspired().steps:
        assert (step.ts - story.STORY_START_TS).total_seconds() == step.at_second
        if step.request is not None:
            assert step.request.ts == step.ts


def test_the_story_is_the_same_every_time():
    first = story.binance_inspired()
    second = story.binance_inspired()
    assert [s.title for s in first.steps] == [s.title for s in second.steps]
    assert [r.model_dump(mode="json") for r in first.requests()] == [
        r.model_dump(mode="json") for r in second.requests()
    ]


def test_every_step_has_norwegian_text_on_screen():
    for step in story.binance_inspired().steps:
        assert step.title.strip()
        assert step.detail.strip()
        assert step.kind in (
            story.STEP_NARRATION,
            story.STEP_REQUEST,
            story.STEP_TRAP,
            story.STEP_SANDBOX,
        )
