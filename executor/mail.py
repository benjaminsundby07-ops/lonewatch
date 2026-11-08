"""Adresser og selve meldingen. Ingen nettverk her, bare tekst.

Delt fra smtp.py med vilje: alt i denne filen kan testes uten at noe som helst
sendes, og det er her innholdet i e-posten blir bestemt.

Om `summary`: agentens egen forklaring er teksten vi SENDER, og det er alt den
brukes til. Den leses aldri for å avgjøre risiko - det er regel 6 i CLAUDE.md,
og den gjelder like mye her. Mellomstasjonen har allerede sagt ja til denne
forespørselen; vi velger bare hvordan den ser ut i en innboks.
"""

from __future__ import annotations

import re
from email.message import EmailMessage
from email.utils import format_datetime

from contracts import ActionRequest, Decision

# Bevisst streng. Vi godtar en kjedelig adresse og nekter resten, i stedet for
# å godta nesten alt og håpe at serveren rydder opp. @ og et toppdomene kreves,
# og alt som kan brekke en header (linjeskift, komma, semikolon,
# vinkelparentes) er ute.
#
# Dette nekter også "noen@localhost" og andre adresser uten punktum. Det er
# med vilje: en adresse uten domene kan ikke sjekkes av noen, og standard
# avsender er derfor lonewatch@lonewatch.invalid. ".invalid" er reservert og
# kan aldri peke på en ekte innboks.
ADDRESS_PATTERN = re.compile(r"^[^@\s,;:<>\"\\()\[\]]+@[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,63}$")

MAX_ADDRESS_CHARS = 254
MAX_SUBJECT_CHARS = 120

DEFAULT_SUBJECT = "Melding fra en AI-agent"

FOOTER = (
    "--\n"
    "Denne meldingen ble skrevet av en AI-agent og sendt gjennom Lonewatch.\n"
    "Agent: {agent_id}\n"
    "Saksnummer: {request_id}\n"
    "Avgjørelse: {verdict}\n"
    "{consequence}\n"
)


class AddressError(ValueError):
    """Adressen er ikke en adresse vi tør sende til."""


def valid_address(value: str | None) -> bool:
    if not value or len(value) > MAX_ADDRESS_CHARS:
        return False
    if any(ch in value for ch in ("\r", "\n", "\t", "\0")):
        return False
    return bool(ADDRESS_PATTERN.match(value))


def require_address(value: str | None, what: str) -> str:
    """Adressen, eller AddressError.

    Adressen selv kommer aldri med i feilmeldingen. En ugyldig adresse kan
    være et forsøk på å smugle tekst inn i en logg et menneske leser.
    """
    if not valid_address(value):
        raise AddressError(f"{what} er ikke en gyldig e-postadresse.")
    return str(value)


def mask_address(value: str | None) -> str:
    """'oline.dahl@nordlys.no' -> 'o***@nordlys.no'. Ingen hele adresser i svar.

    Svaret fra utføreren kan ende i en logg eller på en skjerm. Domenet er nok
    for å vise HVOR noe gikk; resten av adressen er en personopplysning.
    """
    if not value or "@" not in value:
        return "ukjent mottaker"
    local, _, domain = value.rpartition("@")
    if not local:
        return f"***@{domain}"
    return f"{local[0]}***@{domain}"


def subject_from(request: ActionRequest) -> str:
    """Emnefeltet: første linje av agentens forklaring, kuttet."""
    first = ""
    for line in str(request.summary or "").splitlines():
        if line.strip():
            first = " ".join(line.split())
            break
    if not first:
        return DEFAULT_SUBJECT
    if len(first) > MAX_SUBJECT_CHARS:
        return first[: MAX_SUBJECT_CHARS - 1] + "…"
    return first


def build_message(
    request: ActionRequest,
    decision: Decision,
    sender: str,
    fingerprint: str | None = None,
) -> EmailMessage:
    """Bygger meldingen av forespørselen. Kaster AddressError på dårlig adresse.

    Avtrykket legges i en header, slik at en .eml-fil på disk kan holdes opp
    mot loggen etterpå: er dette den forespørselen som ble godkjent.
    """
    to_addr = require_address(request.recipient, "Mottakeren")
    from_addr = require_address(sender, "Avsenderen")

    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject_from(request)
    msg["Date"] = format_datetime(request.ts)
    # Deterministisk, og uten maskinnavnet vårt i den. make_msgid() ville lagt
    # inn vertsnavnet til maskinen som kjører demoen.
    stamp = (fingerprint or request.id)[:32]
    msg["Message-ID"] = f"<{stamp}.{request.id}@lonewatch.invalid>"
    msg["X-Lonewatch-Request-Id"] = request.id
    msg["X-Lonewatch-Agent"] = request.agent_id
    msg["X-Lonewatch-Verdict"] = decision.verdict.value
    msg["X-Lonewatch-Risk"] = decision.risk.value
    if fingerprint:
        msg["X-Lonewatch-Fingerprint"] = fingerprint

    body = str(request.summary or "").strip()
    footer = FOOTER.format(
        agent_id=request.agent_id,
        request_id=request.id,
        verdict=decision.verdict.value,
        consequence=decision.consequence_text,
    )
    msg.set_content(f"{body}\n\n{footer}" if body else footer, subtype="plain", charset="utf-8")
    return msg
