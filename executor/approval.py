"""Et forseglet lov-å-gjøre-det. Avtrykket låser innholdet til godkjenningen.

Problemet: mellomstasjonen vurderer én forespørsel, et menneske godkjenner den
forespørselen - og så er det en helt annen forespørsel som blir utført. Da er
godkjenningen verdiløs. En agent som får endre `recipient` etter at mennesket
har trykket Godkjenn, har i praksis ingen kontroll over seg.

Løsningen er å regne ut et avtrykk (SHA-256 over alle feltene i
forespørselen) i det øyeblikket avgjørelsen faller, og legge avtrykket inn i
godkjenningen. Utføreren regner avtrykket ut på nytt av den forespørselen den
faktisk har fått, og nekter hvis de to ikke er like.

Avtrykket dekker ALLE felt i ActionRequest, også `ts`. Et endret tidspunkt er
også en endret forespørsel.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from contracts import ActionRequest, Decision, HumanResponse, Verdict, canonical_json


def fingerprint(request: ActionRequest) -> str:
    """Avtrykk av en forespørsel. Samme forespørsel gir samme avtrykk hver gang.

    `canonical_json` fra contracts sorterer nøklene, så rekkefølgen i minnet
    kan ikke endre avtrykket. `mode="json"` gjør datoer og enum-er til tekst,
    slik at avtrykket blir det samme etter en tur gjennom en fil eller et
    HTTP-kall.
    """
    body = canonical_json(request.model_dump(mode="json"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Approval:
    """Det som gir en utfører lov til å gjøre noe.

    Lages i det øyeblikket avgjørelsen faller (allow), eller i det øyeblikket
    mennesket svarer (red). Aldri senere: et avtrykk som regnes ut rett før
    utføringen beviser ingenting.
    """

    request_id: str
    request_fingerprint: str
    verdict: Verdict
    human: HumanResponse | None = None

    @property
    def human_approved(self) -> bool:
        return self.human is not None and self.human.approved

    def with_human(self, human: HumanResponse) -> Approval:
        """Samme forsegling, med svaret fra mennesket lagt til.

        Dette er veien en rød sak går: forseglingen lages når avgjørelsen
        faller, og mennesket svarer minutter senere. Avtrykket fra den gang
        BEHOLDES - det er hele poenget. Å kalle `seal()` på nytt ved
        godkjenningen ville regnet ut avtrykket av forespørselen slik den ser
        ut DA, og da ville en endring i mellomtiden gått rett gjennom.
        """
        if human.request_id != self.request_id:
            raise ValueError(
                f"menneskesvaret gjelder {human.request_id!r}, "
                f"men forseglingen er for {self.request_id!r}"
            )
        return Approval(
            request_id=self.request_id,
            request_fingerprint=self.request_fingerprint,
            verdict=self.verdict,
            human=human,
        )


def seal(
    request: ActionRequest,
    decision: Decision,
    human: HumanResponse | None = None,
) -> Approval:
    """Forsegler en avgjørelse mot innholdet i forespørselen.

    Kalles med `human=None` når mellomstasjonen sa allow, og med svaret fra
    mennesket når den sa red. Et `human` som gjelder en annen forespørsel
    stopper her, ikke senere: det er den samme feilen som en rapport om et
    annet tillegg i gateway.
    """
    if decision.request_id != request.id:
        raise ValueError(
            f"avgjørelsen gjelder {decision.request_id!r}, men forespørselen er {request.id!r}"
        )
    if human is not None and human.request_id != request.id:
        raise ValueError(
            f"menneskesvaret gjelder {human.request_id!r}, men forespørselen er {request.id!r}"
        )
    return Approval(
        request_id=request.id,
        request_fingerprint=fingerprint(request),
        verdict=decision.verdict,
        human=human,
    )


def same_amount(left: float | None, right: float | None) -> bool:
    """Er to beløp det samme tallet?

    Flyttall sammenlignes aldri direkte. `Decimal(str(x))` leser tallet slik
    det ser ut skrevet, så 50000.0 og 50000 er like, og 0.1 + 0.2 ikke blir et
    problem. To manglende beløp er IKKE like: da er det ingenting å sjekke mot,
    og den som spør skal få nei.
    """
    if left is None or right is None:
        return False
    try:
        return Decimal(str(left)) == Decimal(str(right))
    except (InvalidOperation, ValueError, TypeError):
        return False
