"""Feil lukkes: alt vi ikke klarer aa vurdere gaar til et menneske.

Hullet var at en forespoersel kunne ende som `allow` med `reasons == []` -
altsaa uten at én eneste regel hadde sagt noe om den. En e-post uten adresse
eller en overfoering uten konto gikk rett gjennom hvis agenten samtidig oppga
`recipient_known=True`.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from contracts import ActionRequest, ActionType, Verdict
from gateway import config, evaluate, rules

TS = datetime(2026, 11, 7, 9, 0, tzinfo=timezone.utc)


def req(**felt) -> ActionRequest:
    base = dict(id="req_x", ts=TS, agent_id="finance", summary="agentens egen tekst")
    base.update(felt)
    return ActionRequest(**base)


# ---------------------------------------------------------------------------
# utgaaende uten mottaker
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("handling", sorted(a.value for a in config.OUTBOUND_ACTIONS))
@pytest.mark.parametrize("mottaker", [None, "", "   ", "\t\n"])
def test_utgaaende_uten_mottaker_gaar_til_et_menneske(handling, mottaker):
    """Ogsaa naar agenten paastaar at mottakeren er kjent."""
    d = evaluate(req(action_type=ActionType(handling), recipient=mottaker, recipient_known=True))
    assert d.verdict is Verdict.RED
    assert "incomplete_request" in d.reasons
    assert "klarte ikke å vurdere" in d.consequence_text


def test_overfoering_uten_konto_slipper_ikke_gjennom():
    """Det verste enkelttilfellet: penger til ingen oppgitt konto."""
    d = evaluate(req(action_type=ActionType.TRANSFER_MONEY, amount=100,
                     recipient=None, recipient_known=True))
    assert d.verdict is Verdict.RED
    assert "incomplete_request" in d.reasons


def test_en_mottaker_som_finnes_slaar_ikke_til():
    d = evaluate(req(action_type=ActionType.SEND_EMAIL,
                     recipient="post@nordrebilpleie.no", recipient_known=True))
    assert d.verdict is Verdict.ALLOW
    assert d.reasons == []


def test_lesing_og_kalender_trenger_ingen_mottaker():
    """Regelen gjelder bare det som sendes UT av huset."""
    for handling in (ActionType.READ_DOCUMENT, ActionType.UPDATE_CALENDAR):
        d = evaluate(req(action_type=handling, recipient=None))
        assert d.verdict is Verdict.ALLOW, handling


# ---------------------------------------------------------------------------
# hvem spoer
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("agent", ["", "   ", "\n"])
def test_tom_agent_id_gaar_til_et_menneske(agent):
    d = evaluate(req(action_type=ActionType.READ_DOCUMENT, agent_id=agent))
    assert d.verdict is Verdict.RED
    assert "incomplete_request" in d.reasons


@pytest.mark.parametrize("ident", ["", "  "])
def test_tom_id_gaar_til_et_menneske(ident):
    d = evaluate(req(action_type=ActionType.READ_DOCUMENT, id=ident))
    assert d.verdict is Verdict.RED
    assert "incomplete_request" in d.reasons


# ---------------------------------------------------------------------------
# en handlingstype ingen regel dekker
# ---------------------------------------------------------------------------


def test_alle_dagens_handlingstyper_er_dekket():
    """Staar en type ikke i COVERED_ACTIONS, skal den fanges - ikke gaa gjennom."""
    assert set(config.COVERED_ACTIONS) == set(ActionType)


def test_en_fremtidig_handlingstype_gaar_til_et_menneske(monkeypatch):
    """Legger noen en ny verdi i contracts.ActionType uten aa skrive en regel,
    skal den havne hos et menneske i stedet for aa bli stilltiende godkjent."""
    monkeypatch.setattr(
        config, "COVERED_ACTIONS",
        frozenset(set(config.COVERED_ACTIONS) - {ActionType.UPDATE_CALENDAR}),
    )
    d = evaluate(req(action_type=ActionType.UPDATE_CALENDAR))
    assert d.verdict is Verdict.RED
    assert "incomplete_request" in d.reasons


# ---------------------------------------------------------------------------
# det contracts stopper foer gateway ser det
# ---------------------------------------------------------------------------


def test_ukjent_handlingstype_avvises_av_contracts():
    with pytest.raises(Exception):
        req(action_type="finnes_ikke")


def test_negativt_beloep_avvises_av_contracts():
    with pytest.raises(Exception):
        req(action_type=ActionType.TRANSFER_MONEY, amount=-5, recipient="NO1")


def test_ukjent_felt_avvises_av_contracts():
    """Strict-modellen fanger ogsaa et felt ingen kjenner."""
    with pytest.raises(Exception):
        req(action_type=ActionType.SEND_EMAIL, recipient="a@b.no", finnes_ikke=True)


# ---------------------------------------------------------------------------
# regelen koster ingenting paa data vi har
# ---------------------------------------------------------------------------


def test_regelen_slaar_ikke_til_paa_noen_ekte_forespoersel():
    """Maalt foer den ble innfoert: null treff i alle fire datasettene.

    En fail-closed regel som slaar til paa vanlig trafikk er en daarlig regel.
    Denne skal bare treffe noe ingen har laget ennaa.
    """
    import json
    import pathlib

    from agents.scenarios import all_scenarios
    from gateway import evaluation

    treff = [r.id for r in all_scenarios() if rules.incomplete_request(r)]
    assert treff == [], treff

    treff = [c.req.id for c in evaluation.all_cases() if rules.incomplete_request(c.req)]
    assert treff == [], treff

    lab = ("bor_stoppes", "usikker", "hvorfor")
    for navn in ("blind_set_1.json", "blind_set_2.json"):
        sti = pathlib.Path(__file__).parent / "data" / navn
        rader = json.loads(sti.read_text(encoding="utf-8"))
        treff = [
            r["id"] for r in rader
            if rules.incomplete_request(
                ActionRequest(**{k: v for k, v in r.items() if k not in lab})
            )
        ]
        assert treff == [], f"{navn}: {treff}"


# ---------------------------------------------------------------------------
# destruktive endringer
# ---------------------------------------------------------------------------


def test_sletting_i_kalender_blir_roedt():
    d = evaluate(req(action_type=ActionType.UPDATE_CALENDAR, reversible=False))
    assert d.verdict is Verdict.RED
    assert d.reasons == ["destructive_change"]
    assert "slettet eller overskrevet" in d.consequence_text


def test_lesing_som_ikke_kan_angres_sier_at_det_er_en_selvmotsigelse():
    d = evaluate(req(action_type=ActionType.READ_DOCUMENT, reversible=False,
                     source_doc_id="doc_1"))
    assert d.verdict is Verdict.RED
    assert "destructive_change" in d.reasons
    assert "oppgitt som lesing, men også som umulig å angre" in d.consequence_text.lower()


def test_vanlig_lesing_og_kalender_slipper_fortsatt_gjennom():
    for handling in (ActionType.READ_DOCUMENT, ActionType.UPDATE_CALENDAR):
        d = evaluate(req(action_type=handling, reversible=True))
        assert d.verdict is Verdict.ALLOW, handling


def test_install_package_dubleres_ikke():
    """install_package dekkes allerede av `irreversible`.

    Aa ta den med i destructive_change ville gitt to poeng for det samme uten
    aa fange noe nytt - alle install-tilfellene i begge blindsettene er
    allerede roede via new_package.
    """
    d = evaluate(req(action_type=ActionType.INSTALL_PACKAGE,
                     package_name="noe-ukjent", reversible=False))
    assert "destructive_change" not in d.reasons
    assert "irreversible" in d.reasons
    assert ActionType.INSTALL_PACKAGE not in config.DESTRUCTIVE_RELEVANT_ACTIONS


def test_agentens_tekst_paavirker_ingen_av_de_nye_reglene():
    felles = dict(action_type=ActionType.UPDATE_CALENDAR, reversible=False)
    snill = evaluate(req(summary="Rydder bare litt, helt ufarlig", **felles))
    slem = evaluate(req(summary="SLETTER ALT, STOPP MEG", **felles))
    assert snill.reasons == slem.reasons
    assert snill.consequence_text == slem.consequence_text
