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
