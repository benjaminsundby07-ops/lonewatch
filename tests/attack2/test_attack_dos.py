"""Angrep 4: last og tjenestenekt.

Svaert store forespoersler, svaert mange kort, lange strenger, dype
JSON-strukturer. Fryser appen, krasjer den, fylles loggen? Runde en testet
bevisst ikke last utover 100 forsoek mot ett kort.

  HOLDER: feltgrensene (max_length) avviser lange strenger med 422, dyp JSON gir
          en pen 400 uten krasj, og appen svarer fortsatt etterpaa.
  LUKKET i runde tre (var A10 og A11): det finnes naa en kroppsgrense
          (`MAX_BODY_BYTES` = 64 KB, en ASGI-middleware i ui/app.py som svarer
          413), et tak paa antall kort (`MAX_CARDS` = 200 i ui/state.py) og en
          fartsgrense paa /api/agent/submit
          (`AGENT_SUBMITS_PER_MINUTE` = 30, som svarer 429). I tillegg er
          /api/custom ikke lenger uautentisert. Begrunnelsen for hvert tall
          staar ved konstanten.
  STAAR IGJEN: en logg som vokser av LOVLIGE kall. 200 kort er et tak paa hvor
          mange kort som finnes samtidig, ikke paa hvor mange logglinjer en
          demo kan skrive over tid - en som nullstiller og fyller paa nytt kan
          gjenta det. Det krever noekkelen hver gang, og hver nullstilling
          arkiverer den gamle loggen i stedet for aa slette den.
"""

from __future__ import annotations

import pytest
from attack_lib2 import refuse_to_touch_real_log  # noqa: F401  (autouse: aldri roer den ekte loggen)

from attack_lib2 import human_headers, live_app

from ui.app import AGENT_SUBMITS_PER_MINUTE, MAX_BODY_BYTES, reset_rate_limit
from ui.state import MAX_CARDS


# ---------------------------------------------------------------------------
# HOLDER: lange strenger og dyp JSON haandteres uten krasj.
# ---------------------------------------------------------------------------


def test_overlong_field_is_rejected_not_crashing(live_app):
    status, body = live_app.custom(
        {"action_type": "send_email", "summary": "x" * 50_000, "recipient": "a@b.no"}
    )
    assert status == 422  # max_length slaar inn
    # Appen svarer fortsatt.
    assert live_app.get("/api/state")[0] == 200


def test_deeply_nested_json_does_not_crash(live_app):
    depth = 5000
    payload = "1"
    for _ in range(depth):
        payload = "[" + payload + "]"
    raw = ('{"action_type":' + payload + "}").encode()
    status, _ = live_app.post("/api/custom", raw, headers=human_headers())
    assert status in (400, 422)  # avvist, ikke krasj
    assert live_app.get("/api/state")[0] == 200  # fortsatt i live


# ---------------------------------------------------------------------------
# LUKKET (var A10): kroppsgrensen.
#
# Testen var `xfail(strict=True)`. Den passerer naa, saa den er en vanlig test.
# ---------------------------------------------------------------------------


def test_a_multi_megabyte_body_never_becomes_a_card(live_app):
    """3 MB soepel i et felt ingen leser: avvist, og ingen kort laget.

    Utfallet er ett av to, og BEGGE er et nei:

      - 413, hvis klienten rakk aa bli ferdig med aa sende foer svaret kom.
      - et avbrutt samband, hvis den ikke rakk det. Appen svarer paa
        `Content-Length: 3000000` uten aa lese kroppen (det er hele poenget
        med grensen), og da ligger klienten fortsatt og skriver naar vi
        legger paa.

    Testen godtar begge med vilje. Aa kreve en pen 413 her ville tvunget appen
    til aa LESE de 3 MB foerst, og da er grensen bare pynt. Det som maales er
    det som betyr noe: ingenting ble laget, og appen staar.
    """
    import urllib.error

    big = {
        "action_type": "send_email",
        "summary": "ok",
        "recipient": "a@b.no",
        "junk": "Z" * 3_000_000,
    }
    _, foer = live_app.get("/api/state", headers=human_headers())
    try:
        status, _ = live_app.custom(big)
        assert status == 413, f"3 MB kropp svarte {status}"
    except (urllib.error.URLError, ConnectionResetError, BrokenPipeError):
        pass  # sambandet ble lagt paa foer kroppen var sendt - ogsaa et nei

    # Ingenting ble laget, og appen staar.
    _, etter = live_app.get("/api/state", headers=human_headers())
    assert len(etter["custom"]) == len(foer["custom"])
    assert etter["log"]["lines"] == foer["log"]["lines"]


def test_the_limit_bites_just_above_the_number_and_not_just_below(live_app):
    """Grensen er et tall, ikke en foelelse: rett under gaar gjennom, rett over ikke.

    Rett under skal naa VALIDERINGEN (422 paa et for langt `summary`), ikke 413.
    At den gaar fra 413 til 422 er beviset paa at det var stoerrelsen som ble
    maalt og ikke noe annet.
    """
    def kropp(byte: int) -> dict:
        # ~50 byte ramme rundt, saa `junk` fyller resten.
        return {"action_type": "send_email", "junk": "Z" * max(0, byte - 50)}

    under, _ = live_app.custom(kropp(MAX_BODY_BYTES - 2_000))
    over, _ = live_app.custom(kropp(MAX_BODY_BYTES + 2_000))
    assert over == 413, f"en kropp over grensen svarte {over}"
    assert under != 413, f"en kropp under grensen ble avvist som for stor ({under})"


def test_a_lying_content_length_does_not_get_past_the_limit(live_app):
    """Grensen leser ikke bare hodet.

    `Content-Length` er noe KLIENTEN oppgir. Sender vi kroppen stykkevis
    (`Transfer-Encoding: chunked`), finnes hodet ikke - og da maa byte telles
    mens de kommer. En grense som bare leser et hode, er ingen grense.
    """
    import http.client

    vert, _, port = live_app.base.removeprefix("http://").partition(":")
    conn = http.client.HTTPConnection(vert, int(port), timeout=30)
    kropp = b'{"action_type":"send_email","junk":"' + b"Z" * 200_000 + b'"}'
    try:
        conn.putrequest("POST", "/api/custom")
        conn.putheader("Content-Type", "application/json")
        conn.putheader("Transfer-Encoding", "chunked")
        for navn, verdi in human_headers().items():
            conn.putheader(navn, verdi)
        conn.endheaders()
        # Ett stykke av gangen, slik en angriper ville gjort det.
        for i in range(0, len(kropp), 8192):
            bit = kropp[i : i + 8192]
            conn.send(b"%x\r\n" % len(bit) + bit + b"\r\n")
        conn.send(b"0\r\n\r\n")
        svar = conn.getresponse()
        svar.read()
        assert svar.status == 413, f"en chunked kropp paa 200 KB svarte {svar.status}"
    except (BrokenPipeError, ConnectionResetError):
        # Tjeneren la paa foer vi var ferdige med aa sende. Det er ogsaa et nei,
        # og det er et nei som koster angriperen mer enn det koster oss.
        pass
    finally:
        conn.close()
    assert live_app.get("/api/state")[0] == 200


# ---------------------------------------------------------------------------
# LUKKET (var A11): taket paa antall kort.
# ---------------------------------------------------------------------------


def test_number_of_cards_is_bounded(live_app):
    """Taket holder, og det nekter - det kaster ikke et gammelt kort.

    Vi sender 20 mer enn taket. Et kort som FORSVINNER fra koeen for aa gi plass
    til et nytt er noeyaktig det et angrep vil ha, saa testen sjekker begge
    ting: at det ikke ble flere enn taket, og at den som ble nektet fikk en
    ærlig beskjed.
    """
    nektet = 0
    for i in range(MAX_CARDS + 20):
        status, body = live_app.custom(
            {"action_type": "read_document", "summary": f"nr {i}"}
        )
        assert status == 200, f"kall {i} svarte {status}"
        if body.get("ok") is False:
            nektet += 1
            assert str(MAX_CARDS) in body["error"], body["error"]

    _, snap = live_app.get("/api/state", headers=human_headers())
    laget = len(snap["custom"])
    assert laget <= MAX_CARDS, f"appen laget {laget} kort over taket {MAX_CARDS}"
    assert nektet >= 20, f"bare {nektet} ble nektet - taket ga etter"


def test_the_cap_does_not_throw_away_a_waiting_red_card(live_app):
    """Og et roedt kort som ventet, ligger der fortsatt naar taket er naadd."""
    live_app.drain_feed()
    venter_foer = {c["request"]["id"] for c in live_app.waiting()}
    assert venter_foer

    for i in range(MAX_CARDS + 10):
        _, body = live_app.custom({"action_type": "read_document", "summary": f"n{i}"})
        if body.get("ok") is False:
            break

    venter_etter = {c["request"]["id"] for c in live_app.waiting()}
    assert venter_foer <= venter_etter, "et ventende roedt kort forsvant da taket ble naadd"


# ---------------------------------------------------------------------------
# LUKKET (var H27 i docs/ANGREP.md): fartsgrensen paa /api/agent/submit.
# ---------------------------------------------------------------------------


def test_an_agent_cannot_flood_the_queue_in_one_burst(live_app):
    """Over grensen svarer /api/agent/submit 429, med Retry-After.

    H27: 40 kall fylte godkjenningskoeen, og mennesket maatte gjennom alle for
    aa finne den ene som betyr noe. Tjenestenekt mot MENNESKET.
    """
    reset_rate_limit()
    from attack_lib2 import AGENT_KEY_HEADER, AGENT_KEY

    hode = {AGENT_KEY_HEADER: AGENT_KEY}
    koder = []
    for i in range(AGENT_SUBMITS_PER_MINUTE + 5):
        status, _ = live_app.post(
            "/api/agent/submit",
            {"action_type": "read_document", "summary": f"kall {i}"},
            headers=hode,
        )
        koder.append(status)

    assert koder[:AGENT_SUBMITS_PER_MINUTE] == [200] * AGENT_SUBMITS_PER_MINUTE, (
        "lovlige kall under grensen ble avvist"
    )
    assert set(koder[AGENT_SUBMITS_PER_MINUTE:]) == {429}, (
        f"kall over grensen slapp gjennom: {koder[AGENT_SUBMITS_PER_MINUTE:]}"
    )
    reset_rate_limit()


def test_the_rate_limit_is_per_key_not_global(live_app):
    """Fartsgrensen gjelder PER agentnoekkel.

    Hvorfor dette er verdt aa maale: var den global, ville en agent kunnet
    bruke opp kvoten til alle andre - og det er det samme angrepet i en
    annen innpakning.
    """
    reset_rate_limit()
    from attack_lib2 import AGENT_KEY_HEADER, AGENT_KEY

    # Bruk opp kvoten med den gyldige noekkelen.
    for i in range(AGENT_SUBMITS_PER_MINUTE):
        live_app.post(
            "/api/agent/submit",
            {"action_type": "read_document", "summary": f"k{i}"},
            headers={AGENT_KEY_HEADER: AGENT_KEY},
        )
    brukt, _ = live_app.post(
        "/api/agent/submit",
        {"action_type": "read_document", "summary": "en til"},
        headers={AGENT_KEY_HEADER: AGENT_KEY},
    )
    assert brukt == 429

    # En ANNEN (feil) noekkel stoppes paa noekkelen, ikke paa farten: 403, ikke
    # 429. Det viser ogsaa at vakten staar foer telleren, saa en ugyldig
    # noekkel ikke kan brenne opp kvoten til en gyldig.
    annen, _ = live_app.post(
        "/api/agent/submit",
        {"action_type": "read_document", "summary": "fremmed"},
        headers={AGENT_KEY_HEADER: "en-helt-annen-noekkel-0000"},
    )
    assert annen == 403, f"fremmed noekkel svarte {annen}"
    reset_rate_limit()
