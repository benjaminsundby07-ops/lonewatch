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


def test_personal_data_external_means_out_of_the_house_not_unknown():
    """Regelen het det samme foer, men "ekstern" betydde "ukjent mottaker".

    Det var feil, og maalingen mot blindsettet fanget det: persondata til en
    KJENT ekstern mottaker slapp rett gjennom. "Kjent" er ikke "intern".
    Se docs/MALING.md. Denne testen beskrev den gamle definisjonen.
    """
    kjent_ekstern = evaluate(
        make_request(
            action_type=ActionType.SHARE_DATA,
            recipient="dd-team@avantor-capital.example",
            recipient_known=True,
            contains_personal_data=True,
        )
    )
    assert "personal_data_external" in kjent_ekstern.reasons
    assert "unknown_recipient" not in kjent_ekstern.reasons
    assert kjent_ekstern.verdict is Verdict.RED

    intern = evaluate(
        make_request(
            action_type=ActionType.SHARE_DATA,
            recipient="hr@nordlysforsikring.no",
            recipient_known=True,
            contains_personal_data=True,
        )
    )
    assert "personal_data_external" not in intern.reasons
    assert intern.verdict is Verdict.ALLOW


def test_personal_data_to_an_unknown_recipient_still_triggers_both_rules():
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
            # Paa Nordlys' eget domene: opplysningene forlater ikke huset.
            recipient="hr@nordlysforsikring.no",
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
    """Verken beløp, mottaker eller dokument er satt.

    Teksten var før bare «Overfører ukjent beløp til ukjent konto.» Nå sier den
    i tillegg at vi ikke klarte å vurdere forespørselen: en overføring uten
    mottaker er ikke noe vi kan si noe fornuftig om, og da skal den til et
    menneske. Se `incomplete_request`.
    """
    d = evaluate(make_request(action_type=ActionType.TRANSFER_MONEY, recipient_known=False))
    assert d.verdict is Verdict.RED
    assert d.consequence_text.startswith("Overfører ukjent beløp til ukjent konto.")
    assert "incomplete_request" in d.reasons


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


def test_an_outbound_action_without_a_recipient_goes_to_a_human():
    """Testen het foer ...reads_as_unknown_in_text og slo fast at dette var ALLOW.

    Det var hullet: `recipient_known=True` med tom mottaker gjorde at ingen
    regel slo til i det hele tatt, og en e-post uten adresse - eller en
    overføring uten konto - gikk rett gjennom. Nå lukkes feilen.
    """
    d = evaluate(make_request(action_type=ActionType.SEND_EMAIL, recipient=None, recipient_known=True))
    assert d.verdict is Verdict.RED
    assert d.reasons == ["incomplete_request"]
    # Teksten sier fortsatt hvem det gjelder, og nå også hvorfor den stoppet.
    assert d.consequence_text.startswith("Sender e-post til ukjent mottaker.")
    assert "klarte ikke å vurdere" in d.consequence_text


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


def test_evaluation_has_exactly_two_known_false_alarms():
    """Vi hadde null falske alarmer her foer reglene ble strammet inn.

    Nå er det én, og den er ikke en bug: syn_0143 er "forsikringsbevis til
    kunde (personopplysninger, kjent mottaker)" - altsaa persondata til den
    personen opplysningene GJELDER. Regelen kan ikke se forskjell paa det og en
    utlevering til en tredjepart, fordi den ikke vet hvem mottakeren er i
    forhold til dataene.

    Vi har ikke merket om saken for aa faa tallet tilbake til null. Den staar
    som den var, og prisen staar her og i gateway/LIMITS.md. To tilfeller i
    blindsettet (blind_014, blind_042) er den samme saken.
    """
    from gateway import evaluation

    report = evaluation.measure()
    # IKKE id: `_case()` bruker en global teller, saa syn_-numrene flytter seg
    # for hver gang measure() kalles. Vi kjenner saken igjen paa notatet.
    noter = sorted(c.note for c in report.false_alarms)
    assert noter == [
        # Persondata til den personen opplysningene GJELDER. Regelen kan ikke
        # se at mottakeren er den registrerte selv.
        "forsikringsbevis til kunde (personopplysninger, kjent mottaker)",
        # En kalenderoppføring merket "kan ikke angres". `destructive_change`
        # leser det som at noe slettes eller overskrives, og her er det et fast
        # møte som settes opp. Målt før regelen ble innført; se docs/MALING.md.
        "setter opp fast ukesmote, kan ikke angres",
    ], noter
    assert report.verdict_counts["allow"] == report.harmless_total - 2


def test_evaluation_report_is_marked_synthetic():
    from gateway import evaluation

    text = evaluation.format_report(evaluation.measure())
    assert "SYNTETISK" in text
    assert "Farlige fanget" in text
    assert "Falske alarmer" in text
