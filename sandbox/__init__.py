"""Sandkassen: prøv et tillegg i en lukket boks før det slippes inn.

    from sandbox import scan
    rapport = scan("free-ai-boost")   # -> SandboxReport

Tillegget kjøres i en egen delprosess. Der inne er nettverket byttet ut med en
vegg som bare skriver ned hvilken adresse tillegget prøvde å nå, og
hjemmemappen er en falsk mappe med oppdiktede filer som ligner et
utviklermiljø. Alt tillegget gjør skrives ned, og rapporten sier `clean` eller
`blocked`.

Avgjørelsen er en fast regel på det tillegget faktisk gjorde - aldri en
AI-modell, og aldri tilleggets egen beskrivelse av seg selv.

Les `sandbox/LIMITS.md` før du tror dette er ekte isolasjon. Det er det ikke.
"""

from __future__ import annotations

from . import config, fake_home
from .runner import (
    SandboxRun,
    UnknownPackage,
    available_packages,
    package_path,
    run_in_box,
    run_plugin_source,
    scan,
)

DEMO_PACKAGES = config.DEMO_PACKAGES
HANGING_PACKAGE = config.HANGING_PACKAGE

__all__ = [
    "scan",
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
