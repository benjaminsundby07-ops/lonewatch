"""Hoeyden paa nettsiden: siden skal aldri rulle.

Dette er en STATISK sjekk av `ui/static/style.css`. Den maaler ingenting - en
ekte maaling krever en nettleser, og den staar i `ui/LIMITS.md` punkt 9 med
tallene fra runden. Det testene her gjoer, er aa pinne reglene maalingen
hvilte paa, slik at de ikke kan forsvinne uten at noen ser det:

  1. skallet er skjermhoeyden, ikke bare minst skjermhoeyden
  2. den aktive fanen faar resten av hoeyden
  3. alt som kan vokse uten grense, ruller INNVENDIG
  4. en liten skjerm faller tilbake til faste tak

Grunnen til at dette er verdt en test: foer denne runden stod hoeydene som
faste tall (`calc(100vh - 340px)`, 340, 200, 96 px). De traff én skjerm og én
tilstand, og med hele stroemmen kjoert var Godkjenning 1388 px paa 1440x900.
Et fast tall som er riktig i dag er feil i morgen, og ingen ser det.
"""

from __future__ import annotations

import pathlib
import re

CSS = (pathlib.Path(__file__).resolve().parents[1] / "ui/static/style.css").read_text(
    encoding="utf-8"
)
HTML = (pathlib.Path(__file__).resolve().parents[1] / "ui/static/index.html").read_text(
    encoding="utf-8"
)

TALL_SKJERM = "@media (min-width: 1241px) and (min-height: 700px) {"


def _blokk(css: str, start: str) -> str:
    """Teksten mellom de ytterste klammene etter `start`."""
    i = css.index(start)
    dybde = 0
    j = i + len(start) - 1
    begynn = j
    while True:
        if css[j] == "{":
            dybde += 1
        elif css[j] == "}":
            dybde -= 1
            if dybde == 0:
                return css[begynn + 1 : j]
        j += 1


def _regel(css: str, velger: str) -> str:
    treff = re.search(re.escape(velger) + r"\s*\{([^}]*)\}", css)
    assert treff, f"fant ikke regelen for {velger}"
    return treff.group(1)


def test_the_shell_is_exactly_the_screen_height():
    """`min-height` alene lar siden vokse forbi skjermkanten.

    Det var akkurat det som skjedde: fanene vokste med innholdet, og da er det
    SIDEN som ruller. Et tak i tillegg til gulvet gjoer at den ikke kan.
    """
    regel = _regel(CSS, ".app-backdrop")
    assert "height: 100vh" in regel
    assert "min-height: 100vh" in regel, "gulvet skal staa, ogsaa naar taket kom"


def test_the_active_tab_gets_the_rest_of_the_height():
    """Toppraden, bannerne og bunnteksten beholder hoeyden sin. Fanen tar resten."""
    hoved = _regel(CSS, ".app-main")
    assert "display: flex" in hoved and "flex-direction: column" in hoved
    assert "min-height: 0" in hoved, "uten denne kan ikke fanen krympe"

    assert ".app-main > * { flex: none; }" in CSS
    visning = _regel(CSS, ".app-main > .app-view")
    assert "flex: 1 1 auto" in visning and "min-height: 0" in visning


def test_everything_that_can_grow_scrolls_inside_itself():
    """Hver liste som vokser med demoen, ruller i sin egen blokk.

    Faller én av dem ut, er det siden som ruller i stedet - og da er vi
    tilbake der vi startet.
    """
    for velger in (
        ".app-list",        # koeen og tilleggene
        ".app-quiet-list",  # «Gaar gjennom»
        ".app-table-wrap",  # loggtabellen
        ".app-after",       # «Oppfoelging»
        "#custom-list",     # «Dine foresproersler»
        ".app-detail",      # saken som er aapen
    ):
        assert re.search(
            re.escape(velger) + r"[^{}]*\{[^}]*overflow-y: auto", CSS
        ), f"{velger} kan vokse uten aa rulle innvendig"


def test_no_list_is_capped_by_a_number_tuned_for_one_screen():
    """Faste tak var feilen. De skal ikke komme tilbake utenfor reservelosningen.

    `calc(100vh - 340px)` gav 560 px paa 900 og 740 px paa 1080 - men den tok
    ikke hensyn til at «Gaar gjennom» stod under og krevde sine egne 420 px.
    Summen ble 1110 px i en kolonne som hadde 742.
    """
    reserve = _blokk(CSS, "@media (max-width: 1240px), (max-height: 699px) {")
    utenfor = CSS.replace(reserve, "")
    for fast in ("max-height: calc(100vh", "max-height: 340px", "max-height: 200px",
                 "max-height: 96px"):
        assert fast not in utenfor, f"fast hoeyde tilbake: {fast}"


def test_a_small_screen_still_has_a_cap():
    """Under 1241 px bredde eller 700 px hoeyde er kolonnene stablet.

    Da deler ingenting hoeyden, og listene trenger et tall igjen - ellers
    ruller fanen i det uendelige paa en telefon.
    """
    reserve = _blokk(CSS, "@media (max-width: 1240px), (max-height: 699px) {")
    assert "max-height" in _regel(reserve, ".app-list")
    assert "max-height" in _regel(reserve, ".app-quiet-list")


def test_the_tall_screen_rules_hook_onto_classes_that_exist():
    """Reglene for Etter henger paa to klassenavn. Forsvinner de, gjoer stilen det ogsaa."""
    tall = _blokk(CSS, TALL_SKJERM)
    for klasse in ("app-log-panel", "app-follow-panel"):
        assert klasse in tall, f"{klasse} brukes ikke lenger i CSS"
        assert klasse in HTML, f"{klasse} finnes ikke i index.html"


def test_the_form_column_is_wide_enough_that_the_help_text_fits_on_two_lines():
    """640 px og ikke 560.

    Paa 560 brot de tre hjelpetekstene i «Proev selv» til en linje ekstra
    hver, og nettopp de linjene var de 22-24 px fanen var for hoey.
    """
    regel = _regel(CSS, ".app-cols-custom")
    assert "minmax(0, 640px)" in regel
