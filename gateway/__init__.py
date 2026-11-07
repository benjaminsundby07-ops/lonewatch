"""Mellomstasjonen: alt en agent vil gjøre går gjennom evaluate() først.

MIDLERTIDIG (skjelett): bare en regel. Overføring av penger til ukjent mottaker gir red,
alt annet gir allow. Ingenting gir block ennå.

Regelen ser kun på strukturerte felt. ActionRequest.summary leses aldri.
"""

from __future__ import annotations

from contracts import ActionRequest, ActionType, Decision, Risk, Verdict

RULE_UNKNOWN_RECIPIENT = "unknown_recipient"


def format_amount(amount: float) -> str:
    """10000000 -> '10 000 000 kr'. Hele kroner, mellomrom mellom tusen."""
    return f"{int(round(amount)):,}".replace(",", " ") + " kr"


def _consequence_text(req: ActionRequest, reasons: list[str]) -> str:
    """Norsk klartekst, satt sammen av regler. Aldri AI, aldri agentens egen summary."""
    if RULE_UNKNOWN_RECIPIENT in reasons:
        belop = format_amount(req.amount) if req.amount is not None else "ukjent beløp"
        tekst = f"Overfører {belop} til ukjent konto {req.recipient}."
        if not req.reversible:
            tekst += " Kan ikke angres."
        return tekst
    return f"Utfører {req.action_type.value} som normalt. Ingen regler slo til."


def evaluate(req: ActionRequest) -> Decision:
    """Avgjør hva som skjer med en forespørsel."""
    reasons: list[str] = []

    if req.action_type is ActionType.TRANSFER_MONEY and not req.recipient_known:
        reasons.append(RULE_UNKNOWN_RECIPIENT)

    if reasons:
        verdict, risk, typed = Verdict.RED, Risk.HIGH, True
    else:
        verdict, risk, typed = Verdict.ALLOW, Risk.LOW, False

    return Decision(
        request_id=req.id,
        ts=req.ts,
        verdict=verdict,
        risk=risk,
        reasons=reasons,
        consequence_text=_consequence_text(req, reasons),
        requires_typed_amount=typed,
    )
