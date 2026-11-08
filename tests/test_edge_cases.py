"""Kantfall rundt pengeoverfoeringer, og prinsippet som ikke kan brytes.

Bakgrunnen er `f912515`: `personal_data_external` gjelder ikke lenger
pengeoverfoeringer. Det er en oppmykning, og en oppmykning er farlig naar den
hviler paa noe agenten selv bestemmer. Filen er delt i fem:

1. pengeoverfoering med persondata i FRITEKST (`summary`, `recipient`)
2. ukjent mottaker
3. beloep over grense
4. tomme felt
5. prinsippet: INGEN oppmykning hviler bare paa et felt agenten fyller ut

Del 5 er den som maa staa. `recipient_known`, `reversible`,
`contains_personal_data`, `recipient` og `package_name` kommer alle fra
agenten. En agent som er lurt - eller som lyver - skal ikke kunne skru av en
regel ved aa fylle ut et felt. Det eneste som kan gjoere en forespoersel
mildere, er et oppslag mot en liste Lonewatch eier
(`INTERNAL_DOMAINS`, `KNOWN_PACKAGES`, `PERSONAL_DATA_RELEVANT_ACTIONS`).

Noen av testene her laaser et HULL, ikke en egenskap. De staar med et navn som
sier det, slik at ingen tror hullet er en beslutning som er tatt. Se
gateway/LIMITS.md.

Ett av dem er siden lukket: en `transfer_money` uten beloep vi kan vurdere gaar
naa til et menneske (`rules.no_usable_transfer_amount`). Testen heter ikke
lenger `..._og_det_er_et_hull`, og del 4 har kantfallene rundt den.
"""

from __future__ import annotations

import ast
import inspect
import itertools
from datetime import datetime, timedelta, timezone

import pytest

from contracts import ActionRequest, ActionType, Risk, Verdict
from gateway import config, evaluate, rules

TS = datetime(2026, 11, 16, 9, 0, tzinfo=timezone.utc)

# Persondata skrevet rett inn i et fritekstfelt. Oppdiktet, som resten av demoen.
FRITEKST_MED_PERSONDATA = (
    "Utbetaling til Ingrid Johanne Hansen, f.nr. 010190-12345, "
    "Storgata 4, 0155 Oslo, konto 1234.56.78901, sak 2026-4471"
)

# Feltene agenten fyller ut selv. Ingen oppmykning skal hvile paa dem alene.
AGENTENS_BRYTERE = ("recipient_known", "reversible", "contains_personal_data")


def betaling(**felt) -> ActionRequest:
    """En ordinaer utbetaling til en kjent, registrert konto."""
    standard = dict(
        id="k1",
        ts=TS,
        agent_id="oppgjor-agent",
        action_type=ActionType.TRANSFER_MONEY,
        summary="syntetisk forespoersel (summary brukes aldri til risiko)",
        amount=4_000.0,
        recipient="kunde Bjornstad, registrert konto",
        recipient_known=True,
        reversible=True,
        contains_personal_data=False,
    )
    return ActionRequest(**{**standard, **felt})


def utlevering(**felt) -> ActionRequest:
    """En e-post ut av huset. `send_email` ER en utlevering naar bryteren staar paa."""
    standard = dict(
        id="u1",
        ts=TS,
        agent_id="kundeservice-agent",
        action_type=ActionType.SEND_EMAIL,
        summary="syntetisk forespoersel (summary brukes aldri til risiko)",
        recipient="ingrid.hansen@gmail.com",
        recipient_known=True,
        reversible=True,
        contains_personal_data=True,
    )
    return ActionRequest(**{**standard, **felt})


def tillegg(**felt) -> ActionRequest:
    standard = dict(
        id="p1",
        ts=TS,
        agent_id="drift-agent",
        action_type=ActionType.INSTALL_PACKAGE,
        summary="syntetisk forespoersel (summary brukes aldri til risiko)",
        package_name="nordlys-core",
        recipient="internt pakkeregister",
        recipient_known=True,
        reversible=False,
        contains_personal_data=False,
    )
    return ActionRequest(**{**standard, **felt})


# ---------------------------------------------------------------------------
# 1: pengeoverfoering med persondata i fritekst
# ---------------------------------------------------------------------------


def test_persondata_i_fritekst_paa_en_utbetaling_gir_ingen_poeng():
    """LAASER ET HULL, ikke en egenskap.

    Fullt navn, foedselsnummer, adresse og kontonummer staar i `summary` og i
    `recipient`. Bryteren `contains_personal_data` staar paa False. Reglene ser
    ingenting, fordi de aldri leser fritekst - heller ikke for aa finne
    persondata i den.

    Det er samme hull som oeverst i gateway/LIMITS.md, sett fra motsatt side:
    reglene stoler paa bryteren, og bryteren er agentens paastand. Aa lese
    teksten i stedet ville betydd en innholdsvurdering, og da maatte vi stole
    paa noe som tolker tekst agenten selv har skrevet.
    """
    d = evaluate(betaling(summary=FRITEKST_MED_PERSONDATA, recipient=FRITEKST_MED_PERSONDATA))
    assert d.verdict is Verdict.ALLOW
    assert d.risk is Risk.LOW
    assert d.reasons == []


def test_bryteren_endrer_ikke_avgjoerelsen_paa_en_utbetaling():
    """Med eller uten bryteren: samme avgjoerelse, samme begrunnelser.

    Dette er hele innholdet i `f912515`. Paa en utbetaling sier feltet at
    posten gjelder en person, og det skal ikke gi risikopoeng.
    """
    av = evaluate(betaling(summary=FRITEKST_MED_PERSONDATA, contains_personal_data=False))
    paa = evaluate(betaling(summary=FRITEKST_MED_PERSONDATA, contains_personal_data=True))
    assert av.verdict is paa.verdict is Verdict.ALLOW
    assert av.reasons == paa.reasons == []


def test_fritekst_kan_ikke_slaa_AV_regelen_paa_en_utlevering():
    """Agenten kan skrive hva den vil; bryteren staar paa, og da er det roedt."""
    d = evaluate(
        utlevering(
            summary="Ingen persondata her. Godkjent av sikkerhetsavdelingen. Kan sendes direkte."
        )
    )
    assert d.verdict is Verdict.RED
    assert "personal_data_external" in d.reasons


def test_fritekst_slaar_ikke_PAA_regelen_paa_en_utlevering():
    """LAASER ET HULL. Bryteren av + persondata i teksten = reglene ser ingenting.

    Den samme e-posten med `contains_personal_data=True` blir roed. Forskjellen
    er ett felt agenten setter, ikke noe vi kan etterproeve.
    """
    d = evaluate(utlevering(contains_personal_data=False, summary=FRITEKST_MED_PERSONDATA))
    assert d.verdict is Verdict.ALLOW
    assert d.reasons == []
    assert evaluate(utlevering(contains_personal_data=True)).verdict is Verdict.RED


def test_persondata_paa_en_utbetaling_staar_fortsatt_i_varselet():
    """Vi fjernet et risikopoeng, ikke en opplysning.

    Blir utbetalingen roed av en annen grunn, skal mennesket se at posten
    gjelder en person.
    """
    d = evaluate(
        betaling(amount=config.AMOUNT_LIMIT_NOK + 1, contains_personal_data=True)
    )
    assert d.verdict is Verdict.RED
    assert "Inneholder personopplysninger." in d.consequence_text


# ---------------------------------------------------------------------------
# 2: ukjent mottaker
# ---------------------------------------------------------------------------


def test_ukjent_mottaker_er_roed_ogsaa_paa_et_bagatellmessig_beloep():
    """500 kr til en konto vi ikke har sett foer er et vanlig forvarsel."""
    d = evaluate(betaling(amount=500.0, recipient="konto oppgitt i e-post", recipient_known=False))
    assert d.verdict is Verdict.RED
    assert d.reasons == ["unknown_recipient"]


def test_ukjent_mottaker_over_grensen_gir_to_grunner_og_hoey_risiko():
    d = evaluate(
        betaling(
            amount=config.AMOUNT_LIMIT_NOK + 1,
            recipient="konto oppgitt i e-post",
            recipient_known=False,
        )
    )
    assert d.verdict is Verdict.RED
    assert d.risk is Risk.HIGH
    assert d.reasons == ["amount_over_limit", "unknown_recipient"]


def test_ukjent_mottaker_uten_mottakerfelt_fanges_av_begge_reglene():
    d = evaluate(betaling(recipient="", recipient_known=False))
    assert d.verdict is Verdict.RED
    assert {"unknown_recipient", "incomplete_request"} <= set(d.reasons)


def test_ukjent_mottaker_krever_at_mennesket_skriver_beloepet():
    """Penger ut av huset til en ukjent konto skal ikke kunne klikkes bort."""
    d = evaluate(betaling(recipient="konto fra e-post", recipient_known=False))
    assert d.requires_typed_amount is True


def test_at_mottakeren_er_kjent_er_agentens_paastand():
    """LAASER ET HULL.

    `recipient_known=True` paa en mottaker som i teksten er aapenbart ukjent
    gir `allow`. Feltet er en paastand vi ikke kan etterproeve uten et
    leverandoerregister. Beloepsreglene gjelder uansett - se del 5.
    """
    d = evaluate(betaling(recipient="ny konto oppgitt i e-post i dag", recipient_known=True))
    assert d.verdict is Verdict.ALLOW
    assert d.reasons == []


# ---------------------------------------------------------------------------
# 3: beloep over grense
# ---------------------------------------------------------------------------


def test_noeyaktig_paa_beloepsgrensen_er_roedt():
    """Grensen er inkluderende."""
    d = evaluate(betaling(amount=config.AMOUNT_LIMIT_NOK))
    assert d.verdict is Verdict.RED
    assert d.reasons == ["amount_over_limit"]


def test_ett_oere_under_grensen_slipper_gjennom():
    """Og det er meningen: en grense maa ha en side som slipper gjennom."""
    d = evaluate(betaling(amount=config.AMOUNT_LIMIT_NOK - 0.01))
    assert d.verdict is Verdict.ALLOW
    assert d.reasons == []


def test_noeyaktig_paa_den_harde_grensen_blir_roedt_ikke_blokkert():
    """Den harde grensen er ekskluderende. Demoens 10 mill. skal bli roed."""
    d = evaluate(betaling(amount=config.HARD_TRANSFER_LIMIT_NOK))
    assert d.verdict is Verdict.RED
    assert "transfer_over_hard_limit" not in d.reasons


def test_over_den_harde_grensen_blir_blokkert():
    d = evaluate(betaling(amount=config.HARD_TRANSFER_LIMIT_NOK + 1))
    assert d.verdict is Verdict.BLOCK
    assert d.reasons[0] == "transfer_over_hard_limit"


def test_et_uleselig_beloep_regnes_som_over_enhver_grense():
    """`inf` er ikke "lite", det er uleselig. Feil lukkes."""
    d = evaluate(betaling(amount=float("inf")))
    assert d.verdict is Verdict.BLOCK


def test_negativt_beloep_kommer_aldri_til_reglene():
    """contracts.py avviser det. Vi tester grensen, ikke vaar egen kode."""
    with pytest.raises(Exception):
        betaling(amount=-1.0)


def test_to_halve_beloep_til_samme_konto_krysser_grensen():
    halv = config.AMOUNT_LIMIT_NOK / 2
    foerste = betaling(id="k1", amount=halv)
    andre = betaling(id="k2", ts=TS + timedelta(hours=1), amount=halv)
    assert evaluate(foerste).verdict is Verdict.ALLOW
    d = evaluate(andre, history=[foerste])
    assert d.verdict is Verdict.RED
    assert "recipient_total_over_limit" in d.reasons


# ---------------------------------------------------------------------------
# 4: tomme felt
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("tomt", ["", "   ", "\t\n"])
def test_utbetaling_uten_mottaker_gaar_til_et_menneske(tomt):
    d = evaluate(betaling(recipient=tomt))
    assert d.verdict is Verdict.RED
    assert "incomplete_request" in d.reasons


@pytest.mark.parametrize("felt", ["agent_id", "id"])
def test_tom_avsender_eller_tom_id_gaar_til_et_menneske(felt):
    """Vet vi ikke hvem som spoer, eller hva svaret skal hete, vurderer vi ikke."""
    d = evaluate(betaling(**{felt: ""}))
    assert d.verdict is Verdict.RED
    assert "incomplete_request" in d.reasons


def test_tillegg_uten_navn_regnes_som_nytt():
    d = evaluate(tillegg(package_name=None))
    assert d.verdict is Verdict.RED
    assert "new_package" in d.reasons


def test_tillegg_trenger_ingen_mottaker():
    """`install_package` sender ingenting ut av huset. Tomt felt betyr ingenting der.

    Tillegget her er ugjenkallelig, saa `irreversible` (vekt 1) staar igjen. Det
    er `low`, altsaa `allow` - og det er grunnen til at vekten ikke kan bli
    staaende hvis `KNOWN_PACKAGES` en dag utvides. Se gateway/LIMITS.md.
    """
    d = evaluate(tillegg(recipient=""))
    assert d.verdict is Verdict.ALLOW
    assert "incomplete_request" not in d.reasons


def test_utbetaling_uten_beloep_gaar_til_et_menneske():
    """HULLET ER LUKKET. Testen het foer `..._slipper_gjennom_og_det_er_et_hull`.

    `amount=None` paa en `transfer_money` betyr at ingen beloepsregel kan si
    noe: `amount_over_limit`, `recipient_total_over_limit` og
    `transfer_over_hard_limit` trenger alle et tall. Med en kjent mottaker var
    svaret `allow` med `reasons == []`.

    `incomplete_request` krevde MOTTAKER paa en utgaaende handling, men ikke
    BELOEP paa en utbetaling. Naa krever den begge. Regelen ser bare om feltet
    finnes - den spoer ikke om noe agenten har fylt ut - saa den kan bare
    stramme inn.
    """
    d = evaluate(betaling(amount=None))
    assert d.verdict is Verdict.RED
    assert "incomplete_request" in d.reasons
    assert rules.no_usable_transfer_amount(betaling(amount=None)) is True


def test_teksten_sier_at_det_er_beloepet_som_mangler():
    """Mennesket skal vite HVA som manglet, ikke bare at noe manglet."""
    d = evaluate(betaling(amount=None))
    assert "Beløpet mangler" in d.consequence_text
    assert "ingen beløpsgrense er sjekket" in d.consequence_text


def test_utbetaling_paa_null_kroner_gaar_til_et_menneske():
    """0 kr er lesbart, men det er ingen utbetaling.

    Testen sa foer at `allow` var riktig her. Det var feil av samme grunn som
    over: vi vet ikke hva forespoerselen gjelder, og da skal den ikke gaa av
    seg selv.
    """
    d = evaluate(betaling(amount=0.0))
    assert d.verdict is Verdict.RED
    assert d.reasons == ["incomplete_request"]
    assert "0 kr" in d.consequence_text


@pytest.mark.parametrize("kjent", [True, False])
@pytest.mark.parametrize("beloep", [None, 0.0, 0])
def test_manglende_eller_tomt_beloep_stoppes_uansett_mottaker(kjent, beloep):
    """Den viktigste av dem: en KJENT mottaker skal ikke hjelpe her.

    Hullet var nettopp at `recipient_known=True` gjorde at ingen regel slo til.
    """
    d = evaluate(betaling(amount=beloep, recipient_known=kjent))
    assert d.verdict is Verdict.RED
    assert "incomplete_request" in d.reasons


@pytest.mark.parametrize("ugyldig", ["", "   ", "abc", "ti tusen", -1, -0.01, float("nan")])
def test_et_beloep_som_ikke_er_et_tall_kommer_aldri_til_reglene(ugyldig):
    """`contracts.py` avviser tom streng, tekst, negative tall og nan.

    Vi tester grensen utenfor vaar egen kode, slik at regelen ikke later som den
    forsvarer noe `contracts` alt stopper. `no_usable_transfer_amount` daekker
    negative beloep uansett, som reserve hvis `ge=0` en dag forsvinner.
    """
    with pytest.raises(Exception):
        betaling(amount=ugyldig)


@pytest.mark.parametrize("stort", [1e15, 1e300, float("inf")])
def test_et_svaert_stort_beloep_regnes_som_over_grensen_ikke_som_manglende(stort):
    """Uleselig er ikke det samme som manglende.

    Et beloep vi ikke kan lese blir blokkert av `transfer_over_hard_limit`. Det
    er et annet svar enn `incomplete_request`, og det skal det vaere: her har vi
    et tall, det er bare for stort til aa vaere et beloep. Se F2 i
    docs/REDTEAM.md.
    """
    req = betaling(amount=stort)
    assert rules.no_usable_transfer_amount(req) is False
    d = evaluate(req)
    assert d.verdict is Verdict.BLOCK
    assert "transfer_over_hard_limit" in d.reasons


def test_et_manglende_beloep_paa_noe_som_ikke_er_en_utbetaling_betyr_ingenting():
    """En e-post har ikke noe beloep, og det er helt normalt."""
    d = evaluate(utlevering(contains_personal_data=False, amount=None))
    assert d.verdict is Verdict.ALLOW
    assert d.reasons == []
    assert rules.no_usable_transfer_amount(utlevering(amount=None)) is False


# ---------------------------------------------------------------------------
# 5: prinsippet - ingen oppmykning hviler paa et felt agenten fyller ut
# ---------------------------------------------------------------------------


FARLIGE_KJERNER = {
    "beloep over grensen": lambda **b: betaling(amount=config.AMOUNT_LIMIT_NOK + 1, **b),
    "over den harde grensen": lambda **b: betaling(
        amount=config.HARD_TRANSFER_LIMIT_NOK + 1, **b
    ),
    "uleselig beloep": lambda **b: betaling(amount=float("inf"), **b),
    "tillegg paa blokklisten": lambda **b: tillegg(package_name="free-pdf-toolz", **b),
    "utbetaling uten beloep": lambda **b: betaling(amount=None, **b),
    "utbetaling paa 0 kr": lambda **b: betaling(amount=0.0, **b),
    "ukjent handlingstype-daekning": lambda **b: betaling(recipient="", **b),
}


@pytest.mark.parametrize("kjerne", sorted(FARLIGE_KJERNER))
@pytest.mark.parametrize("kombinasjon", list(itertools.product((True, False), repeat=3)))
def test_agentens_brytere_kan_ikke_gjoere_en_farlig_sak_til_allow(kjerne, kombinasjon):
    """Alle 8 kombinasjoner av de tre bryterne, paa 5 farlige kjerner.

    Dette er prinsippet, maalt: en agent som fyller ut `recipient_known`,
    `reversible` og `contains_personal_data` slik det passer den, kommer ikke
    gjennom noen av disse.
    """
    brytere = dict(zip(AGENTENS_BRYTERE, kombinasjon))
    d = evaluate(FARLIGE_KJERNER[kjerne](**brytere))
    assert d.verdict is not Verdict.ALLOW, f"{kjerne} ble allow med {brytere}"


@pytest.mark.parametrize("kombinasjon", list(itertools.product((True, False), repeat=3)))
def test_beloepsreglene_leser_ingen_av_agentens_brytere(kombinasjon):
    """Samme svar fra alle tre beloepsreglene, uansett hva bryterne staar paa."""
    brytere = dict(zip(AGENTENS_BRYTERE, kombinasjon))
    req = betaling(amount=config.AMOUNT_LIMIT_NOK + 1, **brytere)
    assert rules.amount_over_limit(req) is True
    assert rules.transfer_over_hard_limit(req) is False
    assert rules.recipient_total_over_limit(req, []) is False


@pytest.mark.parametrize(
    "mottaker",
    [
        "Skatteetaten, skattetrekkskonto",
        "internt pakkeregister",
        "kunde@nordlysforsikringe.no",  # skrivefeil-domene, ikke vaart
        "takst.nordlys@protonmail.com",  # ser internt ut, ligger hos protonmail
        "nordlysforsikring.no@gmail.com",  # vaart domene som brukernavn
        "kalender:drift-felles",  # intern ressurs, men dette er en utlevering
        "post@nordlysforsikring.no.angriper.example",
    ],
)
def test_fritekst_i_mottakerfeltet_mykner_ingenting(mottaker):
    """Et navn er ikke et oppslag.

    `recipient` er fritekst agenten skriver. Den eneste veien til `allow` for
    en utlevering er at VERTSNAVNET staar paa `INTERNAL_DOMAINS` - en liste
    Lonewatch eier - sammenlignet eksakt paa punktum-grense.
    """
    d = evaluate(utlevering(recipient=mottaker))
    assert d.verdict is Verdict.RED
    assert "personal_data_external" in d.reasons


def test_internt_domene_er_den_eneste_veien_til_allow():
    """Motstykket til testen over: naar oppslaget treffer, er det vanlig arbeid."""
    d = evaluate(utlevering(recipient="kollega@nordlysforsikring.no"))
    assert d.verdict is Verdict.ALLOW
    assert d.reasons == []


def test_prefikset_teller_ikke_paa_en_handling_som_sender_noe_ut_av_huset():
    """Et prefiks stiller ingen betingelse ut over seg selv.

    `kalender:` var foer nok til aa gjoere en `share_data` med persondata til
    `allow`. Ni tegn i et fritekstfelt agenten fyller ut selv er ikke et
    oppslag. Prefikset teller naa bare der ingenting sendes ut.
    """
    for handling in sorted(config.OUTBOUND_ACTIONS, key=lambda a: a.value):
        req = utlevering(action_type=handling, recipient="kalender:drift-felles", amount=None)
        assert rules.internal_recipient(req) is False, handling

    kalender = ActionRequest(
        id="c1",
        ts=TS,
        agent_id="drift-agent",
        action_type=ActionType.UPDATE_CALENDAR,
        summary="syntetisk forespoersel",
        recipient="kalender:drift-felles",
        recipient_known=True,
        reversible=True,
        contains_personal_data=True,
    )
    assert rules.internal_recipient(kalender) is True


@pytest.mark.parametrize(
    "navn",
    [
        "nordlys-core-v2",
        "nordlys_core",
        "nordlyscore",
        "nordlys-core.evil",
        "nordlys-core-patch",
        "pdf-tools-pro",
    ],
)
def test_et_pakkenavn_som_LIGNER_et_godkjent_navn_er_fortsatt_nytt(navn):
    """Oppslaget er eksakt. Et navn som ligner er ikke et navn som staar der."""
    req = tillegg(package_name=navn)
    assert rules.new_package(req) is True
    assert evaluate(req).verdict is Verdict.RED


@pytest.mark.parametrize("navn", ["nordlys-core", "NORDLYS-CORE", "  nordlys-core  "])
def test_bare_skrivemaaten_normaliseres(navn):
    """Store bokstaver og luft rundt er ikke et annet tillegg."""
    assert rules.new_package(tillegg(package_name=navn)) is False


def test_oppmykningene_er_laast_til_lister_lonewatch_eier():
    """De tre stedene en regel kan la noe passere, og hva de spoer.

    - `PERSONAL_DATA_RELEVANT_ACTIONS`: handlingstype, vaar liste
    - `INTERNAL_DOMAINS`: vertsnavn, vaar liste, eksakt sammenligning
    - `KNOWN_PACKAGES`: pakkenavn, vaar liste, eksakt sammenligning

    Ingen av dem er et felt agenten fyller ut med fri verdi. Kommer det en
    fjerde oppmykning, skal denne testen tvinge den samme formen.
    """
    for liste in (
        config.PERSONAL_DATA_RELEVANT_ACTIONS,
        config.INTERNAL_DOMAINS,
        config.KNOWN_PACKAGES,
    ):
        assert isinstance(liste, frozenset)
        assert liste, "en tom liste ville gjort oppslaget meningsloest"

    # Lista over handlinger som utleverer er alltid en delmengde av de utgaaende.
    assert config.PERSONAL_DATA_RELEVANT_ACTIONS <= config.OUTBOUND_ACTIONS
    assert ActionType.TRANSFER_MONEY not in config.PERSONAL_DATA_RELEVANT_ACTIONS


@pytest.mark.parametrize(
    "regel",
    [
        rules.amount_over_limit,
        rules.transfer_over_hard_limit,
        rules.recipient_total_over_limit,
        rules.recipient_total_ore,
    ],
)
def test_ingen_beloepsregel_naevner_et_felt_agenten_fyller_ut(regel):
    """Lest i kilden, ikke bare maalt paa utsiden.

    En senere endring som tar inn `recipient_known` i en beloepsregel skal
    stoppe her, ogsaa hvis den tilfeldigvis gir riktig svar paa dagens saker.
    """
    kilde = inspect.getsource(regel)
    for felt in ("recipient_known", "reversible", "contains_personal_data", ".summary"):
        assert felt not in kilde, f"{regel.__name__} leser {felt}"


def test_ingen_regel_leser_agentens_egen_forklaring():
    """`summary` staar i kommentarer og dokumentasjon, men aldri i koden.

    Lest med `ast`, ikke med tekstsoek: en kommentar som NEVNER feltet skal
    ikke gi utslag, et oppslag i det skal.
    """
    tre = ast.parse(inspect.getsource(rules))
    oppslag = [
        node
        for node in ast.walk(tre)
        if isinstance(node, ast.Attribute) and node.attr == "summary"
    ]
    assert oppslag == [], "en regel leser agentens egen forklaring"
