"""Dataminimering slaatt paa i demoen.

Loggen skal ikke inneholde mer persondata enn den trenger for at noen skal
kunne granske hva som skjedde. Testene her leser loggen slik en som HAR
noekkelen ser den - altsaa dekryptert - for det er der det betyr noe. At en
kryptert fil ikke inneholder lesbar tekst beviser ingenting om minimering.
"""

from __future__ import annotations

import json

import pytest

from contracts import Verdict
from ui.state import DemoState
from vault import Vault, redact_enabled
from vault.after import build_after_actions

# Kontoen i demoens store overfoering, og agentens egen forklaring paa den.
HEMMELIG_KONTO = "NO93 8601 1117 947"
KJENT_KONTO = "NO55 1122 3344 556"
AGENTENS_TEKST = "Betaler samleoppgjør for takseringsoppdrag, haster før forfall"


@pytest.fixture()
def state() -> DemoState:
    s = DemoState()
    yield s
    s.close()


def _logg_som_tekst(state: DemoState) -> str:
    """Hele loggen slik den staar paa disk, dekryptert og lest paa nytt.

    Vi lager en FERSK Vault mot den samme filen, slik at vi leser det som
    faktisk ble skrevet - ikke det som ligger i minnet.
    """
    paa_disk = Vault(path=state.vault.path)
    return "\n".join(
        json.dumps(e.payload, ensure_ascii=False) for e in paa_disk.entries()
    )


# ---------------------------------------------------------------------------
# bryteren
# ---------------------------------------------------------------------------


def test_demoen_minimerer_som_standard(state):
    assert redact_enabled() is True
    assert state.vault._redact is True
    assert state.snapshot()["log"]["redacted"] is True


def test_bryteren_kan_slaas_av(monkeypatch):
    from vault.store import ENV_REDACT

    for av in ("0", "false", "nei", "AV", "off"):
        monkeypatch.setenv(ENV_REDACT, av)
        assert redact_enabled() is False
    for paa in ("1", "true", "ja", "", "hva som helst"):
        monkeypatch.setenv(ENV_REDACT, paa)
        assert redact_enabled() is True


def test_vault_selv_minimerer_fortsatt_ikke_som_standard():
    """Den som lager en Vault direkte skal ikke faa en overraskelse."""
    assert Vault()._redact is False


# ---------------------------------------------------------------------------
# det som IKKE skal staa i loggen
# ---------------------------------------------------------------------------


def test_raa_kontonumre_staar_ikke_i_loggen(state):
    while state.step_feed() is not None:
        pass
    logg = _logg_som_tekst(state)

    from agents.scenarios import all_scenarios

    lekkasjer = [
        r.recipient for r in all_scenarios() if r.recipient and r.recipient in logg
    ]
    assert lekkasjer == [], f"raa mottakere i loggen: {lekkasjer}"
    assert HEMMELIG_KONTO not in logg
    assert KJENT_KONTO not in logg


def test_agentens_forklaring_staar_ikke_i_loggen(state):
    while state.step_feed() is not None:
        pass
    logg = _logg_som_tekst(state)

    from agents.scenarios import all_scenarios

    for r in all_scenarios():
        assert r.summary not in logg, r.id
    assert AGENTENS_TEKST not in logg
    assert '"summary"' not in logg


def test_konsekvensteksten_legger_ikke_kontoen_tilbake_i_loggen(state):
    """Den skriver ut mottakeren i klartekst naar mottakeren er kjent.

    Uten at den kastes, ville vi maskert kontonummeret i forespoerselen og lagt
    det tilbake to linjer senere i avgjoerelsen.
    """
    while state.step_feed() is not None:
        pass
    logg = _logg_som_tekst(state)
    assert "consequence_text" not in logg
    assert "Overfører" not in logg


def test_mottakeren_staar_maskert_og_gjenkjennelig(state):
    """Minimering er ikke sletting: nok skal staa til aa granske."""
    while state.step_feed() is not None:
        pass
    paa_disk = Vault(path=state.vault.path)
    forespoersler = [
        e.payload for e in paa_disk.entries()
        if e.kind == "request" and e.payload.get("id") == "req_0037"
    ]
    assert forespoersler
    p = forespoersler[0]
    assert p["recipient"] == "**** 947"
    assert p["amount"] == 10_000_000.0
    assert p["recipient_known"] is False
    assert p["action_type"] == "transfer_money"


# ---------------------------------------------------------------------------
# "Proev selv": det juryen skriver skal heller ikke ligge i klartekst
# ---------------------------------------------------------------------------


def test_det_juryen_skriver_havner_ikke_i_klartekst_i_loggen(state):
    min_konto = "NO99 1234 5678 901"
    min_tekst = "Dette er helt rutinemessig og godkjent av ledelsen"

    out = state.submit_custom(
        action_type="transfer_money",
        amount="10 000 000",
        recipient=min_konto,
        summary=min_tekst,
    )
    assert out["ok"] is True
    assert out["card"]["request"]["agent_id"] == "jury"

    logg = _logg_som_tekst(state)
    assert min_konto not in logg
    assert min_tekst not in logg
    # Men nok staar igjen til aa se hva som skjedde.
    assert "**** 901" in logg
    assert "jury" in logg


def test_juryens_e_postadresse_maskeres_ogsaa(state):
    adresse = "hemmelig.person@eksempel.no"
    out = state.submit_custom(
        action_type="send_email", recipient=adresse, contains_personal_data=True
    )
    assert out["ok"] is True
    logg = _logg_som_tekst(state)
    assert adresse not in logg
    assert "hemmelig.person" not in logg


def test_xss_tekst_fra_juryen_lagres_ikke_i_loggen(state):
    nyttelast = "<script>alert('xss')</script>"
    state.submit_custom(action_type="update_calendar", summary=nyttelast)
    assert nyttelast not in _logg_som_tekst(state)


# ---------------------------------------------------------------------------
# alt annet skal fortsatt virke
# ---------------------------------------------------------------------------


def test_sjekk_loggen_virker_paa_en_minimert_logg(state):
    while state.step_feed() is not None:
        pass
    state.submit_custom(action_type="transfer_money", amount="500", recipient="x")

    result = state.verify()
    assert result["ok"] is True
    assert result["seq"] is None
    assert result["lines"] > 0


def test_sjekk_loggen_peker_fortsatt_paa_en_endret_linje(state):
    while state.step_feed() is not None:
        pass
    entries = state.vault._entries
    entries[5] = entries[5].model_copy(update={"payload": {"tuklet": True}})
    assert state.verify()["seq"] == 5


def test_etter_listen_har_riktig_innhold_og_eier_paa_en_minimert_logg(state):
    while state.step_feed() is not None:
        pass
    state.story_start()
    while not state.story_step()["done"]:
        pass

    paa_disk = Vault(path=state.vault.path)
    actions = build_after_actions(paa_disk.entries())
    assert actions

    per_tittel = {a.title: a.owner_role for a in actions}
    assert per_tittel["Sjekk den flaggede overføringen"] == "finance"
    assert per_tittel["Blokkert tillegg maa granskes"] == "security"
    assert per_tittel["Felle gikk av i et dokument"] == "security"
    assert per_tittel["Bytt tilgangene agenten brukte"] == "employee"
    assert per_tittel["Tillegget prøvde aa sende data ut"] == "security"

    tekst = " ".join(a.detail for a in actions)
    # Detaljene skal fortsatt vaere brukbare ...
    assert "10 000 000 kr" in tekst
    assert "req_0037" in tekst
    # ... uten at kontoen staar der.
    assert HEMMELIG_KONTO not in tekst
    assert KJENT_KONTO not in tekst


def test_etter_listen_er_den_samme_med_og_uten_minimering(state, monkeypatch, tmp_path):
    """Minimering skal ikke endre HVILKE oppgaver som kommer ut, bare detaljene."""
    while state.step_feed() is not None:
        pass
    minimert = {a.title for a in build_after_actions(state.vault.entries())}

    from vault.store import ENV_LOG_PATH, ENV_REDACT

    # Egen logg og egen laas, slik at den ikke roerer den minimerte over.
    monkeypatch.setenv(ENV_REDACT, "0")
    monkeypatch.setenv(ENV_LOG_PATH, str(tmp_path / "full.jsonl"))
    full = DemoState()
    try:
        assert full.vault._redact is False
        while full.step_feed() is not None:
            pass
        assert {a.title for a in build_after_actions(full.vault.entries())} == minimert
        # Og her staar kontoen, siden minimering er av. Det er forskjellen.
        assert HEMMELIG_KONTO in "\n".join(
            json.dumps(e.payload, ensure_ascii=False) for e in full.vault.entries()
        )
    finally:
        full.close()


def test_kortet_i_ui_er_uendret_selv_om_loggen_er_minimert(state):
    """Det roede varselet bygges fra minnet, ikke fra loggen."""
    while state.step_feed() is not None:
        pass
    kort = [c for c in state.snapshot()["waiting"] if c["request"]["amount"] == 10_000_000][0]

    assert kort["request"]["summary"] == AGENTENS_TEKST
    assert kort["request"]["recipient"] == HEMMELIG_KONTO
    assert kort["decision"]["consequence_text"] == (
        "Overfører 10 000 000 kr til ukjent konto. Kan ikke angres."
    )
    assert kort["decision"]["requires_typed_amount"] is True


def test_beloepsporten_virker_fortsatt(state):
    while state.step_feed() is not None:
        pass
    kort = [c for c in state.snapshot()["waiting"] if c["request"]["amount"] == 10_000_000][0]
    request_id = kort["request"]["id"]

    assert state.respond(request_id, approved=True, typed_amount="100000,00")["ok"] is False
    out = state.respond(request_id, approved=True, typed_amount="10 000 000")
    assert out["ok"] is True

    # Menneskesvaret staar i loggen, med pseudonym og beloep. Siste linje er
    # utfoeringen, saa menneskesvaret er den nest siste.
    siste = Vault(path=state.vault.path).entries()[-2]
    assert siste.kind == "human"
    assert siste.payload["typed_amount"] == 10_000_000
    assert siste.payload["employee_pseudonym"].startswith("emp_")
    assert "ansatt" not in json.dumps(siste.payload)


def test_foer_listen_virker_fortsatt(state):
    while state.step_feed() is not None:
        pass
    before = state.snapshot()["before"]
    assert before["clean"] >= 1
    assert before["blocked"] >= 1


def test_blokkerte_og_roede_havner_fortsatt_riktig(state):
    while state.step_feed() is not None:
        pass
    snap = state.snapshot()
    for c in snap["waiting"]:
        assert c["decision"]["verdict"] == Verdict.RED.value
    for c in snap["blocked"]:
        assert c["decision"]["verdict"] == Verdict.BLOCK.value
    assert snap["calm_total"] > 0
