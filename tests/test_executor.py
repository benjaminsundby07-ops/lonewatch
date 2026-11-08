"""Porten, forseglingen og boka: hva som faar lov og hva som ikke faar lov.

Ingenting her roerer nettverket. SmtpExecutor har sine egne tester i
test_executor_smtp.py.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from contracts import (
    ActionRequest,
    ActionType,
    Decision,
    HumanResponse,
    Risk,
    Verdict,
)
from executor import (
    AttemptLedger,
    ExecutionStatus,
    SimulatedExecutor,
    fingerprint,
    may_execute,
    seal,
)
from executor.base import Executor, ExecutorError

TS = datetime(2026, 11, 8, 9, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# byggeklosser
# ---------------------------------------------------------------------------


def epost(req_id: str = "req_1", recipient: str = "oline.dahl@nordlys.no", **felt) -> ActionRequest:
    base = dict(
        id=req_id,
        ts=TS,
        agent_id="kundeservice",
        action_type=ActionType.SEND_EMAIL,
        summary="Svar paa sak 4411.",
        recipient=recipient,
    )
    base.update(felt)
    return ActionRequest(**base)


def penger(req_id: str = "req_p", amount: float = 240000.0) -> ActionRequest:
    return ActionRequest(
        id=req_id,
        ts=TS,
        agent_id="okonomi",
        action_type=ActionType.TRANSFER_MONEY,
        summary="Betaler faktura.",
        amount=amount,
        recipient="ny-leverandor@eksempel.invalid",
        recipient_known=False,
        reversible=False,
    )


def avgjorelse(
    req: ActionRequest,
    verdict: Verdict = Verdict.ALLOW,
    risk: Risk = Risk.LOW,
    requires_typed_amount: bool = False,
    ts: datetime | None = None,
    request_id: str | None = None,
) -> Decision:
    return Decision(
        request_id=request_id or req.id,
        ts=ts or req.ts,
        verdict=verdict,
        risk=risk,
        reasons=[],
        consequence_text="Noe skjer.",
        requires_typed_amount=requires_typed_amount,
    )


def menneske(req_id: str, approved: bool, typed_amount: float | None = None) -> HumanResponse:
    return HumanResponse(
        request_id=req_id,
        ts=TS + timedelta(seconds=30),
        employee_pseudonym="emp_1a2b",
        approved=approved,
        typed_amount=typed_amount,
        seconds_to_decide=30.0,
    )


# ---------------------------------------------------------------------------
# de fire tilstandene: allow, red som venter, red godkjent, red avvist, block
# ---------------------------------------------------------------------------


def test_allow_blir_utfort():
    req = epost()
    dec = avgjorelse(req, Verdict.ALLOW)
    res = SimulatedExecutor().execute(req, dec, seal(req, dec))

    assert res.executed is True
    assert res.status is ExecutionStatus.DONE
    assert res.rule == ""
    assert res.request_id == req.id


def test_red_som_venter_blir_ikke_utfort():
    req = epost()
    dec = avgjorelse(req, Verdict.RED, Risk.HIGH)
    res = SimulatedExecutor().execute(req, dec, seal(req, dec))

    assert res.executed is False
    assert res.status is ExecutionStatus.REFUSED
    assert res.rule == "red_waiting"
    assert "venter" in res.detail


def test_red_uten_godkjenning_i_det_hele_tatt_blir_ikke_utfort():
    """Ingen forsegling er heller ikke en godkjenning."""
    req = epost()
    dec = avgjorelse(req, Verdict.RED, Risk.HIGH)
    res = SimulatedExecutor().execute(req, dec)

    assert res.executed is False
    assert res.rule == "red_waiting"


def test_red_som_et_menneske_godkjente_blir_utfort():
    req = epost()
    dec = avgjorelse(req, Verdict.RED, Risk.HIGH)
    res = SimulatedExecutor().execute(req, dec, seal(req, dec, menneske(req.id, True)))

    assert res.executed is True
    assert res.status is ExecutionStatus.DONE


def test_red_som_et_menneske_avviste_blir_ikke_utfort():
    req = epost()
    dec = avgjorelse(req, Verdict.RED, Risk.HIGH)
    res = SimulatedExecutor().execute(req, dec, seal(req, dec, menneske(req.id, False)))

    assert res.executed is False
    assert res.rule == "red_rejected"
    assert "avviste" in res.detail


def test_block_blir_ikke_utfort():
    req = epost()
    dec = avgjorelse(req, Verdict.BLOCK, Risk.HIGH)
    res = SimulatedExecutor().execute(req, dec, seal(req, dec))

    assert res.executed is False
    assert res.rule == "verdict_block"


def test_block_kan_ikke_godkjennes_av_et_menneske():
    """Det er hele forskjellen mellom block og red. Et ja endrer ingenting."""
    req = epost()
    dec = avgjorelse(req, Verdict.BLOCK, Risk.HIGH)
    res = SimulatedExecutor().execute(req, dec, seal(req, dec, menneske(req.id, True)))

    assert res.executed is False
    assert res.rule == "verdict_block"


def test_allow_som_et_menneske_likevel_avviste_blir_ikke_utfort():
    """Et nei fra et menneske veier mer enn et rolig regelsett."""
    req = epost()
    dec = avgjorelse(req, Verdict.ALLOW)
    res = SimulatedExecutor().execute(req, dec, seal(req, dec, menneske(req.id, False)))

    assert res.executed is False
    assert res.rule == "human_rejected"


def test_ingenting_ble_gjort_naar_porten_sa_nei():
    """"Ikke utfort" betyr at _perform aldri ble kalt, ikke bare at svaret er nei."""
    req = epost()
    utforer = SimulatedExecutor()
    for verdict in (Verdict.RED, Verdict.BLOCK):
        dec = avgjorelse(req, verdict, Risk.HIGH)
        utforer.execute(req, dec, seal(req, dec))
    assert utforer.performed == []


# ---------------------------------------------------------------------------
# innholdet som sendes er det som ble godkjent
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "endring",
    [
        {"recipient": "angriper@eksempel.invalid"},
        {"summary": "Noe helt annet."},
        {"amount": 999999.0},
        {"contains_personal_data": True},
        {"ts": TS + timedelta(seconds=1)},
        {"agent_id": "en_annen_agent"},
    ],
    ids=["mottaker", "tekst", "belop", "personopplysninger", "tidspunkt", "agent"],
)
def test_endret_felt_etter_godkjenning_blir_ikke_utfort(endring):
    req = epost()
    dec = avgjorelse(req, Verdict.ALLOW)
    godkjenning = seal(req, dec)

    endret = req.model_copy(update=endring)
    res = SimulatedExecutor().execute(endret, dec, godkjenning)

    assert res.executed is False
    assert res.rule == "content_changed"
    assert "endret" in res.detail


def test_endret_felt_etter_at_et_menneske_godkjente_blir_ikke_utfort():
    req = epost()
    dec = avgjorelse(req, Verdict.RED, Risk.HIGH)
    godkjenning = seal(req, dec, menneske(req.id, True))

    endret = req.model_copy(update={"recipient": "angriper@eksempel.invalid"})
    res = SimulatedExecutor().execute(endret, dec, godkjenning)

    assert res.executed is False
    assert res.rule == "content_changed"


def test_uendret_forespoersel_har_samme_avtrykk():
    req = epost()
    assert fingerprint(req) == fingerprint(req.model_copy())
    # En tur gjennom JSON skal ikke endre avtrykket.
    assert fingerprint(req) == fingerprint(ActionRequest(**req.model_dump()))


def test_avtrykket_endrer_seg_naar_et_felt_endrer_seg():
    req = epost()
    assert fingerprint(req) != fingerprint(req.model_copy(update={"recipient": "b@c.no"}))


def test_byttet_avgjorelse_etter_forsegling_blir_ikke_utfort():
    """Samme forespoersel, men en allow byttet inn der det stod red."""
    req = epost()
    red = avgjorelse(req, Verdict.RED, Risk.HIGH)
    godkjenning = seal(req, red)

    allow = avgjorelse(req, Verdict.ALLOW)
    res = SimulatedExecutor().execute(req, allow, godkjenning)

    assert res.executed is False
    assert res.rule == "verdict_changed"


def test_avgjorelse_for_en_annen_forespoersel_blir_ikke_utfort():
    req = epost("req_1")
    dec = avgjorelse(req, Verdict.ALLOW, request_id="req_2")
    res = SimulatedExecutor().execute(req, dec)

    assert res.executed is False
    assert res.rule == "decision_other_request"


def test_godkjenning_for_en_annen_forespoersel_blir_ikke_utfort():
    annen = epost("req_2")
    annen_dec = avgjorelse(annen, Verdict.ALLOW)
    godkjenning = seal(annen, annen_dec)

    req = epost("req_1")
    dec = avgjorelse(req, Verdict.ALLOW)
    res = SimulatedExecutor().execute(req, dec, godkjenning)

    assert res.executed is False
    assert res.rule == "approval_other_request"


def test_uten_forsegling_fanges_et_endret_tidspunkt():
    """Siste skanse naar ingen forseglet: avgjoerelsen baerer forespoerselens tid."""
    req = epost()
    dec = avgjorelse(req, Verdict.ALLOW)
    endret = req.model_copy(update={"ts": TS + timedelta(hours=3)})
    res = SimulatedExecutor().execute(endret, dec)

    assert res.executed is False
    assert res.rule == "unsealed_timestamp_changed"


def test_seal_nekter_aa_forsegle_en_avgjorelse_for_en_annen_forespoersel():
    req = epost("req_1")
    dec = avgjorelse(req, Verdict.ALLOW, request_id="req_2")
    with pytest.raises(ValueError):
        seal(req, dec)


def test_seal_nekter_et_menneskesvar_for_en_annen_forespoersel():
    req = epost("req_1")
    dec = avgjorelse(req, Verdict.ALLOW)
    with pytest.raises(ValueError):
        seal(req, dec, menneske("req_2", True))


# ---------------------------------------------------------------------------
# beloepet mennesket skrev inn
# ---------------------------------------------------------------------------


def test_riktig_innskrevet_belop_blir_utfort():
    req = penger(amount=240000.0)
    dec = avgjorelse(req, Verdict.RED, Risk.HIGH, requires_typed_amount=True)
    svar = menneske(req.id, True, typed_amount=240000.0)
    res = SimulatedExecutor().execute(req, dec, seal(req, dec, svar))

    assert res.executed is True


def test_feil_innskrevet_belop_blir_ikke_utfort():
    req = penger(amount=240000.0)
    dec = avgjorelse(req, Verdict.RED, Risk.HIGH, requires_typed_amount=True)
    svar = menneske(req.id, True, typed_amount=24000.0)
    res = SimulatedExecutor().execute(req, dec, seal(req, dec, svar))

    assert res.executed is False
    assert res.rule == "typed_amount_mismatch"


def test_manglende_innskrevet_belop_blir_ikke_utfort():
    req = penger(amount=240000.0)
    dec = avgjorelse(req, Verdict.RED, Risk.HIGH, requires_typed_amount=True)
    svar = menneske(req.id, True, typed_amount=None)
    res = SimulatedExecutor().execute(req, dec, seal(req, dec, svar))

    assert res.executed is False
    assert res.rule == "typed_amount_missing"


def test_belop_med_desimaler_sammenlignes_uten_flyttallsfeil():
    req = penger(amount=49999.50)
    dec = avgjorelse(req, Verdict.RED, Risk.HIGH, requires_typed_amount=True)
    svar = menneske(req.id, True, typed_amount=49999.50)
    assert SimulatedExecutor().execute(req, dec, seal(req, dec, svar)).executed is True


# ---------------------------------------------------------------------------
# aldri to ganger
# ---------------------------------------------------------------------------


def test_samme_forespoersel_utfores_bare_en_gang():
    req = epost()
    dec = avgjorelse(req, Verdict.ALLOW)
    godkjenning = seal(req, dec)
    utforer = SimulatedExecutor()

    forst = utforer.execute(req, dec, godkjenning)
    igjen = utforer.execute(req, dec, godkjenning)

    assert forst.executed is True
    assert igjen.executed is False
    assert igjen.status is ExecutionStatus.ALREADY_ATTEMPTED
    assert utforer.performed == [req.id]


def test_en_handling_som_feilet_proves_ikke_igjen():
    """Etter en feil vet vi ikke om halve handlingen gikk gjennom. Da stopper vi."""

    class Brekker(Executor):
        name = "brekker"

        def _perform(self, request, decision, plan):
            raise RuntimeError("serveren svarte ikke")

    req = epost()
    dec = avgjorelse(req, Verdict.ALLOW)
    godkjenning = seal(req, dec)
    utforer = Brekker()

    forst = utforer.execute(req, dec, godkjenning)
    igjen = utforer.execute(req, dec, godkjenning)

    assert forst.executed is False
    assert forst.status is ExecutionStatus.FAILED
    assert igjen.status is ExecutionStatus.ALREADY_ATTEMPTED


def test_en_nektet_sak_kan_utfores_senere_naar_mennesket_har_svart():
    """Porten skal ikke brenne forespoerselen. En rod sak lever videre."""
    req = epost()
    dec = avgjorelse(req, Verdict.RED, Risk.HIGH)
    utforer = SimulatedExecutor()

    venter = utforer.execute(req, dec, seal(req, dec))
    godkjent = utforer.execute(req, dec, seal(req, dec, menneske(req.id, True)))

    assert venter.executed is False
    assert godkjent.executed is True


def test_feil_oppsett_brenner_ikke_forespoerselen():
    """_prepare feiler uten at noe skjedde ute, saa et nytt forsoek er trygt."""

    class Vanskelig(Executor):
        name = "vanskelig"

        def __init__(self):
            super().__init__()
            self.virker = False
            self.gjort = 0

        def _prepare(self, request, decision, approval):
            if not self.virker:
                raise ExecutorError("postserveren er ikke satt opp")
            return None

        def _perform(self, request, decision, plan):
            self.gjort += 1
            return ("gjort", None)

    req = epost()
    dec = avgjorelse(req, Verdict.ALLOW)
    godkjenning = seal(req, dec)
    utforer = Vanskelig()

    forst = utforer.execute(req, dec, godkjenning)
    assert forst.executed is False
    assert forst.status is ExecutionStatus.FAILED
    assert forst.rule == "setup_error"
    assert len(utforer.ledger) == 0

    utforer.virker = True
    etterpa = utforer.execute(req, dec, godkjenning)
    assert etterpa.executed is True
    assert utforer.gjort == 1


def test_to_utforere_kan_dele_bok():
    req = epost()
    dec = avgjorelse(req, Verdict.ALLOW)
    godkjenning = seal(req, dec)
    bok = AttemptLedger()

    en = SimulatedExecutor(ledger=bok)
    to = SimulatedExecutor(ledger=bok)

    assert en.execute(req, dec, godkjenning).executed is True
    assert to.execute(req, dec, godkjenning).executed is False


def test_boka_gir_bare_en_vinner_naar_mange_trader_sporr_samtidig():
    import threading

    bok = AttemptLedger()
    svar: list[bool] = []
    laas = threading.Lock()
    start = threading.Event()

    def sporr():
        start.wait()
        ok = bok.claim("req_1")
        with laas:
            svar.append(ok)

    trader = [threading.Thread(target=sporr) for _ in range(20)]
    for t in trader:
        t.start()
    start.set()
    for t in trader:
        t.join()

    assert svar.count(True) == 1


# ---------------------------------------------------------------------------
# en feil slipper aldri ut til den som kalte
# ---------------------------------------------------------------------------


def test_execute_kaster_aldri():
    class Eksploderer(Executor):
        name = "eksploderer"

        def _perform(self, request, decision, plan):
            raise KeyError("noe helt uventet")

    req = epost()
    dec = avgjorelse(req, Verdict.ALLOW)
    res = Eksploderer().execute(req, dec, seal(req, dec))

    assert res.executed is False
    assert res.status is ExecutionStatus.FAILED
    assert "KeyError" in res.detail


def test_en_feil_i_forberedelsen_kaster_heller_ikke():
    class Rar(Executor):
        name = "rar"

        def _prepare(self, request, decision, approval):
            raise ZeroDivisionError("dette var ikke planlagt")

        def _perform(self, request, decision, plan):
            return ("gjort", None)

    req = epost()
    dec = avgjorelse(req, Verdict.ALLOW)
    res = Rar().execute(req, dec, seal(req, dec))

    assert res.executed is False
    assert res.status is ExecutionStatus.FAILED
    assert res.rule == "setup_error"


def test_lang_feilmelding_kuttes():
    class Snakkesalig(Executor):
        name = "snakkesalig"

        def _perform(self, request, decision, plan):
            raise RuntimeError("x" * 5000)

    req = epost()
    dec = avgjorelse(req, Verdict.ALLOW)
    res = Snakkesalig().execute(req, dec, seal(req, dec))

    assert len(res.detail) <= 300
    assert "\n" not in res.detail


# ---------------------------------------------------------------------------
# porten er den samme uansett utforer, og svarer det samme hver gang
# ---------------------------------------------------------------------------


def test_porten_er_deterministisk():
    req = epost()
    dec = avgjorelse(req, Verdict.RED, Risk.HIGH)
    godkjenning = seal(req, dec, menneske(req.id, True))
    svar = {may_execute(req, dec, godkjenning) for _ in range(50)}
    assert len(svar) == 1


def test_simulert_utforer_gjor_ingenting_ekte():
    req = epost()
    dec = avgjorelse(req, Verdict.ALLOW)
    res = SimulatedExecutor().execute(req, dec, seal(req, dec))
    assert "Simulert" in res.detail
    assert res.target is None


# ---------------------------------------------------------------------------
# forseglingen lages naar avgjorelsen faller, mennesket svarer senere
# ---------------------------------------------------------------------------


def test_with_human_beholder_avtrykket_fra_avgjorelsen():
    """Den ekte veien: forsegl ved avgjorelsen, legg til svaret senere."""
    req = epost()
    dec = avgjorelse(req, Verdict.RED, Risk.HIGH)
    ved_avgjorelsen = seal(req, dec)

    ved_godkjenningen = ved_avgjorelsen.with_human(menneske(req.id, True))

    assert ved_godkjenningen.request_fingerprint == ved_avgjorelsen.request_fingerprint
    assert SimulatedExecutor().execute(req, dec, ved_godkjenningen).executed is True


def test_with_human_fanger_en_endring_som_skjedde_mens_mennesket_tenkte():
    """Her ligger verdien: seal() paa nytt ved godkjenningen ville godtatt den."""
    req = epost()
    dec = avgjorelse(req, Verdict.RED, Risk.HIGH)
    ved_avgjorelsen = seal(req, dec)

    endret = req.model_copy(update={"recipient": "angriper@eksempel.invalid"})
    godkjenning = ved_avgjorelsen.with_human(menneske(req.id, True))
    res = SimulatedExecutor().execute(endret, dec, godkjenning)

    assert res.executed is False
    assert res.rule == "content_changed"

    # Til sammenligning: en forsegling laget paa nytt av den ENDREDE
    # forespoerselen ville sluppet den gjennom. Derfor with_human().
    for_sent = seal(endret, dec, menneske(req.id, True))
    assert SimulatedExecutor().execute(endret, dec, for_sent).executed is True


def test_with_human_nekter_et_svar_for_en_annen_forespoersel():
    req = epost("req_1")
    dec = avgjorelse(req, Verdict.RED, Risk.HIGH)
    with pytest.raises(ValueError):
        seal(req, dec).with_human(menneske("req_2", True))


def test_forespoersel_som_har_vart_gjennom_json_har_samme_avtrykk_som_forseglingen():
    """UI-et lagrer kortene som dict. Omveien skal ikke endre avtrykket."""
    req = epost()
    dec = avgjorelse(req, Verdict.RED, Risk.HIGH)
    godkjenning = seal(req, dec)

    som_dict = req.model_dump(mode="json")
    bygget_opp_igjen = ActionRequest(**som_dict)

    res = SimulatedExecutor().execute(
        bygget_opp_igjen, dec, godkjenning.with_human(menneske(req.id, True))
    )
    assert res.executed is True
