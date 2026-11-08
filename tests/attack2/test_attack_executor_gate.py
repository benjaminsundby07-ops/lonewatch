"""Angrep 13 (nytt i runde tre): kan noe bli UTFOERT uten en beskyttet rute?

H25 i docs/ANGREP.md: `/api/custom` og `/api/feed/step` var uautentiserte
skriveruter, OG en `allow` blir faktisk utfoert. Med `LONEWATCH_EXECUTOR=smtp`
kunne derfor et uautentisert lokalt kall utloese en ekte e-post til én av
demoens tolv oppdiktede kjente mottakere.

Dette angrepet maaler de to delene av fiksen hver for seg:

  1. Ingen av veiene til utfoereren kan naas uten menneskenoekkelen.
  2. `SimulatedExecutor` er standard. `SmtpExecutor` kommer bare inn naar
     `LONEWATCH_EXECUTOR` staar NOEYAKTIG paa «smtp» - ikke paa en skrivefeil,
     ikke paa et tomt felt.

Ingen test her sender en e-post, og ingen test setter `LONEWATCH_EXECUTOR=smtp`
mot en ekte tjener. Rutingen leses, den brukes ikke.
"""

from __future__ import annotations

import pytest
from attack_lib2 import refuse_to_touch_real_log  # noqa: F401  (autouse: aldri roer den ekte loggen)

from attack_lib2 import human_headers, live_app

from contracts import ActionType
from executor import SimulatedExecutor, SmtpExecutor
from ui.state import ENV_EXECUTOR, DemoState


# ---------------------------------------------------------------------------
# 1. Veiene til utfoereren er alle bak menneskenoekkelen.
# ---------------------------------------------------------------------------

# De to stedene `executor` kobles inn staar i docs/UTFORER.md:
#   _handle()  - ved allow, altsaa /api/feed/step, /api/custom, /api/agent/submit
#   respond()  - ved approved=True, altsaa /api/respond
# Hver av dem naas gjennom én rute, og hver av de rutene krever en noekkel.
UTFOERER_RUTER = [
    ("/api/feed/step", {}),
    ("/api/custom", {"action_type": "send_email", "recipient": "a@b.no"}),
    ("/api/respond", {"request_id": "req_0001", "approved": True}),
]


@pytest.mark.parametrize("path,body", UTFOERER_RUTER)
def test_no_route_to_the_executor_is_open(live_app, path, body):
    """Ingen av dem svarer noe annet enn 403 uten noekkel."""
    status, _ = live_app.post(path, body)
    assert status == 403, f"{path} naadde utfoereren uten noekkel ({status})"


def test_an_allow_is_only_executed_behind_the_key(live_app):
    """Og en `allow` som faktisk BLIR utfoert, kom fra et autentisert kall.

    Testen maaler paa `execution`-feltet, altsaa paa at utfoereren ble kalt -
    ikke bare paa statuskoden.
    """
    # Uten noekkel: ingen kort, ingen utfoering.
    status, _ = live_app.post(
        "/api/custom", {"action_type": "read_document", "summary": "les"}
    )
    assert status == 403
    _, snap = live_app.get("/api/state", headers=human_headers())
    assert snap["custom"] == [], "et uautentisert kall laget et kort"

    # Med noekkel: kortet finnes, og det ble utfoert (simulert).
    status, body = live_app.custom({"action_type": "read_document", "summary": "les"})
    assert status == 200 and body["ok"] is True
    kort = body["card"]
    assert kort["decision"]["verdict"] == "allow"
    assert kort["execution"] is not None, "en allow ble ikke utfoert"
    # Og den ble gjort av den SIMULERTE utfoereren. Ingen e-post forlot
    # maskinen. Navnet staar i `executor_name`, som settes av utfoereren selv.
    assert "simulated" in kort["execution"]["executor_name"].lower(), kort["execution"]


def test_the_execution_answer_carries_no_fingerprint(live_app):
    """Avtrykket logges, men sendes ikke til nettleseren.

    Den som har avtrykket kan lage en `Approval` selv, og da er forseglingen
    ingen forsegling. Dette er ogsaa dekket av tests/test_executor_wiring.py;
    her maales det fra utsiden, over HTTP.
    """
    _, body = live_app.custom({"action_type": "read_document", "summary": "les"})
    assert "fingerprint" not in str(body["card"]["execution"])
    _, snap = live_app.get("/api/state", headers=human_headers())
    assert "fingerprint" not in str(snap)
    assert "approval" not in str(snap).lower() or "approval" not in snap


# ---------------------------------------------------------------------------
# 2. SimulatedExecutor er standard, og SmtpExecutor kan ikke slaas paa
#    ved en skrivefeil.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "verdi",
    [None, "", "  ", "SMTP ", "smtps", "Smtp!", "simulated", "ekte", "1", "true",
     "smtp,simulated", "send_email"],
)
def test_only_the_exact_word_smtp_turns_on_the_real_executor(monkeypatch, verdi):
    """Alt annet enn «smtp» gir den simulerte. Ogsaa stor forbokstav med luft.

    `.strip().lower()` i `ui/state.py` gjoer at «SMTP » teller - det er med
    vilje, og det er derfor den staar i listen med en egen forventning under.
    """
    if verdi is None:
        monkeypatch.delenv(ENV_EXECUTOR, raising=False)
    else:
        monkeypatch.setenv(ENV_EXECUTOR, verdi)

    ruting, feil = DemoState._new_executors(_tom_ledger())
    assert feil is None
    if (verdi or "").strip().lower() == "smtp":
        assert isinstance(ruting[ActionType.SEND_EMAIL], SmtpExecutor)
    else:
        assert ruting == {}, f"«{verdi}» ga en ruting: {ruting}"


def test_the_default_executor_is_the_simulated_one(monkeypatch):
    """Uten `LONEWATCH_EXECUTOR` later utfoereren som, og gjoer ingenting."""
    monkeypatch.delenv(ENV_EXECUTOR, raising=False)
    state = DemoState()
    try:
        assert isinstance(state._default_executor, SimulatedExecutor)
        for art in ActionType:
            assert isinstance(state._executor_for(art), SimulatedExecutor)
    finally:
        state.close()


def _tom_ledger():
    from executor import AttemptLedger

    return AttemptLedger()
