"""Lonewatch: felles avtale mellom alle delene.

REGLER:
- Denne filen er LÅST. Ingen Claude Code-økt får endre den. Trenger du en endring: stopp og si fra.
- Alle moduler importerer typer herfra. Ingen lager egne varianter.
- Alle navn er engelske og uten æøå. Tekst som vises til brukeren kan være norsk.
- Beløp er alltid i NOK.
- Tidsstempler er alltid UTC (timezone-aware datetime).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

GENESIS_HASH = "0" * 64


class Strict(BaseModel):
    """Basisklasse: ukjente felt gir feil med en gang (fanger for eksempel 'beløp' i stedet for 'amount')."""

    model_config = ConfigDict(extra="forbid")


class ActionType(str, Enum):
    SEND_EMAIL = "send_email"
    TRANSFER_MONEY = "transfer_money"
    SHARE_DATA = "share_data"
    INSTALL_PACKAGE = "install_package"
    READ_DOCUMENT = "read_document"
    UPDATE_CALENDAR = "update_calendar"


class Verdict(str, Enum):
    ALLOW = "allow"  # slipp gjennom uten at noen blir forstyrret
    RED = "red"  # lys rødt og vent på et menneske
    BLOCK = "block"  # stopp, ingen kan godkjenne


class Risk(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ActionRequest(Strict):
    """Det en agent vil gjøre. Sendes til mellomstasjonen, aldri rett til verktøyet."""

    id: str
    ts: datetime
    agent_id: str
    action_type: ActionType
    summary: str = Field(description="Kort beskrivelse skrevet av agenten. Skal IKKE brukes til risikovurdering.")
    amount: float | None = Field(default=None, ge=0, description="NOK")
    recipient: str | None = None
    recipient_known: bool = True
    reversible: bool = True
    contains_personal_data: bool = False
    package_name: str | None = None
    source_doc_id: str | None = Field(default=None, description="Dokumentet som utløste forespørselen, hvis kjent")


class Decision(Strict):
    """Mellomstasjonens avgjørelse. Konsekvenstekst lages av regler, aldri av AI."""

    request_id: str
    ts: datetime
    verdict: Verdict
    risk: Risk
    reasons: list[str] = Field(default_factory=list, description="Regelnavn som slo til, f.eks. 'unknown_recipient'")
    consequence_text: str = Field(description="Norsk klartekst: hva som faktisk skjer. Vises i det røde varselet.")
    requires_typed_amount: bool = False


class HumanResponse(Strict):
    """Svaret fra mennesket på en rød forespørsel."""

    request_id: str
    ts: datetime
    employee_pseudonym: str = Field(description="Aldri navn. Se pseudonymize() i security-modulen.")
    approved: bool
    typed_amount: float | None = None
    seconds_to_decide: float = Field(ge=0)


class TrapEvent(Strict):
    """En felle i et dokument gikk av."""

    ts: datetime
    doc_id: str
    agent_id: str
    trap_id: str
    what_happened: str


class SandboxReport(Strict):
    """Resultatet av å kjøre et tillegg i den lukkede boksen."""

    ts: datetime
    package_name: str
    attempted_network: bool
    destinations: list[str] = Field(default_factory=list)
    verdict: Literal["clean", "blocked", "not_tested"]
    notes: str = ""


class AfterAction(Strict):
    """Én linje på 'Etter'-listen."""

    title: str
    detail: str
    owner_role: str = Field(description="F.eks. 'security', 'finance', 'employee'")
    done: bool = False


LogKind = Literal["request", "decision", "human", "trap", "sandbox", "execution"]


class LogEntry(Strict):
    """Én linje i den låste loggen. Hver linje peker på forrige via hash."""

    seq: int = Field(ge=0)
    ts: datetime
    kind: LogKind
    payload: dict[str, Any]
    prev_hash: str
    hash: str = ""


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def compute_entry_hash(seq: int, ts: datetime, kind: str, payload: dict[str, Any], prev_hash: str) -> str:
    body = canonical_json({"seq": seq, "ts": ts.isoformat(), "kind": kind, "payload": payload, "prev_hash": prev_hash})
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def make_log_entry(seq: int, ts: datetime, kind: LogKind, payload: dict[str, Any], prev_hash: str) -> LogEntry:
    return LogEntry(
        seq=seq,
        ts=ts,
        kind=kind,
        payload=payload,
        prev_hash=prev_hash,
        hash=compute_entry_hash(seq, ts, kind, payload, prev_hash),
    )


def verify_chain(entries: list[LogEntry]) -> int | None:
    """Returnerer seq til første ødelagte linje, eller None hvis alt stemmer."""
    prev = GENESIS_HASH
    for i, e in enumerate(entries):
        if e.seq != i or e.prev_hash != prev:
            return e.seq
        if e.hash != compute_entry_hash(e.seq, e.ts, e.kind, e.payload, e.prev_hash):
            return e.seq
        prev = e.hash
    return None
