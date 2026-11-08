"""Reglene. Én liten funksjon per regel, ingen AI, ingen tilfeldighet.

Hver regel ser BARE på strukturerte felt i ActionRequest.
`req.summary` (agentens egen forklaring) leses aldri: en agent som er lurt
eller som lyver skal ikke kunne snakke seg forbi mellomstasjonen.

Navnet på funksjonen er navnet som havner i `Decision.reasons`.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from datetime import timedelta

from contracts import ActionRequest, ActionType, SandboxReport

from . import config
from .money import to_ore


def normalize_package_name(package_name: str | None) -> str:
    """Gjør navn sammenlignbare: små bokstaver, uten luft rundt."""
    if package_name is None:
        return ""
    return package_name.strip().lower()


def _unreadable_amount(amount: float | None) -> bool:
    """Et beløp vi ikke kan regne med: inf, nan, eller for stort til aa leses.

    `contracts.ActionRequest.amount` har bare `ge=0`, saa `float("inf")` er en
    gyldig verdi, og contracts.py er laast. Et slikt beloep er ikke "lite": vi
    kan ikke sammenligne det med noen grense i det hele tatt. Da behandler vi
    det som over enhver grense i stedet for aa la det gaa. Se F2 i
    docs/REDTEAM.md.
    """
    return amount is not None and to_ore(amount) is None


def amount_over_limit(req: ActionRequest) -> bool:
    """Beløpet er på eller over beløpsgrensen.

    Mangler beløp, slår regelen ikke til. Grensen er inkluderende.
    Et beløp vi ikke kan lese regnes alltid som over grensen.

    Sammenligningen skjer i hele øre, nøyaktig det tallet konsekvensteksten
    viser. Ellers kunne 49 999,50 blitt vurdert under grensen og samtidig vist
    som "50 000 kr" (F7 i docs/REDTEAM.md).
    """
    if req.amount is None:
        return False
    ore = to_ore(req.amount)
    if ore is None:
        return True
    return ore >= to_ore(config.AMOUNT_LIMIT_NOK)


def unknown_recipient(req: ActionRequest) -> bool:
    """Noe sendes ut av huset til en mottaker vi ikke kjenner.

    Gjelder bare handlinger som faktisk har en mottaker. At `recipient_known`
    er False på en kalenderoppdatering betyr ingenting.
    Mottakerfeltet kan være tomt; da er mottakeren uansett ukjent.
    """
    if req.action_type not in config.OUTBOUND_ACTIONS:
        return False
    return not req.recipient_known


def irreversible(req: ActionRequest) -> bool:
    """Handlingen kan ikke angres, og det betyr noe for denne typen handling.

    En e-post til en kjent mottaker kan heller ikke angres, men det er vanlig
    arbeid og skal ikke gi utslag alene.
    """
    if req.action_type not in config.IRREVERSIBLE_RELEVANT_ACTIONS:
        return False
    return not req.reversible


def _recipient_host(recipient: str) -> str:
    """Domenet eller vertsnavnet i en mottaker. Tom streng hvis det ikke er noe."""
    text = recipient.strip().lower()
    if "@" in text:
        text = text.rsplit("@", 1)[1]
    return text.strip().strip(".")


def internal_recipient(req: ActionRequest) -> bool:
    """Er mottakeren inne i huset?

    Dette er ikke et felt i `contracts.py` (den er laast), saa vi utleder det av
    mottakeren selv: en adresse paa et av Nordlys' egne domener, eller en intern
    ressurs som en delt kalender.

    Sammenligningen er EKSAKT paa punktum-grense. `nordlysforsikringe.no` er et
    annet domene enn `nordlysforsikring.no`, og `takst.nordlys@protonmail.com`
    ligger hos protonmail. En delstreng-sjekk ville sluppet begge rett inn.

    Mangler mottakeren, er svaret nei: vi gjetter aldri at noe er internt.

    Prefikslisten (`kalender:`) teller BARE paa handlinger som ikke sender noe
    ut av huset. Den sto foer for alle handlinger, og da var den en gratis
    omvei: `share_data` med persondata og `recipient="kalender:drift-felles"`
    ble `allow`, fordi det er nok aa skrive de ni tegnene i et fritekstfelt
    agenten fyller ut selv. Et domene maa staa paa `INTERNAL_DOMAINS` for aa
    telle; et prefiks stilte ingen slik betingelse. Null treff i de tre
    blindsettene, i demoen og i den syntetiske mengden - alle `kalender:`-
    mottakere der er `update_calendar`, og den utleverer ingenting.
    Se "Et prinsipp som ikke kan brytes" i gateway/LIMITS.md.
    """
    recipient = (req.recipient or "").strip()
    if not recipient:
        return False

    lowered = recipient.lower()
    if req.action_type not in config.OUTBOUND_ACTIONS and any(
        lowered.startswith(prefix) for prefix in config.INTERNAL_PREFIXES
    ):
        return True

    host = _recipient_host(recipient)
    if not host:
        return False
    return any(
        host == domain or host.endswith("." + domain) for domain in config.INTERNAL_DOMAINS
    )


def personal_data_external(req: ActionRequest) -> bool:
    """Personopplysninger på vei UT AV HUSET.

    Regelen het det samme før, men "ekstern" betydde "ukjent mottaker". Det var
    feil: "kjent" er ikke det samme som "intern" eller "trygg". Målingen mot
    blindsettet fanget tre tilfeller som slapp rett gjennom fordi mottakeren
    var kjent - en masseutsending til 8400 kunder, hele skadeporteføljen til et
    due diligence-team, og helsedata til en bedriftshelsetjeneste. Se
    docs/MALING.md.

    Nå betyr "ekstern" det ordet betyr: ikke intern. Persondata internt er
    fortsatt vanlig arbeid og slipper gjennom.

    Regelen ser ikke HVOR MANGE personer en utsending gjelder. Én bekreftelse
    til én kunde og en liste over 8400 veier likt. Se gateway/LIMITS.md.

    Den gjelder bare de handlingene der feltet betyr at opplysninger
    UTLEVERES: `send_email` og `share_data`. Paa en `transfer_money` sier
    `contains_personal_data` noe annet - at utbetalingsposten gjelder en
    person. Navn og konto maa staa der for at pengene skal finne fram, og
    mottakeren er den som skal ha dem. Ingenting utleveres til noen som ikke
    alt har det. Lista staar i `config.PERSONAL_DATA_RELEVANT_ACTIONS`, med
    maalingen som ligger bak.

    Et beloep er fortsatt et beloep: en utbetaling blir roed av
    `amount_over_limit`, `recipient_total_over_limit` eller
    `unknown_recipient` som foer. Denne regelen er ikke det som holder
    pengeutbetalinger i tomme.
    """
    if req.action_type not in config.PERSONAL_DATA_RELEVANT_ACTIONS:
        return False
    if not req.contains_personal_data:
        return False
    return not internal_recipient(req)


def new_package(req: ActionRequest) -> bool:
    """Et tillegg som ikke står på listen over godkjente tillegg.

    Mangler pakkenavnet, regnes tillegget som ukjent.
    """
    if req.action_type is not ActionType.INSTALL_PACKAGE:
        return False
    return normalize_package_name(req.package_name) not in config.KNOWN_PACKAGES


def package_on_blocklist(req: ActionRequest) -> bool:
    """Tillegget står på blokklisten. Brukes til block, ikke til risikopoeng."""
    if req.action_type is not ActionType.INSTALL_PACKAGE:
        return False
    return normalize_package_name(req.package_name) in config.PACKAGE_BLOCKLIST


def transfer_over_hard_limit(req: ActionRequest) -> bool:
    """Overføring større enn den harde grensen. Brukes til block, ikke til risikopoeng.

    `nan > grensen` er False, saa et nan-beløp ville sluppet forbi en ren
    sammenligning. Derfor sjekkes det først.
    """
    if req.action_type is not ActionType.TRANSFER_MONEY:
        return False
    if req.amount is None:
        return False
    ore = to_ore(req.amount)
    if ore is None:
        return True
    return ore > to_ore(config.HARD_TRANSFER_LIMIT_NOK)


def sandbox_blocked(req: ActionRequest, sandbox_report: SandboxReport | None) -> bool:
    """Sandkassen kjørte tillegget i en lukket boks og stoppet det.

    Dette er den eneste regelen som ser på noe utenfor ActionRequest, og den ser
    bare paa hva tillegget FAKTISK gjorde (`verdict`), ikke paa hva noen skriver
    om det. Rapporten kommer fra sandbox/, som avgjør clean/blocked/not_tested
    med faste regler. Ingen AI, og tilleggets egen beskrivelse av seg selv
    leses aldri.

    BARE "blocked" slaar til. Verken en manglende rapport eller `not_tested`
    gjoer det: "vi fikk ikke testet det" er ikke det samme som "nei". Tillegget
    blir uansett roedt saa lenge `new_package` gjelder - vi later bare ikke som
    vi har sett noe vi ikke har sett.
    """
    if req.action_type is not ActionType.INSTALL_PACKAGE:
        return False
    if sandbox_report is None:
        return False
    return sandbox_report.verdict == "blocked"


def normalize_recipient(recipient: str | None) -> str:
    """Gjør mottakere sammenlignbare. "NO12 3456 789" og "no12345 6789" er samme konto."""
    return re.sub(r"\s+", "", (recipient or "").strip().lower())


def recipient_total_ore(
    req: ActionRequest, history: Sequence[ActionRequest] | None
) -> int | None:
    """Sum i hele øre av overføringer til samme mottaker innenfor tidsvinduet.

    Vinduet slutter på `req.ts` og er `config.TRANSFER_WINDOW_HOURS` langt.
    Det regnes fra forespørselens eget tidsstempel, ikke fra klokken, slik at
    samme rekke forespørsler alltid gir samme svar.

    Returnerer None hvis det ikke gir mening å summere: ikke en overføring,
    ingen mottaker, eller et beløp vi ikke kan lese.
    """
    if req.action_type is not ActionType.TRANSFER_MONEY:
        return None
    key = normalize_recipient(req.recipient)
    if not key:
        return None
    total = to_ore(req.amount)
    if total is None:
        return None

    start = req.ts - timedelta(hours=config.TRANSFER_WINDOW_HOURS)
    for prior in history or ():
        if prior.action_type is not ActionType.TRANSFER_MONEY:
            continue
        if normalize_recipient(prior.recipient) != key:
            continue
        if not (start < prior.ts <= req.ts):
            continue
        ore = to_ore(prior.amount)
        if ore is not None:
            total += ore
    return total


def recipient_total_over_limit(
    req: ActionRequest, history: Sequence[ActionRequest] | None = None
) -> bool:
    """Flere overføringer til samme mottaker naar beløpsgrensen til sammen.

    Hullet denne lukker: hver enkelt overføring er under grensen, saa
    `amount_over_limit` slaar aldri til, og 100 betalinger paa 49 999 kr til
    samme kjente konto gikk rett gjennom. Se docs/MALING.md.

    Regelen slaar BARE til naar enkeltbeløpet er under grensen. Er det alt over,
    er det allerede fanget av `amount_over_limit`, og aa telle det to ganger
    ville flyttet eksisterende røde kort fra medium til high uten at noe nytt
    var oppdaget.
    """
    if amount_over_limit(req):
        return False
    total = recipient_total_ore(req, history)
    if total is None:
        return False
    grense = to_ore(config.AMOUNT_LIMIT_NOK)
    return grense is not None and total >= grense


def destructive_change(req: ActionRequest) -> bool:
    """Noe slettes eller overskrives, på en handling som ellers er harmløs.

    `reversible=False` betyr ulike ting for ulike handlinger. For en overføring
    er det en egenskap ved handlingen: penger er sendt. For lesing av et
    dokument eller en kalenderoppføring er det noe annet - de er i seg selv
    fullt reversible. Sier agenten at de ikke er det, har den gjort mer enn den
    sier: slettet, overskrevet, fjernet.

    For `read_document` er det i tillegg en selvmotsigelse mellom handlingstype
    og felt, og konsekvensteksten sier det rett ut.

    Målt før den ble innført: fire farlige tilfeller i de to blindsettene
    fanges, og én harmløs sak i vår egen syntetiske testmengde (`syn_0047`)
    blir rød. Se docs/MALING.md.
    """
    if req.action_type not in config.DESTRUCTIVE_RELEVANT_ACTIONS:
        return False
    return not req.reversible


def incomplete_request(req: ActionRequest) -> bool:
    """Forespørselen mangler noe vi trenger for å kunne vurdere den.

    Prinsippet er at feil lukkes: alt vi IKKE klarer å vurdere skal til et
    menneske, ikke gjennom. Tre ting kan skje i dag:

    - en handlingstype ingen regel dekker. `contracts.ActionType` kan få en ny
      verdi uten at noen husker å skrive en regel for den. Før gikk den rett
      gjennom; nå stopper den her.
    - en utgående handling uten mottaker. «Send denne e-posten» uten adresse,
      eller «overfør 100 kr» uten konto. Står `recipient_known=True` samtidig,
      slo ingen regel til i det hele tatt.
    - tom `agent_id` eller `id`. Vi vet ikke hvem som spør, eller hva vi skal
      kalle svaret.

    Målt før den ble innført: null treff i demoen, i begge blindsettene og i de
    syntetiske testene. Den slår bare til på noe ingen har laget ennå, og det
    er meningen med en slik regel.
    """
    if req.action_type not in config.COVERED_ACTIONS:
        return True
    if not (req.agent_id or "").strip():
        return True
    if not (req.id or "").strip():
        return True
    if req.action_type in config.OUTBOUND_ACTIONS and not (req.recipient or "").strip():
        return True
    return False


# Reglene som gir risikopoeng, i den rekkefølgen de skal stå i `reasons`.
RiskRule = Callable[[ActionRequest], bool]

RISK_RULES: tuple[tuple[str, RiskRule], ...] = (
    ("amount_over_limit", amount_over_limit),
    ("unknown_recipient", unknown_recipient),
    ("personal_data_external", personal_data_external),
    ("new_package", new_package),
    ("destructive_change", destructive_change),
    ("incomplete_request", incomplete_request),
    ("irreversible", irreversible),
)

# Reglene som stopper noe helt. Navnene havner også i `reasons`.
BLOCK_RULES: tuple[tuple[str, RiskRule], ...] = (
    ("package_on_blocklist", package_on_blocklist),
    ("transfer_over_hard_limit", transfer_over_hard_limit),
)


def triggered_risk_rules(
    req: ActionRequest, history: Sequence[ActionRequest] | None = None
) -> list[str]:
    """Navnene på risikoreglene som slo til, i fast rekkefølge.

    `recipient_total_over_limit` staar rett etter `amount_over_limit`, fordi de
    handler om det samme: beløpet er for stort til aa gaa av seg selv.
    """
    names = [name for name, rule in RISK_RULES if rule(req)]
    if recipient_total_over_limit(req, history):
        index = names.index("amount_over_limit") + 1 if "amount_over_limit" in names else 0
        names.insert(index, "recipient_total_over_limit")
    return names


def triggered_block_rules(
    req: ActionRequest, sandbox_report: SandboxReport | None = None
) -> list[str]:
    """Navnene på blokkreglene som slo til, i fast rekkefølge.

    `sandbox_blocked` staar først fordi den bygger på noe tillegget faktisk
    gjorde, ikke på en liste vi har skrevet på forhånd.
    """
    names = [name for name, rule in BLOCK_RULES if rule(req)]
    if sandbox_blocked(req, sandbox_report):
        names.insert(0, "sandbox_blocked")
    return names


def risk_score(reasons: list[str]) -> int:
    """Summen av vektene til reglene som slo til."""
    return sum(config.RULE_WEIGHTS.get(name, 0) for name in reasons)
