"""Angrep 1: godkjenne seg selv.

Paastanden Lonewatch bygger paa er at et roedt kort bare kan godkjennes av et
MENNESKE som har sett konsekvensen. Dette angrepet kaller /api/respond rett,
uten nettleser, uten informasjonskapsel og uten token, og ser hva som skjer.
"""

from __future__ import annotations

import pytest

from attack_lib import live_app

# ---------------------------------------------------------------------------
# HULLET: ett uautentisert HTTP-kall godkjenner en overfoering paa 10 mill.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "HULL: /api/respond har ingen autentisering, ingen token og ingen "
        "sjekk av hvem som spoer. Angrepet leser forventet beloep fra det "
        "aapne GET /api/state og poster det tilbake i ETT kall. En overfoering "
        "paa 10 000 000 kr gaar fra 'venter paa menneske' til 'godkjent' uten "
        "at noe menneske har vaert involvert. Beloepsporten beviser bare at "
        "beloepet var KJENT, ikke at noen SAA det. Eneste forsvar i dag er at "
        "appen binder 127.0.0.1."
    ),
)
def test_a_red_card_cannot_be_approved_without_a_browser(live_app):
    live_app.drain_feed()
    gated = live_app.cards_with_amount_gate()
    assert gated, "demoen skal ha minst ett roedt kort med beloepsport"

    card = gated[0]
    request_id = card["request"]["id"]
    expected = card["request"]["amount"]

    status, body = live_app.post(
        "/api/respond",
        {"request_id": request_id, "approved": True, "typed_amount": str(int(expected))},
    )
    assert status == 200
    # Det vi OENSKER: et skript uten nettleser skal ikke kunne godkjenne.
    assert body["ok"] is False, (
        f"skriptet godkjente {request_id} paa {expected} kr uten menneske"
    )


def test_the_expected_amount_is_handed_out_by_the_open_api(live_app):
    """Delforklaring paa hullet over: beloepsporten er ikke en hemmelighet.

    Dette er ikke et hull i seg selv - mennesket SKAL se beloepet - men det er
    grunnen til at porten ikke stopper et skript. Testen staar for aa vise at
    informasjonen ligger aapent, slik at ingen tror porten er en delt
    hemmelighet.
    """
    live_app.drain_feed()
    gated = live_app.cards_with_amount_gate()
    assert gated
    assert gated[0]["request"]["amount"] is not None
    assert gated[0]["decision"]["requires_typed_amount"] is True


# ---------------------------------------------------------------------------
# HULLET: sporet etter godkjenningen er oppgitt av klienten selv
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "HULL: `seconds_to_decide` kommer fra klienten og lagres som den er. "
        "Et skript kan derfor skrive 37,5 sekunder og la loggen se ut som en "
        "overveid menneskelig beslutning paa et kort som ble godkjent paa "
        "millisekunder. Det finnes heller ingen nedre grense: 0,0 sekunder "
        "godtas. For en jurist er dette verre enn ingen maaling - det er et "
        "villedende revisjonsspor."
    ),
)
def test_time_to_decide_cannot_be_dictated_by_the_caller(live_app):
    live_app.drain_feed()
    gated = live_app.cards_with_amount_gate()
    card = gated[0]
    status, body = live_app.post(
        "/api/respond",
        {
            "request_id": card["request"]["id"],
            "approved": True,
            "typed_amount": str(int(card["request"]["amount"])),
            "seconds_to_decide": 37.5,
        },
    )
    assert status == 200 and body["ok"] is True
    logged = body["card"]["human"]["seconds_to_decide"]
    assert logged != 37.5, "loggen tok imot klientens eget tall for betenkningstid"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "HULL: det finnes ingen identitet i det hele tatt. `employee_pseudonym` "
        "regnes ut fra en fast konstant (DEMO_EMPLOYEE_ID), saa alle "
        "godkjenninger faar samme pseudonym uansett hvem - eller hva - som "
        "kalte endepunktet. Loggen kan svare paa HVA som ble godkjent, men "
        "aldri paa HVEM som godkjente det."
    ),
)
def test_two_different_callers_get_two_different_pseudonyms(live_app):
    live_app.drain_feed()
    gated = live_app.cards_with_amount_gate()
    assert len(gated) >= 2

    seen = []
    for card in gated[:2]:
        _, body = live_app.post(
            "/api/respond",
            {
                "request_id": card["request"]["id"],
                "approved": True,
                "typed_amount": str(int(card["request"]["amount"])),
            },
            headers={"X-Forwarded-For": "10.0.0.9"},
        )
        assert body["ok"] is True
        seen.append(body["card"]["human"]["employee_pseudonym"])

    assert len(set(seen)) == 2, f"samme pseudonym paa to ulike kall: {seen}"


# ---------------------------------------------------------------------------
# HULLET: alt annet er ogsaa aapent
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "HULL (kjent fra docs/REDTEAM.md F6, her gjort kjoerbart): /api/reset "
        "er uautentisert. Ett kall arkiverer loggen, toemmer koen og starter "
        "en ny kjede paa seq=0. Et roedt kort som venter paa et menneske kan "
        "altsaa fjernes fra koen av hvem som helst som naar porten. "
        "Nullstillingen er aerlig (ingenting slettes, stien til arkivet vises), "
        "men den er ikke beskyttet."
    ),
)
def test_the_queue_cannot_be_wiped_by_an_unauthenticated_caller(live_app):
    live_app.drain_feed()
    assert live_app.waiting(), "koen skal ha roede kort foer angrepet"
    status, _ = live_app.post("/api/reset")
    assert status == 200
    assert live_app.waiting(), "koen ble toemt av et uautentisert /api/reset"


def test_a_cross_site_form_post_is_turned_away(live_app):
    """HOLDER (men ved uhell): bare application/json godtas.

    En ondsinnet nettside operatoeren besoeker kan ikke poste et vanlig
    HTML-skjema til /api/respond: FastAPI krever en JSON-kropp, og de tre
    innholdstypene en nettleser kan sende uten forhaandssjekk (`text/plain`,
    `application/x-www-form-urlencoded`, `multipart/form-data`) avvises med
    422. Dette er en bieffekt av kroppsformatet, ikke et CSRF-forsvar: det
    finnes verken token eller Origin-sjekk, og en klient utenfor en nettleser
    (curl, et skript, en annen agent paa maskinen) slipper rett inn. Se
    testene over.
    """
    live_app.drain_feed()
    gated = live_app.cards_with_amount_gate()
    assert gated
    card = gated[0]
    body = {
        "request_id": card["request"]["id"],
        "approved": True,
        "typed_amount": str(int(card["request"]["amount"])),
    }
    for content_type in (
        "text/plain;charset=UTF-8",
        "application/x-www-form-urlencoded",
        "multipart/form-data; boundary=x",
    ):
        status, _ = live_app.post(
            "/api/respond",
            body,
            content_type=content_type,
            headers={"Origin": "https://ondsinnet.example", "Referer": "https://ondsinnet.example/s"},
        )
        assert status == 422, f"{content_type} ble godtatt"

    # Kortet staar fortsatt og venter.
    assert any(c["request"]["id"] == card["request"]["id"] for c in live_app.waiting())


def test_an_arbitrary_origin_is_accepted_on_json(live_app):
    """Grensen gaar paa innholdstype, ikke paa avsender.

    Samme kall med `Content-Type: application/json` og en fremmed `Origin`
    godtas fullt ut. Det er dokumentasjon av at forsvaret over er tilfeldig.
    """
    live_app.drain_feed()
    gated = live_app.cards_with_amount_gate()
    card = gated[0]
    status, body = live_app.post(
        "/api/respond",
        {
            "request_id": card["request"]["id"],
            "approved": True,
            "typed_amount": str(int(card["request"]["amount"])),
        },
        headers={"Origin": "https://ondsinnet.example"},
    )
    assert status == 200
    assert body["ok"] is True
    assert body["card"]["status"] == "approved"
