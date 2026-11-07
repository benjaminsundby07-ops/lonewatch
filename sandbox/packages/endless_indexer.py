"""endless-indexer (demotillegg som henger).

Dette er ikke ett av de fire demotilleggene. Det finnes bare for å vise at
tidsgrensen virker: run() blir aldri ferdig. Det sover i småbiter i stedet for
å tråkke rundt i en tom løkke, slik at det ikke spiser CPU mens vi venter.
"""

from __future__ import annotations

import time


def run():
    teller = 0
    while True:
        time.sleep(0.05)
        teller += 1
