"""Designrunden: det som maa vaere sant uansett hvordan stilen ser ut.

Testene her spoer ikke om noe er pent. De spoer om de reglene vi har satt oss
faktisk holder i koden:

* roedt brukes bare der det skal
* ingenting beveger seg for den som har bedt om mindre bevegelse
* presentasjonsmodus skjuler, den endrer ikke tall
* tomtilstander sier hva som skjer, ikke bare at det er tomt
* bjella teller det samme som koeen
* ingenting hentes fra nettet
"""

from __future__ import annotations

import pathlib
import re

import pytest

from ui.state import STATUS_WAITING, DemoState

UI = pathlib.Path(__file__).resolve().parents[1] / "ui"
APP_JS = (UI / "static/app.js").read_text(encoding="utf-8")
CSS = (UI / "static/style.css").read_text(encoding="utf-8")
HTML = (UI / "static/index.html").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# knappefarger
# ---------------------------------------------------------------------------


def test_red_is_only_used_to_stop_or_to_approve_a_red_case():
    """Roedt skal bare baere to ting: aa stoppe, og aa godkjenne en roed sak.

    Blir rødt brukt til navigasjon eller til et skjema, slutter det å bety
    noe - og da ser man det ikke når det faktisk gjelder.
    """
    for linje in APP_JS.splitlines():
        if "lw-btn-danger" not in linje:
            continue
        assert ("data-approve" in linje or "data-reject" in linje), (
            "rød knapp uten avvis/godkjenn: " + linje.strip()
        )


def test_the_alert_card_button_only_navigates_and_is_not_red():
    """«Se og godkjenn» tar deg til køen. Den avgjør ingenting."""
    kort = APP_JS.split("function venterKort(", 1)[1].split("\nfunction ", 1)[0]
    cta = kort.split("app-waiting-cta", 1)[0]
    assert "lw-btn-primary" in cta
    assert "lw-btn-danger" not in cta


def test_reject_is_present_but_does_not_outshout_approve():
    """Avvis er den TRYGGE handlingen og skal ikke konkurrere om blikket."""
    assert "lw-btn-danger-quiet" in APP_JS
    assert ".lw-btn-danger-quiet" in CSS
    stil = CSS.split(".lw-btn-danger-quiet {", 1)[1].split("}", 1)[0]
    assert "background: transparent" in stil


# ---------------------------------------------------------------------------
# bevegelse
# ---------------------------------------------------------------------------


def test_everything_that_moves_asks_the_operating_system_first():
    assert "prefers-reduced-motion" in APP_JS
    assert "prefers-reduced-motion: reduce" in CSS


def test_reduced_motion_turns_the_pulse_off_completely():
    """Ikke en kortere animasjon - ingen."""
    blokk = CSS.split("@media (prefers-reduced-motion: reduce) {", 1)[1]
    blokk = blokk[: blokk.index("\n}")]
    assert "animation: none" in blokk
    assert "app-waiting" in blokk


def test_a_number_that_cannot_be_counted_shows_a_dash_not_a_zero():
    """«–» og «0» er to forskjellige opplysninger."""
    tell = APP_JS.split("function tellOpp(", 1)[1].split("\n}", 1)[0]
    assert 'node.textContent = "–"' in tell


def test_counting_starts_from_the_previous_value():
    """39 -> 40 skal flytte seg ett hakk, ikke rulle hele skalaen hvert sekund."""
    tell = APP_JS.split("function tellOpp(", 1)[1]
    tell = tell[: tell.index("\nfunction ")]
    assert "tellTilstand.get(node)" in tell
    assert "if (fra === til) return;" in tell


# ---------------------------------------------------------------------------
# bjella
# ---------------------------------------------------------------------------


def test_the_bell_exists_and_is_reachable_without_a_mouse():
    assert 'id="btn-bell"' in HTML
    assert "aria-label" in HTML.split('id="btn-bell"', 1)[1][:200]


def test_the_bell_counts_the_same_queue_as_the_menu():
    bjelle = APP_JS.split("function syncBell(", 1)[1].split("\n}", 1)[0]
    assert "latest.waiting.length" in bjelle
    # Null er ingen beskjed: merket skjules i stedet for aa vise "0".
    assert 'classList.toggle("hidden", n === 0)' in bjelle


def test_the_bell_label_says_what_it_means_when_nothing_waits():
    bjelle = APP_JS.split("function syncBell(", 1)[1].split("\n}", 1)[0]
    assert "Ingenting venter" in bjelle


# ---------------------------------------------------------------------------
# presentasjonsmodus
# ---------------------------------------------------------------------------


def test_presentation_mode_only_hides_and_resizes():
    """Den skal ikke kunne endre et eneste tall.

    Alt modusen gjør står under `.is-present` i CSS. Finner vi noe annet enn
    størrelse, farge og `display` der, gjør den mer enn den har lov til.
    """
    regler = re.findall(r"\.is-present[^{]*\{([^}]*)\}", CSS)
    assert regler, "presentasjonsmodus mangler"
    tillatt = {"font-size", "line-height", "display", "color", "box-shadow",
               "letter-spacing", "font-weight", "padding", "gap"}
    for blokk in regler:
        for dek in blokk.split(";"):
            if not dek.strip():
                continue
            navn = dek.split(":", 1)[0].strip()
            assert navn in tillatt, f"presentasjonsmodus endrer {navn}"


def test_presentation_mode_hides_the_noise_but_not_the_decision():
    skjult = " ".join(re.findall(r"(\.is-present[^{]*)\{[^}]*display: none", CSS))
    for stoey in ("app-footer", "app-limits", "app-raw", "app-json"):
        assert stoey in skjult, stoey
    # Det som avgjoer en sak skal ALDRI vaere skjult.
    for kjerne in ("app-gate", "data-approve", "app-rules", "app-waiting-cta",
                   "lw-stat-value", "app-pill"):
        assert kjerne not in skjult, kjerne


def test_presentation_mode_can_be_turned_off_again():
    assert 'aria-pressed="false"' in HTML
    bytt = APP_JS.split("el(\"btn-present\").addEventListener", 1)[1][:300]
    assert 'aria-pressed") !== "true"' in bytt


def test_losing_localstorage_does_not_break_the_mode():
    """Privat vindu kaster paa localStorage. Modusen skal virke likevel."""
    sett = APP_JS.split("function settPresentasjon(", 1)[1].split("\n}", 1)[0]
    assert "try {" in sett and "catch" in sett


# ---------------------------------------------------------------------------
# tomtilstander
# ---------------------------------------------------------------------------


def test_every_empty_state_says_what_is_happening_and_what_to_do():
    """En tom liste skal forklare seg, ikke bare konstatere at den er tom."""
    assert "function tomtFelt(" in APP_JS
    kall = re.findall(r"tomtFelt\(\s*\"([^\"]+)\",\s*\n?\s*\"", APP_JS)
    assert len(kall) >= 6, kall
    # Ingen av dem skal vaere en ren konstatering uten forklaring.
    for blokk in re.findall(r"tomtFelt\((.*?)\);", APP_JS, re.S):
        tekster = re.findall(r'"([^"]{10,})"', blokk)
        assert len(tekster) >= 2, blokk[:80]


def test_the_empty_agent_table_tells_you_how_to_get_data():
    tabell = APP_JS.split("function agentTabell(", 1)[1].split("\n}", 1)[0]
    assert "app-empty-state" in tabell
    assert "Spill av hendelsen" in tabell


# ---------------------------------------------------------------------------
# piller og prikker
# ---------------------------------------------------------------------------


def test_zero_is_a_dash_not_an_empty_pill():
    """En tom pille ville trukket blikket mot det som IKKE skjedde."""
    tabell = APP_JS.split("const pille = ", 1)[1].split("};", 1)[0]
    assert "verdi === 0" in tabell
    assert "app-muted" in tabell


def test_the_three_outcomes_have_three_different_pills():
    for slag in ("is-red", "is-blocked", "is-allow"):
        assert f".app-pill.{slag}" in CSS, slag
    farger = re.findall(r"\.app-pill\.is-\w+ \{[^}]*color: ([^;]+);", CSS)
    assert len(set(farger)) == 3, farger


def test_the_status_dot_follows_the_real_queue(monkeypatch):
    """Prikken skal komme fra kortene, ikke fra en egen teller som kan ryke."""
    tabell = APP_JS.split("function agentTabell(", 1)[1].split("\n}\n", 1)[0]
    assert "latest.waiting" in tabell
    assert "app-status-dot" in tabell


# ---------------------------------------------------------------------------
# dataene bak kortet
# ---------------------------------------------------------------------------


@pytest.fixture()
def kjort() -> DemoState:
    state = DemoState()
    while state.step_feed() is not None:
        pass
    return state


def test_the_alert_card_carries_the_real_rules(kjort):
    w = kjort.waiting_for_you()
    card = kjort.cards[w["request_id"]]
    assert w["reasons"] == list(card["decision"]["reasons"])
    assert w["reasons"], "en rød sak har alltid minst én regel"


def test_the_rules_on_the_card_have_norwegian_text():
    """Regelnavnene er kode. Kortet skal vise setningen, ikke koden."""
    tekst = APP_JS.split("const RULE_TEXT = {", 1)[1].split("\n};", 1)[0]
    kort = APP_JS.split("function venterKort(", 1)[1].split("\nfunction ", 1)[0]
    assert "RULE_TEXT[r]" in kort
    for navn in ("amount_over_limit", "unknown_recipient", "personal_data_external"):
        assert navn in tekst, navn


def test_an_empty_queue_has_no_rules_to_show():
    assert DemoState().waiting_for_you() is None


# ---------------------------------------------------------------------------
# offline
# ---------------------------------------------------------------------------


def test_nothing_is_fetched_from_the_internet():
    for fil in (APP_JS, CSS, HTML):
        treff = re.findall(r"https?://(?!127\.0\.0\.1|localhost)[^\s\"')]+", fil)
        assert not treff, treff
