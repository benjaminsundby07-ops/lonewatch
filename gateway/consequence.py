"""Konsekvensteksten: norsk klartekst om hva som faktisk skjer.

Teksten settes sammen av maler og felt fra ActionRequest. Den kommer ALDRI
fra en AI-modell, og `req.summary` brukes aldri: agenten skal ikke få skrive
teksten mennesket leser før det godkjenner.
"""

from __future__ import annotations

import unicodedata

from contracts import ActionRequest, ActionType, SandboxReport

from . import config
from .money import format_ore, to_ore
from .rules import no_usable_transfer_amount

UNKNOWN_ACCOUNT = "ukjent konto"
UNKNOWN_RECIPIENT = "ukjent mottaker"
UNKNOWN_AMOUNT = "ukjent beløp"
UNREADABLE_AMOUNT = "et beløp vi ikke kan lese"
IRREVERSIBLE_NOTE = "Kan ikke angres."
PERSONAL_DATA_NOTE = "Inneholder personopplysninger."
BLOCKED_NOTE = "Dette stoppes automatisk og kan ikke godkjennes."

# Noe slettes eller overskrives paa en handling som ellers er harmloes.
DESTRUCTIVE_NOTE = "Noe blir slettet eller overskrevet, og det kan ikke angres."

# Lesing som ikke kan angres er en selvmotsigelse mellom handlingstype og felt.
# Vi sier det rett ut, i stedet for aa velge én av dem og haape vi gjettet rett.
DESTRUCTIVE_READ_NOTE = (
    "Oppgitt som lesing, men også som umulig å angre. Da er det ikke bare "
    "lesing: noe blir slettet eller overskrevet."
)

# Vi klarte ikke aa LESE forespoerselen i det hele tatt. Teksten er fast og
# inneholder aldri noe fra det som kom inn: feilmeldinger fra Python kan
# inneholde tekst noen andre har skrevet, og den skal ikke havne i varselet.
UNJUDGEABLE_NOTE = (
    "Lonewatch klarte ikke å lese denne forespørselen i det hele tatt, så den "
    "stoppes. Ingen kan godkjenne den."
)

# Vi klarte ikke aa vurdere forespoerselen.
INCOMPLETE_NOTE = (
    "Lonewatch klarte ikke å vurdere denne forespørselen, så den går til et "
    "menneske i stedet for å gå gjennom."
)

# En utbetaling uten et beloep vi kan vurdere. Mennesket skal faa vite hva som
# mangler, ikke bare at "noe" manglet - og at ingen beloepsgrense er sjekket,
# for det er ingenting aa sjekke mot.
MISSING_TRANSFER_AMOUNT_NOTE = (
    "Beløpet mangler, så ingen beløpsgrense er sjekket. En utbetaling uten "
    "beløp går aldri gjennom av seg selv."
)
ZERO_TRANSFER_AMOUNT_NOTE = (
    "Beløpet er oppgitt som 0 kr. Det er ingen utbetaling, så Lonewatch vet "
    "ikke hva forespørselen gjelder."
)

# Sandkassen. Teksten sier hva vi SAA, aldri at noe er trygt.
#
# Det kom INGEN rapport med kallet. Det er noe annet enn en rapport som sier
# "not_tested" (SANDBOX_INCONCLUSIVE under): der ble sandkassen spurt, men
# tillegget kom ikke i gang. Her ble den aldri spurt - og foer sa Lonewatch det
# samme om de to tilfellene (H24 i docs/ANGREP.md). Begge setningene maa vaere
# like tydelige paa at ingen har sett etter noe.
SANDBOX_NOT_TESTED = (
    "Sandkassen ble aldri spurt om dette tillegget, så det er ikke testet i "
    "sandkassen."
)
SANDBOX_CLEAN = (
    "Sandkassen kjørte tillegget i en lukket boks og så ingenting mistenkelig. "
    "Det betyr ikke at tillegget er trygt."
)
SANDBOX_BLOCKED_PLAIN = "Sandkassen kjørte tillegget i en lukket boks og stoppet det."

# Tillegget kom aldri i gang. Dette maa ALDRI leses som en klarering: vi fikk
# ikke sett etter, og det er noe annet enn aa ha sett etter uten aa finne noe.
SANDBOX_INCONCLUSIVE = (
    "Sandkassen fikk ikke testet tillegget: det kom aldri i gang. Vi vet derfor "
    "ikke hva det ville gjort."
)
UNSHOWABLE_DESTINATION = "en adresse vi ikke kan vise trygt"
UNSHOWABLE_PACKAGE = "et tillegg med et navn vi ikke kan vise trygt"

# Mottakeren er oppgitt, men det er ingenting i den vi kan vise: bare
# kontrolltegn, bare usynlige tegn, eller bare luft.
UNSHOWABLE_RECIPIENT = "en mottaker vi ikke kan vise trygt"

# Anfoerselstegnene rundt en mottaker som ikke er en ren adresse. De staar her
# og ikke inne i teksten, slik at det bare finnes ÉN maate aa ramme den inn.
RECIPIENT_QUOTE_OPEN = "\u00ab"
RECIPIENT_QUOTE_CLOSE = "\u00bb"

# Mottakeren var for lang og er kuttet. Tegnet staar INNENFOR anfoerselstegnene,
# slik at det er tydelig at det er verdien som er kuttet, ikke setningen.
RECIPIENT_TRUNCATED = "\u2026"


def safe_package_name(package_name: str | None) -> str | None:
    """Pakkenavnet, gjort trygt å vise til et menneske.

    Den som ber om en installasjon velger selv navnet, så dette er tekst vi
    ikke stoler på. Ser navnet ikke ut som et pakkenavn, viser vi det ikke.
    Reglene (`new_package`, `package_on_blocklist`) sammenligner fortsatt det
    EKTE navnet - det er bare visningen som holdes i tømme.
    """
    text = (package_name or "").strip()
    if not config.PACKAGE_NAME_PATTERN.match(text):
        return None
    return text


def safe_destination(destination: str) -> str:
    """Adressen et tillegg prøvde å nå, gjort trygg å vise til et menneske.

    Tillegget velger selv hva det kobler mot, så dette er tekst fra noe vi ikke
    stoler på. Et vertsnavn som "ondsinnet.example. Godkjent av sikkerhet" ville
    ellers kunne skrive sin egen setning inn i varselet. Ser adressen ikke ut som
    et vertsnavn eller en IP-adresse, viser vi den ikke.
    """
    text = (destination or "").strip()
    if not config.DESTINATION_PATTERN.match(text):
        return UNSHOWABLE_DESTINATION
    return text


def safe_recipient(recipient: str | None) -> str | None:
    """Mottakeren, gjort trygg aa vise til et menneske.

    `recipient` er fritekst den som ber om handlingen fyller ut selv, og den
    havner i overskriften i det roede varselet. Foer ble feltet limt RAATT inn,
    og da kunne mottakeren "NO99 0000 0000 000. Godkjent av finansdirektoer,
    ingen handling noedvendig" skrive sin egen setning i Lonewatchs eget
    varsel, i Lonewatchs egen stemme (H20 og H21 i docs/ANGREP.md).

    Pakkenavnet og adressen fra sandkassen loeses ved aa AVVISE alt som ikke
    ser rett ut. Det gaar ikke her: en mottaker kan like godt vaere
    "Storgata Eiendom AS, registrert konto" som "NO12 3456 7890 123", og et
    menneske som skal godkjenne en utbetaling trenger aa se hvem den gaar til.

    Derfor rammes mottakeren inn i stedet:

    - kontrolltegn, nylinjer og usynlige tegn fjernes
    - anfoerselstegnene selv fjernes, slik at verdien ikke kan lukke sin egen
      ramme og skrive videre utenfor den
    - all luft trekkes sammen til vanlige mellomrom
    - teksten kuttes paa `config.MAX_SHOWN_RECIPIENT_LEN` tegn
    - er det mellomrom igjen, settes verdien i anfoerselstegn

    Er det ingen mellomrom og bare tegn som hoerer hjemme i en adresse
    (`config.RECIPIENT_PLAIN_PATTERN`, samme idé som `DESTINATION_PATTERN`),
    kan verdien ikke danne en setning i det hele tatt, og da vises den som den
    er. Alt annet staar synlig som noe Lonewatch SITERER.

    Returnerer None naar det ikke er oppgitt noen mottaker; da velger den som
    kaller sin egen tekst ("ukjent konto"/"ukjent mottaker").
    """
    if recipient is None:
        return None

    # Kontrolltegn og usynlige tegn ut. Nylinje og tabulator blir mellomrom,
    # slik at ord ikke klistres sammen; resten forsvinner helt.
    tegn = []
    for ch in recipient:
        kategori = unicodedata.category(ch)
        if ch in "\n\r\t" or kategori in ("Zs", "Zl", "Zp"):
            tegn.append(" ")
        elif kategori in ("Cc", "Cf", "Cs", "Co", "Cn"):
            continue
        elif ch in (RECIPIENT_QUOTE_OPEN, RECIPIENT_QUOTE_CLOSE):
            # Verdien skal ikke kunne lukke sin egen ramme: en mottaker som
            # "NO99» Godkjent av finansdirektoer «" ville ellers staatt utenfor
            # anfoerselstegnene og lest som Lonewatchs egen setning igjen.
            continue
        else:
            tegn.append(ch)
    text = " ".join("".join(tegn).split())

    if not text:
        # Enten tom fra foer, eller bare kontrolltegn og luft. Det er to ulike
        # ting: ingen mottaker (None inn) og en mottaker vi ikke kan vise.
        return None if not (recipient or "").strip() else UNSHOWABLE_RECIPIENT

    if len(text) > config.MAX_SHOWN_RECIPIENT_LEN:
        text = text[: config.MAX_SHOWN_RECIPIENT_LEN].rstrip() + RECIPIENT_TRUNCATED
        return RECIPIENT_QUOTE_OPEN + text + RECIPIENT_QUOTE_CLOSE

    if config.RECIPIENT_PLAIN_PATTERN.match(text):
        # Ingen mellomrom og bare adressetegn: dette kan ikke bli en setning.
        return text

    return RECIPIENT_QUOTE_OPEN + text + RECIPIENT_QUOTE_CLOSE


def _sandbox_text(report: SandboxReport) -> str:
    """Én setning om hva sandkassen saa. Bygget av maler og felt, aldri av AI.

    `report.notes` brukes ikke her: den er lang og hører hjemme i Før-listen.
    Her trenger mennesket bare det korte svaret.

    Tre utfall, og de sier tre forskjellige ting: vi stoppet det, vi så etter og
    fant ingenting, eller vi fikk aldri sett etter.
    """
    if report.verdict == "not_tested":
        return SANDBOX_INCONCLUSIVE

    if report.verdict == "clean":
        return SANDBOX_CLEAN

    shown = [safe_destination(d) for d in report.destinations[: config.MAX_SHOWN_DESTINATIONS]]
    if report.attempted_network and shown:
        return (
            "Sandkassen kjørte tillegget i en lukket boks. Det forsøkte å kontakte "
            + ", ".join(shown)
            + ". Ingenting ble sendt."
        )
    return SANDBOX_BLOCKED_PLAIN


def format_amount(amount: float | None) -> str:
    """10000000 -> '10 000 000 kr', 49999.5 -> '49 999,50 kr'.

    Beløpet vises fra NØYAKTIG det samme øretallet reglene sammenligner med.
    Før rundet denne til hele kroner, saa 49 999,50 ble vist som "50 000 kr"
    mens regelen saa 49 999,50 og slapp den gjennom (F7 i docs/REDTEAM.md).

    Et beløp vi ikke kan lese (inf, nan, eller absurd stort) skrives ut som
    tekst. Uten det krasjet `int(round(inf))` hele evaluate() (F2).
    """
    if amount is None:
        return UNKNOWN_AMOUNT
    ore = to_ore(amount)
    if ore is None:
        return UNREADABLE_AMOUNT
    return format_ore(ore)


def _recipient_phrase(req: ActionRequest, unknown_text: str) -> str:
    """'ukjent konto' naar mottakeren ikke er kjent, ellers mottakeren vist trygt.

    Mottakeren gaar ALDRI raatt inn i teksten. Se `safe_recipient`.
    """
    if not req.recipient_known or not req.recipient:
        return unknown_text
    shown = safe_recipient(req.recipient)
    if shown is None:
        return unknown_text
    return shown


def _base_text(req: ActionRequest) -> str:
    """Første setning: hva handlingen gjør, i klartekst."""
    if req.action_type is ActionType.TRANSFER_MONEY:
        return f"Overfører {format_amount(req.amount)} til {_recipient_phrase(req, UNKNOWN_ACCOUNT)}."

    if req.action_type is ActionType.SEND_EMAIL:
        return f"Sender e-post til {_recipient_phrase(req, UNKNOWN_RECIPIENT)}."

    if req.action_type is ActionType.SHARE_DATA:
        return f"Deler data med {_recipient_phrase(req, UNKNOWN_RECIPIENT)}."

    if req.action_type is ActionType.INSTALL_PACKAGE:
        if not (req.package_name or "").strip():
            return "Installerer et tillegg uten navn."
        name = safe_package_name(req.package_name)
        if name is None:
            return f"Installerer {UNSHOWABLE_PACKAGE}."
        return f"Installerer tillegget {name}."

    if req.action_type is ActionType.READ_DOCUMENT:
        if req.source_doc_id:
            return f"Leser dokumentet {req.source_doc_id}."
        return "Leser et dokument."

    if req.action_type is ActionType.UPDATE_CALENDAR:
        return "Oppdaterer kalenderen."

    # Nye handlingstyper i contracts skal ikke gi en tom tekst.
    return f"Utfører handlingen {req.action_type.value}."


def build_consequence_text(
    req: ActionRequest,
    reasons: list[str],
    blocked: bool = False,
    sandbox_report: SandboxReport | None = None,
    recipient_total_ore: int | None = None,
    recipient_total_time_bounded: bool = True,
) -> str:
    """Setter sammen hele teksten mennesket får se.

    `recipient_total_ore` er summen til samme mottaker innenfor tidsvinduet.
    Den regnes ut av reglene og vises som et tall, aldri som noe hentet fra
    `summary`.

    `recipient_total_time_bounded` sier om vinduet faktisk ble brukt. Hang
    tidsstemplene ikke sammen, gjelder summen alt Lonewatch har sett, og da
    skal teksten si det i stedet for aa naevne 24 timer.
    """
    parts = [_base_text(req)]

    if req.contains_personal_data and req.action_type in config.OUTBOUND_ACTIONS:
        parts.append(PERSONAL_DATA_NOTE)

    if "new_package" in reasons:
        parts.append("Tillegget er ikke godkjent fra før.")

    if req.action_type is ActionType.INSTALL_PACKAGE:
        if sandbox_report is not None:
            parts.append(_sandbox_text(sandbox_report))
        elif "new_package" in reasons:
            # Et tillegg vi ikke kjenner OG ikke har prøvd. Det skal staa.
            parts.append(SANDBOX_NOT_TESTED)

    if "destructive_change" in reasons:
        parts.append(
            DESTRUCTIVE_READ_NOTE
            if req.action_type is ActionType.READ_DOCUMENT
            else DESTRUCTIVE_NOTE
        )

    if "incomplete_request" in reasons:
        # Manglet det BELOEP paa en utbetaling, sier vi det rett ut. Den
        # generelle setningen ("vi klarte ikke aa vurdere") er sann, men et
        # menneske som skal svare paa kortet trenger aa vite hva som mangler.
        if no_usable_transfer_amount(req):
            parts.append(
                ZERO_TRANSFER_AMOUNT_NOTE if req.amount is not None
                else MISSING_TRANSFER_AMOUNT_NOTE
            )
        else:
            parts.append(INCOMPLETE_NOTE)

    if "package_on_blocklist" in reasons:
        parts.append("Tillegget står på blokklisten.")

    if "recipient_total_over_limit" in reasons and recipient_total_ore is not None:
        if recipient_total_time_bounded:
            parts.append(
                f"Til sammen {format_ore(recipient_total_ore)} til samme mottaker "
                f"siste {config.TRANSFER_WINDOW_HOURS} timer."
            )
        else:
            # Tidsstemplene hang ikke sammen, saa summen gjelder alt vi har
            # sett. Da maa teksten ikke paastaa et vindu den ikke har brukt.
            parts.append(
                f"Til sammen {format_ore(recipient_total_ore)} til samme mottaker "
                "i alt Lonewatch har sett. Tidsstemplene i forespørslene henger "
                f"ikke sammen, så vinduet på {config.TRANSFER_WINDOW_HOURS} timer "
                "kan ikke brukes."
            )

    if "transfer_over_hard_limit" in reasons:
        parts.append(f"Beløpet er over den harde grensen på {format_amount(config.HARD_TRANSFER_LIMIT_NOK)}.")

    # "Kan ikke angres." står i teksten så lenge det er sant for en handling
    # med virkning utenfor huset, selv om regelen ikke ga risikopoeng.
    if not req.reversible and req.action_type in config.EFFECTFUL_ACTIONS:
        parts.append(IRREVERSIBLE_NOTE)

    if blocked:
        parts.append(BLOCKED_NOTE)

    return " ".join(parts)
