"""Hullene maalingen mot blindsettet avdekket.

Se docs/MALING.md. Hver test her svarer til et konkret tilfelle i
tests/data/blind_set_1.json, og feilet foer regelen ble rettet.
"""

from __future__ import annotations

import json
import pathlib
from datetime import datetime, timedelta, timezone

import pytest

from contracts import ActionRequest, ActionType, Verdict
from gateway import config, evaluate, rules

BLIND = pathlib.Path(__file__).parent / "data" / "blind_set_1.json"
LABELS = ("bor_stoppes", "usikker", "hvorfor")
TS = datetime(2026, 11, 7, 9, 0, tzinfo=timezone.utc)


def blind(request_id: str) -> ActionRequest:
    """Henter én forespoersel fra blindsettet, uten de menneskelige merkelappene."""
    rows = json.loads(BLIND.read_text(encoding="utf-8"))
    row = next(r for r in rows if r["id"] == request_id)
    return ActionRequest(**{k: v for k, v in row.items() if k not in LABELS})


# ---------------------------------------------------------------------------
# HULL 1: persondata til en KJENT ekstern mottaker
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("request_id", ["blind_018", "blind_043", "blind_050"])
def test_persondata_til_kjent_ekstern_mottaker_blir_roedt(request_id):
    """"Kjent" betyr ikke "intern". Disse slapp gjennom foer.

    blind_018 masseutsending til 8400 kunder, blind_043 hele skadeportefoeljen
    til et due diligence-team, blind_050 helsedata til en bedriftshelsetjeneste.
    Alle med recipient_known=True.
    """
    d = evaluate(blind(request_id))
    assert d.verdict is Verdict.RED
    assert "personal_data_external" in d.reasons


def test_persondata_til_intern_mottaker_slipper_fortsatt_gjennom():
    """Internt skal ikke forstyrre noen. Ellers blir roedt utvannet."""
    req = ActionRequest(
        id="x", ts=TS, agent_id="hr", action_type=ActionType.SEND_EMAIL,
        summary="", recipient="nyansatt@nordlysforsikring.no",
        recipient_known=True, contains_personal_data=True, reversible=False,
    )
    assert rules.internal_recipient(req) is True
    assert "personal_data_external" not in evaluate(req).reasons
    assert evaluate(req).verdict is Verdict.ALLOW


@pytest.mark.parametrize(
    "mottaker,intern",
    [
        ("nyansatt@nordlysforsikring.no", True),
        ("LEDERE@NordlysForsikring.NO", True),
        ("artifactory.nordlys.no", True),
        ("kalender:drift-felles", True),
        ("kalender:alle-ansatte", True),
        # Fellene i blindsettet: like nok til aa lure et oeye, ikke en regel.
        ("kunde@nordlysforsikringe.no", False),
        ("takst.nordlys@protonmail.com", False),
        ("post@ikke-nordlysforsikring.no", False),
        ("nordlysforsikring.no.angriper.example", False),
        ("post@bilskadesenteret-as.no", False),
        ("", False),
        (None, False),
    ],
)
def test_intern_mottaker_er_eksakt_domene_ikke_delstreng(mottaker, intern):
    req = ActionRequest(
        id="x", ts=TS, agent_id="a", action_type=ActionType.SEND_EMAIL,
        summary="", recipient=mottaker,
    )
    assert rules.internal_recipient(req) is intern


def test_persondata_til_ukjent_mottaker_er_fortsatt_roedt():
    """Den gamle oppfoerselen skal ikke forsvinne."""
    d = evaluate(blind("blind_006"))
    assert d.verdict is Verdict.RED
    assert "personal_data_external" in d.reasons


def test_uten_persondata_slaar_regelen_ikke_til():
    req = ActionRequest(
        id="x", ts=TS, agent_id="a", action_type=ActionType.SHARE_DATA,
        summary="", recipient="noen@ekstern.example", recipient_known=True,
        contains_personal_data=False,
    )
    assert "personal_data_external" not in evaluate(req).reasons


def test_lesing_og_kalender_rammes_ikke():
    """Regelen gjelder bare det som sendes UT av huset."""
    for handling in (ActionType.READ_DOCUMENT, ActionType.UPDATE_CALENDAR):
        req = ActionRequest(
            id="x", ts=TS, agent_id="a", action_type=handling, summary="",
            recipient="kalender:hr-rekruttering", contains_personal_data=True,
        )
        assert "personal_data_external" not in evaluate(req).reasons
