"""Mellomstasjonen: alt en agent vil gjøre går gjennom evaluate() først.

Flyten er helt deterministisk:

    1. blokkreglene kjøres   -> slår en til, er svaret block (ingen kan godkjenne)
    2. risikoreglene kjøres  -> navnene legges i Decision.reasons
    3. poengsummen gir risiko low/medium/high
    4. low -> allow, medium/high -> red
    5. konsekvensteksten settes sammen av maler på norsk

Ingen AI-modell er involvert, og `req.summary` leses aldri. Samme forespørsel
gir samme avgjørelse hver gang.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone

from contracts import ActionRequest, ActionType, Decision, Risk, SandboxReport, Verdict

from . import config, rules
from .consequence import UNJUDGEABLE_NOTE, build_consequence_text, format_amount

__all__ = [
    "evaluate",
    "score_to_risk",
    "format_amount",
    "build_consequence_text",
    "SandboxReportMismatch",
    "config",
    "rules",
]


class SandboxReportMismatch(ValueError):
    """Sandkasserapporten hoerer ikke til denne forespoerselen.

    Dette er den ENE feilen `evaluate()` fortsatt kaster. Grunnen: en rapport om
    et annet tillegg er ikke noe vi kan gjoere et fornuftig svar av - hadde vi
    svart `block` og gaatt videre, ville den som kalte trodd at rapporten ble
    lest. Her skal kallet stoppe, slik at feilen rettes der den er gjort.

    Arver fra `ValueError`, slik at kallere som alt fanger `ValueError` ikke
    merker forskjellen.
    """


# Tidspunktet vi setter paa et svar om noe vi ikke klarte aa lese i det hele
# tatt. Det maa vaere ET tidspunkt (`contracts.Decision` krever det), og det
# maa vaere det samme hver gang - klokken ville gjort svaret utidsbestemt.
# 0001-01-01 er ikke til aa forveksle med et ekte tidsstempel.
UNJUDGEABLE_TS = datetime(1, 1, 1, tzinfo=timezone.utc)


def score_to_risk(score: int) -> Risk:
    """Poengsum -> risikonivå. Tersklene står i config."""
    if score >= config.HIGH_SCORE_MIN:
        return Risk.HIGH
    if score >= config.MEDIUM_SCORE_MIN:
        return Risk.MEDIUM
    return Risk.LOW


def _checked_report(
    req: ActionRequest, sandbox_report: SandboxReport | None
) -> SandboxReport | None:
    """Sier fra hvis rapporten ikke hører til denne forespørselen.

    En rapport om et ANNET tillegg maa aldri kunne avgjøre denne forespørselen:
    da kunne en "clean"-rapport om pdf-helper sluppet inn noe helt annet. Vi
    stopper heller hele kallet enn aa se bort fra rapporten i stillhet.
    """
    if sandbox_report is None:
        return None
    if req.action_type is not ActionType.INSTALL_PACKAGE:
        raise SandboxReportMismatch(
            f"sandbox_report gir bare mening for install_package, ikke {req.action_type.value}"
        )
    if rules.normalize_package_name(sandbox_report.package_name) != rules.normalize_package_name(
        req.package_name
    ):
        raise SandboxReportMismatch(
            f"sandbox_report gjelder {sandbox_report.package_name!r}, "
            f"men forespørselen gjelder {req.package_name!r}"
        )
    return sandbox_report


def _unjudgeable(req: object) -> Decision:
    """Svaret paa noe vi ikke klarte aa lese: `block`, og ingen kan godkjenne det.

    Foer kastet `evaluate()` et unntak her. Ingen fikk `allow` - saa langt var
    det fail-closed - men den som KALTE maatte huske aa fange det. `ui/state.py`
    gjoer det; en ny integrasjon kan glemme det, og hva som skjer da (koe som
    stopper, forespoersel som forsvinner, verktoey som kalles likevel) ble
    bestemt utenfor gateway. Naa er fail-closed en EGENSKAP ved svaret. Se H23 i
    docs/ANGREP.md.

    `contracts.Decision` krever `request_id` og `ts`. Vi redder det vi kan av
    feltene og bruker noeytrale verdier for resten: tom id naar vi ikke vet hva
    forespoerselen heter, og `UNJUDGEABLE_TS` naar vi ikke har et tidspunkt.
    Ingenting av det vi leste havner i teksten.
    """
    request_id = ""
    ts = UNJUDGEABLE_TS
    try:
        kandidat_id = getattr(req, "id", None)
        if isinstance(kandidat_id, str):
            request_id = kandidat_id
        kandidat_ts = getattr(req, "ts", None)
        if isinstance(kandidat_ts, datetime):
            ts = kandidat_ts
    except Exception:
        # Selv det aa se paa feltene kan feile. Da staar de noeytrale verdiene.
        pass

    return Decision(
        request_id=request_id,
        ts=ts,
        verdict=Verdict.BLOCK,
        risk=Risk.HIGH,
        reasons=[rules.UNJUDGEABLE_REQUEST],
        consequence_text=UNJUDGEABLE_NOTE,
        requires_typed_amount=False,
    )


def evaluate(
    req: ActionRequest,
    sandbox_report: SandboxReport | None = None,
    history: Sequence[ActionRequest] | None = None,
) -> Decision:
    """Avgjør hva som skjer med en forespørsel fra en agent.

    `sandbox_report` er valgfri og brukes bare ved install_package. Den kommer
    fra sandbox/, som har kjørt tillegget i en lukket boks og sett hva det
    faktisk gjorde. Gateway kjører ingenting selv: den tar imot et resultat.

    `history` er valgfri og er tidligere forespørsler integrasjonslaget har
    sett. Den brukes bare til å summere overføringer til samme mottaker
    innenfor et tidsvindu - hullet der 100 betalinger på 49 999 kr gikk rett
    gjennom fordi hver enkelt var under grensen. Gateway husker ingenting selv:
    den tar imot en liste. Se docs/MALING.md.

    Uten disse to oppfører evaluate() seg nøyaktig som før.

    Fortsatt deterministisk: samme (req, rapport, historikk) gir samme Decision
    hver gang. Tidsvinduet regnes fra tidsstemplene i kallet, aldri fra klokken.

    FAIL-CLOSED: klarer vi ikke å lese forespørselen i det hele tatt, kommer det
    en `block`-Decision ut, ikke et unntak. Den ENE feilen som fortsatt kastes
    er `SandboxReportMismatch`: en rapport om et annet tillegg er en feil hos
    den som kaller, og den skal rettes der.
    """
    try:
        report = _checked_report(req, sandbox_report)
        return _judge(req, report, history)
    except SandboxReportMismatch:
        raise
    except Exception:
        return _unjudgeable(req)


def _judge(
    req: ActionRequest,
    report: SandboxReport | None,
    history: Sequence[ActionRequest] | None,
) -> Decision:
    """Selve vurderingen. Kalles bare fra `evaluate()`, som fanger alt som går galt."""
    block_reasons = rules.triggered_block_rules(req, report)
    risk_reasons = rules.triggered_risk_rules(req, history)
    total_ore = rules.recipient_total_ore(req, history)
    time_bounded = rules.transfer_time_axis_is_usable(
        req, rules.matching_transfer_priors(req, history)
    )

    if block_reasons:
        # Blokk slår alltid risikopoengene. Risikoen settes til high fordi
        # noe vi stopper helt alltid er det alvorligste vi ser.
        reasons = block_reasons + risk_reasons
        return Decision(
            request_id=req.id,
            ts=req.ts,
            verdict=Verdict.BLOCK,
            risk=Risk.HIGH,
            reasons=reasons,
            consequence_text=build_consequence_text(
                req, reasons, blocked=True, sandbox_report=report,
                recipient_total_ore=total_ore,
                recipient_total_time_bounded=time_bounded,
            ),
            requires_typed_amount=False,
        )

    risk = score_to_risk(rules.risk_score(risk_reasons))
    verdict = Verdict.ALLOW if risk is Risk.LOW else Verdict.RED

    # Mennesket må skrive inn beløpet selv når penger skal flyttes og noen må se på det.
    requires_typed_amount = verdict is Verdict.RED and req.action_type is ActionType.TRANSFER_MONEY

    return Decision(
        request_id=req.id,
        ts=req.ts,
        verdict=verdict,
        risk=risk,
        reasons=risk_reasons,
        consequence_text=build_consequence_text(
            req, risk_reasons, sandbox_report=report, recipient_total_ore=total_ore,
            recipient_total_time_bounded=time_bounded,
        ),
        requires_typed_amount=requires_typed_amount,
    )
