"""Den ene ekte koblingen: send_email over SMTP.

Alt annet i Lonewatch er simulert. Dette er stedet der en godkjent handling
faktisk forlater maskinen, og derfor er det her sperrene står tettest.

To sperrer, i denne rekkefølgen:

    1. porten i gate.py           - bare allow, eller red som et menneske godkjente
    2. localhost-sperren her      - adressen må være loopback

Localhost-sperren er der for én grunn: ingen skal kunne sende en ekte e-post
til en ekte person ved et uhell under en demo. Vil du peke utføreren mot
bedriftens egen postserver, må du sette LONEWATCH_SMTP_ALLOW_REMOTE=1 med
vilje. Da har du tatt et valg, og det står i docs/UTFORER.md hva valget betyr.

Oppsettet leses fra miljøvariabler:

    LONEWATCH_SMTP_HOST          standard 127.0.0.1
    LONEWATCH_SMTP_PORT          standard 8025
    LONEWATCH_SMTP_FROM          standard lonewatch@lonewatch.invalid
    LONEWATCH_SMTP_TIMEOUT       standard 10 sekunder
    LONEWATCH_SMTP_ALLOW_REMOTE  1 for å tillate noe annet enn loopback
    LONEWATCH_SMTP_STARTTLS      1 for å kreve STARTTLS (ikke testet, se LIMITS)

Det finnes ingen innlogging her. Ingen brukernavn, ingen passord, ingen
nøkler - verken i koden, i et oppsett eller i et svar. Se docs/UTFORER.md.
"""

from __future__ import annotations

import ipaddress
import os
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Any, Mapping

from contracts import ActionRequest, ActionType, Decision

from .approval import Approval
from .base import Executor, ExecutorError
from .mail import AddressError, build_message, mask_address, require_address
from .once import AttemptLedger

ENV_HOST = "LONEWATCH_SMTP_HOST"
ENV_PORT = "LONEWATCH_SMTP_PORT"
ENV_FROM = "LONEWATCH_SMTP_FROM"
ENV_TIMEOUT = "LONEWATCH_SMTP_TIMEOUT"
ENV_ALLOW_REMOTE = "LONEWATCH_SMTP_ALLOW_REMOTE"
ENV_STARTTLS = "LONEWATCH_SMTP_STARTTLS"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8025
DEFAULT_FROM = "lonewatch@lonewatch.invalid"
DEFAULT_TIMEOUT_S = 10.0

# Navn vi godtar som "min egen maskin". Vi slår dem ikke opp i DNS, se LIMITS.
LOOPBACK_NAMES = frozenset(
    {"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"}
)

# Et vertsnavn skal være et vertsnavn. @ og : er ute fordi en URL av typen
# "bruker:passord@server" aldri skal kunne havne i et svar eller en logg.
FORBIDDEN_IN_HOST = ("@", ":", "/", "\\", " ", "\t", "\r", "\n", "\0")


class SmtpConfigError(ExecutorError):
    """Oppsettet er ikke til å sende med. Ingenting er forsøkt."""


def is_local(host: str) -> bool:
    """Peker adressen på denne maskinen?

    Et navn godtas hvis det står i LOOPBACK_NAMES. En IP-adresse godtas hvis
    den er loopback (127.0.0.0/8, ::1). Alt annet er eksternt.
    """
    name = (host or "").strip().strip("[]").lower()
    if not name:
        return False
    if name in LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(name).is_loopback
    except ValueError:
        return False


def _flag(raw: str | None) -> bool:
    """Bare "1" slår på. Ikke "true", ikke "ja", ikke "0".

    En sperre som kan slås av med et slurvete "false" er ingen sperre. Her må
    du skrive nøyaktig 1.
    """
    return (raw or "").strip() == "1"


@dataclass(frozen=True)
class SmtpConfig:
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    sender: str = DEFAULT_FROM
    timeout_s: float = DEFAULT_TIMEOUT_S
    allow_remote: bool = False
    starttls: bool = False

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> SmtpConfig:
        """Leser oppsettet. Kaster SmtpConfigError på noe vi ikke kan bruke."""
        src = os.environ if env is None else env
        host = (src.get(ENV_HOST) or DEFAULT_HOST).strip()
        raw_port = (src.get(ENV_PORT) or "").strip()
        raw_timeout = (src.get(ENV_TIMEOUT) or "").strip()

        if any(ch in host for ch in FORBIDDEN_IN_HOST) or not host:
            raise SmtpConfigError(
                f"{ENV_HOST} er ikke et gyldig maskinnavn. "
                "Skriv bare navnet eller IP-adressen, uten port, brukernavn eller passord."
            )
        try:
            port = int(raw_port) if raw_port else DEFAULT_PORT
        except ValueError:
            raise SmtpConfigError(f"{ENV_PORT} må være et tall.") from None
        if not 1 <= port <= 65535:
            raise SmtpConfigError(f"{ENV_PORT} må være mellom 1 og 65535.")
        try:
            timeout_s = float(raw_timeout) if raw_timeout else DEFAULT_TIMEOUT_S
        except ValueError:
            raise SmtpConfigError(f"{ENV_TIMEOUT} må være et tall (sekunder).") from None
        if not 0 < timeout_s <= 120:
            raise SmtpConfigError(f"{ENV_TIMEOUT} må være mellom 0 og 120 sekunder.")

        return cls(
            host=host,
            port=port,
            sender=(src.get(ENV_FROM) or DEFAULT_FROM).strip(),
            timeout_s=timeout_s,
            allow_remote=_flag(src.get(ENV_ALLOW_REMOTE)),
            starttls=_flag(src.get(ENV_STARTTLS)),
        )

    def require_allowed(self) -> None:
        """Sperren. Kaster hvis adressen er ekstern og ingen har sagt ja til det."""
        if is_local(self.host):
            return
        if not self.allow_remote:
            raise SmtpConfigError(
                f"Avbrutt: {self.host} er ikke denne maskinen, og sending ut av maskinen "
                f"er avslått. Skal utføreren sende til en ekte postserver, må "
                f"{ENV_ALLOW_REMOTE}=1 settes med vilje."
            )

    @property
    def address(self) -> str:
        return f"{self.host}:{self.port}"


@dataclass(frozen=True)
class SendPlan:
    """Alt som trengs for å sende, ferdig sjekket. Lages før boka merkes."""

    config: SmtpConfig
    message: EmailMessage
    sender: str
    recipient: str


class SmtpExecutor(Executor):
    """Sender e-post på ekte, til localhost med mindre noen har sagt noe annet."""

    name = "smtp"

    def __init__(
        self,
        config: SmtpConfig | None = None,
        ledger: AttemptLedger | None = None,
    ) -> None:
        super().__init__(ledger=ledger)
        # None betyr "les miljøet når vi faktisk skal sende". Da kan oppsettet
        # endres uten å lage en ny utfører, og en feil i miljøet blir et
        # "ikke utført"-svar i stedet for en krasj ved oppstart.
        self._config = config

    def config(self) -> SmtpConfig:
        return self._config if self._config is not None else SmtpConfig.from_env()

    def _prepare(
        self,
        request: ActionRequest,
        decision: Decision,
        approval: Approval | None,
    ) -> Any:
        if request.action_type is not ActionType.SEND_EMAIL:
            raise SmtpConfigError(
                f"Denne utføreren kan bare sende e-post, ikke {request.action_type.value}."
            )
        config = self.config()
        config.require_allowed()
        try:
            recipient = require_address(request.recipient, "Mottakeren")
            sender = require_address(config.sender, "Avsenderen")
            message = build_message(
                request,
                decision,
                sender,
                fingerprint=approval.request_fingerprint if approval is not None else None,
            )
        except AddressError as exc:
            raise SmtpConfigError(str(exc)) from None
        return SendPlan(config=config, message=message, sender=sender, recipient=recipient)

    def _perform(self, request: ActionRequest, decision: Decision, plan: Any) -> tuple[str, str | None]:
        config = plan.config
        # local_hostname settes med vilje. Standarden er socket.getfqdn(), som
        # både slår opp i DNS og legger maskinnavnet vårt inn i EHLO.
        with smtplib.SMTP(
            config.host,
            config.port,
            timeout=config.timeout_s,
            local_hostname="lonewatch.invalid",
        ) as smtp:
            if config.starttls:
                smtp.starttls(context=ssl.create_default_context())
                smtp.ehlo()
            smtp.send_message(plan.message, from_addr=plan.sender, to_addrs=[plan.recipient])
        return (
            f"Sendt til {mask_address(plan.recipient)} via {config.address}.",
            config.address,
        )
