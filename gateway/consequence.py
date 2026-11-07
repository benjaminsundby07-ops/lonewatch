"""Konsekvensteksten: norsk klartekst om hva som faktisk skjer.

Teksten settes sammen av maler og felt fra ActionRequest. Den kommer ALDRI
fra en AI-modell, og `req.summary` brukes aldri: agenten skal ikke få skrive
teksten mennesket leser før det godkjenner.
"""

from __future__ import annotations

from contracts import ActionRequest, ActionType

from . import config

UNKNOWN_ACCOUNT = "ukjent konto"
UNKNOWN_RECIPIENT = "ukjent mottaker"
UNKNOWN_AMOUNT = "ukjent beløp"
IRREVERSIBLE_NOTE = "Kan ikke angres."
PERSONAL_DATA_NOTE = "Inneholder personopplysninger."
BLOCKED_NOTE = "Dette stoppes automatisk og kan ikke godkjennes."


def format_amount(amount: float | None) -> str:
    """10000000 -> '10 000 000 kr'. Hele kroner, mellomrom som tusenskille."""
    if amount is None:
        return UNKNOWN_AMOUNT
    return f"{int(round(amount)):,}".replace(",", " ") + " kr"


def _recipient_phrase(req: ActionRequest, unknown_text: str) -> str:
    """'ukjent konto' når mottakeren ikke er kjent, ellers mottakeren selv."""
    if not req.recipient_known or not req.recipient:
        return unknown_text
    return req.recipient


def _base_text(req: ActionRequest) -> str:
    """Første setning: hva handlingen gjør, i klartekst."""
    if req.action_type is ActionType.TRANSFER_MONEY:
        return f"Overfører {format_amount(req.amount)} til {_recipient_phrase(req, UNKNOWN_ACCOUNT)}."

    if req.action_type is ActionType.SEND_EMAIL:
        return f"Sender e-post til {_recipient_phrase(req, UNKNOWN_RECIPIENT)}."

    if req.action_type is ActionType.SHARE_DATA:
        return f"Deler data med {_recipient_phrase(req, UNKNOWN_RECIPIENT)}."

    if req.action_type is ActionType.INSTALL_PACKAGE:
        name = (req.package_name or "").strip()
        if not name:
            return "Installerer et tillegg uten navn."
        return f"Installerer tillegget {name}."

    if req.action_type is ActionType.READ_DOCUMENT:
        if req.source_doc_id:
            return f"Leser dokumentet {req.source_doc_id}."
        return "Leser et dokument."

    if req.action_type is ActionType.UPDATE_CALENDAR:
        return "Oppdaterer kalenderen."

    # Nye handlingstyper i contracts skal ikke gi en tom tekst.
    return f"Utfører handlingen {req.action_type.value}."


def build_consequence_text(req: ActionRequest, reasons: list[str], blocked: bool = False) -> str:
    """Setter sammen hele teksten mennesket får se."""
    parts = [_base_text(req)]

    if req.contains_personal_data and req.action_type in config.OUTBOUND_ACTIONS:
        parts.append(PERSONAL_DATA_NOTE)

    if "new_package" in reasons:
        parts.append("Tillegget er ikke godkjent fra før.")

    if "package_on_blocklist" in reasons:
        parts.append("Tillegget står på blokklisten.")

    if "transfer_over_hard_limit" in reasons:
        parts.append(f"Beløpet er over den harde grensen på {format_amount(config.HARD_TRANSFER_LIMIT_NOK)}.")

    # "Kan ikke angres." står i teksten så lenge det er sant for en handling
    # med virkning utenfor huset, selv om regelen ikke ga risikopoeng.
    if not req.reversible and req.action_type in config.EFFECTFUL_ACTIONS:
        parts.append(IRREVERSIBLE_NOTE)

    if blocked:
        parts.append(BLOCKED_NOTE)

    return " ".join(parts)
