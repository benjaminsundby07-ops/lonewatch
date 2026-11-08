"""Svaret fra en utfører: ble handlingen gjort, eller ble den ikke gjort.

Det finnes ingen tredje mulighet. En utfører svarer aldri "kanskje", kaster
aldri en feil ut til den som kalte, og lar aldri noe skje i stillhet.

`ExecutionResult` er en ny type i denne mappen. Den står IKKE i contracts.py,
fordi contracts.py er låst. Se executor/LIMITS.md for hva det betyr for
loggen.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from contracts import Strict

# Hvor mye tekst vi tar med av en feilmelding. Samme tanke som i sandkassen:
# en lang feil fra et verktøy skal ikke kunne fylle skjermen eller loggen.
MAX_DETAIL_CHARS = 300


class ExecutionStatus(str, Enum):
    DONE = "done"  # handlingen ble faktisk gjort
    REFUSED = "refused"  # porten sa nei, vi forsøkte aldri
    FAILED = "failed"  # vi forsøkte, og det gikk galt
    ALREADY_ATTEMPTED = "already_attempted"  # denne forespørselen er forsøkt før


class ExecutionResult(Strict):
    """Én utføring, eller én nektet utføring."""

    request_id: str
    ts: datetime
    executed: bool
    status: ExecutionStatus
    detail: str  # norsk klartekst, vises til et menneske
    executor_name: str
    rule: str = ""  # engelsk navn på regelen som sa nei, tom når den sa ja
    target: str | None = None  # hvor handlingen gikk, maskert
    fingerprint: str | None = None  # avtrykket av forespørselen vi utførte


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def shorten(text: str) -> str:
    """Én linje, maks MAX_DETAIL_CHARS tegn. Linjeskift ville brutt visningen."""
    flat = " ".join(str(text).split())
    if len(flat) <= MAX_DETAIL_CHARS:
        return flat
    return flat[: MAX_DETAIL_CHARS - 1] + "…"


def done(
    request_id: str,
    executor_name: str,
    detail: str,
    target: str | None = None,
    fingerprint: str | None = None,
    ts: datetime | None = None,
) -> ExecutionResult:
    return ExecutionResult(
        request_id=request_id,
        ts=ts or now_utc(),
        executed=True,
        status=ExecutionStatus.DONE,
        detail=shorten(detail),
        executor_name=executor_name,
        target=target,
        fingerprint=fingerprint,
    )


def refused(
    request_id: str,
    executor_name: str,
    rule: str,
    detail: str,
    ts: datetime | None = None,
) -> ExecutionResult:
    return ExecutionResult(
        request_id=request_id,
        ts=ts or now_utc(),
        executed=False,
        status=ExecutionStatus.REFUSED,
        detail=shorten(detail),
        executor_name=executor_name,
        rule=rule,
    )


def failed(
    request_id: str,
    executor_name: str,
    detail: str,
    rule: str = "",
    target: str | None = None,
    fingerprint: str | None = None,
    ts: datetime | None = None,
) -> ExecutionResult:
    return ExecutionResult(
        request_id=request_id,
        ts=ts or now_utc(),
        executed=False,
        status=ExecutionStatus.FAILED,
        detail=shorten(detail),
        executor_name=executor_name,
        rule=rule,
        target=target,
        fingerprint=fingerprint,
    )


def already_attempted(
    request_id: str,
    executor_name: str,
    detail: str,
    ts: datetime | None = None,
) -> ExecutionResult:
    return ExecutionResult(
        request_id=request_id,
        ts=ts or now_utc(),
        executed=False,
        status=ExecutionStatus.ALREADY_ATTEMPTED,
        detail=shorten(detail),
        executor_name=executor_name,
        rule="already_attempted",
    )
