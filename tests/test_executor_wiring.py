"""Utføreren koblet inn i hele flyten, og «execution» som en art i loggen.

Tre spørsmål denne filen svarer på:

1. **Skjer handlingen på de to riktige stedene, og BARE der?** `allow` utføres
   med én gang, en `red` som et menneske godkjente utføres, og de tre andre
   utfallene - rød som venter, rød som ble avvist, blokkert - utfører
   ingenting. Alle fire måles gjennom `DemoState`, ikke bare i `executor/`.

2. **Tåler alt som leser loggen den nye arten?** `"execution"` kom inn i
   `LogKind` i den låste `contracts.py`. Tellerne i Oversikt, logg-tabellen,
   Etter-fanen, `vault.after` og loggsjekken skal være NØYAKTIG de samme med
   og uten en execution-linje.

3. **Forlater forseglingen aldri tjeneren?** `Approval.request_fingerprint` er
   det eneste som binder en godkjenning til den forespørselen mennesket faktisk
   så. Kommer den til nettleseren, kan den som har den lage en godkjenning som
   ser riktig ut.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from contracts import ActionType, LogEntry
from executor import Approval, ExecutionStatus, SimulatedExecutor, SmtpExecutor
from ui.state import (
    ENV_EXECUTOR,
    LOG_EXECUTION,
    PRIVATE_CARD_KEYS,
    PRIVATE_EXECUTION_KEYS,
    DemoState,
)

PROSJEKT = Path(__file__).resolve().parents[1]

UKJENT_KONTO = "NO93 8601 1117 947"
KJENT_KONTO = "NO12 3456 7890 123"


@pytest.fixture()
def state():
    s = DemoState()
    yield s
    s.close()


def _kjor_alt(state) -> list[dict]:
    kort = []
    while True:
        c = state.step_feed()
        if c is None:
            return kort
        kort.append(c)


def _kinds(state) -> list[str]:
    return [e.kind for e in state.vault.entries()]


def _execution_lines(state) -> list[dict]:
    return [e.payload for e in state.vault.entries() if e.kind == LOG_EXECUTION]


# ---------------------------------------------------------------------------
# 1. de fire utfallene, gjennom hele flyten
# ---------------------------------------------------------------------------


def test_an_allow_is_executed_right_away(state):
    out = state.submit_custom(
        action_type="update_calendar", summary="Flytter et moete"
    )
    kort = out["card"]
    assert kort["status"] == "allow"
    e = kort["execution"]
    assert e is not None
    assert e["executed"] is True
    assert e["status"] == ExecutionStatus.DONE.value
    assert e["request_id"] == kort["request"]["id"]
    # Og det staar i loggen.
    assert _kinds(state)[-1] == LOG_EXECUTION


def test_a_red_card_that_waits_executes_nothing(state):
    out = state.submit_custom(
        action_type="transfer_money", amount="450000", recipient=UKJENT_KONTO
    )
    kort = out["card"]
    assert kort["status"] == "waiting"
    # Ingen utfoering, og ingen execution-linje i loggen.
    assert kort["execution"] is None
    assert LOG_EXECUTION not in _kinds(state)


def test_a_red_card_a_human_approved_is_executed(state):
    out = state.submit_custom(
        action_type="transfer_money", amount="450000", recipient=UKJENT_KONTO
    )
    request_id = out["card"]["request"]["id"]
    svar = state.respond(request_id, approved=True, typed_amount="450 000")
    assert svar["ok"] is True

    e = svar["card"]["execution"]
    assert e is not None and e["executed"] is True
    # Rekkefoelgen i loggen: svaret fra mennesket, saa utfoeringen.
    assert _kinds(state)[-2:] == ["human", LOG_EXECUTION]


def test_a_red_card_a_human_rejected_executes_nothing(state):
    out = state.submit_custom(
        action_type="transfer_money", amount="450000", recipient=UKJENT_KONTO
    )
    request_id = out["card"]["request"]["id"]
    svar = state.respond(request_id, approved=False)
    assert svar["ok"] is True
    assert svar["card"]["status"] == "rejected"
    assert svar["card"]["execution"] is None
    assert LOG_EXECUTION not in _kinds(state)


def test_a_blocked_card_executes_nothing_and_cannot_be_approved(state):
    out = state.submit_custom(
        action_type="transfer_money", amount="99000000", recipient=UKJENT_KONTO
    )
    kort = out["card"]
    assert kort["status"] == "blocked"
    assert kort["execution"] is None
    assert LOG_EXECUTION not in _kinds(state)

    # Og ingen kan klikke den gjennom.
    svar = state.respond(kort["request"]["id"], approved=True, typed_amount="99000000")
    assert svar["ok"] is False
    assert LOG_EXECUTION not in _kinds(state)


def test_a_wrong_typed_amount_executes_nothing(state):
    out = state.submit_custom(
        action_type="transfer_money", amount="450000", recipient=UKJENT_KONTO
    )
    request_id = out["card"]["request"]["id"]
    assert state.respond(request_id, approved=True, typed_amount="45000")["ok"] is False
    assert LOG_EXECUTION not in _kinds(state)
    # Kortet venter fortsatt, og kan godkjennes etterpaa.
    assert state.cards[request_id]["status"] == "waiting"


def test_the_whole_demo_executes_exactly_the_allowed_cards(state):
    kort = _kjor_alt(state)
    groenne = [c for c in kort if c["status"] == "allow"]
    andre = [c for c in kort if c["status"] != "allow"]

    assert groenne, "demoen skal ha groenne kort"
    assert all(c["execution"]["executed"] is True for c in groenne)
    assert all(c["execution"] is None for c in andre)
    assert len(_execution_lines(state)) == len(groenne)


# ---------------------------------------------------------------------------
# forseglingen: den samme forespoerselen, eller ingenting
# ---------------------------------------------------------------------------


def test_a_request_changed_after_the_decision_is_not_executed(state):
    """Dette er hele grunnen til at forseglingen finnes.

    Mennesket godkjenner én e-post. Mellom avgjoerelsen og godkjenningen
    bytter noe mottakeren paa kortet. Avtrykket fra da avgjoerelsen falt
    stemmer da ikke lenger, og utfoereren nekter.
    """
    out = state.submit_custom(
        action_type="transfer_money", amount="450000", recipient=UKJENT_KONTO
    )
    request_id = out["card"]["request"]["id"]

    # En endring INNENFRA, etter at avgjoerelsen falt.
    state.cards[request_id]["request"]["recipient"] = "NO99 0000 0000 000"

    svar = state.respond(request_id, approved=True, typed_amount="450 000")
    assert svar["ok"] is True  # mennesket svarte, det er sant
    e = svar["card"]["execution"]
    assert e["executed"] is False
    assert e["status"] == ExecutionStatus.REFUSED.value
    assert e["rule"] == "content_changed"
    # Og det staar i loggen at den IKKE ble utfoert.
    assert _execution_lines(state)[-1]["executed"] is False


def test_the_card_carries_the_seal_internally(state):
    out = state.submit_custom(action_type="read_document", recipient="rapport.pdf")
    request_id = out["card"]["request"]["id"]
    seal = state.cards[request_id]["approval"]
    assert isinstance(seal, Approval)
    assert seal.request_id == request_id
    assert len(seal.request_fingerprint) == 64


def test_the_seal_never_reaches_the_browser(state):
    """Hele API-flaten, gjennomsoekt for forseglingen.

    Dette er en invariant-test og ikke en enhetstest med vilje: det finnes
    fire steder et kort forlater `DemoState`, og en femte kan komme til.
    Testen leser svarene, ikke koden.
    """
    _kjor_alt(state)
    custom = state.submit_custom(
        action_type="transfer_money", amount="450000", recipient=UKJENT_KONTO
    )
    agent = state.submit_agent(action_type="read_document", recipient="a.pdf")
    request_id = custom["card"]["request"]["id"]
    svar = state.respond(request_id, approved=True, typed_amount="450 000")

    avtrykk = state.cards[request_id]["approval"].request_fingerprint

    svar_fra_api = [
        state.snapshot(),
        state.overview(),
        state.after_actions(),
        state.log_rows(),
        state.verify(),
        custom,
        agent,
        svar,
        state.agent_status(agent["card"]["request"]["id"]),
        state.waiting_for_you(),
        state.story_snapshot(),
        state.before_list(),
        state.custom_help(),
        state.traps_overview(),
        state.agent_trail(request_id),
    ]
    for ut in svar_fra_api:
        tekst = json.dumps(ut, default=str)
        for forbudt in PRIVATE_CARD_KEYS:
            assert f'"{forbudt}"' not in tekst, (forbudt, tekst[:200])
        assert avtrykk not in tekst, tekst[:200]


def test_the_fingerprint_is_logged_but_not_sent_to_the_browser(state):
    """Avtrykket hoerer i loggen, ikke i et JSON-svar.

    I loggen er det det som binder en `.eml`-fil paa disken til godkjenningen
    som slapp den gjennom. I nettleseren er det bare et avtrykk alle har.
    """
    out = state.submit_custom(action_type="update_calendar", summary="Flytter")
    assert "fingerprint" not in out["card"]["execution"]
    logget = _execution_lines(state)[-1]
    assert len(logget["fingerprint"]) == 64
    assert PRIVATE_EXECUTION_KEYS == {"fingerprint"}


def test_the_public_card_keeps_everything_the_page_needs(state):
    """`_public()` skal ta bort forseglingen - ikke noe annet."""
    out = state.submit_custom(action_type="read_document", recipient="a.pdf")
    offentlig = set(out["card"])
    internt = set(state.cards[out["card"]["request"]["id"]])
    assert internt - offentlig == set(PRIVATE_CARD_KEYS)
    for noekkel in ("request", "decision", "status", "source", "human", "execution"):
        assert noekkel in offentlig


# ---------------------------------------------------------------------------
# 2. boka leses fra loggen: en omstart utfoerer ikke noe to ganger
# ---------------------------------------------------------------------------


def test_a_restart_does_not_execute_the_same_request_twice(state):
    """Dette er grunnen til at utfoeringen MAATTE i loggen.

    Boka over hva som er forsoekt (`AttemptLedger`) levde bare i minnet. En
    omstart toemte den, og den samme forespoerselen kunne gaa ut en gang til.
    Naa leses den fra execution-linjene i loggen ved oppstart.
    """
    out = state.submit_custom(action_type="update_calendar", summary="Flytter")
    request_id = out["card"]["request"]["id"]
    assert out["card"]["execution"]["executed"] is True
    state.close()

    # Samme loggfil, ny prosess. Samme forespoersel, spilt om.
    ny = DemoState()
    try:
        assert ny._ledger.attempted(request_id), "boka ble ikke lest fra loggen"
        kort = ny._handle(
            __import__("contracts").ActionRequest(**out["card"]["request"]), source="feed"
        )
        e = kort["execution"]
        assert e["executed"] is False
        assert e["status"] == ExecutionStatus.ALREADY_ATTEMPTED.value
    finally:
        ny.close()


def test_the_ledger_also_remembers_what_was_refused(state):
    """En linje i loggen betyr at utfoereren har hatt saken, uansett utfall.

    En handling som feilet proeves aldri om av seg selv - det staar i
    executor/once.py, og grunnen er at vi ikke vet om den gikk halvveis.
    """
    out = state.submit_custom(
        action_type="transfer_money", amount="450000", recipient=UKJENT_KONTO
    )
    request_id = out["card"]["request"]["id"]
    state.cards[request_id]["request"]["recipient"] = "NO99 0000 0000 000"
    state.respond(request_id, approved=True, typed_amount="450 000")
    assert _execution_lines(state)[-1]["executed"] is False
    state.close()

    ny = DemoState()
    try:
        assert ny._ledger.attempted(request_id)
    finally:
        ny.close()


# ---------------------------------------------------------------------------
# 3. alt som leser loggen taaler den nye arten
# ---------------------------------------------------------------------------


def _legg_til_execution_linje(state) -> None:
    """Skriver en ekstra execution-linje rett i loggen, utenom utfoereren.

    Hensikten er aa maale TOLERANSE: hva skjer med tellerne, Etter-fanen og
    loggsjekken naar en art de ikke kjenner dukker opp.
    """
    state.vault.append(
        LOG_EXECUTION,
        {
            "request_id": "req_0001",
            "ts": datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc).isoformat(),
            "executed": True,
            "status": "done",
            "detail": "Sendt til o***@nordlysforsikring.no via 127.0.0.1:8025.",
            "executor_name": "smtp",
            "rule": "",
            "target": "127.0.0.1:8025",
            "fingerprint": "0" * 64,
        },
    )


def test_the_overview_counters_are_unchanged_by_an_execution_line(state):
    _kjor_alt(state)
    foer = state.overview()
    _legg_til_execution_linje(state)
    etter = state.overview()
    assert etter["counts"] == foer["counts"]
    assert etter["agents"] == foer["agents"]
    assert etter["sandbox"] == foer["sandbox"]
    assert etter["chartShapes"] == foer["chartShapes"]


def test_the_log_table_counters_are_unchanged_by_an_execution_line(state):
    _kjor_alt(state)
    foer = state.log_rows()
    _legg_til_execution_linje(state)
    etter = state.log_rows()
    assert etter["counts"] == foer["counts"]
    assert etter["rows"] == foer["rows"]
    assert etter["tidsbaser"] == foer["tidsbaser"]


def test_the_after_tab_is_unchanged_by_an_execution_line(state):
    _kjor_alt(state)
    request_id = [
        c["request"]["id"] for c in state.snapshot()["waiting"]
    ][0]
    state.respond(request_id, approved=False)

    foer = state.after_actions()
    _legg_til_execution_linje(state)
    etter = state.after_actions()
    assert etter["items"] == foer["items"]
    assert etter["view"] == foer["view"]
    assert etter["available"] is True


def test_vault_after_ignores_an_execution_entry():
    """`vault.after.build_after_actions` henger ikke, og lager ingen oppgave."""
    from vault.after import build_after_actions
    from contracts import compute_entry_hash

    payload = {"request_id": "req_0001", "status": "done", "executed": True}
    e = LogEntry(
        seq=0,
        ts=datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc),
        kind=LOG_EXECUTION,
        payload=payload,
        prev_hash="0" * 64,
        hash="",
    )
    assert build_after_actions([e]) == []


def test_the_log_check_still_passes_with_execution_lines(state):
    _kjor_alt(state)
    _legg_til_execution_linje(state)
    sjekk = state.verify()
    assert sjekk["ok"] is True, sjekk
    assert state.vault.verify() is None


def test_an_execution_line_survives_the_minimisation(state):
    """Dataminimeringen skal ikke kaste det som gjoer linjen verdt noe.

    `redact_payload` kjenner ikke arten «execution». Den faller derfor
    gjennom til regelen som bare kaster `summary` og `consequence_text` - og
    ingen av dem staar i et `ExecutionResult`. Det som staar der er
    request_id, status, executed, teksten og tidspunktet, og mottakeren er alt
    maskert av `executor/mail.py`.
    """
    from vault.redaction import redact_payload

    payload = {
        "request_id": "req_0001",
        "ts": "2026-11-08T12:00:00+00:00",
        "executed": True,
        "status": "done",
        "detail": "Sendt til o***@nordlysforsikring.no via 127.0.0.1:8025.",
        "executor_name": "smtp",
        "rule": "",
        "target": "127.0.0.1:8025",
        "fingerprint": "0" * 64,
    }
    minimert = redact_payload(LOG_EXECUTION, payload)
    for noekkel in ("request_id", "status", "executed", "detail", "ts"):
        assert noekkel in minimert
    # Ingen hel e-postadresse i linjen.
    assert "o***@" in minimert["detail"]


def test_eval_never_reads_the_log():
    """`eval/` maaler reglene, ikke loggen. Da kan den nye arten ikke naa den.

    Testen staar for at paastanden skal holde seg: begynner `eval/` aa lese
    loggen, maa den ogsaa taale «execution».
    """
    kilde = (PROSJEKT / "eval" / "measure.py").read_text(encoding="utf-8").lower()
    for forbudt in ("vault", "logentry", "entries()"):
        assert forbudt not in kilde, forbudt


# ---------------------------------------------------------------------------
# hvilken utfoerer
# ---------------------------------------------------------------------------


def test_the_default_executor_is_the_simulated_one(state):
    for action in ActionType:
        assert isinstance(state._executor_for(action), SimulatedExecutor)
    assert state._executor_error is None


def test_smtp_is_only_used_when_it_is_asked_for_and_only_for_email(monkeypatch):
    monkeypatch.setenv(ENV_EXECUTOR, "smtp")
    s = DemoState()
    try:
        assert isinstance(s._executor_for(ActionType.SEND_EMAIL), SmtpExecutor)
        for action in ActionType:
            if action is not ActionType.SEND_EMAIL:
                assert isinstance(s._executor_for(action), SimulatedExecutor)
    finally:
        s.close()


@pytest.mark.parametrize("verdi", ["", "SMTP ", "ja", "true", "1", "smtpx", "simulated"])
def test_a_typo_never_turns_on_the_real_sender(monkeypatch, verdi):
    """En utfoerer som roerer omverdenen skal ikke kunne slaas paa ved en skrivefeil.

    Merk at `"SMTP "` MED mellomrom og store bokstaver er med i listen og
    skal... slaas paa: vi klipper luft og senker bokstaver. Alt annet er av.
    """
    monkeypatch.setenv(ENV_EXECUTOR, verdi)
    s = DemoState()
    try:
        forventet_smtp = verdi.strip().lower() == "smtp"
        er_smtp = isinstance(s._executor_for(ActionType.SEND_EMAIL), SmtpExecutor)
        assert er_smtp is forventet_smtp, verdi
    finally:
        s.close()


def test_all_executors_share_one_ledger(state):
    """To utfoerere med hver sin bok kunne gjort den samme handlingen to ganger."""
    boker = {id(state._executor_for(a).ledger) for a in ActionType}
    assert len(boker) == 1


# ---------------------------------------------------------------------------
# hele veien med den ekte senderen, mot postfangeren paa loopback
# ---------------------------------------------------------------------------
#
# Dette er den eneste testen i filen der noe faktisk forlater prosessen, og
# det gaar til 127.0.0.1. Postfangeren binder seg til loopback paa en port
# operativsystemet velger, saa ingenting naar nettet og testene kan kjoere
# samtidig.
#
# Merk hva som IKKE kan maales her: en `send_email` som blir BLOKKERT. Reglene
# i gateway/ har ingen vei dit - `block` kommer fra `transfer_over_hard_limit`
# og fra blokklisten for tillegg. Den blokkerte saken under er derfor en
# overfoering, og at porten nekter en blokkert e-post er maalt i
# tests/test_executor_smtp.py.


@pytest.fixture()
def postfanger(tmp_path):
    from executor import MailCatcher

    with MailCatcher(directory=tmp_path / "maildrop") as catcher:
        yield catcher


@pytest.fixture()
def smtp_state(postfanger, monkeypatch):
    host, port = postfanger.address
    monkeypatch.setenv(ENV_EXECUTOR, "smtp")
    monkeypatch.setenv("LONEWATCH_SMTP_HOST", host)
    monkeypatch.setenv("LONEWATCH_SMTP_PORT", str(port))
    monkeypatch.delenv("LONEWATCH_SMTP_ALLOW_REMOTE", raising=False)
    s = DemoState()
    yield s
    s.close()


KJENT_EPOST = "alle@nordlysforsikring.no"
UKJENT_EPOST = "ukjent@eksempel.invalid"


def test_an_allowed_email_really_lands_as_an_eml_file(smtp_state, postfanger):
    out = smtp_state.submit_custom(
        action_type="send_email", summary="Svar paa sak 4411", recipient=KJENT_EPOST
    )
    assert out["card"]["status"] == "allow"
    e = out["card"]["execution"]
    assert e["executed"] is True and e["status"] == "done"
    # Mottakeren staar maskert i svaret og i loggen, slik mail.py gjoer det.
    assert "a***@nordlysforsikring.no" in e["detail"]
    assert KJENT_EPOST not in json.dumps(_execution_lines(smtp_state))

    assert len(postfanger.eml_files()) == 1
    raa = postfanger.eml_files()[0].read_text(encoding="utf-8")
    assert out["card"]["request"]["id"] in raa


def test_a_waiting_red_email_sends_nothing(smtp_state, postfanger):
    out = smtp_state.submit_custom(
        action_type="send_email", summary="Sender kundelisten", recipient=UKJENT_EPOST
    )
    assert out["card"]["status"] == "waiting"
    assert out["card"]["execution"] is None
    assert postfanger.eml_files() == []


def test_a_rejected_red_email_sends_nothing(smtp_state, postfanger):
    out = smtp_state.submit_custom(
        action_type="send_email", summary="Sender kundelisten", recipient=UKJENT_EPOST
    )
    svar = smtp_state.respond(out["card"]["request"]["id"], approved=False)
    assert svar["ok"] is True and svar["card"]["status"] == "rejected"
    assert svar["card"]["execution"] is None
    assert postfanger.eml_files() == []


def test_an_approved_red_email_is_sent(smtp_state, postfanger):
    out = smtp_state.submit_custom(
        action_type="send_email", summary="Sender kundelisten", recipient=UKJENT_EPOST
    )
    request_id = out["card"]["request"]["id"]
    assert postfanger.eml_files() == []

    svar = smtp_state.respond(request_id, approved=True)
    assert svar["ok"] is True
    assert svar["card"]["execution"]["executed"] is True
    assert len(postfanger.eml_files()) == 1
    raa = postfanger.eml_files()[0].read_text(encoding="utf-8")
    assert request_id in raa
    # Avtrykket staar i e-posten OG i loggen, saa de kan holdes opp mot hverandre.
    avtrykk = _execution_lines(smtp_state)[-1]["fingerprint"]
    assert avtrykk in raa


def test_a_blocked_request_sends_nothing(smtp_state, postfanger):
    out = smtp_state.submit_custom(
        action_type="transfer_money", amount="99000000", recipient=UKJENT_KONTO
    )
    assert out["card"]["status"] == "blocked"
    assert out["card"]["execution"] is None
    assert postfanger.eml_files() == []
    # Og ingen kan godkjenne den fram til en sending.
    assert smtp_state.respond(
        out["card"]["request"]["id"], approved=True, typed_amount="99000000"
    )["ok"] is False
    assert postfanger.eml_files() == []


def test_the_smtp_executor_refuses_to_send_anywhere_but_this_machine(
    postfanger, monkeypatch
):
    """Sperren staar fortsatt naar utfoereren er koblet inn i appen.

    Peker oppsettet et annet sted enn loopback, og ingen har satt
    LONEWATCH_SMTP_ALLOW_REMOTE=1, blir en `allow` «ikke utfoert» - ikke en
    sending ut av maskinen.
    """
    monkeypatch.setenv(ENV_EXECUTOR, "smtp")
    # RFC 5737-nettet. Det rutes ikke, og vi slaar det ikke opp.
    monkeypatch.setenv("LONEWATCH_SMTP_HOST", "192.0.2.1")
    monkeypatch.setenv("LONEWATCH_SMTP_PORT", "2525")
    monkeypatch.delenv("LONEWATCH_SMTP_ALLOW_REMOTE", raising=False)
    s = DemoState()
    try:
        out = s.submit_custom(
            action_type="send_email", summary="Rutinemelding", recipient=KJENT_EPOST
        )
        e = out["card"]["execution"]
        assert e["executed"] is False
        assert e["status"] == "failed"
        assert e["rule"] == "setup_error"
        assert "LONEWATCH_SMTP_ALLOW_REMOTE" in e["detail"]
    finally:
        s.close()
    assert postfanger.eml_files() == []
