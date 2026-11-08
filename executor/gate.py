"""Porten: har denne handlingen lov til å skje i det hele tatt.

Dette er det eneste stedet i executor/ som avgjør ja eller nei, og den er
helt deterministisk: samme (forespørsel, avgjørelse, godkjenning) gir samme
svar hver gang. Ingen AI, ingen klokke, ingen tilfeldighet.

Porten slipper gjennom NØYAKTIG to ting:

    allow                            -> gjennomføres
    red som et menneske har godkjent -> gjennomføres

og nekter alt annet:

    red som venter på et menneske    -> nei
    red som et menneske avviste      -> nei
    block                            -> nei, uansett hvem som spør
    innhold endret etter godkjenning -> nei

Rekkefølgen er valgt slik at identitet sjekkes først, så innholdet, så
avgjørelsen. Første regel som slår til bestemmer. Faller vi gjennom alle, er
svaret ja - aldri omvendt.
"""

from __future__ import annotations

from dataclasses import dataclass

from contracts import ActionRequest, Decision, Verdict

from .approval import Approval, fingerprint, same_amount


@dataclass(frozen=True)
class Gate:
    ok: bool
    rule: str  # engelsk regelnavn, havner i ExecutionResult.rule
    detail: str  # norsk klartekst


_YES = Gate(ok=True, rule="", detail="Godkjent for utføring.")


def may_execute(
    request: ActionRequest,
    decision: Decision,
    approval: Approval | None = None,
) -> Gate:
    """Avgjør om utføreren får lov. Sier aldri ja når den er i tvil."""

    # ---- 1. snakker de tre om samme forespørsel ----------------------------
    if decision.request_id != request.id:
        return Gate(
            False,
            "decision_other_request",
            "Ikke utført: avgjørelsen gjelder en annen forespørsel.",
        )
    if approval is not None and approval.request_id != request.id:
        return Gate(
            False,
            "approval_other_request",
            "Ikke utført: godkjenningen gjelder en annen forespørsel.",
        )
    if approval is not None and approval.human is not None and approval.human.request_id != request.id:
        return Gate(
            False,
            "human_other_request",
            "Ikke utført: menneskesvaret gjelder en annen forespørsel.",
        )

    # ---- 2. er det det samme som ble godkjent -----------------------------
    if approval is not None:
        if approval.verdict is not decision.verdict:
            return Gate(
                False,
                "verdict_changed",
                "Ikke utført: avgjørelsen er byttet ut etter godkjenningen.",
            )
        if approval.request_fingerprint != fingerprint(request):
            return Gate(
                False,
                "content_changed",
                "Ikke utført: innholdet er endret etter godkjenningen.",
            )
    elif decision.ts != request.ts:
        # Uten forsegling er dette alt vi kan sjekke. Mellomstasjonen stempler
        # avgjørelsen med forespørselens eget tidspunkt, så to ulike tidspunkt
        # betyr at forespørselen er rørt etter vurderingen. Se executor/LIMITS.md:
        # dette fanger ikke en endret mottaker, og derfor skal den som kaller
        # alltid sende en forsegling.
        return Gate(
            False,
            "unsealed_timestamp_changed",
            "Ikke utført: forespørselen er endret etter at den ble vurdert.",
        )

    # ---- 3. hva sa mellomstasjonen ----------------------------------------
    if decision.verdict is Verdict.BLOCK:
        return Gate(
            False,
            "verdict_block",
            "Ikke utført: mellomstasjonen blokkerte handlingen. Ingen kan godkjenne den.",
        )

    if decision.verdict is Verdict.RED:
        if approval is None or approval.human is None:
            return Gate(
                False,
                "red_waiting",
                "Ikke utført: saken venter på at et menneske ser på den.",
            )
        if not approval.human.approved:
            return Gate(
                False,
                "red_rejected",
                "Ikke utført: et menneske avviste saken.",
            )
    elif approval is not None and approval.human is not None and not approval.human.approved:
        # Mellomstasjonen sa allow, men et menneske har likevel sagt nei.
        # Mennesket vinner. Et nei skal aldri bli et ja fordi reglene var rolige.
        return Gate(
            False,
            "human_rejected",
            "Ikke utført: et menneske avviste saken.",
        )

    # ---- 4. skrev mennesket inn riktig beløp ------------------------------
    if decision.requires_typed_amount:
        human = approval.human if approval is not None else None
        if human is None or human.typed_amount is None:
            return Gate(
                False,
                "typed_amount_missing",
                "Ikke utført: mennesket må skrive inn beløpet selv.",
            )
        if not same_amount(human.typed_amount, request.amount):
            return Gate(
                False,
                "typed_amount_mismatch",
                "Ikke utført: beløpet mennesket skrev inn er ikke beløpet i forespørselen.",
            )

    return _YES
