"""Hvordan et skrevet beløp tolkes. Dette er fasiten.

Mennesket må skrive beløpet selv for å godkjenne en stor overføring. Da må
"skrev beløpet" bety at tallet faktisk er det samme. Den gamle regelen kastet
alle tegn som ikke var 0-9 og sammenlignet sifrene, så "100000,00" (hundre tusen
kroner og null øre) ble lest som 10 000 000. Se F1 i docs/REDTEAM.md.

Regelen her tolker teksten som et BELØP:

- mellomrom og punktum er tusenskille, og må gruppere riktig (10.000.000, ikke 10.00.000)
- komma er desimalskille, og kan stå én gang med ett eller to siffer etter seg
- "kr", "NOK" og "kroner" kan stå til slutt
- minus, pluss og bokstaver avvises
- alt regnes i hele øre, så flyttall aldri kan gjøre to ulike beløp like

Punktum som DESIMALSKILLE godtas ikke: "1234.56" kan like gjerne være et
mislykket tusenskille, og i en bekreftelsesrute gjetter vi ikke. Da sier vi
heller nei og lar mennesket skrive det på nytt.

`ui/static/amount.js` er den samme regelen for nettleseren. De to holdes i takt
av `tests/test_amount.py`, som kjører nøyaktig samme tilfeller gjennom begge.
"""

from __future__ import annotations

import math
import re
from decimal import Decimal, InvalidOperation

# Lengdegrense FØR vi regner på noe. Uten denne krasjer Pythons int() på en
# streng med mer enn 4300 siffer (F3 i rapporten), og endepunktet svarer 500.
MAX_INPUT_CHARS = 64

# Flere sifre enn dette er ikke et beløp noen skriver inn for hånd.
# 13 siffer er ogsaa grensen for at nettleseren kan regne eksakt: et JS-tall
# er eksakt opp til 2^53, og 9 999 999 999 999,99 kr i oere ligger trygt
# under. En hoyere grense her ville gjort amount.js uenig med denne filen.
MAX_DIGITS = 13

# Valutaord som kan stå til slutt. Ingenting annet av bokstaver godtas.
CURRENCY_SUFFIX = re.compile(r"(?:kr|nok|kroner)$", re.IGNORECASE)

# Mellomrom vi behandler som tusenskille: vanlig, hardt og smalt hardt mellomrom.
SPACES = " \t\u00a0\u202f"

_GROUP_SEPARATORS = re.compile("[ \t\u00a0\u202f.]")
_ONLY_DIGITS = re.compile(r"^[0-9]+$")


def parse_amount(text: str | None) -> int | None:
    """Tolker et skrevet beløp og gir hele øre, eller None hvis det ikke er et beløp.

    None betyr "dette kan jeg ikke lese som et beløp". Det er aldri det samme
    som 0: et tomt felt skal ikke kunne bekrefte en overføring på 0 kr heller.
    """
    if not isinstance(text, str):
        return None

    cleaned = text.strip(SPACES + "\r\n")
    if not cleaned or len(cleaned) > MAX_INPUT_CHARS:
        return None

    # Valutaordet til slutt, hvis det står der.
    cleaned = CURRENCY_SUFFIX.sub("", cleaned).strip(SPACES)
    if not cleaned:
        return None

    # Desimaldelen. Komma er det eneste desimalskillet vi godtar.
    if cleaned.count(",") > 1:
        return None
    if "," in cleaned:
        whole, _, fraction = cleaned.partition(",")
        if not _ONLY_DIGITS.match(fraction) or len(fraction) > 2:
            return None
        ore_part = int(fraction.ljust(2, "0"))
    else:
        whole = cleaned
        ore_part = 0

    # Heltallsdelen, gruppert med mellomrom eller punktum.
    groups = _GROUP_SEPARATORS.split(whole)
    if not all(_ONLY_DIGITS.match(g) for g in groups):
        return None
    if len(groups) > 1:
        # Første gruppe er 1-3 siffer, resten nøyaktig 3. Dette stopper
        # "100000.00", som ellers ville sett ut som et beløp med øre.
        if not 1 <= len(groups[0]) <= 3:
            return None
        if any(len(g) != 3 for g in groups[1:]):
            return None

    digits = "".join(groups)
    if len(digits) > MAX_DIGITS:
        return None

    return int(digits) * 100 + ore_part


def to_ore(amount: float | int | None) -> int | None:
    """Beløpet fra forespørselen som hele øre. None hvis det ikke er et tall."""
    if amount is None or isinstance(amount, bool):
        return None
    try:
        if not math.isfinite(float(amount)):
            return None
        return int((Decimal(str(amount)) * 100).to_integral_value())
    except (TypeError, ValueError, InvalidOperation):
        return None


def amount_matches(typed: str | None, expected: float | None) -> bool:
    """Skrev mennesket nøyaktig det beløpet forespørselen gjelder?

    Sammenligningen skjer i hele øre, så "100000,00" og "10000000" aldri kan
    bli det samme tallet.
    """
    forventet = to_ore(expected)
    if forventet is None:
        return False
    skrevet = parse_amount(typed)
    if skrevet is None:
        return False
    return skrevet == forventet


def format_ore(ore: int) -> str:
    """Hele øre -> '10 000 000 kr' eller '1 234,56 kr'."""
    kroner, rest = divmod(abs(int(ore)), 100)
    tall = f"{kroner:,}".replace(",", " ")
    if rest:
        tall = f"{tall},{rest:02d}"
    fortegn = "-" if ore < 0 else ""
    return f"{fortegn}{tall} kr"
