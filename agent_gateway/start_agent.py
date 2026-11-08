"""Starter Claude Code med det låste agentoppsettet.

Bruk:
    python -m agent_gateway.start_agent            start agenten låst
    python -m agent_gateway.start_agent --vis      bare skriv kommandolinjen
    python -m agent_gateway.start_agent --help     forklaringen

Den gjør tre ting, i denne rekkefølgen:

1. sjekker at `.mcp.json` og `.claude/settings.json` finnes (lages av
   `python -m agent_gateway.oppsett`) og at `claude` finnes på maskinen
2. skriver en norsk melding om hva som er låst OG hva som ikke er det
3. bytter prosessen ut med `claude`, med flaggene fra `agent_gateway/laas.py`

Ingenting startes med mindre du kjører kommandoen. `--vis` starter ingenting:
den skriver bare kommandolinjen, slik at du kan lese den før du bruker den.

Dette er klientkonfigurasjon. En agent som alt kan kjøre kode på maskinen kan
slette innstillingsfilen, droppe flaggene eller starte `claude` selv. Det
eneste som ville lukket hullet er at all trafikk tvinges gjennom Lonewatch på
nettverksnivå, og det er ikke bygget. Se `agent_gateway/LIMITS.md` punkt 1.
"""

from __future__ import annotations

import os
import shutil
import shlex
import sys
from pathlib import Path

from agent_gateway import laas

ROOT = laas.ROOT


def build_command(*, root: Path = ROOT, claude: str = "claude") -> list[str]:
    """Kommandolinjen. Egen funksjon slik at den kan testes uten å starte noe."""
    return laas.build_claude_argv(root=root, claude=claude)


def missing_files(root: Path = ROOT) -> list[str]:
    """Filene oppsettet skulle laget, og som ikke er der."""
    mangler = []
    for rel in (laas.MCP_REL, laas.SETTINGS_REL):
        if not (Path(root) / rel).exists():
            mangler.append(rel)
    return mangler


def _skriv_melding(argv: list[str], root: Path) -> None:
    print("Starter Claude Code i", root)
    print()
    for linje in laas.summary_lines(root):
        print(linje)
    print()
    print("Kommandolinjen:")
    print("  " + " ".join(shlex.quote(d) for d in argv))
    print()
    print("Inne i agenten:")
    print("  /mcp      skal vise lonewatch med fire verktøy")
    print("  /status   skal vise at de innebygde verktøyene er nektet")
    print()
    print(
        "Claude Code 2.1.241 skriver «Permission deny rule \"MultiEdit\" matches "
        "no known tool»."
    )
    print(
        "Det er riktig: MultiEdit finnes ikke i denne versjonen. Navnet står i "
        "listen likevel."
    )
    print()


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if "--help" in args or "-h" in args:
        print(__doc__)
        return 0
    bare_vis = "--vis" in args

    root = ROOT
    claude = shutil.which("claude") or "claude"
    kommando = build_command(root=root, claude=claude)

    mangler = missing_files(root)
    if mangler:
        print(
            "Oppsettet mangler: " + ", ".join(mangler) + "\n"
            "Kjør `python -m agent_gateway.oppsett` først.",
            file=sys.stderr,
        )
        if not bare_vis:
            return 1

    _skriv_melding(kommando, root)

    if bare_vis:
        print("--vis: ingenting ble startet.")
        return 0

    if shutil.which("claude") is None:
        print(
            "Fant ikke `claude` på maskinen. Installer Claude Code først.",
            file=sys.stderr,
        )
        return 1

    # Vi bytter ut prosessen vår med claude, slik at agenten eier terminalen og
    # Ctrl-C går dit den skal. Gjør vi det med en underprosess i stedet, ville
    # agenten fått en Python-prosess mellom seg og tastaturet.
    os.chdir(root)
    os.execvp(kommando[0], kommando)
    return 0  # pragma: no cover - execvp kommer ikke tilbake


if __name__ == "__main__":
    raise SystemExit(main())
