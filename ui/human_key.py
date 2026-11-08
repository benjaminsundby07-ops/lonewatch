"""Menneskenøkkelen: beviset på at et menneske - og ikke en agent - godkjente.

Hele fortellingen til Lonewatch er at et rødt kort venter på et menneske. Fram
til nå kunne hvem som helst som nådde porten poste `/api/respond` og få kortet
fra «venter» til «godkjent» (H1 i docs/ANGREP.md). Denne modulen er porten
foran det endepunktet.

Tre valg, og ingen av dem er pyntet på:

1. **Egen nøkkel, atskilt fra agentnøkkelen.** `LONEWATCH_HUMAN_KEY` er ikke
   `LONEWATCH_AGENT_KEY`. En agent som har agentnøkkelen (den står i
   `.mcp.json`, som Claude Code selv leser) kan sende inn forespørsler, men
   ikke godkjenne dem. Er de to satt til samme verdi, slår vi godkjenningen AV
   i stedet for å late som skillet finnes.

2. **Fail closed.** Er `LONEWATCH_HUMAN_KEY` ikke satt, svarer `/api/respond`
   503 og ingenting kan godkjennes. En port som åpner seg når oppsettet
   mangler, er ingen port. Demoen og testene setter nøkkelen med vilje.

3. **Nøkkelen ER identiteten.** `employee_pseudonym` i loggen regnes ut fra
   HVILKEN nøkkel som kom inn, ikke fra en fast konstant og ikke fra et navn
   den som kaller skriver selv. `LONEWATCH_HUMAN_KEY` kan inneholde flere
   nøkler skilt med komma - én per person - og da får hver person sitt eget
   pseudonym i loggen. Med én delt nøkkel vet loggen fortsatt bare «noen med
   menneskenøkkelen», og det står i `ui/LIMITS.md`.

Nøkkelen selv skrives ALDRI ut: ikke i et svar, ikke i en feilmelding, ikke i
loggen. Det eneste som forlater modulen er en ugjenkjennelig operatør-id som
`vault.pseudonymize()` kan gjøre til `emp_xxxx`.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
from typing import Mapping

ENV_HUMAN_KEY = "LONEWATCH_HUMAN_KEY"
# Agentnøkkelen leses bare for å kunne NEKTE at den er den samme. Navnet står
# også i ui/app.py; her er det med fordi sjekken hører hjemme ved siden av
# sammenligningen, ikke i ruten.
ENV_AGENT_KEY = "LONEWATCH_AGENT_KEY"

HUMAN_KEY_HEADER = "X-Lonewatch-Human-Key"

# Kortere enn dette er ikke en nøkkel, det er et passord noen gjetter seg til.
MIN_KEY_CHARS = 16

# Flere nøkler i samme variabel: komma, semikolon eller luft mellom dem.
_SPLIT = re.compile(r"[,;\s]+")

# Prefikset gjør operatør-iden til noe annet enn en ansatt-id. Loggen skal
# kunne si «dette pseudonymet er en menneskenøkkel», ikke blande det med
# `ansatt-007` fra demodataene.
OPERATOR_PREFIX = "human-key:"


class HumanKeyOff(RuntimeError):
    """Menneskenøkkelen er ikke satt opp. Da kan ingenting godkjennes."""


class HumanKeyRefused(RuntimeError):
    """Nøkkelen som kom inn er feil, eller den mangler."""


def configured_keys(env: Mapping[str, str] | None = None) -> tuple[str, ...]:
    """Nøklene som gjelder nå, i rekkefølgen de står. Tom hvis ingen er satt.

    For korte nøkler kastes bort. En nøkkel på fire tegn ville sett ut som et
    forsvar og ikke vært et.
    """
    src = os.environ if env is None else env
    raw = (src.get(ENV_HUMAN_KEY) or "").strip()
    if not raw:
        return ()
    ut: list[str] = []
    for bit in _SPLIT.split(raw):
        bit = bit.strip()
        if len(bit) >= MIN_KEY_CHARS and bit not in ut:
            ut.append(bit)
    return tuple(ut)


def operator_id(key: str) -> str:
    """Hvem godkjente? En id avledet av nøkkelen, som ikke kan regnes tilbake.

    SHA-256 av nøkkelen, kuttet. Den går videre til `vault.pseudonymize()`, som
    HMAC-er den med en annen nøkkel igjen, så det som står i loggen er to steg
    unna nøkkelen. 16 hex er nok til at to menneskenøkler aldri kolliderer i
    praksis, og for lite til å brukes til noe annet.
    """
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return f"{OPERATOR_PREFIX}{digest[:16]}"


def _agent_key(env: Mapping[str, str] | None = None) -> str:
    src = os.environ if env is None else env
    return (src.get(ENV_AGENT_KEY) or "").strip()


def _same(left: str, right: str) -> bool:
    """`hmac.compare_digest` paa byte, ikke paa tekst.

    `compare_digest` kaster TypeError paa tekst som ikke er ren ASCII, og en
    noekkel med et norsk tegn i - eller et HTTP-hode noen har fylt med
    soppel - skal gi "nei", ikke en 500-feil. Sammenligningen er fortsatt
    konstant tid for like lengder.
    """
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def check_human_key(given: str | None, env: Mapping[str, str] | None = None) -> str:
    """Slipper gjennom riktig menneskenøkkel. Returnerer operatør-iden.

    Kaster `HumanKeyOff` når ingenting er satt opp (fail closed, 503) og
    `HumanKeyRefused` når nøkkelen er feil eller mangler (403). Forskjellen er
    med vilje: den som holder demoen skal kunne se at nøkkelen ikke er satt,
    uten at en feil nøkkel får vite hvorfor den ikke slapp inn.
    """
    keys = configured_keys(env)
    if not keys:
        raise HumanKeyOff(
            f"Godkjenning er av: {ENV_HUMAN_KEY} er ikke satt i terminalen som "
            "kjører appen. Kjør `python -m agent_gateway.oppsett`, gjør "
            "`source .lonewatch-agent-env`, og start appen på nytt. "
            "Ingenting kan godkjennes før den er satt."
        )

    agent = _agent_key(env)
    if agent and any(_same(agent, k) for k in keys):
        # Et oppsett som gjør de to nøklene like, fjerner hele skillet mellom
        # «en agent ba om dette» og «et menneske godkjente det». Da svarer vi
        # nei til alle, ikke ja til agenten.
        raise HumanKeyOff(
            f"Godkjenning er av: {ENV_HUMAN_KEY} er satt til samme verdi som "
            f"{ENV_AGENT_KEY}. Da ville agentnøkkelen kunne godkjenne sine egne "
            "forespørsler. Sett to ulike nøkler og start appen på nytt."
        )

    candidate = (given or "").strip()
    treff: str | None = None
    for key in keys:
        # Alle nøklene sammenlignes, også etter et treff: en løkke som bryter
        # ut tidlig lekker hvor i listen nøkkelen sto.
        if _same(candidate, key):
            treff = key
    if treff is None:
        raise HumanKeyRefused(
            f"Feil eller manglende menneskenøkkel. Et rødt kort godkjennes bare "
            f"av den som har {ENV_HUMAN_KEY}. Agentnøkkelen gjelder ikke her."
        )
    return operator_id(treff)


def is_configured(env: Mapping[str, str] | None = None) -> bool:
    """Kan noe godkjennes i det hele tatt akkurat nå? Brukes av nettsiden."""
    try:
        keys = configured_keys(env)
    except Exception:  # pragma: no cover - configured_keys kaster ikke
        return False
    if not keys:
        return False
    agent = _agent_key(env)
    return not (agent and any(_same(agent, k) for k in keys))
