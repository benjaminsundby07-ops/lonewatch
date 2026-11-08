"""Angrep 5: de oevrige rutene.

/api/story/*, /api/trail, /api/overview, /api/after, /api/verify, /api/custom,
/api/feed/step, /api/reset. Kan noen av dem endre loggen, avsloere persondata
eller noekler, eller nullstille ekte data uten innlogging? Spesielt /api/reset:
kan den slette den ekte loggen?

  HOLDER: lese-rutene endrer ikke loggen og laekker ingen noekkel. /api/reset
          ARKIVERER (gir ny fil), den SLETTER ikke - den gamle loggen beholdes
          og stien vises i UI.
  LUKKET i runde tre (var A12 / H4 / vault/LIMITS.md punkt 10): /api/reset er
          ikke lenger uautentisert. Alle de skrivende rutene - /api/reset,
          /api/custom, /api/feed/step, /api/story/start, /api/story/step og den
          nye /api/tamper - krever menneskenoekkelen. Agentnoekkelen duger ikke
          paa noen av dem. Testene under maaler at de ER lukket.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from attack_lib2 import refuse_to_touch_real_log  # noqa: F401  (autouse: aldri roer den ekte loggen)

from attack_lib2 import human_headers, live_app


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

    _, snap = live_app.post("/api/reset", headers=human_headers())
    archived = snap["log"]["archived"]
    assert archived, "reset oppga ingen arkivsti"
    # Den gamle loggen finnes fortsatt, under nytt navn, med innhold.
    assert Path(archived).exists()
    assert Path(archived).stat().st_size > 0
    # Den nye loggen starter tom.
    assert snap["log"]["lines"] == 0


# ---------------------------------------------------------------------------
# LUKKET: alle de skrivende rutene krever menneskenoekkelen.
#
# Var A12 i denne filen og H4 i docs/ANGREP.md: /api/reset krevde ingenting.
# Testen under var `xfail(strict=True)` og passerer naa, saa den er en vanlig
# test. Den er samtidig utvidet fra én rute til alle seks, for at det ikke skal
# kunne lukkes for reset og staa aapent for de andre.
# ---------------------------------------------------------------------------

# Rutene som SKRIVER: de endrer loggen, koeen eller begge. /api/tamper skriver
# ikke, men leser og dekrypterer hele loggen med loggnoekkelen.
SKRIVERUTER = [
    ("/api/reset", {}),
    ("/api/feed/step", {}),
    ("/api/story/start", {}),
    ("/api/story/step", {}),
    ("/api/custom", {"action_type": "read_document", "summary": "hei"}),
    ("/api/tamper", {"attack": "endre"}),
]

AGENT_NOEKKEL_HODE = {"X-Lonewatch-Agent-Key": "attack2-agent-key-local-only"}


@pytest.mark.parametrize("path,body", SKRIVERUTER)
def test_writing_routes_refuse_without_the_human_key(live_app, path, body):
    """Uten noekkel: 403. Ingen av dem gjoer noe.

    Dette er det A12 ba om. Ett kall mot /api/reset arkiverte loggen og toemte
    koeen - inkludert et roedt kort som ventet paa et menneske.
    """
    status, _ = live_app.post(path, body)
    assert status == 403, f"uautentisert {path} svarte {status}"


@pytest.mark.parametrize("path,body", SKRIVERUTER)
def test_writing_routes_refuse_the_agent_key(live_app, path, body):
    """Og agentnoekkelen duger ikke.

    Den staar i `.mcp.json`, altsaa i en fil agenten selv leser. Kunne den
    styre demoen, ville agenten kunnet nullstille loggen over seg selv.
    """
    status, _ = live_app.post(path, body, headers=AGENT_NOEKKEL_HODE)
    assert status == 403, f"{path} godtok agentnoekkelen ({status})"


@pytest.mark.parametrize("path,body", SKRIVERUTER)
def test_writing_routes_work_with_the_human_key(live_app, path, body):
    """Og med noekkelen virker de. En laas som laaser alt er ingen laas.

    /api/tamper svarer 409 paa en tom logg (den nekter aa kjoere en demo den
    ikke kan kjoere ærlig), saa den godtas her ogsaa - det vi maaler er at
    noekkelen slapp forbi porten, ikke at loggen var lang nok.
    """
    status, _ = live_app.post(path, body, headers=human_headers())
    assert status in (200, 409), f"{path} med riktig noekkel svarte {status}"


def test_a_red_card_cannot_be_flushed_out_of_the_queue_without_the_key(live_app):
    """Det A12 faktisk handlet om: et roedt kort som venter skal ikke kunne
    spoles bort av noen uten noekkelen."""
    live_app.drain_feed()
    assert live_app.waiting(), "demoen skal ha roede kort som venter"

    status, _ = live_app.post("/api/reset")
    assert status == 403
    assert live_app.waiting(), "koeen ble toemt av et uautentisert kall"
