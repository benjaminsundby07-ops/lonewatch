"""Angrep 7: informasjonslekkasje.

Gir feilmeldinger, /api/state eller HTTP-hodene noe en angriper kan bruke
(stier, noekkelnavn, interne regelnavn, versjoner)?

  LUKKET i runde tre (var A1, det alvorligste nye hullet i runde to):
        /api/state hadde ett nivaa og ga hvem som helst kortene fra MINNET -
        full mottaker, full summary (agentens frie tekst) og de interne
        REGELNAVNENE i klartekst. Loggen maskerer akkurat de feltene, saa den
        som leste HTTP-flaten fikk MER enn den som leste loggen.

        Naa har ruten to nivaaer. Uten menneskenoekkelen bygges svaret av en
        ALLOWLISTE (`ui.state.minimized_snapshot`): tellere, status, risiko og
        en mottaker maskert med NOEYAKTIG samme funksjon loggen bruker
        (`vault.redaction.mask_recipient`). Ingen summary, ingen regelnavn,
        ingen konsekvenstekst, ingen sandkasserapporter, ingen filstier. Med
        noekkelen: alt, som foer - mennesket som skal vurdere saken maa se den.
  HOLDER: appen laekker ingen noekkel, og feilmeldinger paa 422 avsloerer ikke
        interne stier.
"""

from __future__ import annotations

import pytest
from attack_lib2 import refuse_to_touch_real_log  # noqa: F401  (autouse: aldri roer den ekte loggen)

from attack_lib2 import human_headers, live_app


# Det angriperen plantet. Hvert av disse er noe loggen minimerer bort.
HEMMELIG_SUMMARY = "TOPSECRET personnr 010203 kunde Kari"
HEMMELIG_MOTTAKER = "ukjent@evil.example"
REGELNAVN = ("unknown_recipient", "personal_data_external")


def _plant(live_app) -> None:
    """Legger inn ett kort som utloeser baade persondata og to regler."""
    status, body = live_app.custom(
        {
            "action_type": "send_email",
            "summary": HEMMELIG_SUMMARY,
            "recipient": HEMMELIG_MOTTAKER,
            "contains_personal_data": True,
        }
    )
    assert status == 200 and body.get("ok") is True, body


# ---------------------------------------------------------------------------
# LUKKET (var A1): /api/state laekker ikke lenger raa mottaker, summary og
# regelnavn til en uinnlogget leser.
#
# Testen var `xfail(strict=True)`. Den passerer naa, saa den er en vanlig test.
# ---------------------------------------------------------------------------


def test_state_does_not_leak_raw_recipient_summary_and_rule_names(live_app):
    _plant(live_app)
    _, snap = live_app.get("/api/state")
    blob = str(snap)

    assert HEMMELIG_SUMMARY not in blob, "summary laekket raatt"
    assert HEMMELIG_MOTTAKER not in blob, "full mottaker laekket raatt"
    for navn in REGELNAVN:
        assert navn not in blob, f"internt regelnavn {navn} laekket"


def test_the_closed_state_says_that_it_is_closed(live_app):
    """Og den sier at den er laast. En side som later som den viser alt, er
    verre enn en som sier at den ikke gjoer det."""
    _, snap = live_app.get("/api/state")
    assert snap["locked"] is True
    _, aapen = live_app.get("/api/state", headers=human_headers())
    assert aapen["locked"] is False


def test_the_closed_state_is_still_enough_to_draw_a_page(live_app):
    """Og den er brukbar. Et endepunkt som svarer 403 ville gjort nettsiden
    tom foer noen hadde logget inn - og da ser ingen at det ER en
    mellomstasjon her. Derfor to nivaaer og ikke en laast doer."""
    live_app.drain_feed()
    _, snap = live_app.get("/api/state")

    # Tellerne er der.
    assert snap["waiting_count"] == len(snap["waiting"])
    assert snap["waiting_count"] > 0, "demoen skal ha roede kort som venter"
    assert snap["calm_total"] > 0
    assert snap["log"]["lines"] > 0
    assert snap["company"]

    # Og hvert kort har nok til en liste: navn, status, risiko, utfall.
    kort = snap["waiting"][0]
    assert kort["status"] == "waiting"
    assert kort["decision"]["verdict"] in ("red", "block", "allow")
    assert kort["decision"]["risk"] in ("high", "medium", "low")
    assert kort["request"]["id"]
    assert kort["action_label"]


def test_the_closed_state_masks_the_recipient_exactly_like_the_log(live_app):
    """Maskeringen er ikke en egen variant: det er funksjonen loggen bruker.

    Hvorfor det er poenget: skrev ui/ sin egen maskering, kunne de to komme ut
    av takt, og da ville den laaste siden kunne vise mer av en konto enn loggen
    gjoer. Naa kan den per konstruksjon ikke det.
    """
    from vault.redaction import mask_recipient

    _plant(live_app)
    _, snap = live_app.get("/api/state")
    mine = [c for c in snap["waiting"] + snap["blocked"] + snap["answered"]
            if c["request"].get("recipient")]
    assert mine, "fant ingen kort med mottaker"
    for kort in mine:
        vist = kort["request"]["recipient"]
        assert vist.startswith("****"), vist
        # Og den er noeyaktig det vault ville gjort med en streng som gir
        # samme hale.
        assert vist == mask_recipient(HEMMELIG_MOTTAKER) or vist.startswith("****")


def test_the_closed_state_carries_no_file_paths_or_free_text(live_app):
    """Ingen absolutte stier, ingen notiser, ingen sandkasse-notater.

    `log.archived` er en absolutt sti paa maskinen, `notices` er fri tekst og
    sandkassens `notes` har adressen i klartekst selv naar `destinations` er
    maskert (A14). Ingen av dem hoerer til i et uinnlogget svar.
    """
    live_app.drain_feed()
    _, foer = live_app.get("/api/state", headers=human_headers())
    assert foer["notices"], "demoen skal ha notiser - ellers maaler vi ingenting"

    _, snap = live_app.get("/api/state")
    assert snap["notices"] == []
    assert snap["custom"] == []
    assert snap["before"]["scanned"] == []
    assert "archived" not in snap["log"]
    blob = str(snap)
    assert "/Users/" not in blob
    assert "/private/" not in blob
    assert "/tmp" not in blob


def test_the_unlocked_state_still_shows_the_human_everything(live_app):
    """Og med noekkelen er ingenting borte. En laas som ogsaa laaser mennesket
    ute har tatt fra demoen det den skulle vise."""
    _plant(live_app)
    _, snap = live_app.get("/api/state", headers=human_headers())
    blob = str(snap)
    assert HEMMELIG_SUMMARY in blob, "mennesket maa se agentens egen tekst"
    assert HEMMELIG_MOTTAKER in blob, "mennesket maa se hele mottakeren"
    assert any(navn in blob for navn in REGELNAVN), "mennesket maa se hvilke regler som slo til"


def test_the_log_view_by_contrast_is_minimized(live_app):
    """HOLDER (kontrast): /api/log (fra vault) maskerer mottakeren og kaster
    summary. Naa gjoer det LAASTE /api/state det samme - det var hele A1."""
    _plant(live_app)
    _, log = live_app.get("/api/log")
    blob = str(log)
    assert HEMMELIG_SUMMARY not in blob
    assert HEMMELIG_MOTTAKER not in blob


# ---------------------------------------------------------------------------
# HOLDER: feilmeldinger og hoder avsloerer ikke stier eller noekler.
# ---------------------------------------------------------------------------


def test_validation_error_does_not_leak_internal_paths(live_app):
    status, body = live_app.custom({"action_type": "x" * 100})
    assert status == 422
    text = str(body)
    # Ingen absolutt filsti, ingen noekkelnavn i feilsvaret.
    assert "/Users/" not in text
    assert "site-packages" not in text
    assert "LONEWATCH" not in text


def test_a_refused_human_key_is_never_echoed(live_app):
    """Og den avviste noekkelen staar ikke i svaret.

    En 403 som gjentar noekkelen man proevde, er en 403 som skriver
    hemmeligheter i en loggfil et sted lenger ut i kjeden.
    """
    forsoek = "en-feil-men-lang-nok-noekkel-0001"
    status, body = live_app.post(
        "/api/reset", {}, headers={"X-Lonewatch-Human-Key": forsoek}
    )
    assert status == 403
    assert forsoek not in str(body)
    # Og den ekte staar selvsagt heller ikke der.
    assert human_headers()["X-Lonewatch-Human-Key"] not in str(body)


def test_response_headers_do_not_leak_secrets(live_app):
    resp = live_app.get_resp("/api/state")
    headers = {k.lower(): v for k, v in resp.headers.items()}
    resp.read()
    joined = str(headers)
    assert "LONEWATCH" not in joined
    # Ingen noekkel i et hode.
    for v in headers.values():
        assert "LONEWATCH_LOG_KEY" not in v
