"""Angrep 5: de oevrige rutene.

/api/story/*, /api/trail, /api/overview, /api/after, /api/verify, /api/custom,
/api/feed/step, /api/reset. Kan noen av dem endre loggen, avsloere persondata
eller noekler, eller nullstille ekte data uten innlogging? Spesielt /api/reset:
kan den slette den ekte loggen?

  HOLDER: lese-rutene endrer ikke loggen og laekker ingen noekkel. /api/reset
          ARKIVERER (gir ny fil), den SLETTER ikke - den gamle loggen beholdes
          og stien vises i UI.
  HULL (dokumentert H4 / LIMITS punkt 10): /api/reset er uautentisert. Hvem som
          helst med tilgang til porten kan "spole historien" og toemme en ventende
          roed koe. Appen binder bare 127.0.0.1, det er hele forsvaret.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from attack_lib2 import refuse_to_touch_real_log  # noqa: F401  (autouse: aldri roer den ekte loggen)

from attack_lib2 import live_app


READONLY_GETS = [
    "/api/state",
    "/api/overview",
    "/api/after",
    "/api/verify",
    "/api/log",
    "/api/custom/help",
    "/api/story",
]


# ---------------------------------------------------------------------------
# HOLDER: lese-rutene roerer ikke loggen.
# ---------------------------------------------------------------------------


def test_readonly_routes_do_not_change_the_log(live_app):
    live_app.drain_feed()
    _, before = live_app.get("/api/state")
    lines_before = before["log"]["lines"]

    for path in READONLY_GETS:
        status, _ = live_app.get(path)
        assert status == 200

    _, after = live_app.get("/api/state")
    assert after["log"]["lines"] == lines_before  # ingen ny linje


def test_no_route_exposes_a_key(live_app):
    live_app.drain_feed()
    blob = ""
    for path in READONLY_GETS:
        _, body = live_app.get(path)
        blob += str(body)
    # Ingen noekkel, ingen noekkelverdi, ingen noekkelnavn med verdi laekker.
    assert "LONEWATCH_LOG_KEY" not in blob
    assert "LONEWATCH_PSEUDONYM_KEY" not in blob
    assert "LONEWATCH_AGENT_KEY" not in blob


# ---------------------------------------------------------------------------
# HOLDER: /api/reset arkiverer, den sletter ikke.
# ---------------------------------------------------------------------------


def test_reset_archives_the_log_it_does_not_delete_it(live_app):
    live_app.drain_feed()
    _, before = live_app.get("/api/state")
    assert before["log"]["lines"] > 0

    _, snap = live_app.post("/api/reset")
    archived = snap["log"]["archived"]
    assert archived, "reset oppga ingen arkivsti"
    # Den gamle loggen finnes fortsatt, under nytt navn, med innhold.
    assert Path(archived).exists()
    assert Path(archived).stat().st_size > 0
    # Den nye loggen starter tom.
    assert snap["log"]["lines"] == 0


# ---------------------------------------------------------------------------
# HULL (dokumentert): /api/reset er uautentisert.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "HULL (docs/ANGREP.md H4, vault/LIMITS.md punkt 10): POST /api/reset "
        "krever ingen innlogging, ingen token og ingen noekkel. Ett kall "
        "arkiverer loggen, toemmer koen og starter en ny, tom kjede - inkludert "
        "et roedt kort som ventet paa et menneske. Til forskjell fra "
        "/api/agent/* (som krever LONEWATCH_AGENT_KEY) staar reset helt aapen. "
        "Eneste forsvar: appen binder 127.0.0.1. Alvor: middels. Reset SLETTER "
        "riktignok ikke (den arkiverer), saa ingenting forsvinner i det skjulte "
        "- men en uautentisert 'start ny logg'-knapp er et problem i seg selv. "
        "Fiks: innlogging foran alt som skriver eller nullstiller."
    ),
)
def test_reset_requires_authentication(live_app):
    """Forventningen (som IKKE innfris): reset uten noekkel skal avvises."""
    status, _ = live_app.post("/api/reset")
    assert status in (401, 403, 503), f"uautentisert /api/reset svarte {status}"
