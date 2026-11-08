"""Angrep 4: last og tjenestenekt.

Svaert store forespoersler, svaert mange kort, lange strenger, dype
JSON-strukturer. Fryser appen, krasjer den, fylles loggen? Runde en testet
bevisst ikke last utover 100 forsoek mot ett kort.

  HOLDER: feltgrensene (max_length) avviser lange strenger med 422, dyp JSON gir
          en pen 400 uten krasj, og appen svarer fortsatt etterpaa.
  HULL: det finnes INGEN grense paa kroppsstoerrelsen og INGEN grense paa antall
          kort. /api/custom er uautentisert, saa enhver lokal prosess kan fylle
          minne og logg.
"""

from __future__ import annotations

import pytest

from attack_lib2 import live_app


# ---------------------------------------------------------------------------
# HOLDER: lange strenger og dyp JSON haandteres uten krasj.
# ---------------------------------------------------------------------------


def test_overlong_field_is_rejected_not_crashing(live_app):
    status, body = live_app.post(
        "/api/custom",
        {"action_type": "send_email", "summary": "x" * 50_000, "recipient": "a@b.no"},
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
    status, _ = live_app.post("/api/custom", raw)
    assert status in (400, 422)  # avvist, ikke krasj
    assert live_app.get("/api/state")[0] == 200  # fortsatt i live


# ---------------------------------------------------------------------------
# HULL: ingen grense paa kroppsstoerrelsen. En stor kropp bufres i sin helhet.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "HULL: /api/custom har ingen grense paa kroppsstoerrelse. CustomIn "
        "ignorerer ukjente felt (ikke extra='forbid'), saa en kropp paa "
        "flere MB med soepel aksepteres med 200 - hele kroppen bufres i minne "
        "foer validering. En angriper kan sende vilkaarlig store kropper mot et "
        "uautentisert endepunkt. Alvor: middels (bare lokalt, 127.0.0.1), men "
        "det er en ekte tjenestenektvei. Fiks: en max-body-size foran appen "
        "(ASGI-middleware eller revers-proxy)."
    ),
)
def test_there_is_a_body_size_limit():
    """Forventningen (som IKKE innfris): en flere-MB kropp skal avvises."""
    # Kjoeres mot TestClient i-prosess for aa slippe aa sende MB over socket.
    import os
    os.environ.setdefault("LONEWATCH_AGENT_KEY", "k")
    from fastapi.testclient import TestClient
    from ui.app import app

    client = TestClient(app)
    big = {
        "action_type": "send_email",
        "summary": "ok",
        "recipient": "a@b.no",
        "junk": "Z" * 3_000_000,  # 3 MB soepel i et ignorert felt
    }
    resp = client.post("/api/custom", json=big)
    assert resp.status_code >= 400, "en 3 MB kropp ble akseptert uten noen stoerrelsesgrense"


# ---------------------------------------------------------------------------
# HULL: ingen grense paa antall kort. Loggen og minnet vokser ubegrenset.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "HULL: det finnes ingen grense paa hvor mange kort /api/custom lager. "
        "Hver innsending lager et kort i minnet og 1-3 krypterte, fsync-ede "
        "logglinjer. 200 innsendinger gir 200 kort og en voksende logg, uten "
        "noen rate- eller volumgrense, mot et uautentisert endepunkt. Alvor: "
        "middels (lokalt). Fiks: en oevre grense paa antall aktive kort og/eller "
        "rate-begrensning."
    ),
)
def test_number_of_cards_is_bounded(live_app):
    for i in range(200):
        live_app.post(
            "/api/custom",
            {"action_type": "send_email", "summary": f"nr {i}", "recipient": "a@b.no"},
        )
    _, snap = live_app.get("/api/state")
    created = len(snap.get("custom", []))
    # Forventningen (som IKKE innfris): et tak skulle hindret ubegrenset vekst.
    assert created < 200, f"appen laget {created} kort uten noen oevre grense"
