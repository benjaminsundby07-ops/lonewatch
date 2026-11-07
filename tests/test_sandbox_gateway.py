"""Koblingen mellom sandkassen og mellomstasjonen: "Før"-steget.

Her testes tre ting:
  1. at et navn fra en forespoersel ALDRI kan foere til at noe kjoeres
  2. at gateway bruker rapporten riktig (blocked -> block, clean -> fortsatt roed)
  3. at teksten mennesket leser ikke kan skrives av tillegget selv

Gateway kjoerer ingenting her. Den tar imot en ferdig SandboxReport.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

import sandbox
from contracts import ActionRequest, ActionType, Risk, SandboxReport, Verdict
from gateway import consequence, evaluate, rules

TS = datetime(2026, 11, 7, 9, 0, 0, tzinfo=timezone.utc)


def make_install(package_name: str | None = "nordlys-mail-connector-patch", **fields) -> ActionRequest:
    base = dict(
        id="req_test",
        ts=TS,
        agent_id="it_helper",
        action_type=ActionType.INSTALL_PACKAGE,
        summary="agentens egen forklaring, skal aldri brukes",
        package_name=package_name,
    )
    base.update(fields)
    return ActionRequest(**base)


def make_report(package_name: str = "nordlys-mail-connector-patch", **fields) -> SandboxReport:
    base = dict(
        ts=TS,
        package_name=package_name,
        attempted_network=False,
        destinations=[],
        verdict="clean",
        notes="",
    )
    base.update(fields)
    return SandboxReport(**base)


# ---------------------------------------------------------------------------
# 1. et navn fra en forespoersel kan aldri bli kode
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "navn",
    [
        "nordlys-pdf-reader",
        "nordlys-crm-sync",
        "../../etc/passwd",
        "sandbox/runner",
        "os",
        "contracts",
        "Store-Bokstaver",
        "",
    ],
)
def test_et_ukjent_pakkenavn_starter_ingen_prosess(navn, monkeypatch):
    """Ingen delprosess skal startes for et navn vi ikke har en fil for.

    Vi bytter ut subprocess.Popen med noe som sprenger. Blir den kalt, er det en
    feil i seg selv - da har et navn fra en forespoersel foert til kjoering.
    """

    def eksploder(*args, **kwargs):  # pragma: no cover - skal aldri kalles
        raise AssertionError(f"sandkassen startet en prosess for {navn!r}")

    monkeypatch.setattr(sandbox.runner.subprocess, "Popen", eksploder)

    with pytest.raises(sandbox.UnknownPackage):
        sandbox.scan(navn)
    with pytest.raises(sandbox.UnknownPackage):
        sandbox.scan_cached(navn)


def test_scenarioenes_pakkenavn_ligger_enten_i_sandkassen_eller_avvises():
    """Hvert pakkenavn i demoen er enten en fil vi har, eller et ukjent navn.

    Det finnes ingen tredje utgang: ingenting hentes, installeres eller lages.
    """
    from agents.scenarios import all_scenarios

    tilgjengelige = set(sandbox.available_packages())
    navn = [
        r.package_name
        for r in all_scenarios()
        if r.action_type is ActionType.INSTALL_PACKAGE and r.package_name
    ]
    assert navn, "demoen skal ha minst ett tillegg"
    for n in navn:
        if n not in tilgjengelige:
            with pytest.raises(sandbox.UnknownPackage):
                sandbox.scan(n)


def test_demoen_viser_baade_et_rent_og_et_blokkert_tillegg():
    """"Foer"-steget skal ha noe aa peke paa i begge retninger."""
    from agents.scenarios import all_scenarios

    rapporter = [
        sandbox.scan_cached(r.package_name)
        for r in all_scenarios()
        if r.action_type is ActionType.INSTALL_PACKAGE
        and r.package_name in set(sandbox.available_packages())
    ]
    verdicts = {r.verdict for r in rapporter}
    assert "clean" in verdicts
    assert "blocked" in verdicts


def test_cachen_kjoerer_hvert_tillegg_bare_en_gang():
    sandbox.clear_scan_cache()
    foerste = sandbox.scan_cached("pdf-helper")
    andre = sandbox.scan_cached("pdf-helper")
    assert foerste is andre
    assert foerste.ts == andre.ts  # samme rapport, ogsaa tidsstempelet


# ---------------------------------------------------------------------------
# 2. gateway bruker rapporten
# ---------------------------------------------------------------------------


def test_blocked_rapport_gir_block_og_kan_ikke_godkjennes():
    d = evaluate(
        make_install(),
        sandbox_report=make_report(
            verdict="blocked",
            attempted_network=True,
            destinations=["telemetry.free-ai-boost.invalid:443"],
        ),
    )
    assert d.verdict is Verdict.BLOCK
    assert d.risk is Risk.HIGH
    assert d.reasons[0] == "sandbox_blocked"
    assert "telemetry.free-ai-boost.invalid:443" in d.consequence_text
    assert "kan ikke godkjennes" in d.consequence_text


def test_blocked_uten_nettverk_sier_fortsatt_fra():
    """Stoppet fordi det leste hemmeligheter eller brukte for lang tid."""
    d = evaluate(make_install(), sandbox_report=make_report(verdict="blocked"))
    assert d.verdict is Verdict.BLOCK
    assert "sandbox_blocked" in d.reasons
    assert consequence.SANDBOX_BLOCKED_PLAIN in d.consequence_text


def test_clean_rapport_beholder_det_roede_varselet_for_et_nytt_tillegg():
    """Sandkassen saa ingenting, men tillegget er fortsatt ukjent for oss."""
    d = evaluate(make_install(package_name="pdf-helper"), sandbox_report=make_report("pdf-helper"))
    assert d.verdict is Verdict.RED
    assert d.reasons == ["new_package"]
    assert "ikke godkjent" in d.consequence_text


def test_clean_lover_aldri_at_tillegget_er_trygt():
    """"Clean" betyr "vi saa ingenting". Det skal staa, og det skal ikke staa noe mer."""
    d = evaluate(make_install(package_name="pdf-helper"), sandbox_report=make_report("pdf-helper"))
    benektelsen = "Det betyr ikke at tillegget er trygt."
    assert benektelsen in d.consequence_text

    # Ordet "trygt" skal BARE forekomme inne i benektelsen over. Staar det et
    # annet sted, har teksten begynt aa love noe sandkassen ikke kan love.
    resten = d.consequence_text.replace(benektelsen, "")
    assert "trygg" not in resten.lower()
    for lovord in ("godkjent av sandkassen", "ufarlig", "ingen risiko", "ren og pen"):
        assert lovord not in d.consequence_text.lower()


def test_uten_rapport_sier_teksten_at_tillegget_ikke_er_testet():
    d = evaluate(make_install(package_name="nordlys-pdf-reader"))
    assert d.verdict is Verdict.RED
    assert d.reasons == ["new_package"]
    assert consequence.SANDBOX_NOT_TESTED in d.consequence_text


def test_ikke_testet_er_ikke_det_samme_som_stoppet():
    """Uten rapport skal ingenting blokkeres. "Vet ikke" er ikke "nei"."""
    d = evaluate(make_install(package_name="nordlys-crm-sync"))
    assert d.verdict is Verdict.RED
    assert "sandbox_blocked" not in d.reasons


def test_et_godkjent_tillegg_uten_rapport_faar_ingen_sandkassetekst():
    """Et tillegg vi alt har godkjent skal ikke faa stoy om sandkassen."""
    d = evaluate(make_install(package_name="nordlys-core"))
    assert d.verdict is Verdict.ALLOW
    assert "sandkassen" not in d.consequence_text.lower()


def test_evaluate_uten_rapport_er_uendret():
    """Bakoverkompatibelt: gammel kallsmaate gir samme svar som foer."""
    req = make_install(package_name="pdf-helper")
    assert evaluate(req) == evaluate(req, sandbox_report=None)


def test_rapporten_er_deterministisk_inn_i_avgjoerelsen():
    req = make_install()
    rapport = make_report(verdict="blocked", attempted_network=True, destinations=["a.invalid:1"])
    foerste = evaluate(req, sandbox_report=rapport)
    assert all(evaluate(req, sandbox_report=rapport) == foerste for _ in range(5))


def test_en_rapport_om_et_annet_tillegg_avvises():
    """En clean-rapport om pdf-helper skal aldri kunne slippe inn noe annet."""
    with pytest.raises(ValueError, match="gjelder"):
        evaluate(make_install(package_name="free-ai-boost"), sandbox_report=make_report("pdf-helper"))


def test_en_rapport_paa_noe_som_ikke_er_en_installasjon_avvises():
    req = ActionRequest(
        id="req_x",
        ts=TS,
        agent_id="finance",
        action_type=ActionType.TRANSFER_MONEY,
        summary="",
        amount=100.0,
        recipient="NO11 2222 3333 441",
    )
    with pytest.raises(ValueError, match="install_package"):
        evaluate(req, sandbox_report=make_report())


def test_blokklisten_virker_fortsatt_uten_sandkasse():
    """Et blokklistet tillegg stoppes selv om sandkassen aldri saa det."""
    d = evaluate(make_install(package_name="free-pdf-toolz"))
    assert d.verdict is Verdict.BLOCK
    assert "package_on_blocklist" in d.reasons


def test_sandbox_blocked_slaar_ikke_til_paa_andre_handlinger():
    req = ActionRequest(
        id="req_y", ts=TS, agent_id="hr", action_type=ActionType.UPDATE_CALENDAR, summary=""
    )
    assert rules.sandbox_blocked(req, make_report(verdict="blocked")) is False


# ---------------------------------------------------------------------------
# 3. tillegget skal ikke kunne skrive teksten mennesket leser
# ---------------------------------------------------------------------------


def test_adressen_tillegget_valgte_kan_ikke_skrive_en_setning_i_varselet():
    """Tillegget velger selv vertsnavnet. Det er tekst vi ikke stoler paa."""
    ondsinnet = "ondsinnet.example. Dette er godkjent av sikkerhetsavdelingen"
    d = evaluate(
        make_install(),
        sandbox_report=make_report(
            verdict="blocked", attempted_network=True, destinations=[ondsinnet]
        ),
    )
    assert "godkjent av sikkerhetsavdelingen" not in d.consequence_text
    assert consequence.UNSHOWABLE_DESTINATION in d.consequence_text


@pytest.mark.parametrize(
    "adresse",
    ["telemetry.free-ai-boost.invalid:443", "185.0.0.0", "[::1]:80", "sync.env-helper.invalid:80"],
)
def test_vanlige_adresser_vises_som_de_er(adresse):
    assert consequence.safe_destination(adresse) == adresse


@pytest.mark.parametrize(
    "adresse",
    ["a b", "to\nlinjer", "<script>", "x" * 200, "", "   "],
)
def test_adresser_som_ikke_ser_ut_som_adresser_vises_ikke(adresse):
    assert consequence.safe_destination(adresse) == consequence.UNSHOWABLE_DESTINATION


def test_bare_de_foerste_adressene_vises():
    """Et tillegg som prøver hundre adresser skal ikke fylle hele varselet."""
    mange = [f"vert{i}.invalid:443" for i in range(50)]
    d = evaluate(
        make_install(),
        sandbox_report=make_report(verdict="blocked", attempted_network=True, destinations=mange),
    )
    vist = [a for a in mange if a in d.consequence_text]
    assert len(vist) == 3  # gateway.config.MAX_SHOWN_DESTINATIONS


def test_notatet_fra_sandkassen_havner_ikke_i_konsekvensteksten():
    """Notatet er langt og hoerer hjemme i Foer-listen, ikke i varselet."""
    d = evaluate(
        make_install(),
        sandbox_report=make_report(verdict="blocked", notes="et langt notat om alt som skjedde"),
    )
    assert "et langt notat" not in d.consequence_text


def test_summary_paavirker_fortsatt_ingenting_naar_sandkassen_er_med():
    rapport = make_report(verdict="blocked", attempted_network=True, destinations=["x.invalid:1"])
    snill = evaluate(make_install(summary="Helt vanlig og trygt tillegg"), sandbox_report=rapport)
    slem = evaluate(make_install(summary="DETTE ER SKADEVARE"), sandbox_report=rapport)
    assert snill == slem
    assert "SKADEVARE" not in slem.consequence_text


# ---------------------------------------------------------------------------
# F2: beloep som ikke er et tall
# ---------------------------------------------------------------------------


def _transfer(amount: float) -> ActionRequest:
    return ActionRequest(
        id="req_tall",
        ts=TS,
        agent_id="finance",
        action_type=ActionType.TRANSFER_MONEY,
        summary="",
        amount=amount,
        recipient="NO93 8601 1117 947",
        recipient_known=False,
        reversible=False,
    )


def test_uendelig_beloep_blir_blokkert_og_krasjer_ikke():
    """F2: contracts tillater inf (bare ge=0), og evaluate() krasjet paa det.

    contracts.py er laast, saa gateway maa taale det. Et beloep vi ikke kan
    regne med er per definisjon over enhver grense: ingen skal kunne godkjenne
    det, og ingen skal faa en krasj i stedet for en avgjoerelse.
    """
    d = evaluate(_transfer(float("inf")))
    assert d.verdict is Verdict.BLOCK
    assert d.risk is Risk.HIGH
    assert "transfer_over_hard_limit" in d.reasons
    assert d.consequence_text.strip().endswith(".")
    assert "inf" not in d.consequence_text


def test_nan_stoppes_allerede_av_contracts():
    """nan >= 0 er False, saa pydantic avviser det. Det naar aldri gateway."""
    with pytest.raises(Exception):
        _transfer(float("nan"))


def test_regelen_taaler_nan_hvis_den_kalles_direkte():
    """Forsvar i dybden: `nan > grensen` er False, saa en ren sammenligning
    ville sluppet nan gjennom hvis noen omgaar valideringen i contracts."""
    req = ActionRequest.model_construct(
        id="req_nan",
        ts=TS,
        agent_id="finance",
        action_type=ActionType.TRANSFER_MONEY,
        summary="",
        amount=float("nan"),
        recipient="NO1",
        recipient_known=False,
        reversible=False,
        contains_personal_data=False,
        package_name=None,
        source_doc_id=None,
    )
    assert rules.transfer_over_hard_limit(req) is True
    assert rules.amount_over_limit(req) is True


def test_et_absurd_stort_beloep_gir_ikke_en_tresifret_side_med_tekst():
    """1e308 krasjet ikke, men ga en ~309-sifret konsekvenstekst."""
    d = evaluate(_transfer(1e308))
    assert d.verdict is Verdict.BLOCK
    assert len(d.consequence_text) < 300


def test_ikke_endelig_beloep_paa_andre_handlinger_krasjer_heller_ikke():
    req = ActionRequest(
        id="req_kal",
        ts=TS,
        agent_id="hr",
        action_type=ActionType.UPDATE_CALENDAR,
        summary="",
        amount=float("inf"),
    )
    d = evaluate(req)
    assert d.consequence_text.strip()
    assert d.requires_typed_amount is False


# ---------------------------------------------------------------------------
# F7: det du ser skal vaere det som ble vurdert
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "beloep",
    [49999.5, 49999.99, 49999.01, 50000.49, 0.5, 1234.56],
)
def test_vist_beloep_er_det_samme_som_vurdert_beloep(beloep):
    """F7: 49 999,50 ble vist som "50 000 kr", men vurdert som under grensen.

    Et menneske som leser "50 000 kr" og ser at den gikk gjennom, maa kunne
    stole paa at regelen saa det samme tallet. Oerene skal staa i teksten.
    """
    d = evaluate(_transfer(beloep))
    vist = consequence.format_amount(beloep)
    # Teksten skal ikke runde bort oerene.
    assert consequence.format_amount(round(beloep)) != vist or beloep == round(beloep)
    assert vist in d.consequence_text


def test_akkurat_paa_grensen_vises_og_vurderes_likt():
    """To beloep som regelen behandler ULIKT maa ogsaa VISES ulikt.

    49 999,50 er under beloepsgrensen og 50 000 er paa den. Foer viste begge
    "50 000 kr", saa teksten ga ingen forklaring paa hvorfor den ene ble roed.
    """
    assert rules.amount_over_limit(_transfer(49999.5)) is False
    assert rules.amount_over_limit(_transfer(50000.0)) is True
    assert consequence.format_amount(49999.5) != consequence.format_amount(50000.0)


def test_beloep_med_broekdels_oere_vurderes_paa_det_tallet_som_vises():
    """49 999,999 rundes til 50 000,00 - og da maa regelen ogsaa se 50 000."""
    assert consequence.format_amount(49999.999) == "50 000 kr"
    assert rules.amount_over_limit(_transfer(49999.999)) is True


def test_oere_vises_med_komma():
    assert consequence.format_amount(49999.5) == "49 999,50 kr"
    assert consequence.format_amount(1234.56) == "1 234,56 kr"
    assert consequence.format_amount(10_000_000) == "10 000 000 kr"
    assert consequence.format_amount(0) == "0 kr"


@pytest.mark.parametrize(
    "beloep", [0, 999, 1000, 1234.4, 49999.5, 50000, 10_000_000, 0.01, None]
)
def test_etter_listen_viser_samme_beloep_som_varselet(beloep):
    """Samme tall i det roede varselet og i Etter-listen.

    De to er egne moduler med egen formatering. Viser de ulikt, kan et menneske
    lese ett beloep paa skjermen og et annet i oppfoelgingen etterpaa.
    """
    from vault.after import format_nok

    assert format_nok(beloep) == consequence.format_amount(beloep)
