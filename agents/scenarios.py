"""Hardkodede demoscenarioer.

MIDLERTIDIG: tre faste forespørsler. Ingen ekte agent lager disse, de er skrevet for hånd.
"""

from __future__ import annotations

from datetime import datetime, timezone

from contracts import ActionRequest, ActionType


def _ts(second: int) -> datetime:
    return datetime(2026, 11, 7, 10, 15, second, tzinfo=timezone.utc)


def all_scenarios() -> list[ActionRequest]:
    """Returnerer demoens forespørsler i den rekkefølgen de skal spilles."""
    return [
        ActionRequest(
            id="req_0001",
            ts=_ts(0),
            agent_id="office_agent",
            action_type=ActionType.UPDATE_CALENDAR,
            summary="Flytter statusmøtet til torsdag kl 09",
            reversible=True,
        ),
        ActionRequest(
            id="req_0002",
            ts=_ts(5),
            agent_id="report_agent",
            action_type=ActionType.SEND_EMAIL,
            summary="Sender månedsrapport til regnskapsfører",
            recipient="regnskap@kjentpartner.no",
            recipient_known=True,
            reversible=False,
        ),
        ActionRequest(
            id="req_0003",
            ts=_ts(10),
            agent_id="finance_agent",
            action_type=ActionType.TRANSFER_MONEY,
            summary="Betaler faktura fra leverandør",
            amount=10_000_000,
            recipient="NO93 8601 1117 947",
            recipient_known=False,
            reversible=False,
            source_doc_id="doc_invoice_77",
        ),
    ]
