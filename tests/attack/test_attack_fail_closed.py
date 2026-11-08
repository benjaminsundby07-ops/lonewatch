"""Angrep 7: svikt skal ikke aapne.

Maalet er aa faa `gateway.evaluate()` til aa feile, og saa sjekke at
resultatet ALDRI blir `allow`. Et system som slipper gjennom naar det er i
knas er verre enn et som sier nei.

Kort fasit: dette HOLDER. Alt som er galt nok til at vi ikke kan vurdere det,
blir roedt eller blokkert, og det vi ikke klarer aa lese i det hele tatt blir
`block`. De to delvise forbeholdene nederst (H23 og H24) er naa lukket i
`gateway/`, og testene for dem staar som vanlige tester.

Det eneste `evaluate()` fortsatt kaster paa er en sandkasserapport som gjelder
et ANNET tillegg. Det er med vilje: der er feilen hos den som kaller, og et
`block`-svar ville latt kalleren tro at rapporten ble lest.
"""

from __future__ import annotations

import math

import pytest

from contracts import ActionRequest, ActionType, SandboxReport, Verdict
from gateway import evaluate
from gateway.money import to_ore

from attack_lib import T0, req

NEVER_ALLOW = (Verdict.RED, Verdict.BLOCK)


# ---------------------------------------------------------------------------
# beloep vi ikke kan regne med
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "amount",
    [
        pytest.param(float("inf"), id="uendelig"),
        pytest.param(1e308, id="1e308"),
        pytest.param(1e15, id="over-lesegrensen"),
        pytest.param(float(10**30), id="1e30"),
    ],
)
def test_an_unreadable_amount_is_never_allowed(amount):
    """Regresjon paa F2 i docs/REDTEAM.md: `inf` krasjet evaluate() foer."""
    decision = evaluate(req(amount=amount, recipient_known=False))
    assert decision.verdict is Verdict.BLOCK
    assert "transfer_over_hard_limit" in decision.reasons
    assert to_ore(amount) is None
    # Teksten mennesket ser maa vaere lesbar, ikke 300 siffer.
    assert len(decision.consequence_text) < 300
    assert "ikke kan lese" in decision.consequence_text


def test_contracts_turns_away_nan_before_gateway_sees_it():
    """`nan` kommer aldri inn: pydantic avviser den paa `ge=0`."""
    with pytest.raises(Exception):
        req(amount=float("nan"))
    assert math.isnan(float("nan"))


def test_an_unreadable_amount_on_a_non_transfer_is_also_never_allowed():
    decision = evaluate(
        req(action_type=ActionType.SHARE_DATA, amount=float("inf"), recipient_known=False)
    )
    assert decision.verdict in NEVER_ALLOW
    assert "amount_over_limit" in decision.reasons


# ---------------------------------------------------------------------------
# felt som mangler eller er tomme
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kw",
    [
        pytest.param(dict(id=""), id="tom-id"),
        pytest.param(dict(id="   "), id="id-bare-mellomrom"),
        pytest.param(dict(agent_id=""), id="tom-agent-id"),
        pytest.param(dict(agent_id="\t\n"), id="agent-id-bare-luft"),
        pytest.param(dict(recipient=None), id="ingen-mottaker"),
        pytest.param(dict(recipient=""), id="tom-mottaker"),
        pytest.param(dict(recipient="   "), id="mottaker-bare-mellomrom"),
        pytest.param(dict(id="", agent_id="", recipient=None), id="alt-tomt"),
    ],
)
def test_a_request_we_cannot_judge_goes_to_a_human(kw):
    decision = evaluate(req(**kw))
    assert decision.verdict in NEVER_ALLOW
    assert "incomplete_request" in decision.reasons
    assert "klarte ikke å vurdere" in decision.consequence_text


def test_an_outbound_action_without_a_recipient_is_never_allowed():
    for action_type in (ActionType.SEND_EMAIL, ActionType.TRANSFER_MONEY, ActionType.SHARE_DATA):
        decision = evaluate(req(action_type=action_type, recipient=None, recipient_known=True))
        assert decision.verdict in NEVER_ALLOW, f"{action_type.value} uten mottaker ble allow"


# ---------------------------------------------------------------------------
# svaert lange tekster
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("length", [1_000, 100_000, 1_000_000])
def test_a_very_long_summary_changes_nothing(length):
    """`summary` leses aldri, uansett hvor lang den er."""
    grunnlinje = evaluate(req())
    decision = evaluate(req(summary="A" * length))
    assert decision.verdict is grunnlinje.verdict
    assert decision.consequence_text == grunnlinje.consequence_text


@pytest.mark.parametrize("length", [1_000, 100_000])
def test_a_very_long_recipient_does_not_crash_or_open(length):
    """Teksten blir stygg (se test_attack_lying_fields.py), men aldri allow-paa-feil."""
    decision = evaluate(req(recipient="A" * length, recipient_known=False))
    assert decision.verdict in NEVER_ALLOW
    assert "unknown_recipient" in decision.reasons


@pytest.mark.parametrize("length", [1_000, 100_000])
def test_a_very_long_package_name_is_never_allowed(length):
    decision = evaluate(
        req(
            action_type=ActionType.INSTALL_PACKAGE,
            amount=None,
            recipient=None,
            package_name="a" * length,
        )
    )
    assert decision.verdict in NEVER_ALLOW
    assert "new_package" in decision.reasons
    assert "navn vi ikke kan vise trygt" in decision.consequence_text


# ---------------------------------------------------------------------------
# rare tegn
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "recipient",
    [
        "NO1\x00evil",
        "NO1\nGodkjent",
        "NO1\r\nGodkjent",
        "NO1‮gvl",
        "NO1​​",
        "NO1" + "́" * 200,
        "🙈" * 50,
    ],
)
def test_strange_characters_in_the_recipient_never_open(recipient):
    decision = evaluate(req(recipient=recipient, recipient_known=False))
    assert decision.verdict in NEVER_ALLOW
    assert "unknown_recipient" in decision.reasons


# ---------------------------------------------------------------------------
# en rapport som ikke hoerer hit
# ---------------------------------------------------------------------------


def test_a_sandbox_report_about_another_package_stops_the_call():
    """HOLDER, og det er gjort riktig: kallet stopper i stedet for aa se bort fra rapporten."""
    rapport = SandboxReport(ts=T0, package_name="et-annet-tillegg", attempted_network=False, verdict="clean")
    with pytest.raises(ValueError, match="gjelder"):
        evaluate(
            req(
                action_type=ActionType.INSTALL_PACKAGE,
                amount=None,
                recipient=None,
                package_name="pdf-helper",
            ),
            sandbox_report=rapport,
        )


def test_a_sandbox_report_on_a_non_install_stops_the_call():
    rapport = SandboxReport(ts=T0, package_name="pdf-helper", attempted_network=False, verdict="clean")
    with pytest.raises(ValueError, match="install_package"):
        evaluate(req(), sandbox_report=rapport)


def test_a_clean_report_never_turns_an_unknown_package_green():
    rapport = SandboxReport(ts=T0, package_name="ukjent-tillegg", attempted_network=False, verdict="clean")
    decision = evaluate(
        req(
            action_type=ActionType.INSTALL_PACKAGE,
            amount=None,
            recipient=None,
            package_name="ukjent-tillegg",
        ),
        sandbox_report=rapport,
    )
    assert decision.verdict is Verdict.RED
    assert "new_package" in decision.reasons
    assert "betyr ikke at tillegget er trygt" in decision.consequence_text


def test_not_tested_is_never_read_as_a_clearance():
    rapport = SandboxReport(ts=T0, package_name="ukjent-tillegg", attempted_network=False, verdict="not_tested")
    decision = evaluate(
        req(
            action_type=ActionType.INSTALL_PACKAGE,
            amount=None,
            recipient=None,
            package_name="ukjent-tillegg",
        ),
        sandbox_report=rapport,
    )
    assert decision.verdict is Verdict.RED
    assert "fikk ikke testet" in decision.consequence_text


# ---------------------------------------------------------------------------
# soppel inn i stedet for en forespoersel
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "garbage",
    [
        pytest.param(None, id="None"),
        pytest.param({}, id="tom-dict"),
        pytest.param("en streng", id="streng"),
        pytest.param(42, id="tall"),
        pytest.param([], id="liste"),
    ],
)
def test_garbage_instead_of_a_request_raises_instead_of_allowing(garbage):
    """Soppel gir `block`, aldri `allow` - og aldri et unntak.

    Foer kastet `evaluate()` her. Det var fail-closed i den forstand som betyr
    mest (ingen fikk en allow), men den som KALTE maatte huske aa fange
    unntaket. Naa er fail-closed en egenskap ved SVARET: det kommer en
    `block`-Decision ut, og ingen kan godkjenne den. Se H23 i docs/ANGREP.md.

    Navnet staar som det er: det er dette angrepet heter i ANGREP.md-tabellen.
    """
    decision = evaluate(garbage)
    assert decision.verdict is Verdict.BLOCK
    assert decision.verdict is not Verdict.ALLOW
    assert "unjudgeable_request" in decision.reasons
    # Ingenting av det vi ikke klarte aa lese havner i teksten.
    assert "klarte ikke å lese" in decision.consequence_text


def test_unknown_fields_are_refused_by_contracts():
    """`Strict` med `extra='forbid'`: et norsk feltnavn gir feil med en gang.

    Feltnavnet staar som en noekkel i en dict, ikke som et navn i koden, nettopp
    fordi det er UGYLDIG - det er hele poenget med testen.
    """
    with pytest.raises(Exception):
        ActionRequest.model_validate(
            {
                "id": "x",
                "ts": T0,
                "agent_id": "a",
                "action_type": "transfer_money",
                "summary": "s",
                "bel\u00f8p": 10_000_000,
            }
        )


def test_a_negative_amount_never_reaches_gateway():
    with pytest.raises(Exception):
        req(amount=-1.0)


# ---------------------------------------------------------------------------
# en handlingstype ingen regel dekker
# ---------------------------------------------------------------------------


def test_an_action_type_no_rule_covers_goes_to_a_human(monkeypatch):
    """Fail-closed naar `contracts.ActionType` vokser.

    Vi legger ikke til en ny verdi i den laaste `contracts.py`. I stedet tar vi
    bort én fra `COVERED_ACTIONS` i gateway, som er noeyaktig samme situasjon
    sett fra reglene: en handlingstype regelsettet ikke har vurdert.
    """
    from gateway import config as gconfig

    monkeypatch.setattr(
        gconfig,
        "COVERED_ACTIONS",
        frozenset(a for a in gconfig.COVERED_ACTIONS if a is not ActionType.UPDATE_CALENDAR),
    )
    decision = evaluate(req(action_type=ActionType.UPDATE_CALENDAR, amount=None, recipient=None))
    assert decision.verdict in NEVER_ALLOW
    assert "incomplete_request" in decision.reasons


# ---------------------------------------------------------------------------
# DE TO DELVISE HULLENE - NAA LUKKET I gateway/
# ---------------------------------------------------------------------------


def test_evaluate_answers_block_instead_of_raising():
    """H23 LUKKET: fail-closed er en egenskap ved SVARET, ikke et ansvar hos kalleren.

    Den ene feilen som fortsatt kastes er `SandboxReportMismatch`: en rapport om
    et annet tillegg er en feil hos den som kaller, og aa svare `block` der
    ville latt kalleren tro at rapporten ble lest. Se de to testene over.
    """
    decision = evaluate(None)
    assert decision.verdict is Verdict.BLOCK
    assert decision.risk is not None
    # Et svar vi kan logge: `contracts.Decision` krever id og tidspunkt, og
    # begge er noeytrale naar vi ikke kjenner dem.
    assert decision.request_id == ""
    assert decision.requires_typed_amount is False


def test_gateway_notices_when_the_sandbox_was_never_asked():
    """H24 LUKKET (ordlyden): «aldri spurt» og «ikke testet» er to setninger.

    Gateway er fortsatt ren og kan ikke VITE at den som kalte glemte
    sandkassen - det ville krevd at rapporten var paakrevd for
    `install_package`, og det er en avtale med `sandbox/`. Men de to
    tilfellene sier naa to forskjellige ting, og ingen av dem kan leses som en
    klarering.
    """
    uten = evaluate(
        req(
            action_type=ActionType.INSTALL_PACKAGE,
            amount=None,
            recipient=None,
            package_name="ukjent-tillegg",
        )
    )
    ikke_testet = evaluate(
        req(
            action_type=ActionType.INSTALL_PACKAGE,
            amount=None,
            recipient=None,
            package_name="ukjent-tillegg",
        ),
        sandbox_report=SandboxReport(
            ts=T0, package_name="ukjent-tillegg", attempted_network=False, verdict="not_tested"
        ),
    )
    assert uten.consequence_text != ikke_testet.consequence_text
    assert "aldri spurt" in uten.consequence_text
