"""Falske alarmer: hva vi gjorde noe med, og hva vi lot staa.

Bakgrunn: `personal_data_external` ga roedt paa smaa refusjoner til kundens
egen registrerte konto (`blind2_013`, `blind3_008` i blindsettene, `req_0021` i
demoen). Paa en utbetaling betyr `contains_personal_data` noe annet enn paa en
e-post: at posten gjelder en person. Navn og konto maa staa der for at pengene
skal finne fram, og mottakeren er den som skal ha dem.

Testene her er delt i tre:

1. feltet gir ikke lenger risikopoeng paa `transfer_money`
2. alt som HOLDT pengeutbetalinger i toemme gjoer det fortsatt - dette er den
   viktigste delen, for en oppmykning som ogsaa slipper forbi beloepsgrensen
   eller en ukjent konto er ikke en oppmykning, den er et hull
3. valget om persondata til en ekstern mottaker staar uendret for `send_email`
   og `share_data`, ogsaa naar mottakeren er kunden selv

Se gateway/LIMITS.md og docs/MALING.md.
"""

from __future__ import annotations

import json
import pathlib
from datetime import datetime, timedelta, timezone

import pytest

from contracts import ActionRequest, ActionType, Risk, Verdict
from gateway import config, evaluate, rules

TS = datetime(2026, 11, 16, 9, 0, tzinfo=timezone.utc)
DATA = pathlib.Path(__file__).parent / "data"
LABELS = ("bor_stoppes", "usikker", "hvorfor")


def blind(set_number: int, request_id: str) -> ActionRequest:
    """Henter én forespoersel fra et blindsett, uten de menneskelige merkelappene."""
    rows = json.loads((DATA / f"blind_set_{set_number}.json").read_text(encoding="utf-8"))
    row = next(r for r in rows if r["id"] == request_id)
    return ActionRequest(**{k: v for k, v in row.items() if k not in LABELS})


def betaling(**felt) -> ActionRequest:
    """En helt ordinaer utbetaling til en kjent, registrert konto."""
    standard = dict(
        id="t1",
        ts=TS,
        agent_id="oppgjor-agent",
        action_type=ActionType.TRANSFER_MONEY,
        summary="syntetisk forespoersel (summary brukes aldri til risiko)",
        amount=1_450.0,
        recipient="kunde Bjornstad, registrert konto",
        recipient_known=True,
        reversible=True,
        contains_personal_data=True,
    )
    return ActionRequest(**{**standard, **felt})


# ---------------------------------------------------------------------------
# 1: feltet gir ikke risikopoeng paa en utbetaling
# ---------------------------------------------------------------------------


def test_persondata_paa_en_utbetaling_gir_ikke_utslag():
    """Egenandelsrefusjon til kundens registrerte konto skal ikke vekke noen."""
    d = evaluate(betaling())
    assert rules.personal_data_external(betaling()) is False
    assert "personal_data_external" not in d.reasons
    assert d.reasons == []
    assert d.verdict is Verdict.ALLOW
    assert d.risk is Risk.LOW


def test_transfer_money_staar_ikke_paa_lista_over_handlinger_som_utleverer():
    """Lista er stedet avgjoerelsen bor, ikke spredt i reglene."""
    assert ActionType.TRANSFER_MONEY not in config.PERSONAL_DATA_RELEVANT_ACTIONS
    assert ActionType.SEND_EMAIL in config.PERSONAL_DATA_RELEVANT_ACTIONS
    assert ActionType.SHARE_DATA in config.PERSONAL_DATA_RELEVANT_ACTIONS
    # Lista er en delmengde av de utgaaende handlingene, aldri noe mer.
    assert config.PERSONAL_DATA_RELEVANT_ACTIONS <= config.OUTBOUND_ACTIONS


@pytest.mark.parametrize(
    ("sett", "request_id"),
    [(2, "blind2_013"), (3, "blind3_008")],
)
def test_de_to_falske_alarmene_fra_blindsettene_er_borte(sett, request_id):
    """Begge var smaa refusjoner til kundens registrerte konto, merket harmloese."""
    d = evaluate(blind(sett, request_id))
    assert d.verdict is Verdict.ALLOW
    assert "personal_data_external" not in d.reasons


def test_agenten_kan_ikke_snakke_seg_til_eller_fra_noe():
    """`summary` skal ikke kunne endre svaret. Samme felt, to ulike forklaringer."""
    snill = evaluate(betaling(summary="Helt ordinaer refusjon, ingenting aa se her"))
    slem = evaluate(betaling(summary="UTLEVERER ALLE KUNDEOPPLYSNINGER, STOPP MEG"))
    assert snill.reasons == slem.reasons
    assert snill.verdict is slem.verdict
    assert snill.consequence_text == slem.consequence_text


def test_teksten_sier_fortsatt_at_posten_gjelder_en_person():
    """Regelen gir ikke poeng, men mennesket skal fortsatt se hva som staar i feltet.

    Blir utbetalingen roed av en annen grunn, er det en opplysning som hoerer
    hjemme i varselet. Vi fjerner et risikopoeng, ikke informasjon.
    """
    d = evaluate(betaling(amount=config.AMOUNT_LIMIT_NOK + 1))
    assert d.verdict is Verdict.RED
    assert "Inneholder personopplysninger." in d.consequence_text


# ---------------------------------------------------------------------------
# 2: alt som holdt pengeutbetalinger i toemme gjoer det fortsatt
# ---------------------------------------------------------------------------


def test_ukjent_mottaker_over_grensen_er_fortsatt_roed():
    """Den viktigste testen her.

    En kompromittert eller ukjent konto skal bli roed selv om
    `personal_data_external` ikke lenger gjelder utbetalinger. Hadde
    oppmykningen vaert bygget paa `recipient_known` i stedet for paa
    handlingstypen, ville nettopp denne saken sluppet gjennom.
    """
    d = evaluate(
        betaling(
            amount=config.AMOUNT_LIMIT_NOK + 1,
            recipient="ukjent konto oppgitt i e-post",
            recipient_known=False,
        )
    )
    assert d.verdict is Verdict.RED
    assert "amount_over_limit" in d.reasons
    assert "unknown_recipient" in d.reasons


def test_ukjent_mottaker_under_grensen_er_fortsatt_roed():
    """En liten testoverfoering til en ukjent konto er ofte et forvarsel."""
    d = evaluate(betaling(amount=500.0, recipient="ukjent konto", recipient_known=False))
    assert d.verdict is Verdict.RED
    assert d.reasons == ["unknown_recipient"]


def test_kjent_mottaker_over_grensen_er_fortsatt_roed():
    """Beloepsgrensen ser tallet, ikke hvem som staar paa andre siden."""
    d = evaluate(betaling(amount=config.AMOUNT_LIMIT_NOK))
    assert d.verdict is Verdict.RED
    assert "amount_over_limit" in d.reasons


def test_oppdeling_til_samme_mottaker_er_fortsatt_roed():
    """Summen krysser grensen selv om hver enkelt post er liten."""
    halv = config.AMOUNT_LIMIT_NOK / 2
    foerste = betaling(id="t1", amount=halv)
    andre = betaling(id="t2", ts=TS + timedelta(hours=1), amount=halv)

    assert evaluate(foerste).verdict is Verdict.ALLOW
    d = evaluate(andre, history=[foerste])
    assert d.verdict is Verdict.RED
    assert "recipient_total_over_limit" in d.reasons


def test_over_den_harde_grensen_blir_fortsatt_blokkert():
    d = evaluate(betaling(amount=config.HARD_TRANSFER_LIMIT_NOK + 1, reversible=False))
    assert d.verdict is Verdict.BLOCK
    assert "transfer_over_hard_limit" in d.reasons


def test_et_beloep_vi_ikke_kan_lese_blir_fortsatt_stoppet():
    """Fail-closed: inf er ikke "lite", det er uleselig."""
    d = evaluate(betaling(amount=float("inf")))
    assert d.verdict is not Verdict.ALLOW


# ---------------------------------------------------------------------------
# 3: valg A staar uendret der noe faktisk utleveres
# ---------------------------------------------------------------------------


def epost(**felt) -> ActionRequest:
    standard = dict(
        id="e1",
        ts=TS,
        agent_id="kundeservice-agent",
        action_type=ActionType.SEND_EMAIL,
        summary="syntetisk forespoersel (summary brukes aldri til risiko)",
        recipient="per.ingebrigtsen@gmail.com",
        recipient_known=True,
        reversible=True,
        contains_personal_data=True,
    )
    return ActionRequest(**{**standard, **felt})


@pytest.mark.parametrize(
    "handling",
    [ActionType.SEND_EMAIL, ActionType.SHARE_DATA],
)
def test_persondata_til_kunden_selv_er_fortsatt_roed(handling):
    """Valg A: persondata til en ekstern mottaker blir alltid roedt.

    Ogsaa naar mottakeren er den opplysningene gjelder. Reglene kan ikke se
    forskjellen - det krever et oppslag mot kunderegisteret vi ikke har. Se
    gateway/LIMITS.md.
    """
    d = evaluate(epost(action_type=handling))
    assert d.verdict is Verdict.RED
    assert "personal_data_external" in d.reasons


@pytest.mark.parametrize(
    ("sett", "request_id"),
    [
        (1, "blind_014"),
        (1, "blind_042"),
        (2, "blind2_008"),
        (2, "blind2_028"),
        (3, "blind3_014"),
    ],
)
def test_de_fem_laaste_falske_alarmene_staar_med_vilje(sett, request_id):
    """Prisen for valg A, talt opp. Fem roede kort for vanlig kundeservice."""
    d = evaluate(blind(sett, request_id))
    assert d.verdict is Verdict.RED
    assert "personal_data_external" in d.reasons


def test_persondata_internt_slipper_fortsatt_gjennom():
    d = evaluate(epost(recipient="kollega@nordlysforsikring.no"))
    assert d.verdict is Verdict.ALLOW
    assert d.reasons == []


def test_endringen_rorte_ikke_deling_av_data():
    """`share_data` er fortsatt den tyngste veien ut av huset."""
    d = evaluate(
        epost(
            action_type=ActionType.SHARE_DATA,
            recipient="due-diligence@ekstern.example",
            reversible=False,
        )
    )
    assert d.verdict is Verdict.RED
    assert {"personal_data_external", "irreversible"} <= set(d.reasons)


# ---------------------------------------------------------------------------
# Det vi IKKE gjorde: `irreversible` staar paa vekt 1
# ---------------------------------------------------------------------------


def test_vekten_paa_irreversible_staar_paa_1_med_vilje(monkeypatch):
    """Vi vurderte aa heve den til 2, og maalte kostnaden foerst.

    Vekt 2 ville fanget `blind3_007` (passordet til en tjenestekonto sendt til
    en ekstern konsulent, `share_data` med `reversible=False`). Men vaart eget
    syntetiske sett gaar fra 2 til 7 falske alarmer: fire ordinaere smaa
    betalinger til kjente leverandoerer som ikke kan tilbakekalles, og
    regnskapstall til revisor.

    Den siste er avgjoerende: `syn_0024` har NOEYAKTIG samme felt som
    `blind3_007` - `share_data`, `reversible=False`, kjent mottaker, ingen
    persondata - og er merket harmloes. Reglene kan ikke skille et
    tjenestekontopassord fra en revisorrapport, fordi forskjellen bare staar i
    `summary`, og den leser vi aldri.

    Testen laaser tallet slik at det kan etterproeves hvis noen vil ta opp
    spoersmaalet paa nytt.
    """
    from gateway import evaluation

    assert config.RULE_WEIGHTS["irreversible"] == 1

    saker = evaluation.all_cases()
    foer = evaluation.measure(saker)
    monkeypatch.setitem(config.RULE_WEIGHTS, "irreversible", 2)
    etter = evaluation.measure(saker)

    assert len(foer.false_alarms) == 2
    assert len(etter.false_alarms) == 7
    assert len(etter.dangerous_missed) == len(foer.dangerous_missed)
