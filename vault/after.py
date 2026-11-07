"""Etter-listen: hva maa menneskene faktisk gjøre, naar hendelsen er over.

Bygges KUN fra loggen. Ingen AI, ingen gjetting: hver linje i listen kommer fra en
konkret logglinje. Taaler at payloaden er minimert (redact_payload), da blir detaljene
bare kortere.
"""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Iterable

from contracts import ActionType, AfterAction, LogEntry, Verdict
from vault.redaction import mask_recipient

UNKNOWN_RECIPIENT = "ukjent konto"


def format_nok(amount: float | int | None) -> str:
    """10000000 -> '10 000 000 kr', 49999.5 -> '49 999,50 kr'.

    Oerene staar i teksten. Rundet vi dem bort, kunne Etter-listen vist et
    annet beloep enn det gateway faktisk vurderte (F7 i docs/REDTEAM.md).
    Beregningen gjoeres i hele oere, slik at flyttall aldri flytter tallet.
    """
    if amount is None:
        return "ukjent beløp"
    try:
        ore = int((Decimal(str(amount)) * 100).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    except (ArithmeticError, TypeError, ValueError):
        return "ukjent beløp"
    negativ = ore < 0
    kroner, rest = divmod(abs(ore), 100)
    tall = f"{kroner:,}".replace(",", " ")
    if rest:
        tall = f"{tall},{rest:02d}"
    return f"{'-' if negativ else ''}{tall} kr"


def _recipient(payload: dict[str, Any]) -> str:
    """Mottakeren vises alltid maskert: Etter-listen henger paa en skjerm."""
    value = payload.get("recipient")
    if not value:
        return UNKNOWN_RECIPIENT
    masked = mask_recipient(value)
    if payload.get("recipient_known") is False:
        return f"{UNKNOWN_RECIPIENT} {masked}"
    return str(masked)


def _add(seen: set[tuple[str, str, str]], out: list[AfterAction], action: AfterAction) -> None:
    key = (action.title, action.detail, action.owner_role)
    if key not in seen:
        seen.add(key)
        out.append(action)


def build_after_actions(entries: Iterable[LogEntry]) -> list[AfterAction]:
    """Lager Etter-listen fra logglinjene, i den rekkefølgen ting skjedde."""
    entries = list(entries)
    requests: dict[str, dict[str, Any]] = {}
    for e in entries:
        if e.kind == "request":
            rid = e.payload.get("id")
            if isinstance(rid, str):
                requests[rid] = e.payload

    out: list[AfterAction] = []
    seen: set[tuple[str, str, str]] = set()

    for e in entries:
        payload = e.payload

        if e.kind == "decision":
            req = requests.get(str(payload.get("request_id")), {})
            action_type = req.get("action_type") or payload.get("action_type")
            verdict = payload.get("verdict")

            if verdict == Verdict.RED.value and action_type == ActionType.TRANSFER_MONEY.value:
                _add(seen, out, AfterAction(
                    title="Sjekk den flaggede overføringen",
                    detail=(
                        f"{format_nok(req.get('amount'))} til {_recipient(req)} ble stoppet for "
                        f"menneskelig godkjenning ({payload.get('request_id')}). "
                        "Bekreft med mottaker gjennom en annen kanal før noe utbetales."
                    ),
                    owner_role="finance",
                ))

            if verdict == Verdict.BLOCK.value and action_type == ActionType.INSTALL_PACKAGE.value:
                _add(seen, out, AfterAction(
                    title="Blokkert tillegg maa granskes",
                    detail=(
                        f"Pakken '{req.get('package_name') or 'ukjent'}' ble blokkert "
                        f"({payload.get('request_id')}). Sjekk om den er forsøkt installert andre "
                        "steder, og hvem som ba om den."
                    ),
                    owner_role="security",
                ))

            if verdict in (Verdict.RED.value, Verdict.BLOCK.value) and req.get("contains_personal_data"):
                _add(seen, out, AfterAction(
                    title="Persondata var paa vei ut",
                    detail=(
                        f"{action_type or 'handling'} med persondata til {_recipient(req)} ble "
                        f"{'stoppet' if verdict == Verdict.BLOCK.value else 'holdt tilbake'} "
                        f"({payload.get('request_id')}). Vurder om dette er avvik som skal meldes."
                    ),
                    owner_role="security",
                ))

        elif e.kind == "human":
            if payload.get("approved") is True:
                _add(seen, out, AfterAction(
                    title="Rød forespørsel ble godkjent",
                    detail=(
                        f"{payload.get('employee_pseudonym', 'ukjent ansatt')} godkjente "
                        f"{payload.get('request_id')} etter "
                        f"{payload.get('seconds_to_decide', '?')} sekunder. "
                        "Kontroller i ettertid at godkjenningen var riktig."
                    ),
                    owner_role="security",
                ))

        elif e.kind == "trap":
            _add(seen, out, AfterAction(
                title="Felle gikk av i et dokument",
                detail=(
                    f"Dokument {payload.get('doc_id')} fikk agenten {payload.get('agent_id')} til aa "
                    f"gjøre noe den ikke skulle: {payload.get('what_happened')}. "
                    "Fjern dokumentet og finn ut hvem som la det inn."
                ),
                owner_role="security",
            ))
            _add(seen, out, AfterAction(
                title="Bytt tilgangene agenten brukte",
                detail=(
                    f"Agenten {payload.get('agent_id')} leste et dokument med felle "
                    f"({payload.get('doc_id')}). Bytt nøkler og passord agenten hadde tilgang til."
                ),
                owner_role="employee",
            ))

        elif e.kind == "sandbox":
            name = payload.get("package_name") or "ukjent tillegg"
            if payload.get("attempted_network"):
                dests = payload.get("destinations") or []
                _add(seen, out, AfterAction(
                    title="Tillegget prøvde aa sende data ut",
                    detail=(
                        f"'{name}' ble kjørt i den lukkede boksen og forsøkte nettverk mot "
                        f"{', '.join(str(d) for d in dests) or 'ukjent sted'}. Sandkassen svarte "
                        "nei, saa ingenting forlot maskinen. Blokker adressene og se etter samme "
                        "forsøk i ekte logger."
                    ),
                    owner_role="security",
                ))
            elif payload.get("verdict") == "blocked":
                # Stoppet uten nettverk: leste hemmeligheter, kom ikke ut av boksen
                # i tide, eller forsøkte noe annet sandkassen ikke tillater.
                _add(seen, out, AfterAction(
                    title="Tillegget ble stoppet i sandkassen",
                    detail=(
                        f"'{name}' ble kjørt i den lukkede boksen og stoppet uten at det "
                        "forsøkte nettverk. Les notatet paa sandkasselinjen i loggen og finn "
                        "ut hvem som ba om tillegget."
                    ),
                    owner_role="security",
                ))

    return out
