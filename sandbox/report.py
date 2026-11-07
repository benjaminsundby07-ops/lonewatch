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

NETWORK_EVENTS = ("network_connect", "network_lookup", "network_send", "network_bind")


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

    destinations = _unique(
        [str(e["data"].get("destination", "")) for e in events if e.get("kind") in NETWORK_EVENTS],
        config.MAX_DESTINATIONS,
    )
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
    if attempted_network:
        notes.append(
            f"Tillegget prøvde å koble seg til {_antall(len(destinations), 'adresse', 'adresser')}: "
            + ", ".join(destinations)
            + ". Sandkassen svarte nei, så ingenting ble sendt."
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
    if timed_out:
        notes.append(
            f"Tillegget ble ikke ferdig innen tidsgrensen på {_sekunder(timeout_s)} sekunder. "
            "Delprosessen ble drept."
        )
    elif not finished:
        notes.append(
            "Delprosessen stoppet før tillegget var ferdig"
            + (f" (sluttkode {returncode})" if returncode not in (None, 0) else "")
            + ". Vi vet derfor ikke hva tillegget rakk å gjøre."
        )

    plugin_errors = [e["data"] for e in events if e.get("kind") == "plugin_error"]
    if plugin_errors:
        first = plugin_errors[0]
        notes.append(f"Tillegget krasjet: {first.get('type', 'Feil')}: {first.get('message', '')}")

    if not notes:
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
        verdict="blocked" if blocked else "clean",
        notes=" ".join(notes),
    )
