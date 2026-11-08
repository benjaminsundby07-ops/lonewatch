"""Hva som faktisk skjer når agenten kaller et verktøy.

Denne filen kjenner ikke MCP. Den tar en klient, et verktøynavn og noen felt,
og gir tilbake teksten agenten skal lese. `agent_gateway/server.py` er bare et
tynt lag med MCP-verktøy over dette, slik at hele flyten kan testes uten å
starte en agent og uten å ha `mcp` installert.

Fire ting er med vilje:

- **Agenten kan ikke oppgi `recipient_known` eller `reversible`.** De står ikke
  i noen verktøysignatur her, og endepunktet i appen nekter ukjente felt. Begge
  regnes ut på tjenersiden. En agent som er lurt skal ikke kunne påstå at en
  ukjent konto er kjent.
- **`summary` er agentens egen forklaring, og brukes aldri i vurderingen.** Den
  sendes med fordi mennesket i dashbordet skal se hva agenten trodde den gjorde.
- **Et blokkert kall får en kort avvisning uten begrunnelse.** Regelnavnene
  ville vært en oppskrift på hva som må endres for å slippe gjennom.
- **Ingenting utføres.** "Utført" er en tekst. Se `agent_gateway/LIMITS.md`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from agent_gateway import validering
from agent_gateway.client import LonewatchClient, LonewatchRefused, LonewatchUnavailable

# Handlingstypene i contracts.py som har et verktøy her. Vi legger ikke til
# nye: contracts.py er laast, og et verktøy for en handlingstype uten regler
# ville sett ut som daekning vi ikke har.
TRANSFER_MONEY = "transfer_money"
SEND_EMAIL = "send_email"
READ_DOCUMENT = "read_document"
INSTALL_PACKAGE = "install_package"


@dataclass(frozen=True)
class ToolSpec:
    """Ett verktøy: navnet agenten ser, og handlingstypen det blir i Lonewatch."""

    name: str
    action_type: str
    description: str


TOOL_SPECS: tuple[ToolSpec, ...] = (
    ToolSpec(
        name="lonewatch_read_document",
        action_type=READ_DOCUMENT,
        description=(
            "Les et internt dokument i den oppdiktede bedriften. "
            "Går gjennom Lonewatch først. Ingenting leses i virkeligheten: "
            "svaret er simulert."
        ),
    ),
    ToolSpec(
        name="lonewatch_send_email",
        action_type=SEND_EMAIL,
        description=(
            "Send en e-post på vegne av den oppdiktede bedriften. "
            "Går gjennom Lonewatch først, og kan kreve at et menneske godkjenner. "
            "Ingen e-post sendes i virkeligheten."
        ),
    ),
    ToolSpec(
        name="lonewatch_transfer_money",
        action_type=TRANSFER_MONEY,
        description=(
            "Overfør penger fra den oppdiktede bedriftens konto. Beløp i NOK. "
            "Går gjennom Lonewatch først. Store eller uvanlige overføringer "
            "stoppes til et menneske har godkjent dem i dashbordet. "
            "Ingen penger flyttes i virkeligheten."
        ),
    ),
    ToolSpec(
        name="lonewatch_install_package",
        action_type=INSTALL_PACKAGE,
        description=(
            "Installer et tillegg (en pakke) i den oppdiktede bedriftens miljø. "
            "Går gjennom Lonewatch først, som kjører tillegget i en lukket "
            "sandkasse før noen bestemmer seg. Ingenting installeres i "
            "virkeligheten."
        ),
    ),
)

TOOL_BY_NAME: dict[str, ToolSpec] = {spec.name: spec for spec in TOOL_SPECS}

# Statusene appen bruker. Samme ord som ui/state.py, uten aa importere derfra:
# MCP-tjeneren skal kunne kjøre uten resten av Lonewatch paa sys.path.
STATUS_ALLOW = "allow"
STATUS_WAITING = "waiting"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_BLOCKED = "blocked"


def format_amount(amount: float | int | None) -> str:
    """Beløpet som tekst Lonewatch tolker likt hver gang.

    `ui/amount.py` er fasiten for hvordan et skrevet beløp leses, og den godtar
    IKKE punktum som desimalskille: "450000.00" avvises med vilje, fordi det
    like gjerne kan være et mislykket tusenskille. Derfor sender vi hele kroner
    som rene siffer, og øre med komma.
    """
    if amount is None:
        return ""
    try:
        ore = int((Decimal(str(amount)) * 100).to_integral_value())
    except (InvalidOperation, ValueError, TypeError):
        # La appen svare "beløpet kunne ikke leses". Vi gjetter ikke her.
        return str(amount)
    kroner, rest = divmod(ore, 100)
    return str(kroner) if rest == 0 else f"{kroner},{rest:02d}"


def _lw(reply: dict[str, Any]) -> str:
    """Visningsnavnet appen ga forespørselen, eller den raa IDen."""
    return str(reply.get("name") or reply.get("request_id") or "ukjent")


def run_action(
    client: LonewatchClient,
    *,
    tool_name: str,
    summary: str = "",
    amount: float | None = None,
    recipient: str = "",
    package_name: str = "",
    contains_personal_data: bool = False,
    wait_seconds: float = 120.0,
    poll_seconds: float = 2.0,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    **ukjente_felt: Any,
) -> str:
    """Hele veien for ett verktøykall, og teksten agenten får tilbake.

    `sleep` og `clock` kan byttes ut i tester, slik at tidsavbruddet kan prøves
    uten å faktisk vente i to minutter.
    """
    spec = TOOL_BY_NAME.get(tool_name)
    if spec is None:  # pragma: no cover - server.py registrerer bare kjente navn
        return f"Ukjent verktøy: {tool_name}."

    # Formsjekk FØR noe sendes. Her avgjøres ingenting om risiko - det gjør
    # gateway/ alene. Her kastes bare input som ikke har en form Lonewatch kan
    # behandle. Se agent_gateway/validering.py.
    try:
        felt = validering.sjekk_input(
            summary=summary,
            amount=amount,
            recipient=recipient,
            package_name=package_name,
            contains_personal_data=contains_personal_data,
            extra=ukjente_felt,
        )
    except validering.UgyldigInput as exc:
        return (
            f"Lonewatch tok ikke imot forespørselen: {exc} "
            "Ingenting ble utført, og kallet ble ikke vurdert."
        )

    payload = {
        "action_type": spec.action_type,
        "summary": felt["summary"],
        "amount": format_amount(felt["amount"]),
        "recipient": felt["recipient"],
        "package_name": felt["package_name"],
        "contains_personal_data": felt["contains_personal_data"],
    }

    try:
        reply = client.submit(payload)
    except LonewatchRefused as exc:
        return (
            "Lonewatch slapp ikke kallet inn: "
            f"{exc} "
            "Handlingen ble IKKE utført. Si det til brukeren i stedet for å prøve en annen vei."
        )
    except LonewatchUnavailable as exc:
        return (
            f"Lonewatch er ikke tilgjengelig: {exc} "
            "Handlingen ble IKKE utført. Uten mellomstasjonen skal ingenting skje. "
            "Si det til brukeren."
        )

    if not reply.get("ok"):
        # Forespørselen holdt ikke formelt (manglende beløp, ukjent
        # handlingstype). Dette er ikke en avgjørelse - den er ikke vurdert.
        return (
            f"Lonewatch tok ikke imot forespørselen: {reply.get('error') or 'ukjent feil'} "
            "Ingenting ble utført."
        )

    verdict = reply.get("verdict")
    if verdict == "block":
        # Kort og uten begrunnelse. Regelnavnene ville vært en oppskrift.
        return (
            f"BLOKKERT av Lonewatch ({_lw(reply)}). Handlingen ble ikke utført, "
            "og ingen kan godkjenne den. Ikke prøv en annen variant av det samme "
            "- si til brukeren at Lonewatch stoppet den."
        )

    if verdict == "allow":
        return (
            f"UTFØRT (simulert). Lonewatch slapp kallet gjennom ({_lw(reply)}), "
            f"og det står i loggen. {_consequence(reply)}"
            "\n\nMerk: dette er en simulering. Ingenting skjedde i virkeligheten."
        )

    # Rødt: et menneske må se på det. Vi venter.
    return _wait_for_human(
        client,
        reply=reply,
        wait_seconds=wait_seconds,
        poll_seconds=poll_seconds,
        sleep=sleep,
        clock=clock,
    )


def _consequence(reply: dict[str, Any]) -> str:
    text = (reply.get("consequence_text") or "").strip()
    return f"Lonewatch beskriver konsekvensen slik: «{text}»" if text else ""


def _wait_for_human(
    client: LonewatchClient,
    *,
    reply: dict[str, Any],
    wait_seconds: float,
    poll_seconds: float,
    sleep: Callable[[float], None],
    clock: Callable[[], float],
) -> str:
    """Venter på at et menneske svarer i dashbordet, eller gir opp."""
    request_id = str(reply.get("request_id") or "")
    navn = _lw(reply)
    started = clock()

    while True:
        try:
            status_reply = client.status(request_id)
        except (LonewatchRefused, LonewatchUnavailable) as exc:
            return (
                f"Kallet ligger til godkjenning i Lonewatch ({navn}), men jeg mistet "
                f"kontakten med mellomstasjonen: {exc} "
                "Jeg vet ikke om noen godkjente det. Gå ut fra at det IKKE ble utført."
            )

        status = str(status_reply.get("status") or "")

        if status == STATUS_APPROVED:
            skrevet = status_reply.get("typed_amount")
            bekreftelse = (
                f" Mennesket skrev inn beløpet ({format_amount(skrevet)} kr) for å bekrefte."
                if skrevet is not None
                else ""
            )
            return (
                f"GODKJENT av et menneske i Lonewatch ({navn}).{bekreftelse} "
                "UTFØRT (simulert)."
                "\n\nMerk: dette er en simulering. Ingenting skjedde i virkeligheten."
            )

        if status == STATUS_REJECTED:
            return (
                f"AVVIST av et menneske i Lonewatch ({navn}). Handlingen ble ikke utført. "
                "Ikke prøv igjen med andre ord - si til brukeren at den ble avvist."
            )

        if status in (STATUS_BLOCKED, STATUS_ALLOW):  # pragma: no cover - skifter ikke
            return (
                f"Lonewatch endte på «{status}» for {navn}. Jeg ventet på et menneske, "
                "men det kom ingen avgjørelse fra noen. Gå ut fra at den IKKE ble utført."
            )

        ventet = clock() - started
        if ventet >= wait_seconds:
            try:
                client.abandon(request_id, ventet)
            except (LonewatchRefused, LonewatchUnavailable):
                pass  # Notisen i dashbordet er en vennlighet, ikke en del av flyten.
            return (
                f"INGEN SVARTE innen {int(wait_seconds)} sekunder ({navn}). Handlingen ble "
                "IKKE utført, og jeg behandler det som et nei. Kortet ligger fortsatt i "
                "godkjenningskøen i Lonewatch, så et menneske kan se på det senere - men "
                "jeg kommer ikke til å utføre noe på grunnlag av et svar som kommer etterpå."
            )

        sleep(min(poll_seconds, max(0.0, wait_seconds - ventet)))
