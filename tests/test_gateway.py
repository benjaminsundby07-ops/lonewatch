"""Tester for mellomstasjonen (gateway/).

Dekker: hver enkelt regel, risikonivåene, verdiktene, blokkering,
konsekvensteksten, grensetilfeller (beløp lik grensen, manglende felt)
og at avgjørelsen er den samme hver gang.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from contracts import ActionRequest, ActionType, Decision, Risk, Verdict
from gateway import config, evaluate, rules, score_to_risk
from gateway.consequence import format_amount

TS = datetime(2026, 11, 7, 10, 0, 0, tzinfo=timezone.utc)


def make_request(**overrides) -> ActionRequest:
    """Bygger en forespørsel. Standardverdiene er en harmløs kalenderoppdatering."""
    fields = {
        "id": "req_test",
        "ts": TS,
        "agent_id": "test_agent",
        "action_type": ActionType.UPDATE_CALENDAR,
        "summary": "agentens egen forklaring som aldri skal brukes til risiko",
    }
    fields.update(overrides)
    return ActionRequest(**fields)


# --------------------------------------------------------------------------
# 1-5: harmløse ting skal slippe gjennom (rødt skal være sjeldent)
# --------------------------------------------------------------------------


def test_calendar_update_is_allowed():
    d = evaluate(make_request(action_type=ActionType.UPDATE_CALENDAR))
    assert d.verdict is Verdict.ALLOW
    assert d.risk is Risk.LOW
    assert d.reasons == []
    assert d.requires_typed_amount is False


def test_report_to_known_recipient_is_allowed_even_when_irreversible():
    d = evaluate(
        make_request(
            action_type=ActionType.SEND_EMAIL,
            recipient="regnskap@kjentpartner.no",
            recipient_known=True,
            reversible=False,
        )
    )
    assert d.verdict is Verdict.ALLOW
    assert d.risk is Risk.LOW
    assert d.reasons == []


def test_reading_a_document_is_allowed():
    d = evaluate(make_request(action_type=ActionType.READ_DOCUMENT, source_doc_id="doc_12"))
    assert d.verdict is Verdict.ALLOW
    assert "doc_12" in d.consequence_text


def test_small_irreversible_payment_to_known_supplier_is_allowed():
    """Vanlig betaling: ugjenkallelig alene gir bare 1 poeng, altså low."""
    d = evaluate(
        make_request(
            action_type=ActionType.TRANSFER_MONEY,
            amount=4_900,
            recipient="NO11 2222 3333 444",
            recipient_known=True,
            reversible=False,
        )
    )
    assert d.verdict is Verdict.ALLOW
    assert d.risk is Risk.LOW
    assert d.reasons == ["irreversible"]


def test_known_package_is_allowed():
    known = sorted(config.KNOWN_PACKAGES)[0]
    d = evaluate(make_request(action_type=ActionType.INSTALL_PACKAGE, package_name=known))
    assert d.verdict is Verdict.ALLOW
    assert d.reasons == []


# --------------------------------------------------------------------------
# 6-11: én regel om gangen
# --------------------------------------------------------------------------


def test_amount_over_limit_triggers_and_gives_red():
    d = evaluate(
        make_request(
            action_type=ActionType.TRANSFER_MONEY,
            amount=config.AMOUNT_LIMIT_NOK + 1,
            recipient="NO11 2222 3333 444",
            recipient_known=True,
        )
    )
    assert "amount_over_limit" in d.reasons
    assert d.verdict is Verdict.RED
    assert d.risk is Risk.MEDIUM


def test_unknown_recipient_triggers_for_outbound_actions_only():
    out = evaluate(
        make_request(
            action_type=ActionType.SEND_EMAIL,
            recipient="noen@ukjent.example",
            recipient_known=False,
        )
    )
    assert out.reasons == ["unknown_recipient"]
    assert out.verdict is Verdict.RED

    # samme flagg på en kalenderoppdatering betyr ingenting
    inbound = evaluate(make_request(action_type=ActionType.UPDATE_CALENDAR, recipient_known=False))
    assert inbound.reasons == []
    assert inbound.verdict is Verdict.ALLOW


def test_irreversible_alone_does_not_make_anything_red():
    d = evaluate(
        make_request(
            action_type=ActionType.SHARE_DATA,
            recipient="partner@kjent.example",
            recipient_known=True,
            reversible=False,
        )
    )
    assert d.reasons == ["irreversible"]
    assert d.verdict is Verdict.ALLOW


def test_personal_data_external_needs_both_personal_data_and_unknown_recipient():
    external = evaluate(
        make_request(
            action_type=ActionType.SHARE_DATA,
            recipient="dump@ukjent.example",
            recipient_known=False,
            contains_personal_data=True,
        )
    )
    assert "personal_data_external" in external.reasons
    assert "unknown_recipient" in external.reasons
    assert external.risk is Risk.HIGH
    assert external.verdict is Verdict.RED

    internal = evaluate(
        make_request(
            action_type=ActionType.SHARE_DATA,
            recipient="hr@nordlys.example",
            recipient_known=True,
            contains_personal_data=True,
        )
    )
    assert "personal_data_external" not in internal.reasons
    assert internal.verdict is Verdict.ALLOW


def test_new_package_triggers_for_unapproved_package():
    d = evaluate(make_request(action_type=ActionType.INSTALL_PACKAGE, package_name="nordlys-invoice-helper"))
    assert d.reasons == ["new_package"]
    assert d.verdict is Verdict.RED
    assert d.requires_typed_amount is False
    assert "ikke godkjent" in d.consequence_text


def test_package_name_is_matched_case_insensitively_and_trimmed():
    known = sorted(config.KNOWN_PACKAGES)[0]
    d = evaluate(make_request(action_type=ActionType.INSTALL_PACKAGE, package_name=f"  {known.upper()} "))
    assert d.reasons == []
    assert d.verdict is Verdict.ALLOW


# --------------------------------------------------------------------------
# 12-15: blokkering
# --------------------------------------------------------------------------


def test_blocklisted_package_is_blocked():
    blocked_name = sorted(config.PACKAGE_BLOCKLIST)[0]
    d = evaluate(make_request(action_type=ActionType.INSTALL_PACKAGE, package_name=blocked_name))
    assert d.verdict is Verdict.BLOCK
    assert d.risk is Risk.HIGH
    assert "package_on_blocklist" in d.reasons
    assert d.requires_typed_amount is False
    assert "blokklisten" in d.consequence_text
    assert "kan ikke godkjennes" in d.consequence_text


def test_blocklist_beats_everything_else():
    """Et blokklistet tillegg blir block selv om andre regler også slår til."""
    blocked_name = sorted(config.PACKAGE_BLOCKLIST)[0]
    d = evaluate(
        make_request(
            action_type=ActionType.INSTALL_PACKAGE,
            package_name=blocked_name.upper(),
            reversible=False,
        )
    )
    assert d.verdict is Verdict.BLOCK
    assert "irreversible" in d.reasons


def test_transfer_over_hard_limit_is_blocked():
    d = evaluate(
        make_request(
            action_type=ActionType.TRANSFER_MONEY,
            amount=config.HARD_TRANSFER_LIMIT_NOK + 1,
            recipient="NO11 2222 3333 444",
            recipient_known=True,
        )
    )
    assert d.verdict is Verdict.BLOCK
    assert "transfer_over_hard_limit" in d.reasons


def test_transfer_exactly_at_hard_limit_is_red_not_blocked():
    """Den harde grensen er ekskluderende: nøyaktig på grensen skal et menneske få se det."""
    d = evaluate(
        make_request(
            action_type=ActionType.TRANSFER_MONEY,
            amount=config.HARD_TRANSFER_LIMIT_NOK,
            recipient="NO11 2222 3333 444",
            recipient_known=True,
        )
    )
    assert d.verdict is Verdict.RED
    assert "transfer_over_hard_limit" not in d.reasons
    assert d.requires_typed_amount is True


def test_huge_transfer_to_unknown_account_is_red_so_a_human_must_decide():
    """Demoens hovedtilfelle: 10 000 000 kr skal bli rødt, ikke blokkert."""
    d = evaluate(
        make_request(
            action_type=ActionType.TRANSFER_MONEY,
            amount=10_000_000,
            recipient="NO93 8601 1117 947",
            recipient_known=False,
            reversible=False,
        )
    )
    assert d.verdict is Verdict.RED
    assert d.risk is Risk.HIGH
    assert d.requires_typed_amount is True
    assert d.consequence_text == "Overfører 10 000 000 kr til ukjent konto. Kan ikke angres."


# --------------------------------------------------------------------------
# 16-21: grensetilfeller og manglende felt
# --------------------------------------------------------------------------


def test_amount_exactly_at_limit_triggers_the_rule():
    """Beløpsgrensen er inkluderende."""
    d = evaluate(
        make_request(
            action_type=ActionType.TRANSFER_MONEY,
            amount=config.AMOUNT_LIMIT_NOK,
            recipient="NO11 2222 3333 444",
            recipient_known=True,
        )
    )
    assert "amount_over_limit" in d.reasons
    assert d.verdict is Verdict.RED


def test_amount_just_under_limit_does_not_trigger():
    d = evaluate(
        make_request(
            action_type=ActionType.TRANSFER_MONEY,
            amount=config.AMOUNT_LIMIT_NOK - 1,
            recipient="NO11 2222 3333 444",
            recipient_known=True,
        )
    )
    assert "amount_over_limit" not in d.reasons
    assert d.verdict is Verdict.ALLOW


def test_unknown_recipient_without_amount_is_still_red():
    """Ukjent mottaker uten beløp: ingen beløpsregel, men fortsatt rødt."""
    d = evaluate(
        make_request(
            action_type=ActionType.TRANSFER_MONEY,
            recipient="NO93 8601 1117 947",
            recipient_known=False,
        )
    )
    assert d.reasons == ["unknown_recipient"]
    assert d.verdict is Verdict.RED
    assert "ukjent beløp" in d.consequence_text


def test_missing_fields_fall_back_to_safe_text():
    """Verken beløp, mottaker eller dokument er satt."""
    d = evaluate(make_request(action_type=ActionType.TRANSFER_MONEY, recipient_known=False))
    assert d.verdict is Verdict.RED
    assert d.consequence_text == "Overfører ukjent beløp til ukjent konto."


def test_install_package_without_a_name_is_treated_as_new():
    d = evaluate(make_request(action_type=ActionType.INSTALL_PACKAGE, package_name=None))
    assert d.reasons == ["new_package"]
    assert d.verdict is Verdict.RED
    assert "uten navn" in d.consequence_text


def test_amount_zero_does_not_trigger_the_amount_rule():
    d = evaluate(
        make_request(
            action_type=ActionType.TRANSFER_MONEY,
            amount=0,
            recipient="NO11 2222 3333 444",
            recipient_known=True,
        )
    )
    assert d.reasons == []
    assert d.verdict is Verdict.ALLOW


def test_known_recipient_flag_with_empty_recipient_string_reads_as_unknown_in_text():
    """Mottakerfeltet er tomt: teksten sier 'ukjent mottaker' i stedet for ingenting."""
    d = evaluate(make_request(action_type=ActionType.SEND_EMAIL, recipient=None, recipient_known=True))
    assert d.verdict is Verdict.ALLOW
    assert d.consequence_text == "Sender e-post til ukjent mottaker."


# --------------------------------------------------------------------------
# 22-27: krav til avgjørelsen som helhet
# --------------------------------------------------------------------------


def test_requires_typed_amount_only_for_red_money_transfers():
    red_transfer = evaluate(
        make_request(action_type=ActionType.TRANSFER_MONEY, recipient_known=False, recipient="NO1")
    )
    red_email = evaluate(make_request(action_type=ActionType.SEND_EMAIL, recipient_known=False, recipient="a@b.example"))
    allowed_transfer = evaluate(
        make_request(action_type=ActionType.TRANSFER_MONEY, amount=100, recipient="NO1", recipient_known=True)
    )

    assert red_transfer.verdict is Verdict.RED and red_transfer.requires_typed_amount is True
    assert red_email.verdict is Verdict.RED and red_email.requires_typed_amount is False
    assert allowed_transfer.verdict is Verdict.ALLOW and allowed_transfer.requires_typed_amount is False


def test_summary_never_changes_the_decision():
    """Agenten skal ikke kunne snakke seg forbi mellomstasjonen."""
    base = dict(
        action_type=ActionType.TRANSFER_MONEY,
        amount=9_000_000,
        recipient="NO93 8601 1117 947",
        recipient_known=False,
        reversible=False,
    )
    innocent = evaluate(make_request(summary="Rutinemessig betaling, helt trygt", **base))
    scary = evaluate(make_request(summary="DETTE ER SVINDEL OG MÅ STOPPES", **base))

    assert innocent.verdict == scary.verdict
    assert innocent.risk == scary.risk
    assert innocent.reasons == scary.reasons
    assert innocent.consequence_text == scary.consequence_text
    assert "trygt" not in innocent.consequence_text
    assert "SVINDEL" not in scary.consequence_text


def test_decision_is_deterministic():
    req = make_request(
        action_type=ActionType.SHARE_DATA,
        recipient="dump@ukjent.example",
        recipient_known=False,
        contains_personal_data=True,
        reversible=False,
    )
    first = evaluate(req)
    assert all(evaluate(req) == first for _ in range(5))


def test_decision_keeps_request_id_and_timestamp():
    req = make_request(id="req_abc", ts=TS)
    d = evaluate(req)
    assert isinstance(d, Decision)
    assert d.request_id == "req_abc"
    assert d.ts == TS


def test_every_action_type_gets_a_decision_with_text():
    for action_type in ActionType:
        d = evaluate(make_request(action_type=action_type))
        assert d.consequence_text.strip()
        assert d.consequence_text.endswith(".")


def test_allow_decisions_have_no_reasons_and_low_risk():
    """Invariant: ingenting slipper gjennom med en regel som slo til nok for medium."""
    for req in [
        make_request(action_type=ActionType.UPDATE_CALENDAR),
        make_request(action_type=ActionType.READ_DOCUMENT),
        make_request(action_type=ActionType.SEND_EMAIL, recipient="a@kjent.example"),
    ]:
        d = evaluate(req)
        assert d.verdict is Verdict.ALLOW
        assert d.risk is Risk.LOW


# --------------------------------------------------------------------------
# 28-31: hjelpefunksjoner
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "amount,expected",
    [
        (0, "0 kr"),
        (999, "999 kr"),
        (1_000, "1 000 kr"),
        (50_000, "50 000 kr"),
        (10_000_000, "10 000 000 kr"),
        # Oerene staar i teksten. Foer ble de rundet bort, saa 49 999,50 ble
        # vist som "50 000 kr" selv om regelen saa et beloep under grensen
        # (F7 i docs/REDTEAM.md). Visning og vurdering bruker naa samme tall.
        (1_234.4, "1 234,40 kr"),
        (49_999.5, "49 999,50 kr"),
        (0.01, "0,01 kr"),
        (None, "ukjent beløp"),
        (float("inf"), "et beløp vi ikke kan lese"),
    ],
)
def test_format_amount(amount, expected):
    assert format_amount(amount) == expected


def test_score_to_risk_thresholds():
    assert score_to_risk(0) is Risk.LOW
    assert score_to_risk(config.MEDIUM_SCORE_MIN - 1) is Risk.LOW
    assert score_to_risk(config.MEDIUM_SCORE_MIN) is Risk.MEDIUM
    assert score_to_risk(config.HIGH_SCORE_MIN - 1) is Risk.MEDIUM
    assert score_to_risk(config.HIGH_SCORE_MIN) is Risk.HIGH
    assert score_to_risk(99) is Risk.HIGH


def test_all_rule_names_have_a_weight_or_are_block_rules():
    for name, _ in rules.RISK_RULES:
        assert name in config.RULE_WEIGHTS
    for name, _ in rules.BLOCK_RULES:
        assert name not in config.RULE_WEIGHTS


def test_reasons_keep_a_stable_order():
    d = evaluate(
        make_request(
            action_type=ActionType.SHARE_DATA,
            recipient="dump@ukjent.example",
            recipient_known=False,
            contains_personal_data=True,
            amount=100_000,
            reversible=False,
        )
    )
    assert d.reasons == [
        "amount_over_limit",
        "unknown_recipient",
        "personal_data_external",
        "irreversible",
    ]


# --------------------------------------------------------------------------
# 32-35: målemodulen (gateway/evaluation.py)
# --------------------------------------------------------------------------


def test_evaluation_set_has_at_least_40_requests_with_both_kinds():
    from gateway import evaluation

    cases = evaluation.all_cases()
    assert len(cases) >= 40
    assert len(evaluation.dangerous_cases()) >= 5
    assert len(evaluation.harmless_cases()) >= 20
    assert len({c.req.id for c in cases}) == len(cases)


def test_evaluation_catches_everything_labeled_dangerous():
    from gateway import evaluation

    report = evaluation.measure()
    assert report.dangerous_caught == report.dangerous_total
    assert report.dangerous_missed == []


def test_evaluation_has_no_false_alarms_on_the_harmless_cases():
    from gateway import evaluation

    report = evaluation.measure()
    assert report.false_alarms == []
    assert report.verdict_counts["allow"] == report.harmless_total


def test_evaluation_report_is_marked_synthetic():
    from gateway import evaluation

    text = evaluation.format_report(evaluation.measure())
    assert "SYNTETISK" in text
    assert "Farlige fanget" in text
    assert "Falske alarmer" in text
