"""Fra hendelser i delprosessen til en SandboxReport.

Regelen er enkel og fast: ett eneste forsøk på å nå nettet, lese en agnfil,
komme seg ut av boksen eller starte et program er nok til "blocked". Det samme
gjelder et tillegg som ikke ble ferdig i tid. Ingen AI-modell er involvert, og
tillegget får ikke forklare seg - vi ser bare på hva det faktisk gjorde.
"""

from __future__ import annotations

from datetime import datetime, timezone

from contracts import SandboxReport

from . import config

# Alt som er et nettverksforsøk. Alle staar ogsaa i config.BLOCKING_EVENTS, saa
# `attempted_network` og `verdict` kan ikke bli uenige.
NETWORK_EVENTS = ("network_connect", "network_lookup", "network_send", "network_bind")

# Forsøk paa aa naa noe UT. bind() hoerer ikke hjemme her: der vil tillegget
# ta imot, ikke sende.
OUTBOUND_EVENTS = ("network_connect", "network_lookup", "network_send")

# Hendelser som betyr at tillegget aldri kom i gang. Da har vi ikke TESTET det:
# vi har sett at det ikke virket.
#
# Dette er et eget verdikt, `not_tested`. "Clean" ville betydd "vi saa etter og
# fant ingenting", og det er noe helt annet enn "vi fikk aldri sett etter".
#
# En tidsgrense er IKKE med her. Et tillegg som henger har faktisk gjort noe vi
# saa - det nektet aa gi seg - og det blir `blocked` som foer.
INCONCLUSIVE_EVENTS = ("plugin_error", "no_entry_point")

# Hendelsen harness-et skriver HELT til slutt, etter aa ha sjekket at sperrene
# fortsatt staar der de ble satt. Den er beviset vi krever for aa si `clean`:
# uten den har vi ikke sett ferdig etter, og da sier vi `not_tested`.
#
# Dette er regelen "alt vi ikke kan bevise er ikke clean". Foer dette kunne et
# tillegg bryte ut via `open.__globals__`, lese en fil utenfor boksen, og
# rapporten sa `clean` fordi ingen sperre var blitt spurt.
GUARDS_INTACT_EVENT = "guards_intact"

NOT_PROVEN_NOTE = (
    "IKKE TESTET: sandkassen fikk ikke bekreftet at sperrene sto igjen etter "
    "kjoeringen, saa den kan ikke si at tillegget ikke gjorde noe. Dette er "
    "ikke det samme som at vi saa etter og ikke fant noe."
)

NOT_TESTED_NOTE = (
    "IKKE TESTET: sandkassen fikk ikke kjørt tillegget ferdig, så vi vet ikke "
    "hva det ville gjort. Dette er ikke det samme som at vi så etter og ikke "
    "fant noe."
)


def is_inconclusive(events: list[dict]) -> bool:
    """Kom tillegget aldri i gang?"""
    return any(str(e.get("kind", "")) in INCONCLUSIVE_EVENTS for e in events)


def guards_proven(events: list[dict]) -> bool:
    """Bekreftet harness-et at sperrene sto igjen da tillegget var ferdig?"""
    return any(str(e.get("kind", "")) == GUARDS_INTACT_EVENT for e in events)


def _unique(values: list[str], limit: int) -> list[str]:
    """Beholder rekkefølgen, fjerner duplikater, kutter på grensen."""
    seen: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.append(value)
        if len(seen) >= limit:
            break
    return seen


def _antall(n: int, ental: str, flertall: str) -> str:
    return f"{n} {ental}" if n == 1 else f"{n} {flertall}"


def _sekunder(value: float) -> str:
    return f"{value:.1f}".replace(".", ",")


def build_report(
    package_name: str,
    events: list[dict],
    *,
    timed_out: bool,
    timeout_s: float,
    returncode: int | None,
    stderr: str = "",
) -> SandboxReport:
    kinds = [str(e.get("kind", "")) for e in events]
    finished = "done" in kinds
    # Avvist av den statiske sjekken: da ble det ikke startet noen delprosess,
    # og "stoppet foer tillegget var ferdig" ville vaert en misvisende setning.
    static = [e["data"] for e in events if e.get("kind") == "static_reject"]

    outbound = _unique(
        [str(e["data"].get("destination", "")) for e in events if e.get("kind") in OUTBOUND_EVENTS],
        config.MAX_DESTINATIONS,
    )
    bound = _unique(
        [str(e["data"].get("destination", "")) for e in events if e.get("kind") == "network_bind"],
        config.MAX_DESTINATIONS,
    )
    # SandboxReport har bare ett felt for adresser (contracts er laast), saa
    # begge slags staar der. Teksten skiller dem.
    destinations = _unique(outbound + bound, config.MAX_DESTINATIONS)
    attempted_network = any(k in NETWORK_EVENTS for k in kinds)

    secrets = _unique(
        [str(e["data"].get("label") or e["data"].get("path", "")) for e in events if e.get("kind") == "secret_read"],
        config.MAX_LISTED_FILES,
    )
    denied_files = _unique(
        [str(e["data"].get("path", "")) for e in events if e.get("kind") == "denied_file"],
        config.MAX_LISTED_FILES,
    )
    denied_processes = _unique(
        [str(e["data"].get("call", "")) for e in events if e.get("kind") == "denied_process"],
        config.MAX_LISTED_FILES,
    )

    blocked = (
        any(k in config.BLOCKING_EVENTS for k in kinds)
        or timed_out
        or not finished
        or (returncode not in (None, 0))
    )

    notes: list[str] = []
    inconclusive = is_inconclusive(events)
    if inconclusive:
        notes.append(NOT_TESTED_NOTE)
    if outbound:
        notes.append(
            f"Tillegget prøvde å koble seg til {_antall(len(outbound), 'adresse', 'adresser')}: "
            + ", ".join(outbound)
            + ". Sandkassen svarte nei, så ingenting ble sendt."
        )
    if bound:
        notes.append(
            f"Tillegget prøvde å åpne {_antall(len(bound), 'port', 'porter')} for å ta imot "
            "innkommende trafikk: "
            + ", ".join(bound)
            + ". Et tillegg som vil lytte, vil slippe noe INN. Sandkassen svarte nei."
        )
    if secrets:
        notes.append(
            f"Tillegget leste {_antall(len(secrets), 'fil som ser ut som en hemmelighet', 'filer som ser ut som hemmeligheter')}: "
            + ", ".join(secrets)
            + ". Alle filene er oppdiktede demofiler."
        )
    if denied_files:
        notes.append(
            f"Sandkassen avviste {_antall(len(denied_files), 'filtilgang', 'filtilganger')} utenfor boksen: "
            + ", ".join(denied_files)
            + "."
        )
    if denied_processes:
        notes.append(
            f"Tillegget prøvde å starte {_antall(len(denied_processes), 'program', 'programmer')} "
            f"({', '.join(denied_processes)}). Det ble stoppet."
        )
    denied_imports = _unique(
        [str(e["data"].get("module", "")) for e in events if e.get("kind") == "denied_import"],
        config.MAX_LISTED_FILES,
    )
    if denied_imports:
        notes.append(
            f"Tillegget prøvde å hente inn {_antall(len(denied_imports), 'sperret modul', 'sperrede moduler')} "
            f"({', '.join(denied_imports)}). Det er en kjent måte å gå rundt sandkassen på, og det ble stoppet."
        )
    bypass = _unique(
        [str(e["data"].get("name", "")) for e in events if e.get("kind") == "guard_bypass"],
        config.MAX_LISTED_FILES,
    )
    if bypass:
        notes.append(
            f"Tillegget strakk seg etter {_antall(len(bypass), 'ting sandkassen holder for seg selv', 'ting sandkassen holder for seg selv')} "
            f"({', '.join(bypass)}) - altsaa de EKTE funksjonene bak sperrene. "
            "Det fikk en snare i stedet, og forsoeket staar her."
        )
    tampered = _unique(
        [str(e["data"].get("guard", "")) for e in events if e.get("kind") == "guard_tampered"],
        config.MAX_LISTED_FILES,
    )
    if tampered:
        notes.append(
            f"Sperrene sto ikke igjen etter kjoeringen ({', '.join(tampered)}). "
            "Tillegget har byttet dem ut, saa vi kan ikke stole paa noe av det vi "
            "ellers saa."
        )
    if static:
        regler = _unique([str(d.get("rule", "")) for d in static], config.MAX_LISTED_FILES)
        linjer = _unique([str(d.get("text", "")) for d in static], config.MAX_LISTED_FILES)
        notes.append(
            "AVVIST FOER KJOERING: den statiske sjekken fant "
            f"{_antall(len(static), 'kjent roemningsmoenster', 'kjente roemningsmoenstre')} "
            f"i kilden ({', '.join(regler)}): " + "; ".join(linjer) + ". "
            "Tillegget ble derfor ikke kjoert i det hele tatt."
        )
    if timed_out:
        notes.append(
            f"Tillegget ble ikke ferdig innen tidsgrensen på {_sekunder(timeout_s)} sekunder. "
            "Delprosessen ble drept."
        )
    elif not finished and not static:
        notes.append(
            "Delprosessen stoppet før tillegget var ferdig"
            + (f" (sluttkode {returncode})" if returncode not in (None, 0) else "")
            + ". Vi vet derfor ikke hva tillegget rakk å gjøre."
        )

    plugin_errors = [e["data"] for e in events if e.get("kind") == "plugin_error"]
    if plugin_errors:
        first = plugin_errors[0]
        notes.append(f"Tillegget krasjet: {first.get('type', 'Feil')}: {first.get('message', '')}")

    proven = guards_proven(events)
    if not proven and not static and not inconclusive and not blocked:
        # Vi kan ikke si "ingenting skjedde" naar vi ikke fikk bekreftet at
        # sperrene sto igjen. Da er svaret `not_tested`, ikke `clean`.
        notes.append(NOT_PROVEN_NOTE)

    if not notes:
        # Denne setningen er en klarering, og den skal bare staa naar tillegget
        # faktisk kjoerte ferdig. Et tillegg uten run() rakk aldri aa gjoere
        # noe, og "ingen forsøk paa nettverk" ville da lest som en godkjenning.
        notes.append(
            "Ingen forsøk på nettverk, ingen lesing av de falske hemmelighetene "
            "og ingenting utenfor boksen."
        )
    if stderr.strip() and not finished:
        notes.append("Feilmelding fra delprosessen: " + stderr.strip().splitlines()[-1])

    return SandboxReport(
        ts=datetime.now(timezone.utc),
        package_name=package_name,
        attempted_network=attempted_network,
        destinations=destinations,
        # Rekkefoelgen betyr noe: BLOCKED slaar alt.
        #
        # Saa vi et forsoek paa aa naa nettet eller lese et agn, er det et ekte
        # funn, og det gjelder selv om tillegget krasjet rett etterpaa. Det er
        # bare naar vi IKKE saa noe - fordi tillegget aldri kom i gang, eller
        # fordi vi ikke fikk bekreftet at sperrene sto igjen - at svaret er at
        # vi ikke fikk testet det. `clean` krever bevis, ikke bare stillhet.
        verdict=(
            "blocked"
            if blocked
            else ("not_tested" if (inconclusive or not proven) else "clean")
        ),
        notes=" ".join(notes),
    )
