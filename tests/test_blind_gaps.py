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


# ---------------------------------------------------------------------------
# HULL 2: reglene har ingen hukommelse
# ---------------------------------------------------------------------------


def _transfer(nr: int, belop: float, konto: str, minutter: int = 0) -> ActionRequest:
    return ActionRequest(
        id=f"t{nr:04d}",
        ts=TS + timedelta(minutes=minutter),
        agent_id="finance",
        action_type=ActionType.TRANSFER_MONEY,
        summary="",
        amount=belop,
        recipient=konto,
        recipient_known=True,
        reversible=False,
    )


KONTO = "NO12 3456 7890 123"


def test_tre_overfoeringer_paa_20000_gir_roedt_paa_den_tredje():
    """Hver for seg under grensen. Til sammen 60 000."""
    historikk: list[ActionRequest] = []
    avgjorelser = []
    for i in range(3):
        req = _transfer(i, 20_000, KONTO, minutter=i * 10)
        avgjorelser.append(evaluate(req, history=historikk))
        historikk.append(req)

    assert avgjorelser[0].verdict is Verdict.ALLOW
    assert avgjorelser[1].verdict is Verdict.ALLOW

    tredje = avgjorelser[2]
    assert tredje.verdict is Verdict.RED
    assert "recipient_total_over_limit" in tredje.reasons
    # Summen er de tre til sammen, ikke bare de to foerste.
    assert "Til sammen 60 000 kr til samme mottaker siste 24 timer." in tredje.consequence_text
    # Og enkeltbeloepet staar fortsatt foerst, saa mennesket ser begge tall.
    assert tredje.consequence_text.startswith("Overfører 20 000 kr")
    assert tredje.requires_typed_amount is True


def test_hundre_overfoeringer_paa_49999_blir_roede_naar_summen_krysser():
    """Hullet i ren form: 100 x 49 999 kr til en KJENT konto."""
    historikk: list[ActionRequest] = []
    forste_roede = None
    for i in range(100):
        req = _transfer(i, 49_999, KONTO, minutter=i)
        d = evaluate(req, history=historikk)
        if d.verdict is Verdict.RED and forste_roede is None:
            forste_roede = i
        historikk.append(req)

    # Den foerste er under grensen og skal slippe gjennom.
    assert forste_roede == 1, forste_roede


def test_ulike_mottakere_summeres_ikke():
    historikk = [
        _transfer(0, 20_000, "NO11 1111 1111 111", minutter=0),
        _transfer(1, 20_000, "NO22 2222 2222 222", minutter=5),
    ]
    d = evaluate(_transfer(2, 20_000, "NO33 3333 3333 333", minutter=10), history=historikk)
    assert d.verdict is Verdict.ALLOW
    assert "recipient_total_over_limit" not in d.reasons


def test_mottakeren_gjenkjennes_uavhengig_av_mellomrom_og_store_bokstaver():
    historikk = [
        _transfer(0, 20_000, "NO12 3456 7890 123", minutter=0),
        _transfer(1, 20_000, "no1234567890123", minutter=5),
    ]
    d = evaluate(_transfer(2, 20_000, "NO12 3456 7890 123", minutter=10), history=historikk)
    assert "recipient_total_over_limit" in d.reasons


def test_forespoersler_utenfor_vinduet_summeres_ikke():
    """Vinduet regnes fra forespoerselens ts, ikke fra klokken."""
    gammel = _transfer(0, 40_000, KONTO, minutter=0)
    historikk = [gammel]

    # 25 timer senere: den gamle teller ikke lenger.
    utenfor = _transfer(1, 20_000, KONTO, minutter=25 * 60)
    assert evaluate(utenfor, history=historikk).verdict is Verdict.ALLOW

    # 23 timer senere: den teller.
    innenfor = _transfer(2, 20_000, KONTO, minutter=23 * 60)
    assert "recipient_total_over_limit" in evaluate(innenfor, history=historikk).reasons


def test_regelen_dublerer_ikke_et_beloep_som_alt_er_over_grensen():
    """Et enkelt beloep over grensen fanges av amount_over_limit alene.

    Ellers ville eksisterende roede kort flyttet seg fra medium til high uten
    at noe nytt var oppdaget.
    """
    d = evaluate(_transfer(0, 112_500, KONTO), history=[])
    assert "amount_over_limit" in d.reasons
    assert "recipient_total_over_limit" not in d.reasons


def test_uten_historikk_er_evaluate_uendret():
    """Bakoverkompatibelt: gammel kallsmaate gir samme svar som foer."""
    req = _transfer(0, 20_000, KONTO)
    assert evaluate(req) == evaluate(req, history=None) == evaluate(req, history=[])


def test_bare_overfoeringer_summeres():
    historikk = [
        ActionRequest(
            id="e1", ts=TS, agent_id="a", action_type=ActionType.SEND_EMAIL,
            summary="", amount=40_000, recipient=KONTO, recipient_known=True,
        )
    ]
    d = evaluate(_transfer(1, 20_000, KONTO, minutter=5), history=historikk)
    assert "recipient_total_over_limit" not in d.reasons


def test_summen_regnes_i_hele_oere():
    """0,5 kr x 2 skal ikke bli 0,9999 av flyttall."""
    historikk = [_transfer(i, 16_666.67, KONTO, minutter=i * 5) for i in range(2)]
    d = evaluate(_transfer(2, 16_666.66, KONTO, minutter=10), history=historikk)
    assert "recipient_total_over_limit" in d.reasons
    assert "50 000 kr" in d.consequence_text
