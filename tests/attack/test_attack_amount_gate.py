"""Angrep 2: omgaa beloepsporten.

Et roedt kort med `requires_typed_amount` kan bare godkjennes av noen som
skriver beloepet. Angrepet proever aa bekrefte et beloep UTEN aa skrive det
riktige: mellomrom, tusenskille, unicode-sifre, negative tall, absurde tall,
desimaler, tom streng - og de samme forsoekene rett mot API-et.

Resultatet: porten holder. Alle forsoekene under avvises, og ingen av dem gir
en krasj. Angrepet som virker staar i test_attack_self_approval.py, og det
angriper ikke selve tolkningen - det skriver det RIKTIGE beloepet fra et
skript.
"""

from __future__ import annotations

import pytest

from attack_lib import live_app
from conftest import HUMAN_KEY

from ui.amount import amount_matches, parse_amount
from ui.human_key import HUMAN_KEY_HEADER
from ui.state import STATUS_WAITING, DemoState

# Menneskenoekkelen. Den staar her fordi dette angrepet handler om
# BELOEPSPORTEN, ikke om hvem som naar endepunktet: for aa maale porten maa vi
# komme forbi laasen foran den. Angrepet mot selve laasen staar i
# test_attack_self_approval.py.
MENNESKE = {HUMAN_KEY_HEADER: HUMAN_KEY}

BIG = 10_000_000.0

# Ting som skal avvises mot forventet 10 000 000. Hvert tilfelle er et forsoek
# paa aa bekrefte uten aa ha skrevet beloepet.
REJECTED = [
    pytest.param("100000,00", id="desimal-forveksling-hundre-tusen-og-null-oere"),
    pytest.param("100000.00", id="punktum-som-desimalskille"),
    pytest.param("1000000,0", id="ett-siffer-for-lite"),
    pytest.param("10000000.00", id="punktum-pluss-oere"),
    pytest.param("-10000000", id="negativt"),
    pytest.param("+10000000", id="pluss-foran"),
    pytest.param("abc10000000xyz", id="bokstaver-rundt"),
    pytest.param("", id="tom-streng"),
    pytest.param("   ", id="bare-mellomrom"),
    pytest.param(None, id="ingen-verdi"),
    pytest.param("ti millioner", id="ord"),
    pytest.param("1e7", id="eksponent"),
    pytest.param("0x989680", id="heksadesimal"),
    pytest.param("10,000,000", id="engelsk-tusenskille"),
    pytest.param("10'000'000", id="apostrof-tusenskille"),
    pytest.param("10_000_000", id="understrek-tusenskille"),
    pytest.param("1 0000000", id="feil-gruppering"),
    pytest.param("1 000 0000", id="feil-gruppering-bakerst"),
    pytest.param("10000000.", id="punktum-til-slutt"),
    pytest.param("10000000,", id="komma-til-slutt"),
    pytest.param("10000000,000", id="tre-desimaler"),
    pytest.param("10000000%", id="prosenttegn"),
    pytest.param("(10000000)", id="parentes"),
    pytest.param("10000000;", id="semikolon"),
    pytest.param("kr10000000", id="valuta-foran"),
    pytest.param("10000000 kr kr", id="valuta-to-ganger"),
    pytest.param("١٠٠٠٠٠٠٠", id="arabisk-indiske-sifre"),
    pytest.param("１０００００００", id="fullbredde-sifre"),
    pytest.param("১০০০০০০০", id="bengalske-sifre"),
    pytest.param("​10000000", id="nullbredde-mellomrom-foran"),
    pytest.param("10000000​", id="nullbredde-mellomrom-bak"),
    pytest.param("10 000 000", id="figure-space-som-tusenskille"),
    pytest.param("9" * 20, id="absurd-stort"),
    pytest.param("1" * 5000, id="5000-siffer"),
    pytest.param("9999999999999", id="maks-siffer-men-feil-tall"),
]

# Ting som SKAL godtas: det er faktisk beloepet, skrevet slik folk skriver det.
ACCEPTED = ["10000000", "10 000 000", "10.000.000", "10 000 000 kr", "10000000 NOK",
            "10000000kroner", "10000000KR", "0010000000", " 10000000 ", "10000000,00",
            "\t10000000\n", "10 000 000", "10 000 000"]


@pytest.mark.parametrize("written", REJECTED)
def test_the_amount_gate_rejects_everything_that_is_not_the_amount(written):
    assert amount_matches(written, BIG) is False, f"{written!r} ble godtatt som 10 000 000"


@pytest.mark.parametrize("written", ACCEPTED)
def test_the_gate_still_accepts_the_amount_written_the_normal_ways(written):
    assert amount_matches(written, BIG) is True


def test_a_very_long_digit_string_is_rejected_without_crashing():
    """Regresjon paa F3 i docs/REDTEAM.md: 5000 siffer ga HTTP 500 foer."""
    assert parse_amount("1" * 5000) is None
    assert parse_amount("1" * 65) is None


def test_the_gate_cannot_be_satisfied_by_a_number_from_another_card():
    """Beloepet er bundet til kortet, ikke til koen."""
    state = DemoState()
    while state.step_feed() is not None:
        pass
    gated = [c for c in state.snapshot()["waiting"] if c["decision"]["requires_typed_amount"]]
    assert len(gated) >= 2
    a, b = gated[0], gated[1]
    assert a["request"]["amount"] != b["request"]["amount"]

    result = state.respond(b["request"]["id"], True, typed_amount=str(int(a["request"]["amount"])))
    assert result["ok"] is False
    assert state.cards[b["request"]["id"]]["status"] == STATUS_WAITING


@pytest.mark.parametrize("written", [None, "", "   ", "0"])
def test_an_empty_amount_never_confirms_a_transfer(written):
    state = DemoState()
    while state.step_feed() is not None:
        pass
    gated = [c for c in state.snapshot()["waiting"] if c["decision"]["requires_typed_amount"]]
    card = gated[0]
    result = state.respond(card["request"]["id"], True, typed_amount=written)
    assert result["ok"] is False
    assert state.cards[card["request"]["id"]]["status"] == STATUS_WAITING


def test_the_gate_survives_a_hundred_wrong_attempts_on_the_same_card(live_app):
    """Ingen laasing, men ogsaa ingen vei inn: kortet staar og venter.

    Merk hva testen IKKE viser: det finnes ingen forsoeksgrense og ingen
    forsinkelse. Hundre gale forsoek koster ingenting. Det er ufarlig her fordi
    beloepet ikke er en hemmelighet, men det betyr at endepunktet heller ikke
    har noe vern mot gjetting hvis noe senere blir hemmelig.
    """
    live_app.drain_feed()
    card = live_app.cards_with_amount_gate()[0]
    request_id = card["request"]["id"]
    for i in range(100):
        status, body = live_app.post(
            "/api/respond",
            {"request_id": request_id, "approved": True, "typed_amount": f"{i}"},
            headers=MENNESKE,
        )
        assert status == 200
        assert body["ok"] is False
    assert any(c["request"]["id"] == request_id for c in live_app.waiting())


# ---------------------------------------------------------------------------
# porten gjelder bare penger
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "DELVIS HULL: `requires_typed_amount` settes bare for "
        "TRANSFER_MONEY. Et roedt kort som deler hele kundebasen eller sender "
        "personalmappen ut av huset godkjennes med ett kall uten noe aa skrive "
        "- {'approved': true} er nok. Den sterkeste delen av forsvaret "
        "beskytter altsaa bare penger, ikke personopplysninger. Teksten "
        "mennesket skal se finnes, men ingenting krever at noen har lest den."
    ),
)
def test_every_red_card_requires_the_human_to_type_something(live_app):
    live_app.drain_feed()
    red = live_app.waiting()
    assert red
    uten_port = [c for c in red if not c["decision"]["requires_typed_amount"]]
    assert not uten_port, (
        "roede kort uten noe aa skrive: "
        + ", ".join(f"{c['request']['id']} ({c['request']['action_type']})" for c in uten_port)
    )
