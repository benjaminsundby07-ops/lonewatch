"""Utføreren: den som faktisk gjør handlingen etter at Lonewatch har sagt ja.

Resten av Lonewatch vurderer, logger og viser. Denne mappen er den eneste som
rører omverdenen, og den gjør det bare når to ting stemmer:

    allow                            -> gjennomføres
    red som et menneske har godkjent -> gjennomføres

Alt annet - en rød sak som venter, en rød sak som ble avvist, en blokkert sak,
eller en forespørsel som er endret etter godkjenningen - svarer "ikke utført".

Flyten:

    forseglingen   seal(request, decision, human) -> Approval
    utføringen     executor.execute(request, decision, approval) -> ExecutionResult

Forseglingen regner ut et avtrykk av forespørselen i det øyeblikket
avgjørelsen faller. Utføreren regner det ut på nytt og nekter hvis innholdet er
endret. Uten den kunne et menneske godkjent én e-post og en annen blitt sendt.

Utførerne:

    SimulatedExecutor   standarden. Later som, gjør ingenting.
    SmtpExecutor        den ene ekte koblingen: send_email over SMTP til localhost.

`execute()` kaster aldri. Svaret er alltid et ExecutionResult.

Ærlige begrensninger: se executor/LIMITS.md og docs/UTFORER.md.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .approval import Approval, fingerprint, seal
from .base import Executor, ExecutorError, SimulatedExecutor
from .gate import Gate, may_execute
from .mail import AddressError, build_message, mask_address, subject_from, valid_address
from .once import AttemptLedger
from .result import ExecutionResult, ExecutionStatus
from .smtp import (
    ENV_ALLOW_REMOTE,
    ENV_FROM,
    ENV_HOST,
    ENV_PORT,
    ENV_STARTTLS,
    ENV_TIMEOUT,
    SmtpConfig,
    SmtpConfigError,
    SmtpExecutor,
    is_local,
)

__all__ = [
    # forseglingen
    "Approval",
    "seal",
    "fingerprint",
    # porten
    "Gate",
    "may_execute",
    # utførerne
    "Executor",
    "ExecutorError",
    "SimulatedExecutor",
    "SmtpExecutor",
    "SmtpConfig",
    "SmtpConfigError",
    "is_local",
    # svaret
    "ExecutionResult",
    "ExecutionStatus",
    "AttemptLedger",
    # e-posten
    "AddressError",
    "build_message",
    "mask_address",
    "subject_from",
    "valid_address",
    # postfangeren
    "MailCatcher",
    "CaughtMail",
    # miljøvariabler
    "ENV_HOST",
    "ENV_PORT",
    "ENV_FROM",
    "ENV_TIMEOUT",
    "ENV_ALLOW_REMOTE",
    "ENV_STARTTLS",
]


# Postfangeren hentes ved behov, ikke ved import. Grunnen er praktisk: hadde
# `__init__` importert den, ville `python -m executor.mailcatcher` lastet den
# to ganger og klaget om det hver gang demoen startes. `from executor import
# MailCatcher` virker som før.
if TYPE_CHECKING:  # pragma: no cover
    from .mailcatcher import CaughtMail, MailCatcher

_LAZY = {"MailCatcher": "mailcatcher", "CaughtMail": "mailcatcher"}


def __getattr__(name: str) -> Any:
    module_name = _LAZY.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} har ingen {name!r}")
    from importlib import import_module

    return getattr(import_module(f".{module_name}", __name__), name)


def __dir__() -> list[str]:
    return sorted(set(__all__))
