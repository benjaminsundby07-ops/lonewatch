"""Angrep 7: informasjonslekkasje.

Gir feilmeldinger, /api/state eller HTTP-hodene noe en angriper kan bruke
(stier, noekkelnavn, interne regelnavn, versjoner)?

  HULL (nytt, staar ikke i runde en): /api/state er uautentisert og returnerer
        kortene fra MINNET - ikke den minimerte loggen. Full mottaker, full
        summary (agentens frie tekst) og de interne REGELNAVNENE staar der i
        klartekst. Loggen maskerer akkurat det samme feltet. En angriper som
        leser /api/state ser altsaa mer enn den som leser loggen.
  HOLDER: appen laekker ingen noekkel, og feilmeldinger paa 422 avsloerer ikke
        interne stier.
"""

from __future__ import annotations

import pytest

from attack_lib2 import live_app


# ---------------------------------------------------------------------------
# HULL (nytt): /api/state laekker full mottaker + summary + regelnavn.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "HULL (nytt): /api/state er uautentisert og viser kortene fra minnet, "
        "IKKE den minimerte loggen. Full mottaker ('ukjent@evil.example'), full "
        "summary (agentens frie tekst, som kan inneholde persondata fra et "
        "dokument) og de interne regelnavnene (decision.reasons: "
        "'unknown_recipient', 'personal_data_external') staar i klartekst. "
        "Loggen (/api/log) maskerer mottakeren og kaster summary - men /api/state "
        "gjoer ingen av delene. En angriper paa porten faar baade persondata og "
        "en oppskrift paa hvilke regler som slo til. Alvor: hoey. Fiks: "
        "autentiser /api/state, eller send ut det samme minimerte synet som "
        "loggen (agenten faar alt regelnavnene fjernet - mennesket boer ikke faa "
        "persondata ufiltrert over et aapent endepunkt)."
    ),
)
def test_state_does_not_leak_raw_recipient_summary_and_rule_names(live_app):
    live_app.post(
        "/api/custom",
        {
            "action_type": "send_email",
            "summary": "TOPSECRET personnr 010203 kunde Kari",
            "recipient": "ukjent@evil.example",
            "contains_personal_data": True,
        },
    )
    _, snap = live_app.get("/api/state")
    blob = str(snap)
    # Forventningen (som IKKE innfris): disse skal IKKE ligge i klartekst i /api/state.
    assert "TOPSECRET personnr 010203 kunde Kari" not in blob, "summary laekket raatt"
    assert "ukjent@evil.example" not in blob, "full mottaker laekket raatt"
    assert "unknown_recipient" not in blob and "personal_data_external" not in blob, (
        "interne regelnavn laekket"
    )


def test_the_log_view_by_contrast_is_minimized(live_app):
    """HOLDER (kontrast): /api/log (fra vault) maskerer mottakeren og kaster
    summary - det er DEN som er minimert, og nettopp derfor stikker /api/state ut."""
    live_app.post(
        "/api/custom",
        {"action_type": "send_email", "summary": "TOPSECRET", "recipient": "ukjent@evil.example"},
    )
    _, log = live_app.get("/api/log")
    blob = str(log)
    assert "TOPSECRET" not in blob
    assert "ukjent@evil.example" not in blob


# ---------------------------------------------------------------------------
# HOLDER: feilmeldinger og hoder avsloerer ikke stier eller noekler.
# ---------------------------------------------------------------------------


def test_validation_error_does_not_leak_internal_paths(live_app):
    status, body = live_app.post("/api/custom", {"action_type": "x" * 100})
    assert status == 422
    text = str(body)
    # Ingen absolutt filsti, ingen noekkelnavn i feilsvaret.
    assert "/Users/" not in text
    assert "site-packages" not in text
    assert "LONEWATCH" not in text


def test_response_headers_do_not_leak_secrets(live_app):
    resp = live_app.get_resp("/api/state")
    headers = {k.lower(): v for k, v in resp.headers.items()}
    resp.read()
    joined = str(headers)
    assert "LONEWATCH" not in joined
    # Ingen noekkel i et hode.
    for v in headers.values():
        assert "LONEWATCH_LOG_KEY" not in v
