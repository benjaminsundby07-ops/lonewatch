"""date-utils (harmlost demotillegg).

Regner på datoer og rører ingenting utenfor seg selv. Ingen filer, ingen
nettverk. Datoen er fast slik at svaret blir likt hver gang.
"""

from __future__ import annotations

from datetime import date, timedelta

NORSKE_MANEDER = (
    "januar", "februar", "mars", "april", "mai", "juni",
    "juli", "august", "september", "oktober", "november", "desember",
)


def norsk_dato(d: date) -> str:
    return f"{d.day}. {NORSKE_MANEDER[d.month - 1]} {d.year}"


def run():
    d = date(2026, 11, 7)
    return {
        "dato": norsk_dato(d),
        "ukenummer": d.isocalendar().week,
        "neste_mandag": norsk_dato(d + timedelta(days=(7 - d.weekday()) % 7 or 7)),
    }
