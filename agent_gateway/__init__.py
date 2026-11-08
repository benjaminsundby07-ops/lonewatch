"""Broen mellom en ekte AI-agent (Claude Code) og Lonewatch.

Dette er en MCP-tjener. Agenten ser fire verktøy - les dokument, send e-post,
overfør penger, installer tillegg - og hvert kall går samme vei som alt annet i
Lonewatch:

    verktøykall -> HTTP til den kjørende appen -> gateway.evaluate() -> loggen
                -> allow / rødt kort i dashbordet / block -> svar til agenten

Tjeneren inneholder INGEN regler. Den vurderer ingenting, den logger ingenting
og den kan ikke godkjenne noe. Den spør appen og venter på svar. Appen eier
tilstanden, avgjørelsen og loggen, slik at mennesket i dashbordet og agenten
ser nøyaktig det samme.

Verktøyene utfører heller ingenting ekte. "Utført" betyr at tjeneren returnerer
en tekst som sier at det er simulert. Ingen penger, ingen e-post, ingen
pakkeinstallasjon, ingen nettverkskall utenom til 127.0.0.1.

Ærlige begrensninger - og særlig det store hullet (Claude Code har andre
verktøy som går rett forbi Lonewatch): se `agent_gateway/LIMITS.md`.
"""

from __future__ import annotations

from agent_gateway.client import (
    LonewatchClient,
    LonewatchRefused,
    LonewatchUnavailable,
)
from agent_gateway.config import (
    ENV_BASE_URL,
    ENV_KEY,
    ENV_POLL_SECONDS,
    ENV_WAIT_SECONDS,
    HEADER_KEY,
    AgentConfig,
    load_config,
)
from agent_gateway.tools import TOOL_SPECS, format_amount, run_action

__all__ = [
    "AgentConfig",
    "ENV_BASE_URL",
    "ENV_KEY",
    "ENV_POLL_SECONDS",
    "ENV_WAIT_SECONDS",
    "HEADER_KEY",
    "LonewatchClient",
    "LonewatchRefused",
    "LonewatchUnavailable",
    "TOOL_SPECS",
    "format_amount",
    "load_config",
    "run_action",
]
