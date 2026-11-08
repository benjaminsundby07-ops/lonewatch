"""Angrep 3: dele en stor overfoering i mange smaa under grensen.

Grensen er 50 000 kr. Angrepet sender 49 000 kr om gangen og ser om reglene
ser summen. `gateway.evaluate()` tar et `history`-argument nettopp for dette.

Kort fasit:
  HOLDER  naar historikken sendes inn OG kontonummeret staves likt hver gang.
  HULL    naar kontonummeret staves med punktum eller bindestrek i stedet for
          mellomrom - samme konto for en bank, ulik noekkel for Lonewatch.
  HULL    naar agenten setter `ts` bakover: vinduet maales fra forespoerselens
          eget tidsstempel.
  HULL    naar betalingene spres paa flere kontoer.
  HULL    naar den som kaller evaluate() glemmer `history`.
"""

from __future__ import annotations

import pytest

from contracts import ActionType, Verdict
from gateway import evaluate

from attack_lib import T0, minutes, req

GRENSE = 50_000.0
DEL = 49_000.0
KONTO = "NO93 8601 1117 947"


def _run(amounts_and_recipients, *, descending=False, hours_apart=0, pass_history=True):
    """Kjoerer en rekke overfoeringer og gir listen av (verdict, reasons)."""
    from datetime import timedelta

    history = []
    out = []
    for i, (amount, recipient) in enumerate(amounts_and_recipients):
        if hours_apart:
            ts = T0 + timedelta(hours=hours_apart * i)
        elif descending:
            ts = T0 - timedelta(minutes=i)
        else:
            ts = minutes(i)
        r = req(id=f"split_{i}", ts=ts, amount=amount, recipient=recipient, reversible=False)
        decision = evaluate(r, history=list(history) if pass_history else None)
        out.append((decision.verdict, decision.reasons))
        history.append(r)
    return out


# ---------------------------------------------------------------------------
# HOLDER: samme konto, samme staving, historikk sendt inn
# ---------------------------------------------------------------------------


def test_splitting_into_small_transfers_is_caught_when_the_sum_is_seen():
    results = _run([(DEL, KONTO)] * 5)
    assert results[0][0] is Verdict.ALLOW, "foerste betaling er lovlig alene"
    for verdict, reasons in results[1:]:
        assert verdict is Verdict.RED
        assert "recipient_total_over_limit" in reasons


def test_the_sum_is_shown_to_the_human():
    """Mennesket skal se summen, ikke bare den ene betalingen."""
    history = [req(id=f"p{i}", ts=minutes(i), amount=DEL, recipient=KONTO) for i in range(2)]
    decision = evaluate(req(id="p9", ts=minutes(9), amount=DEL, recipient=KONTO), history=history)
    assert "recipient_total_over_limit" in decision.reasons
    assert "147 000 kr" in decision.consequence_text
    assert "til samme mottaker" in decision.consequence_text


def test_whitespace_and_case_in_the_account_number_do_not_help():
    """`normalize_recipient` fjerner mellomrom og store bokstaver. Det holder."""
    stavinger = [KONTO, "no93 8601 1117 947", "NO9386011117947", " NO93  8601 1117 947 ",
                 "NO93860111 17947"]
    results = _run([(DEL, s) for s in stavinger])
    assert results[0][0] is Verdict.ALLOW
    for verdict, reasons in results[1:]:
        assert verdict is Verdict.RED, "en annen staving med bare luft slapp unna summen"
        assert "recipient_total_over_limit" in reasons


# ---------------------------------------------------------------------------
# HULL: skilletegn i kontonummeret
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "HULL: `rules.normalize_recipient` fjerner BARE mellomrom "
        "(`re.sub(r'\\s+', ...)`) og setter smaa bokstaver. Punktum og "
        "bindestrek staar igjen, saa 'NO93 8601 1117 947', "
        "'NO93.8601.1117.947' og 'NO93-8601-1117-947' er tre ulike mottakere "
        "for Lonewatch og samme konto for banken. Angrepet sender 49 000 kr "
        "til hver staving: 196 000 kr til samme konto, fire ganger ALLOW, "
        "ingen summering, ingen roedt kort. Fiks: normaliser bort alt som ikke "
        "er bokstav eller siffer foer sammenligningen."
    ),
)
def test_punctuation_in_the_account_number_does_not_defeat_the_sum():
    stavinger = [KONTO, "NO93.8601.1117.947", "NO93-8601-1117-947", "NO93/8601/1117/947"]
    results = _run([(DEL, s) for s in stavinger])
    assert results[0][0] is Verdict.ALLOW
    for i, (verdict, reasons) in enumerate(results[1:], start=1):
        assert verdict is Verdict.RED, (
            f"staving {stavinger[i]!r} slapp gjennom; summen ble aldri sett"
        )


# ---------------------------------------------------------------------------
# HULL: agenten bestemmer tiden
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "HULL: vinduet regnes som `req.ts - 24t < prior.ts <= req.ts`, og "
        "`ts` er et felt agenten fyller ut selv. Setter agenten tidsstemplet "
        "BAKOVER for hver betaling, ligger alle tidligere betalinger etter "
        "`req.ts` og faller utenfor vinduet. Fem betalinger paa 49 000 kr blir "
        "fem ganger ALLOW. Aa regne fra `req.ts` i stedet for fra klokken er "
        "bevisst (det gjoer avgjoerelsen deterministisk), men prisen er at "
        "angriperen eier tidsaksen. Fiks: summer paa mottakstid i "
        "integrasjonslaget, eller avvis en `ts` som ligger foer forrige "
        "forespoersel fra samme agent."
    ),
)
def test_backdating_the_timestamp_does_not_defeat_the_window():
    results = _run([(DEL, KONTO)] * 5, descending=True)
    assert results[0][0] is Verdict.ALLOW
    for verdict, reasons in results[1:]:
        assert verdict is Verdict.RED, "tilbakedatering gjorde summen usynlig"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DELVIS HULL (bevisst satt grense, men verdt aa si hoeyt): vinduet er "
        "24 timer. 49 000 kr hver 25. time er 490 000 kr paa to uker, og hver "
        "enkelt er ALLOW. Taalmodighet er en gyldig angrepsstrategi. Fiks: et "
        "lengre vindu i tillegg (doegn + uke + maaned), eller et tak per "
        "mottaker per periode."
    ),
)
def test_spreading_the_payments_over_more_than_a_day_does_not_help():
    results = _run([(DEL, KONTO)] * 5, hours_apart=25)
    assert results[0][0] is Verdict.ALLOW
    for verdict, _ in results[1:]:
        assert verdict is Verdict.RED, "betalinger spredt over doegn ble aldri summert"


# ---------------------------------------------------------------------------
# HULL: spre paa flere kontoer
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "HULL: `recipient_total_ore` summerer bare per MOTTAKER. Ti betalinger "
        "paa 49 000 kr til ti forskjellige kontoer er 490 000 kr ut av huset, "
        "og hver enkelt er ALLOW. Reglene har ingen sum per AGENT, per doegn "
        "eller per virksomhet. Det staar ikke i gateway/LIMITS.md i dag. Fiks: "
        "en sum per agent-id (og gjerne per doegn) i tillegg til summen per "
        "mottaker."
    ),
)
def test_fanning_the_payments_out_over_many_accounts_does_not_help():
    kontoer = [f"NO93 8601 1117 9{i:02d}" for i in range(10)]
    results = _run([(DEL, k) for k in kontoer])
    roede = [v for v, _ in results if v is Verdict.RED]
    assert roede, (
        "ti betalinger paa 49 000 kr til ti kontoer: 490 000 kr ut, ingen roedt kort"
    )


# ---------------------------------------------------------------------------
# HULL: historikken er frivillig
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "HULL: `history` har standardverdi None, saa summeringen er noe den "
        "som KALLER evaluate() maa huske paa. `ui/state.py` husker det; "
        "`run_demo.py` og enhver ny integrasjon kan glemme det, og da er "
        "forsvaret borte uten at noe feiler eller advarer. Gateway husker "
        "ingenting selv. Fiks: gjoer `history` paakrevd (krever endring i "
        "grensesnittet), eller la gateway eie et kort minne over forespoersler "
        "den alt har sett."
    ),
)
def test_forgetting_to_pass_history_does_not_silently_remove_the_defence():
    results = _run([(DEL, KONTO)] * 5, pass_history=False)
    for verdict, _ in results[1:]:
        assert verdict is Verdict.RED, "uten history-argumentet forsvinner summeringen stille"


def test_the_demo_app_does_remember_the_history():
    """HOLDER: UI-laget sender historikken inn, saa demoen er dekket."""
    from ui.state import DemoState

    state = DemoState()
    for i in range(3):
        result = state.submit_custom("transfer_money", amount="49 000", recipient=KONTO)
        assert result["ok"] is True, result
    siste = result["card"]["decision"]
    assert siste["verdict"] == Verdict.RED.value
    assert "recipient_total_over_limit" in siste["reasons"]


def test_the_hard_limit_still_blocks_one_huge_transfer():
    """HOLDER: oppdelingen er noedvendig fordi ett stort beloep stoppes helt."""
    decision = evaluate(req(amount=60_000_000.0, action_type=ActionType.TRANSFER_MONEY))
    assert decision.verdict is Verdict.BLOCK
    assert "transfer_over_hard_limit" in decision.reasons
