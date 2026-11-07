"""Tall og navn sandkassen bruker. Alt som kan justeres står her.

Ingenting her bestemmer allow/red/block i mellomstasjonen. Sandkassen svarer
bare "clean" eller "blocked" om et tillegg, og gjør det med faste regler.
"""

from __future__ import annotations

import re

# Hvor lenge et tillegg får kjøre før delprosessen drepes.
DEFAULT_TIMEOUT_S = 6.0

# Hard bremse inne i delprosessen, i tillegg til klokka utenfor.
# CPU-grensen fanger et tillegg som tråkker rundt i en evig løkke, filgrensen
# fanger et tillegg som prøver å fylle disken.
CPU_SECONDS_SLACK = 2
MAX_FILE_BYTES = 2_000_000

# Hvor mye tekst vi tar med av en feilmelding eller et returnert objekt.
MAX_TEXT_CHARS = 300

# Hvor mange adresser og filnavn vi tar med i rapporten.
MAX_DESTINATIONS = 20
MAX_LISTED_FILES = 10

# Tillegg vi har laget til demoen. De to første er harmløse, de to siste
# later som de er nyttige og prøver å stjele.
DEMO_PACKAGES = ("pdf-helper", "date-utils", "free-ai-boost", "env-sync-helper")

# Et tillegg som bare henger. Brukes for å vise at tidsgrensen virker.
HANGING_PACKAGE = "endless-indexer"

# Et pakkenavn blir slått om til et filnavn, så navnet må være kjedelig.
# Dette stopper også "../../etc/passwd" som pakkenavn.
PACKAGE_NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:[-_][a-z0-9]+)*$")

# Hendelser fra delprosessen som alene gjør at et tillegg ikke slippes inn.
BLOCKING_EVENTS = (
    "network_connect",
    "network_lookup",
    "network_send",
    "secret_read",
    "denied_file",
    "denied_process",
    "denied_import",
)
