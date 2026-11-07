"""Dataminimering: loggen skal inneholde minst mulig, men nok til aa granske.

Tre nivaaer:
- allow (harmløst): bare type, risiko og avgjørelse. Ingen mottaker, ingen beløp.
- red / block: detaljene beholdes, men mottakeren maskeres (bare siste 4 tegn vises).
- forespørsler (vi vet ikke avgjørelsen ennaa): felt reglene trenger beholdes,
  mottakeren maskeres, og agentens frie tekst (summary) kastes.
"""

from __future__ import annotations

from typing import Any

from contracts import LogKind, Verdict

MASK = "****"

# Felt vi beholder naar noe er harmløst.
ALLOW_KEEP = ("request_id", "id", "action_type", "risk", "verdict")

# Felt en forespørsel beholder: det reglene faktisk bruker.
REQUEST_KEEP = (
    "id",
    "agent_id",
    "action_type",
    "amount",
    "recipient",
    "recipient_known",
    "reversible",
    "contains_personal_data",
    "package_name",
    "source_doc_id",
)

# Felt som er fri tekst og derfor aldri trengs i loggen.
DROP_ALWAYS = ("summary",)


def mask_recipient(value: Any) -> Any:
    """Viser bare siste 4 tegn av en mottaker."""
    if not isinstance(value, str) or not value:
        return value
    if len(value) <= 4:
        return MASK
    return MASK + value[-4:]


def _mask_recipients(out: dict[str, Any]) -> dict[str, Any]:
    if out.get("recipient") is not None:
        out["recipient"] = mask_recipient(out["recipient"])
    if isinstance(out.get("destinations"), list):
        out["destinations"] = [mask_recipient(d) for d in out["destinations"]]
    return out


def redact_payload(kind: LogKind, payload: dict[str, Any]) -> dict[str, Any]:
    """Lager en minimert kopi av payload. Endrer aldri originalen."""
    verdict = payload.get("verdict")

    if verdict == Verdict.ALLOW.value:
        return {k: payload[k] for k in ALLOW_KEEP if k in payload}

    if kind == "request":
        out = {k: payload[k] for k in REQUEST_KEEP if k in payload}
        return _mask_recipients(out)

    out = {k: v for k, v in payload.items() if k not in DROP_ALWAYS}
    return _mask_recipients(out)
