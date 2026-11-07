"""Beløp i hele øre. Ett tall, brukt både til vurdering og til visning.

F7 i docs/REDTEAM.md: `amount_over_limit` sammenlignet rå `amount >= 50000`,
mens `format_amount()` rundet til hele kroner for visning. Et beløp på
49 999,50 ble derfor **allow**, men vist som **"50 000 kr"** - nøyaktig
grensen. Tallet mennesket så var ikke tallet regelen brukte.

Løsningen er ikke å runde likt to steder, men å regne på det samme tallet:
alt gjøres om til hele øre her, og både reglene og konsekvensteksten bruker
resultatet. Da kan de ikke bli uenige, uansett hvor mange desimaler som
kommer inn.

Flyttall brukes aldri til selve sammenligningen. `Decimal(str(amount))` leser
tallet slik det ser ut skrevet, så 0.1 + 0.2-problemet aldri oppstår.
"""

from __future__ import annotations

import math
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

# Over dette er tallet ikke lenger noe et menneske kan lese. Se F2.
MAX_READABLE_NOK = 1e15


def to_ore(amount: float | int | None) -> int | None:
    """Beløp i NOK -> hele øre. None hvis beløpet ikke kan leses.

    None betyr "dette er ikke et tall jeg kan regne med" (mangler, inf, nan,
    eller så stort at det ikke er til å lese). Reglene behandler det som over
    enhver grense; de later aldri som det er null.
    """
    if amount is None or isinstance(amount, bool):
        return None
    try:
        value = float(amount)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value) or abs(value) >= MAX_READABLE_NOK:
        return None
    try:
        return int((Decimal(str(amount)) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError):
        return None


def format_ore(ore: int) -> str:
    """Hele øre -> '10 000 000 kr' eller '49 999,50 kr'.

    Ørene står i teksten når de finnes. Uten dem ville visningen avrundet til
    et annet tall enn det som ble vurdert.
    """
    negativ = ore < 0
    kroner, rest = divmod(abs(int(ore)), 100)
    tall = f"{kroner:,}".replace(",", " ")
    if rest:
        tall = f"{tall},{rest:02d}"
    return f"{'-' if negativ else ''}{tall} kr"
