"""Angrep 4: gjenbruke en godkjenning.

Ideen: fa et menneske til aa godkjenne sak A, og saa bruke den godkjenningen
paa noe annet - en annen handling, et annet beloep, en annen mottaker.

Kort fasit: dette HOLDER. Godkjenningen er bundet til `request_id`, kortet kan
bare besvares én gang, beloepet maa stemme med DET kortet, og et kort som er
`allow` eller `block` kan ikke besvares i det hele tatt.

Det staar ett aerlig forbehold nederst: det finnes ingen utfoerende del i
demoen, saa en godkjenning er en logglinje, ikke en noekkel noe verktoey
senere kontrollerer. I et ekte produkt er det DER gjenbruk ville skjedd.
"""

from __future__ import annotations

import pytest

from ui.state import (
    STATUS_ALLOW,
    STATUS_APPROVED,
    STATUS_BLOCKED,
    STATUS_REJECTED,
    STATUS_WAITING,
    DemoState,
)


@pytest.fixture()
def drained() -> DemoState:
    state = DemoState()
    while state.step_feed() is not None:
        pass
    return state


def _gated(state: DemoState) -> list[dict]:
    return [c for c in state.snapshot()["waiting"] if c["decision"]["requires_typed_amount"]]


# ---------------------------------------------------------------------------
# HOLDER: én godkjenning, ett kort
# ---------------------------------------------------------------------------


def test_the_same_card_cannot_be_answered_twice(drained):
    card = _gated(drained)[0]
    rid, amount = card["request"]["id"], card["request"]["amount"]
    assert drained.respond(rid, True, typed_amount=str(int(amount)))["ok"] is True
    again = drained.respond(rid, True, typed_amount=str(int(amount)))
    assert again["ok"] is False
    assert "allerede besvart" in again["error"]
    assert drained.cards[rid]["status"] == STATUS_APPROVED


def test_a_rejection_cannot_be_turned_into_an_approval(drained):
    card = drained.snapshot()["waiting"][0]
    rid = card["request"]["id"]
    assert drained.respond(rid, False)["ok"] is True
    assert drained.cards[rid]["status"] == STATUS_REJECTED
    assert drained.respond(rid, True, typed_amount="1")["ok"] is False
    assert drained.cards[rid]["status"] == STATUS_REJECTED


def test_an_approval_for_one_card_does_not_carry_to_another(drained):
    """Beloepet fra sak A bekrefter ikke sak B."""
    gated = _gated(drained)
    assert len(gated) >= 2
    a, b = gated[0], gated[1]
    assert a["request"]["amount"] != b["request"]["amount"]

    assert drained.respond(a["request"]["id"], True, typed_amount=str(int(a["request"]["amount"])))["ok"]
    smugled = drained.respond(b["request"]["id"], True, typed_amount=str(int(a["request"]["amount"])))
    assert smugled["ok"] is False
    assert drained.cards[b["request"]["id"]]["status"] == STATUS_WAITING


def test_a_blocked_card_can_never_be_approved(drained):
    blocked = drained.snapshot()["blocked"]
    assert blocked, "demoen skal ha minst ett blokkert kort"
    for card in blocked:
        rid = card["request"]["id"]
        for typed in (None, "0", "1", str(card["request"].get("amount") or 0)):
            result = drained.respond(rid, True, typed_amount=typed)
            assert result["ok"] is False
            assert drained.cards[rid]["status"] == STATUS_BLOCKED


def test_a_quiet_allow_cannot_be_given_a_fake_human_approval(drained):
    """En allow er ikke et roedt kort. Den kan ikke faa en godkjenningslinje."""
    calm = drained.snapshot()["calm"]
    assert calm
    rid = calm[0]["request"]["id"]
    assert drained.respond(rid, True, typed_amount="0")["ok"] is False
    assert drained.cards[rid]["status"] == STATUS_ALLOW
    humans = [e for e in drained.vault.entries() if e.kind == "human"]
    assert all(e.payload["request_id"] != rid for e in humans)


def test_an_unknown_request_id_cannot_be_approved(drained):
    for rid in ("", "req_9999", "custom_0001", "../req_0037", "req_0037 ", "REQ_0037"):
        result = drained.respond(rid, True, typed_amount="10000000")
        assert result["ok"] is False, f"{rid!r} ble godkjent"


def test_the_log_binds_each_approval_to_one_request_id(drained):
    """Loggen kan svare paa HVA som ble godkjent, én linje per sak."""
    gated = _gated(drained)[:2]
    for card in gated:
        drained.respond(card["request"]["id"], True, typed_amount=str(int(card["request"]["amount"])))
    humans = [e for e in drained.vault.entries() if e.kind == "human"]
    ids = [e.payload["request_id"] for e in humans]
    assert ids == [c["request"]["id"] for c in gated]
    assert len(ids) == len(set(ids))


def test_the_logged_amount_is_the_one_lonewatch_parsed(drained):
    """Loggen viser tallet Lonewatch tolket, ikke raateksten mennesket skrev."""
    card = _gated(drained)[0]
    rid, amount = card["request"]["id"], card["request"]["amount"]
    drained.respond(rid, True, typed_amount=f"{int(amount):,}".replace(",", "."))
    human = [e for e in drained.vault.entries() if e.kind == "human"][-1]
    assert human.payload["typed_amount"] == amount


# ---------------------------------------------------------------------------
# HOLDER: beloepet kan ikke endres etter at kortet er laget
# ---------------------------------------------------------------------------


def test_a_second_request_cannot_overwrite_a_waiting_card(drained):
    """Ingen vei inn til aa bytte beloep eller mottaker paa et kort som venter.

    `/api/custom` lager alltid en ny, egen id (`custom_NNNN`), og
    stroemmen bruker demoens faste id-er. Det finnes ingen endepunkt som
    endrer en forespoersel. Testen fester det: etter en ny forespoersel staar
    det ventende kortet uendret.
    """
    card = _gated(drained)[0]
    rid = card["request"]["id"]
    before = dict(drained.cards[rid]["request"])

    result = drained.submit_custom(
        "transfer_money", amount="1", recipient="NO93 8601 1117 947", summary="bytt beloep"
    )
    assert result["ok"] is True
    assert result["card"]["request"]["id"] != rid
    assert drained.cards[rid]["request"] == before
    assert drained.cards[rid]["status"] == STATUS_WAITING


# ---------------------------------------------------------------------------
# AERLIG FORBEHOLD: det finnes ingen utfoerende del aa gjenbruke en noekkel mot
# ---------------------------------------------------------------------------


def test_an_approval_is_a_log_line_and_not_a_capability(drained):
    """Det angrepet IKKE kunne proeve, og hvorfor det er verdt aa si.

    En godkjenning setter `card["status"]` og skriver én `HumanResponse` til
    loggen. Den gir ingen signert billett, ingen token med utloepstid og ingen
    noekkel et verktoey senere maa vise fram - for det finnes ingen utfoerende
    del i demoen. «Gjenbruke en godkjenning» har derfor ingenting aa rette seg
    mot her.

    I et ekte produkt er nettopp dette stedet gjenbruk ville skjedd: mellom
    «mennesket sa ja» og «verktoeyet gjorde det». Da maa billetten vaere bundet
    til noeyaktig én handling med beloep og mottaker, brukes én gang, og utloepe.
    Vi har ikke bygget det, og vi kan derfor ikke paastaa at det holder.
    """
    card = _gated(drained)[0]
    rid = card["request"]["id"]
    drained.respond(rid, True, typed_amount=str(int(card["request"]["amount"])))
    human = drained.cards[rid]["human"]
    assert set(human) == {
        "request_id",
        "ts",
        "employee_pseudonym",
        "approved",
        "typed_amount",
        "seconds_to_decide",
    }
    # Ingen token, ingen utloepstid, ingen signatur.
    assert "token" not in human and "expires_at" not in human
