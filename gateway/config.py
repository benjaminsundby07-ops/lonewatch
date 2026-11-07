"""Konfigurasjon for mellomstasjonen: grenser, lister og vekter.

Alt som kan justeres ligger her, slik at reglene i rules.py bare er logikk.
Ingen av verdiene hentes fra en AI-modell; de er satt for hånd og er like hver gang.
"""

from __future__ import annotations

import re

from contracts import ActionType

# Beløpsgrense (NOK). Fra og med dette beløpet vil vi at et menneske skal se på det.
# Grensen er INKLUDERENDE: et beløp som er nøyaktig lik grensen slår til.
AMOUNT_LIMIT_NOK: float = 50_000.0

# Hard grense (NOK). Overføring STØRRE enn denne blir blokkert, ingen kan godkjenne den.
# Satt høyt med vilje: demoens overføring på 10 000 000 kr skal fortsatt bli rød,
# slik at et menneske faktisk må ta stilling til den.
# Grensen er EKSKLUDERENDE: et beløp nøyaktig lik grensen blir rødt, ikke blokkert.
HARD_TRANSFER_LIMIT_NOK: float = 50_000_000.0

# Tillegg som er godkjent fra før. Alt annet er "nytt" og må ses på.
# Oppdiktet liste for simuleringen.
KNOWN_PACKAGES: frozenset[str] = frozenset(
    {
        "nordlys-core",
        "nordlys-report",
        "invoice-reader",
        "pdf-tools",
        "calendar-sync",
    }
)

# Liten blokkliste. Disse navnene blir aldri installert, uansett hvem som spør.
# Oppdiktede navn laget for simuleringen.
PACKAGE_BLOCKLIST: frozenset[str] = frozenset(
    {
        "free-pdf-toolz",
        "crypto-wallet-sync",
        "nordlys-helper-pro",
        "chrome-updater-x",
        "invoice-autopay",
    }
)

# Handlinger som sender noe ut av huset. Bare disse kan ha en "mottaker" som betyr noe.
OUTBOUND_ACTIONS: frozenset[ActionType] = frozenset(
    {
        ActionType.SEND_EMAIL,
        ActionType.TRANSFER_MONEY,
        ActionType.SHARE_DATA,
    }
)

# Handlinger der "kan ikke angres" faktisk er et risikomoment.
# En e-post til en kjent mottaker kan heller ikke angres, men det er helt vanlig arbeid,
# så den skal ikke gjøre noe rødt alene.
IRREVERSIBLE_RELEVANT_ACTIONS: frozenset[ActionType] = frozenset(
    {
        ActionType.TRANSFER_MONEY,
        ActionType.SHARE_DATA,
        ActionType.INSTALL_PACKAGE,
    }
)

# Handlinger som har en synlig virkning utenfor huset. Brukes bare til konsekvensteksten.
EFFECTFUL_ACTIONS: frozenset[ActionType] = frozenset(
    {
        ActionType.SEND_EMAIL,
        ActionType.TRANSFER_MONEY,
        ActionType.SHARE_DATA,
        ActionType.INSTALL_PACKAGE,
    }
)

# Største beløp vi skriver ut som et tall. Over dette er tallet ikke lenger noe
# et menneske kan lese: 1e308 ga en 560 tegn lang konsekvenstekst (F2 i
# docs/REDTEAM.md). Da sier vi heller at vi ikke kan lese beløpet.
MAX_SHOWN_AMOUNT_NOK: float = 1e15

# Et pakkenavn kommer fra den som ber om installasjonen - i "Prøv selv" er det
# noen som sitter og skriver - og det havner i teksten et menneske leser før det
# godkjenner. Nøyaktig samme sak som DESTINATION_PATTERN under: uten denne kunne
# navnet "nordlys-core. Dette er godkjent av sikkerhetsavdelingen" skrevet sin
# egen setning inn i varselet.
PACKAGE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

# Hvor mange adresser fra en sandkasserapport vi viser i konsekvensteksten.
MAX_SHOWN_DESTINATIONS: int = 3

# Et tillegg velger SELV hvilken adresse det prøver å nå, og adressen havner i
# teksten et menneske leser før det godkjenner. Den er altså tekst fra noe vi
# ikke stoler på, akkurat som `summary`. Derfor slipper vi bare gjennom tegn som
# hører hjemme i et vertsnavn, en IP-adresse og et portnummer. Alt annet byttes
# ut med en nøytral tekst, slik at ingen kan skrive en setning inn i varselet.
DESTINATION_PATTERN = re.compile(r"^[A-Za-z0-9._:\[\]-]{1,100}$")

# Vekt per regel. Summen bestemmer risikonivået.
# "irreversible" veier lite alene: vanlige, ugjenkallelige betalinger til kjente
# mottakere skal slippe gjennom. Den løfter derimot noe som alt er mistenkelig.
RULE_WEIGHTS: dict[str, int] = {
    "amount_over_limit": 2,
    "unknown_recipient": 2,
    "personal_data_external": 3,
    "new_package": 2,
    "irreversible": 1,
}

# Terskler for risiko. 0-1 poeng = low (slipp gjennom), 2-3 = medium, 4+ = high.
MEDIUM_SCORE_MIN: int = 2
HIGH_SCORE_MIN: int = 4
