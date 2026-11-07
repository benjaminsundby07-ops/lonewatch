"""Mellomstasjonen: alt en agent vil gjøre går gjennom evaluate() først.

Flyten er helt deterministisk:

    1. blokkreglene kjøres   -> slår en til, er svaret block (ingen kan godkjenne)
    2. risikoreglene kjøres  -> navnene legges i Decision.reasons
    3. poengsummen gir risiko low/medium/high
    4. low -> allow, medium/high -> red
    5. konsekvensteksten settes sammen av maler på norsk

Ingen AI-modell er involvert, og `req.summary` leses aldri. Samme forespørsel
gir samme avgjørelse hver gang.
"""

from __future__ import annotations

from contracts import ActionRequest, ActionType, Decision, Risk, Verdict

from . import config, rules
from .consequence import build_consequence_text, format_amount

__all__ = [
    "evaluate",
    "score_to_risk",
    "format_amount",
    "build_consequence_text",
    "config",
    "rules",
]


def score_to_risk(score: int) -> Risk:
    """Poengsum -> risikonivå. Tersklene står i config."""
    if score >= config.HIGH_SCORE_MIN:
        return Risk.HIGH
    if score >= config.MEDIUM_SCORE_MIN:
        return Risk.MEDIUM
    return Risk.LOW


def evaluate(req: ActionRequest) -> Decision:
    """Avgjør hva som skjer med en forespørsel fra en agent."""
    block_reasons = rules.triggered_block_rules(req)
    risk_reasons = rules.triggered_risk_rules(req)

    if block_reasons:
        # Blokk slår alltid risikopoengene. Risikoen settes til high fordi
        # noe vi stopper helt alltid er det alvorligste vi ser.
        reasons = block_reasons + risk_reasons
        return Decision(
            request_id=req.id,
            ts=req.ts,
            verdict=Verdict.BLOCK,
            risk=Risk.HIGH,
            reasons=reasons,
            consequence_text=build_consequence_text(req, reasons, blocked=True),
            requires_typed_amount=False,
        )

    risk = score_to_risk(rules.risk_score(risk_reasons))
    verdict = Verdict.ALLOW if risk is Risk.LOW else Verdict.RED

    # Mennesket må skrive inn beløpet selv når penger skal flyttes og noen må se på det.
    requires_typed_amount = verdict is Verdict.RED and req.action_type is ActionType.TRANSFER_MONEY

    return Decision(
        request_id=req.id,
        ts=req.ts,
        verdict=verdict,
        risk=risk,
        reasons=risk_reasons,
        consequence_text=build_consequence_text(req, risk_reasons),
        requires_typed_amount=requires_typed_amount,
    )
