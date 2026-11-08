"""Oppsettet til MCP-tjeneren. Alt kommer fra miljøvariabler, ingenting er hardkodet.

To valg er bevisst strenge, og de er ikke pyntet på:

1. **Nøkkelen er påkrevd.** Uten `LONEWATCH_AGENT_KEY` starter tjeneren ikke, og
   endepunktet i appen svarer 503. Da kan ingen annen prosess på maskinen legge
   forespørsler i godkjenningskøen ved et uhell.
2. **Bare 127.0.0.1.** Adressen må være loopback. Det er ikke appen som
   beskyttes av det - det er deg: en MCP-tjener som kunne pekt hvor som helst,
   ville vært en kanal ut av maskinen som agenten selv kontrollerte.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse

ENV_BASE_URL = "LONEWATCH_AGENT_URL"
ENV_KEY = "LONEWATCH_AGENT_KEY"
ENV_WAIT_SECONDS = "LONEWATCH_AGENT_WAIT_SECONDS"
ENV_POLL_SECONDS = "LONEWATCH_AGENT_POLL_SECONDS"

# Navnet paa den delte hemmeligheten i HTTP-hodet. Samme navn i ui/app.py.
HEADER_KEY = "X-Lonewatch-Agent-Key"

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_WAIT_SECONDS = 120.0
DEFAULT_POLL_SECONDS = 2.0

# Vertsnavn vi regner som "denne maskinen". Alt annet avvises.
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})


class ConfigError(RuntimeError):
    """Oppsettet holder ikke. Tjeneren skal si fra og stoppe, ikke gjette."""


@dataclass(frozen=True)
class AgentConfig:
    base_url: str
    key: str
    wait_seconds: float
    poll_seconds: float


def check_loopback(base_url: str) -> str:
    """Godtar bare http mot denne maskinen. Returnerer adressen uten skråstrek til slutt."""
    parsed = urlparse(base_url)
    if parsed.scheme not in ("http", "https"):
        raise ConfigError(f"{ENV_BASE_URL} må være en http-adresse, ikke {base_url!r}.")
    if (parsed.hostname or "") not in LOOPBACK_HOSTS:
        raise ConfigError(
            f"{ENV_BASE_URL} må peke på 127.0.0.1 (denne maskinen), ikke {parsed.hostname!r}. "
            "Lonewatch-broen snakker aldri ut av maskinen."
        )
    return base_url.rstrip("/")


def _positive_float(name: str, raw: str | None, default: float) -> float:
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} må være et tall, ikke {raw!r}.") from exc
    if value <= 0:
        raise ConfigError(f"{name} må være større enn 0, ikke {value}.")
    return value


def load_config(env: dict[str, str] | None = None) -> AgentConfig:
    """Leser oppsettet. Kaster ConfigError med en setning som sier hva som mangler."""
    source = os.environ if env is None else env

    key = (source.get(ENV_KEY) or "").strip()
    if not key:
        raise ConfigError(
            f"{ENV_KEY} er ikke satt. Lag en nøkkel (for eksempel med "
            "`python -c \"import secrets;print(secrets.token_urlsafe(32))\"`), "
            "sett den i BÅDE terminalen som kjører appen og i MCP-oppsettet, "
            "og hold den utenfor git."
        )
    if len(key) < 16:
        raise ConfigError(f"{ENV_KEY} er for kort. Bruk minst 16 tegn.")

    base_url = check_loopback((source.get(ENV_BASE_URL) or DEFAULT_BASE_URL).strip())
    wait = _positive_float(
        ENV_WAIT_SECONDS, source.get(ENV_WAIT_SECONDS), DEFAULT_WAIT_SECONDS
    )
    poll = _positive_float(
        ENV_POLL_SECONDS, source.get(ENV_POLL_SECONDS), DEFAULT_POLL_SECONDS
    )
    return AgentConfig(base_url=base_url, key=key, wait_seconds=wait, poll_seconds=poll)
