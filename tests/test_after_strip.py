"""Etter-fanen: striper over loggen, og tidskolonnen i Hendelser.

To ting ble funnet i kontroll av commit ecb7026, og begge handler om det samme:
tall og tekst paa skjermen kom fra to forskjellige oejeblikk.

1. **Striper.** «Kjeden er hel / Loggen er tom.» stod ved siden av «Siste blokk
   #31». Teksten var fra sjekken som ble kjoert rett etter en nullstilling, da
   loggen faktisk var tom. Tallet var fra naa. Ingen av dem var feil for seg -
   sammen var de en loegn.

2. **Tidskolonnen.** Demoen har to klokker: demodataene i `agents/` har faste,
   oppdiktede tidspunkter, mens sandkassen og «Proev selv» stempler med
   maskinens ekte klokke. Blandet i samme kolonne uten merking ser radene ut
   til aa komme i feil rekkefoelge.
"""

from __future__ import annotations

import pathlib

import pytest

from ui.state import TID_SANNTID, TID_SIMULERT, DemoState

UI = pathlib.Path(__file__).resolve().parents[1] / "ui"


@pytest.fixture()
def state() -> DemoState:
    return DemoState()


def _play_story(state: DemoState) -> None:
    state.story_start()
    while not state.story_step()["done"]:
        pass


# ---------------------------------------------------------------------------
# 1. Striper: sjekken skal gjelde loggen slik den er NAA
# ---------------------------------------------------------------------------


def test_a_verify_from_before_the_story_is_marked_stale(state):
    """Nøyaktig feilen: «Loggen er tom.» ved siden av et blokknummer.

    Rekkefølgen er den brukeren faktisk gikk gjennom: nullstill, sjekk loggen
    (den er tom), spill av hendelsen, åpne Etter.
    """
    state.reset()
    tom = state.verify()
    assert tom["lines"] == 0
    assert tom["reason"] == "ok_empty"
    assert "tom" in tom["text"]

    _play_story(state)

    log = state.snapshot()["log"]
    assert log["lines"] > 0, "hendelsen skal ha lagt linjer i loggen"
    # Svaret fra før er fortsatt husket - det er det «Sist sjekket» viser.
    assert log["last_verify"]["lines"] == 0
    # ... men det gjelder ikke denne loggen lenger, og det skal UI vite.
    assert log["verify_stale"] is True


def test_a_fresh_verify_makes_the_text_and_the_number_agree(state):
    """Etter en fersk sjekk skal teksten og blokknummeret komme fra samme logg."""
    state.reset()
    state.verify()
    _play_story(state)

    fersk = state.verify()
    log = state.snapshot()["log"]

    assert log["verify_stale"] is False
    assert fersk["lines"] == log["lines"]
    assert fersk["reason"] == "ok"
    assert "tom" not in fersk["text"]


def test_the_log_is_never_called_empty_while_it_has_lines(state):
    """Invarianten bak hele rettingen, sjekket gjennom hele demoen.

    Et svar som sier «tom» skal aldri staa som gyldig naar loggen har linjer.
    Enten er svaret ferskt og stemmer, eller saa er det merket utdatert.
    """
    state.reset()
    state.verify()

    _play_story(state)
    while state.step_feed() is not None:
        log = state.snapshot()["log"]
        v = log["last_verify"]
        if v is not None and not log["verify_stale"]:
            assert v["lines"] == log["lines"]
            assert (v["reason"] == "ok_empty") == (log["lines"] == 0)
        if log["lines"] % 7 == 0:
            state.verify()  # av og til trykker noen «Sjekk loggen»

    state.verify()
    log = state.snapshot()["log"]
    assert log["verify_stale"] is False
    assert log["last_verify"]["reason"] == "ok"


def test_an_unverified_log_has_no_stale_flag_to_show(state):
    """Har ingen sjekket ennaa, er det ingenting som er utdatert heller."""
    log = state.snapshot()["log"]
    assert log["last_verify"] is None
    assert log["verify_stale"] is False


def test_the_page_asks_for_a_fresh_check_instead_of_repeating_an_old_one():
    """UI-siden av det samme: Etter henter en fersk sjekk, og stoler paa flagget."""
    app_js = (UI / "static/app.js").read_text(encoding="utf-8")

    # Etter aapnes -> fersk /api/verify foer striper tegnes.
    etter = app_js.split("async function loadAfter() {", 1)
    assert len(etter) == 2, "loadAfter() tegner Etter"
    kropp = etter[1].split("\n}", 1)[0]
    assert kropp.index("verifyQuietly()") < kropp.index("renderChainStrip()")

    # Hendelsen ferdig spilt -> sjekken kjoeres paa nytt.
    ferdig = app_js.split("async function storyFerdig() {", 1)
    assert len(ferdig) == 2, "storyFerdig() kjoeres naar hendelsen er ferdig"
    assert "verifyQuietly()" in ferdig[1].split("\n}", 1)[0]
    assert app_js.count("await storyFerdig();") == 2, "baade avspilling og «Neste steg»"

    # Striper viser aldri et utdatert svar som om det gjaldt loggen naa.
    strip = app_js.split("function renderChainStrip() {", 1)[1].split("\n}", 1)[0]
    assert "log.verify_stale" in strip
    assert "if (!v || utdatert)" in strip
    # Blokknummeret kommer fra sjekken, ikke fra oejeblikksbildet.
    assert "v.lines" in strip

    # Vokser loggen mens Etter staar aapen, hentes striper OG tabell paa nytt.
    assert "if (activeTab === \"after\") oppdaterEtter();" in app_js
    oppdater = app_js.split("async function oppdaterEtter() {", 1)
    assert len(oppdater) == 2, "oppdaterEtter() holder Etter i takt med loggen"
    kropp = oppdater[1].split("\n}", 1)[0]
    assert "latest.log.verify_stale" in kropp
    assert kropp.index("verifyQuietly()") < kropp.index("hentLogg()")


# ---------------------------------------------------------------------------
# 2. Tidskolonnen: hvilken klokke kommer tallet fra?
# ---------------------------------------------------------------------------


def test_every_log_row_says_which_clock_its_time_came_from(state):
    while state.step_feed() is not None:
        pass
    rows = state.log_rows()["rows"]
    assert rows
    for r in rows:
        assert r["tidsbase"] in (TID_SIMULERT, TID_SANNTID), r


def test_demo_rows_are_simulated_and_the_sandbox_runs_on_the_real_clock(state):
    _play_story(state)
    while state.step_feed() is not None:
        pass
    rows = state.log_rows()["rows"]

    sandkasse = [r for r in rows if r["kall"] == "sandkasse"]
    assert sandkasse, "demoen kjoerer minst ett tillegg i sandkassen"
    for r in sandkasse:
        # sandbox/report.py stempler med datetime.now(). Den tiden er ekte.
        assert r["tidsbase"] == TID_SANNTID

    feller = [r for r in rows if r["kall"] == "felle"]
    assert feller
    for r in feller:
        assert r["tidsbase"] == TID_SIMULERT

    demo = [r for r in rows if r["request_id"] and not r["request_id"].startswith("custom_")]
    assert demo
    for r in demo:
        assert r["tidsbase"] == TID_SIMULERT


def test_a_request_the_jury_writes_is_stamped_with_the_real_clock(state):
    ut = state.submit_custom(
        action_type="transfer_money",
        summary="juryens egen",
        amount="4 000",
        recipient="NO93 8601 1117 947",
    )
    assert ut["ok"] is True
    rid = ut["card"]["request"]["id"]

    rad = next(r for r in state.log_rows()["rows"] if r["request_id"] == rid)
    assert rad["tidsbase"] == TID_SANNTID


def test_the_table_says_which_clocks_are_actually_in_it(state):
    """Staar det bare én klokke i tabellen, skal ikke UI forklare at det er to."""
    assert state.log_rows()["tidsbaser"] == []

    _play_story(state)
    while state.step_feed() is not None:
        pass
    assert state.log_rows()["tidsbaser"] == [TID_SANNTID, TID_SIMULERT]


def test_the_rows_stay_in_the_order_the_log_has_them(state):
    """Merkingen forklarer spranget i tidskolonnen. Rekkefoelgen er loggens egen.

    Tidene hopper (to klokker), men blokknumrene skal gaa jevnt nedover: det er
    rekkefoelgen tingene faktisk skjedde i.
    """
    _play_story(state)
    while state.step_feed() is not None:
        pass
    seqs = [r["seq"] for r in state.log_rows()["rows"]]
    assert seqs == sorted(seqs, reverse=True)

    tider = [r["ts"] for r in state.log_rows()["rows"]]
    assert tider != sorted(tider, reverse=True), (
        "hadde tidene vaert sortert, ville det ikke vaert noe aa merke"
    )


def test_the_time_column_is_drawn_with_the_marker_and_explains_itself():
    app_js = (UI / "static/app.js").read_text(encoding="utf-8")
    style = (UI / "static/style.css").read_text(encoding="utf-8")

    # Kolonnen tegnes ett sted, og det stedet bruker merket.
    celle = app_js.split("function tidsCelle(rad) {", 1)
    assert len(celle) == 2, "tidsCelle() tegner Tid-kolonnen"
    kropp = celle[1].split("\n}", 1)[0]
    assert "rad.tidsbase" in kropp
    assert "app-time-base" in kropp

    # Tabellen bruker den, og ikke den nakne klokken.
    tabell = app_js.split("function renderLogTable() {", 1)[1].split("\nfunction ", 1)[0]
    assert "tidsCelle(r)" in tabell
    assert "esc(klokke(r.ts))" not in tabell
    # Forklaringen kommer bare naar det faktisk staar to klokker i tabellen.
    assert "logData.log.tidsbaser" in tabell

    for merke in ('merke: "sim"', 'merke: "nå"'):
        assert merke in app_js, merke
    assert ".app-time-base" in style
