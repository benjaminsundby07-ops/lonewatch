"""Formsjekk av det agenten sender, FØR det når Lonewatch.

Dette er ikke en risikovurdering. Her avgjøres ingenting om allow, rødt eller
block - det gjør `gateway/` alene, på samme måte som før. Her kastes bare input
som åpenbart ikke har en form Lonewatch kan behandle:

- tekstfelt som er lengre enn noe et menneske skal lese i et rødt kort
- kontrolltegn og linjeskift i `recipient` og `package_name`, altså de to
  feltene som havner i en e-post, en logglinje og et kort i dashbordet
- felt vi ikke kjenner
- beløp som er negative, eller som ikke er et endelig tall

Feilmeldingen sier hvilket FELT som ikke holder, og ingenting mer. Den nevner
ingen regel, ingen grense for beløp og ingen liste over kjente mottakere: det
ville vært en oppskrift på hva som må endres for å slippe gjennom. Lengdene og
tegnreglene under er form, ikke risiko, og de står med vilje i koden - en agent
som leser denne filen lærer ingenting om hva som blir stoppet.

Grunnen til at det finnes: `ui/state.py` og det røde kortet viser `recipient`
til et menneske. Et linjeskift eller et kontrolltegn i den teksten er det
billigste trikset som finnes for å få et kort til å se ut som noe annet enn det
er, og en tekst på 50 000 tegn er det billigste trikset for at mennesket ikke
leser kortet i det hele tatt.
"""

from __future__ import annotations

import math
import unicodedata

# Lengdene. `summary` er alt satt til 200 i MCP-verktøyene (server.py), og
# står her også fordi `run_action` kan kalles uten MCP (scripted_demo).
MAX_SUMMARY = 200
MAX_RECIPIENT = 200
MAX_PACKAGE = 100

# Et tak på beløpet. Dette er IKKE en risikogrense - gateway eier dem. Det er
# en formgrense: et beløp på 1e308 er ikke et beløp, det er et forsøk på å
# sprenge noe som regner. Alt under taket sendes videre uvurdert.
MAX_AMOUNT = 10**15

# Feltene et verktøykall kan ha. Alt annet avvises i stedet for å bli ignorert
# stille, på samme måte som `AgentSubmitIn` i appen svarer 422 på ukjente felt.
KNOWN_FIELDS = frozenset(
    {
        "summary",
        "amount",
        "recipient",
        "package_name",
        "contains_personal_data",
    }
)


class UgyldigInput(ValueError):
    """Formen holder ikke. Dette er ikke en avgjørelse - kallet er ikke vurdert."""


def _har_kontrolltegn(text: str) -> bool:
    """Kontrolltegn (C0/C1) eller noe unicode regner som et formattegn."""
    for ch in text:
        if ch in "\t\n\r\v\f":
            return True
        if unicodedata.category(ch) in ("Cc", "Cf", "Cs", "Co", "Cn"):
            return True
    return False


def _tekst(navn: str, verdi: object, *, maks: int, ren: bool) -> str:
    if verdi is None:
        return ""
    if not isinstance(verdi, str):
        raise UgyldigInput(f"Feltet «{navn}» må være tekst.")
    if len(verdi) > maks:
        raise UgyldigInput(f"Feltet «{navn}» er for langt (maks {maks} tegn).")
    if ren and _har_kontrolltegn(verdi):
        raise UgyldigInput(
            f"Feltet «{navn}» kan ikke inneholde linjeskift eller usynlige tegn."
        )
    return verdi.strip()


def _belop(verdi: object) -> float | int | None:
    if verdi is None:
        return None
    # `True` er en int i Python. En bryter er ikke et beløp.
    if isinstance(verdi, bool) or not isinstance(verdi, (int, float)):
        raise UgyldigInput("Feltet «amount» må være et tall.")
    if isinstance(verdi, float) and not math.isfinite(verdi):
        raise UgyldigInput("Feltet «amount» må være et endelig tall.")
    if verdi < 0:
        raise UgyldigInput("Feltet «amount» kan ikke være negativt.")
    if verdi > MAX_AMOUNT:
        raise UgyldigInput("Feltet «amount» er for stort for å være et beløp.")
    return verdi


def sjekk_input(
    *,
    summary: object = "",
    amount: object = None,
    recipient: object = "",
    package_name: object = "",
    contains_personal_data: object = False,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    """Returnerer de rensede feltene, eller kaster `UgyldigInput`.

    Rekkefølgen er med vilje: ukjente felt først. Sender noen et felt som ville
    avgjort noe (`recipient_known`, `reversible`), skal svaret si at feltet er
    ukjent - ikke at teksten i et annet felt var for lang.
    """
    if extra:
        ukjente = ", ".join(sorted(str(navn) for navn in extra))
        raise UgyldigInput(f"Ukjent(e) felt: {ukjente}.")

    if not isinstance(contains_personal_data, bool):
        raise UgyldigInput("Feltet «contains_personal_data» må være true eller false.")

    return {
        "summary": _tekst("summary", summary, maks=MAX_SUMMARY, ren=False),
        "amount": _belop(amount),
        "recipient": _tekst("recipient", recipient, maks=MAX_RECIPIENT, ren=True),
        "package_name": _tekst(
            "package_name", package_name, maks=MAX_PACKAGE, ren=True
        ),
        "contains_personal_data": contains_personal_data,
    }
