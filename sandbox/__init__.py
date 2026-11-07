"""Sandkassen: prøv et tillegg i en lukket boks før det slippes inn.

    from sandbox import scan
    rapport = scan("free-ai-boost")   # -> SandboxReport

Tillegget kjøres i en egen delprosess. Der inne er nettverket byttet ut med en
vegg som bare skriver ned hvilken adresse tillegget prøvde å nå, og
hjemmemappen er en falsk mappe med oppdiktede filer som ligner et
utviklermiljø. Alt tillegget gjør skrives ned, og rapporten sier `clean`,
`blocked` eller `not_tested` (tillegget kom aldri i gang, så vi fikk ikke sett
hva det ville gjort).

Avgjørelsen er en fast regel på det tillegget faktisk gjorde - aldri en
AI-modell, og aldri tilleggets egen beskrivelse av seg selv.

Les `sandbox/LIMITS.md` før du tror dette er ekte isolasjon. Det er det ikke.
"""

from __future__ import annotations

import sys

# Sandkassen starter en delprosess med `python -I` og bygger miljoeet fra null.
# Paa eldre Python feiler det paa maater som er vanskelige aa lese: delprosessen
# doer uten hendelser, og rapporten sier bare "Delprosessen stoppet foer
# tillegget var ferdig". Da er det bedre aa si fra med én gang hva som er galt.
#
# ui/state.py fanger denne og viser den i UI; `python -m sandbox` skriver den
# til stderr. Begge steder blir den altsaa synlig, ikke en stille krasj.
MIN_PYTHON = (3, 11)

if sys.version_info < MIN_PYTHON:  # pragma: no cover - avhenger av tolkeren
    raise RuntimeError(
        "Lonewatch sandkassen krever Python "
        f"{MIN_PYTHON[0]}.{MIN_PYTHON[1]} eller nyere, men kjoerer paa "
        f"{sys.version_info.major}.{sys.version_info.minor}."
        f"{sys.version_info.micro} ({sys.executable}). "
        "Lag et nytt venv med en nyere Python: "
        "python3.11 -m venv .venv && source .venv/bin/activate && "
        "pip install -r requirements.txt"
    )

from . import config, fake_home
from .report import INCONCLUSIVE_EVENTS, NOT_TESTED_NOTE, is_inconclusive
from .runner import (
    SandboxRun,
    UnknownPackage,
    available_packages,
    clear_scan_cache,
    package_path,
    run_in_box,
    run_plugin_source,
    scan,
    scan_cached,
)

DEMO_PACKAGES = config.DEMO_PACKAGES
HANGING_PACKAGE = config.HANGING_PACKAGE

__all__ = [
    "MIN_PYTHON",
    "INCONCLUSIVE_EVENTS",
    "NOT_TESTED_NOTE",
    "is_inconclusive",
    "scan",
    "scan_cached",
    "clear_scan_cache",
    "run_plugin_source",
    "run_in_box",
    "SandboxRun",
    "available_packages",
    "package_path",
    "UnknownPackage",
    "DEMO_PACKAGES",
    "HANGING_PACKAGE",
    "config",
    "fake_home",
]
