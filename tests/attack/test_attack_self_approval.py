"""Angrep 1: godkjenne seg selv.

Paastanden Lonewatch bygger paa er at et roedt kort bare kan godkjennes av et
MENNESKE som har sett konsekvensen. Dette angrepet kaller /api/respond rett,
uten nettleser, uten informasjonskapsel og uten token, og ser hva som skjer.

**Denne filen er skrevet om.** Forrige runde fant tre hull (H1, H2, H3 i
docs/ANGREP.md): endepunktet var helt aapent, betenkningstiden kom fra
klienten, og pseudonymet var en fast konstant. Alle tre er lukket med
menneskenoekkelen (`ui/human_key.py`). Testene under maaler at de ER lukket, og
de to som fortsatt er aapne - /api/reset og at noekkelen ligger paa maskinen -
staar her som `xfail(strict=True)` og som en test som pinner hullet med vilje.

Et hull skal ikke kunne bli borte i stillhet, og en fiks skal ikke kunne bli
staaende upaavist.
"""

from __future__ import annotations

import pytest

from attack_lib import live_app
from conftest import HUMAN_KEY, HUMAN_KEY_TWO

from ui.human_key import ENV_HUMAN_KEY, HUMAN_KEY_HEADER

# Hodet med riktig menneskenoekkel. Alt som skal LYKKES i denne filen bruker
# dette; alt som skal NEKTES lar det vaere.
MENNESKE = {HUMAN_KEY_HEADER: HUMAN_KEY}
MENNESKE_TO = {HUMAN_KEY_HEADER: HUMAN_KEY_TWO}


def _gated_cards(live_app) -> list[dict]:
    """Roede kort med beloepsport, rett fra demoen.

    Vi nullstiller foerst. `ui.app` har én DemoState for hele prosessen, saa
    et kort en tidligere test godkjente ligger fortsatt som «godkjent» - og da
    maaler neste test paa et kort som ikke venter. At nullstillingen i det hele
    tatt er mulig uten noekkel er for oevrig H4, nederst i filen.
    """
    live_app.post("/api/reset")
    live_app.drain_feed()
    gated = live_app.cards_with_amount_gate()
    assert gated, "demoen skal ha minst ett roedt kort med beloepsport"
    return gated


def _gated_card(live_app) -> dict:
    return _gated_cards(live_app)[0]


def _body(card: dict, approved: bool = True) -> dict:
    return {
        "request_id": card["request"]["id"],
        "approved": approved,
        "typed_amount": str(int(card["request"]["amount"])),
    }


# ---------------------------------------------------------------------------
# LUKKET: et skript uten menneskenoekkel godkjenner ingenting
# ---------------------------------------------------------------------------


def test_a_red_card_cannot_be_approved_without_the_human_key(live_app):
    """Det samme angrepet som fant H1. Naa blir det avvist.

    Angrepet leser forventet beloep fra det aapne GET /api/state og poster det
    tilbake. Beloepet er fortsatt riktig - porten er ikke til aa lure - men
    kallet kommer ikke forbi laasen foran endepunktet.
    """
    card = _gated_card(live_app)
    request_id = card["request"]["id"]

    status, _ = live_app.post("/api/respond", _body(card))
    assert status == 403, "et kall uten menneskenoekkel ble sluppet inn"

    # Kortet staar fortsatt og venter. Ingenting er avgjort.
    assert any(c["request"]["id"] == request_id for c in live_app.waiting())


def test_a_wrong_human_key_is_refused(live_app):
    card = _gated_card(live_app)
    for feil in ("", "x", "feil-noekkel-men-lang-nok-0000", HUMAN_KEY + "x", HUMAN_KEY[:-1]):
        status, _ = live_app.post(
            "/api/respond", _body(card), headers={HUMAN_KEY_HEADER: feil}
        )
        assert status == 403, f"{feil!r} ble godtatt"
    assert any(c["request"]["id"] == card["request"]["id"] for c in live_app.waiting())


def test_the_agent_key_cannot_approve(live_app, monkeypatch):
    """Agentnoekkelen aapner /api/agent/*. Den aapner ikke godkjenningen.

    Dette er hele skillet: agenten ber om noe, et menneske godkjenner. Satt
    med vilje er agentnoekkelen den som ligger lettest tilgjengelig for en
    agent - den staar i `.mcp.json`, som Claude Code selv leser.
    """
    agentnoekkel = "agent-noekkel-til-angrep-0001"
    monkeypatch.setenv("LONEWATCH_AGENT_KEY", agentnoekkel)
    card = _gated_card(live_app)

    # I menneskehodet.
    status, _ = live_app.post(
        "/api/respond", _body(card), headers={HUMAN_KEY_HEADER: agentnoekkel}
    )
    assert status == 403

    # Og i sitt eget hode, i tillegg.
    status, _ = live_app.post(
        "/api/respond",
        _body(card),
        headers={"X-Lonewatch-Agent-Key": agentnoekkel},
    )
    assert status == 403

    assert any(c["request"]["id"] == card["request"]["id"] for c in live_app.waiting())


def test_a_shared_key_shuts_approval_off_entirely(live_app, monkeypatch):
    """Setter noen de to noeklene til samme verdi, slutter alt aa virke.

    Det er det eneste aerlige svaret: et oppsett der agentnoekkelen ogsaa
    godkjenner har ikke noe skille, og da skal ingen slippe gjennom - heller
    ikke mennesket. Ellers ville feilen vaert usynlig.
    """
    card = _gated_card(live_app)
    monkeypatch.setenv("LONEWATCH_AGENT_KEY", HUMAN_KEY)

    status, _ = live_app.post("/api/respond", _body(card), headers=MENNESKE)
    assert status == 503

    status, svar = live_app.get("/api/human")
    assert status == 200 and svar["configured"] is False


def test_approval_fails_closed_when_the_key_is_not_configured(live_app, monkeypatch):
    """Uten `LONEWATCH_HUMAN_KEY` svarer endepunktet 503 - det aapner seg ikke.

    En port som slipper alle gjennom naar oppsettet mangler, er ingen port.
    Dette er den retningen det maa feile i.
    """
    card = _gated_card(live_app)
    monkeypatch.delenv(ENV_HUMAN_KEY, raising=False)

    for headers in (None, MENNESKE, {HUMAN_KEY_HEADER: ""}):
        status, _ = live_app.post("/api/respond", _body(card), headers=headers)
        assert status == 503, f"{headers} slapp gjennom uten noekkel i miljoeet"

    assert any(c["request"]["id"] == card["request"]["id"] for c in live_app.waiting())


def test_the_right_key_still_approves(live_app):
    """Og med riktig noekkel virker det. Laasen skal ikke stenge demoen."""
    card = _gated_card(live_app)
    status, body = live_app.post("/api/respond", _body(card), headers=MENNESKE)
    assert status == 200 and body["ok"] is True
    assert body["card"]["status"] == "approved"


def test_the_expected_amount_is_handed_out_by_the_open_api(live_app):
    """Delforklaring: beloepsporten er ikke en hemmelighet, og skal ikke vaere det.

    Mennesket SKAL se beloepet. Derfor er porten aldri et vern mot et skript -
    den beviser at beloepet var kjent, ikke at noen saa det. Det som stopper
    skriptet er menneskenoekkelen, ett hakk foran.
    """
    card = _gated_card(live_app)
    assert card["request"]["amount"] is not None
    assert card["decision"]["requires_typed_amount"] is True


# ---------------------------------------------------------------------------
# LUKKET: sporet etter godkjenningen er regnet av tjeneren
# ---------------------------------------------------------------------------


def test_time_to_decide_cannot_be_dictated_by_the_caller(live_app):
    """H2 er lukket: feltet finnes ikke lenger i kroppen, og tiden maales her.

    Foer kunne et skript skrive 37,5 sekunder og la loggen se ut som en
    overveid menneskelig beslutning paa et kort som ble godkjent paa
    millisekunder. Naa avvises forsoeket med 422 i stedet for aa bli
    stilltiende ignorert: en klient som tror den bestemmer tiden, skal faa
    vite at den ikke gjoer det.
    """
    card = _gated_card(live_app)
    kropp = _body(card)
    kropp["seconds_to_decide"] = 37.5

    status, _ = live_app.post("/api/respond", kropp, headers=MENNESKE)
    assert status == 422, "klienten fikk oppgi betenkningstiden"
    assert any(c["request"]["id"] == card["request"]["id"] for c in live_app.waiting())


def test_the_server_measures_the_time_itself(live_app):
    """Tallen som havner i loggen er tjenerens egen maaling.

    Vi kan ikke si noeyaktig hva den blir, og det er riktig: den maaler ekte
    tid. Det vi kan si er at den er et tall, at den er liten naar svaret kom
    med en gang, og at den ikke er et tall klienten valgte.
    """
    card = _gated_card(live_app)
    status, body = live_app.post("/api/respond", _body(card), headers=MENNESKE)
    assert status == 200 and body["ok"] is True

    maalt = body["card"]["human"]["seconds_to_decide"]
    assert isinstance(maalt, (int, float))
    assert 0.0 <= maalt < 120.0, maalt
    assert maalt != 37.5


# ---------------------------------------------------------------------------
# LUKKET (innenfor noekkelmodellen): loggen vet hvilken noekkel som godkjente
# ---------------------------------------------------------------------------


def test_two_different_keys_give_two_different_pseudonyms(live_app):
    """H3 er lukket saa langt noekler kan lukke den.

    `employee_pseudonym` regnes naa ut av HVILKEN menneskenoekkel som kom inn,
    ikke av en fast konstant. To noekler - i praksis to personer, én noekkel
    hver - gir to ulike pseudonymer i loggen.
    """
    gated = _gated_cards(live_app)
    assert len(gated) >= 2

    sett = []
    for card, headers in zip(gated[:2], (MENNESKE, MENNESKE_TO)):
        status, body = live_app.post("/api/respond", _body(card), headers=headers)
        assert status == 200 and body["ok"] is True
        sett.append(body["card"]["human"]["employee_pseudonym"])

    assert all(p.startswith("emp_") for p in sett), sett
    assert len(set(sett)) == 2, f"samme pseudonym paa to ulike noekler: {sett}"


def test_the_pseudonym_follows_the_key_and_not_the_caller(live_app):
    """Det aerlige forbeholdet: noekkelen er identiteten, ikke personen.

    Samme noekkel gir samme pseudonym uansett hvem som holder den, og uansett
    hva kallet ellers sier om seg selv. Deler to mennesker én noekkel, kan
    loggen ikke skille dem. Det staar i ui/LIMITS.md, og det er grunnen til at
    en produksjonsversjon maa ha en egen enhet eller konto per person.
    """
    gated = _gated_cards(live_app)
    assert len(gated) >= 2

    sett = []
    for card in gated[:2]:
        status, body = live_app.post(
            "/api/respond",
            _body(card),
            headers={**MENNESKE, "X-Forwarded-For": "10.0.0.9", "User-Agent": "angrep"},
        )
        assert status == 200 and body["ok"] is True
        sett.append(body["card"]["human"]["employee_pseudonym"])

    assert len(set(sett)) == 1, (
        "samme noekkel ga to pseudonymer - da er pseudonymet ikke noekkelen"
    )


def test_the_human_key_never_comes_back_in_an_answer(live_app):
    """Noekkelen skal ikke kunne leses ut av et svar, heller ikke av en feil."""
    card = _gated_card(live_app)
    svar = []

    status, body = live_app.post("/api/respond", _body(card))
    svar.append(str(body))
    status, body = live_app.post(
        "/api/respond", _body(card), headers={HUMAN_KEY_HEADER: "feil-noekkel-0000000000"}
    )
    svar.append(str(body))
    status, body = live_app.get("/api/human")
    svar.append(str(body))
    status, body = live_app.post("/api/human/check", {}, headers=MENNESKE)
    svar.append(str(body))
    status, body = live_app.get("/api/state")
    svar.append(str(body))

    for tekst in svar:
        assert HUMAN_KEY not in tekst
        assert HUMAN_KEY_TWO not in tekst


# ---------------------------------------------------------------------------
# HOLDER NAA PAA ORDENTLIG: en fremmed nettside naar ikke endepunktet
# ---------------------------------------------------------------------------


def test_a_cross_site_form_post_is_turned_away(live_app):
    """To grunner naa, og den foerste er ikke lenger tilfeldig.

    Forrige runde holdt dette ved et UHELL: FastAPI krever en JSON-kropp, og
    de tre innholdstypene en nettleser kan sende uten forhaandssjekk avvises
    med 422. Det var et kroppsformat, ikke et CSRF-forsvar.

    Naa kreves i tillegg `X-Lonewatch-Human-Key`, og et egendefinert hode kan
    en fremmed nettside ikke sette uten en CORS-forhaandssjekk - som appen
    ikke svarer paa. Forsvaret hviler altsaa paa noe som er der med vilje.
    """
    card = _gated_card(live_app)
    for content_type in (
        "text/plain;charset=UTF-8",
        "application/x-www-form-urlencoded",
        "multipart/form-data; boundary=x",
    ):
        status, _ = live_app.post(
            "/api/respond",
            _body(card),
            content_type=content_type,
            headers={
                "Origin": "https://ondsinnet.example",
                "Referer": "https://ondsinnet.example/s",
            },
        )
        assert status in (403, 422), f"{content_type} ble godtatt"

    # Og med riktig innholdstype, men uten noekkel: 403.
    status, _ = live_app.post(
        "/api/respond", _body(card), headers={"Origin": "https://ondsinnet.example"}
    )
    assert status == 403

    # Kortet staar fortsatt og venter.
    assert any(c["request"]["id"] == card["request"]["id"] for c in live_app.waiting())


def test_an_arbitrary_origin_with_the_key_is_still_accepted(live_app):
    """Det aerlige forbeholdet: `Origin` sjekkes ikke.

    Har noen noekkelen, spoer ikke appen hvor kallet kom fra. Det er med vilje
    i en noekkelmodell - en token er en token - men det betyr at et skript,
    curl eller en agent paa maskinen slipper rett inn naar de har noekkelen.
    Se `test_aerlig_hull_menneskenoekkelen_ligger_paa_maskinen` i
    tests/test_agent_mcp_live.py.
    """
    card = _gated_card(live_app)
    status, body = live_app.post(
        "/api/respond",
        _body(card),
        headers={**MENNESKE, "Origin": "https://ondsinnet.example"},
    )
    assert status == 200
    assert body["ok"] is True
    assert body["card"]["status"] == "approved"


# ---------------------------------------------------------------------------
# HULLET SOM STAAR: /api/reset er fortsatt aapen
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "HULL (H4, kjent fra docs/REDTEAM.md F6, fortsatt aapent): /api/reset "
        "er uautentisert. Ett kall arkiverer loggen, toemmer koen og starter "
        "en ny kjede paa seq=0. Et roedt kort som venter paa et menneske kan "
        "altsaa fjernes fra koen av hvem som helst som naar porten. "
        "Menneskenoekkelen ble lagt foran /api/respond, ikke foran /api/reset: "
        "Nullstill er knappen den som holder demoen bruker mellom kjoeringer, "
        "og en laas der ville stengt demoen uten aa stoppe en godkjenning. "
        "Nullstillingen er aerlig (ingenting slettes, stien til arkivet vises), "
        "men den er ikke beskyttet."
    ),
)
def test_the_queue_cannot_be_wiped_by_an_unauthenticated_caller(live_app):
    live_app.post("/api/reset")
    live_app.drain_feed()
    assert live_app.waiting(), "koen skal ha roede kort foer angrepet"
    status, _ = live_app.post("/api/reset")
    assert status == 200
    assert live_app.waiting(), "koen ble toemt av et uautentisert /api/reset"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "HULL: /api/custom og /api/feed/step er fortsatt uautentiserte "
        "SKRIVEruter. De kan ikke godkjenne noe - alt de kan er aa lage nye "
        "forespoersler - men naa som utfoereren er koblet inn, betyr en "
        "`allow` at noe FAKTISK skjer. Med LONEWATCH_EXECUTOR=smtp kan et "
        "uautentisert lokalt kall derfor utloese en ekte e-post til én av "
        "demoens tolv kjente (oppdiktede) mottakere. Alt annet enn de tolv "
        "blir `unknown_recipient` -> roedt -> krever menneskenoekkelen. "
        "Se ui/LIMITS.md."
    ),
)
def test_the_write_routes_that_create_requests_need_no_key(live_app):
    live_app.post("/api/reset")
    status, body = live_app.post(
        "/api/custom",
        {"action_type": "send_email", "summary": "hei", "recipient": "alle@nordlysforsikring.no"},
    )
    assert status == 200 and body["ok"] is True
    # Det vi OENSKER: en skriverute skal kreve at noen er logget inn.
    assert body["card"]["decision"]["verdict"] != "allow", (
        "et uautentisert kall fikk en allow, og en allow utfoeres naa"
    )
