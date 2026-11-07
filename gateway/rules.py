"""Reglene. Én liten funksjon per regel, ingen AI, ingen tilfeldighet.

Hver regel ser BARE på strukturerte felt i ActionRequest.
`req.summary` (agentens egen forklaring) leses aldri: en agent som er lurt
eller som lyver skal ikke kunne snakke seg forbi mellomstasjonen.

Navnet på funksjonen er navnet som havner i `Decision.reasons`.
"""

from __future__ import annotations

from collections.abc import Callable

from contracts import ActionRequest, ActionType

from . import config


def normalize_package_name(package_name: str | None) -> str:
    """Gjør navn sammenlignbare: små bokstaver, uten luft rundt."""
    if package_name is None:
        return ""
    return package_name.strip().lower()


def amount_over_limit(req: ActionRequest) -> bool:
    """Beløpet er på eller over beløpsgrensen.

    Mangler beløp, slår regelen ikke til. Grensen er inkluderende.
    """
    if req.amount is None:
        return False
    return req.amount >= config.AMOUNT_LIMIT_NOK


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


def personal_data_external(req: ActionRequest) -> bool:
    """Personopplysninger på vei ut til en ukjent mottaker."""
    if req.action_type not in config.OUTBOUND_ACTIONS:
        return False
    return req.contains_personal_data and not req.recipient_known


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
    """Overføring større enn den harde grensen. Brukes til block, ikke til risikopoeng."""
    if req.action_type is not ActionType.TRANSFER_MONEY:
        return False
    if req.amount is None:
        return False
    return req.amount > config.HARD_TRANSFER_LIMIT_NOK


# Reglene som gir risikopoeng, i den rekkefølgen de skal stå i `reasons`.
RiskRule = Callable[[ActionRequest], bool]

RISK_RULES: tuple[tuple[str, RiskRule], ...] = (
    ("amount_over_limit", amount_over_limit),
    ("unknown_recipient", unknown_recipient),
    ("personal_data_external", personal_data_external),
    ("new_package", new_package),
    ("irreversible", irreversible),
)

# Reglene som stopper noe helt. Navnene havner også i `reasons`.
BLOCK_RULES: tuple[tuple[str, RiskRule], ...] = (
    ("package_on_blocklist", package_on_blocklist),
    ("transfer_over_hard_limit", transfer_over_hard_limit),
)


def triggered_risk_rules(req: ActionRequest) -> list[str]:
    """Navnene på risikoreglene som slo til, i fast rekkefølge."""
    return [name for name, rule in RISK_RULES if rule(req)]


def triggered_block_rules(req: ActionRequest) -> list[str]:
    """Navnene på blokkreglene som slo til, i fast rekkefølge."""
    return [name for name, rule in BLOCK_RULES if rule(req)]


def risk_score(reasons: list[str]) -> int:
    """Summen av vektene til reglene som slo til."""
    return sum(config.RULE_WEIGHTS.get(name, 0) for name in reasons)
