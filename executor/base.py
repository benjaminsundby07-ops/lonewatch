"""Grensesnittet alle utførere deler, og den som ikke gjør noe.

Alt som er felles ligger her, slik at en ny utfører bare trenger å skrive de
to siste stegene:

    execute(request, decision, approval)
      1. porten            gate.may_execute()   -> nei gir "ikke utført"
      2. forberedelse      _prepare()           -> rører ingenting ute
      3. boka              ledger.claim()       -> andre gang gir "ikke utført"
      4. selve handlingen  _perform()           -> det ENESTE irreversible steget
      5. svaret            ExecutionResult

Rekkefølgen er hele poenget. Porten kommer før boka, slik at en rød sak som
venter kan utføres senere når mennesket har svart. Forberedelsen kommer også
før boka, slik at et feil oppsett (ingen postserver satt opp) ikke brenner
forespørselen - der kan ingenting ha skjedd ute, og et nytt forsøk er trygt.
Boka kommer rett før handlingen, så en handling som brekker midtveis aldri
gjentas.

`execute()` kaster aldri. Alt som går galt kommer tilbake som
`executed=False` med en norsk setning. En stille feil er den ene feilen en
mellomstasjon ikke har lov til å ha.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from contracts import ActionRequest, Decision

from . import result as res
from .approval import Approval
from .gate import may_execute
from .once import AttemptLedger
from .result import ExecutionResult


class ExecutorError(RuntimeError):
    """Noe er galt med oppsettet eller forespørselen, og vi rører ikke omverdenen.

    Kastes fra `_prepare()`. Den som kalte `execute()` ser den aldri: den blir
    et "ikke utført"-svar, og forespørselen kan forsøkes igjen når oppsettet er
    rettet.
    """


class Executor(ABC):
    """Den som faktisk gjør handlingen etter at Lonewatch har sagt ja."""

    name = "executor"

    def __init__(self, ledger: AttemptLedger | None = None) -> None:
        # Hver utfører har sin egen bok med mindre du gir den en felles. Flere
        # utførere som deler bok er riktig når de kan gjøre samme handling.
        self.ledger = ledger if ledger is not None else AttemptLedger()

    # -- det en ny utfører skriver -----------------------------------------

    def _prepare(
        self,
        request: ActionRequest,
        decision: Decision,
        approval: Approval | None,
    ) -> Any:
        """Alt som kan gå galt uten at noe skjer ute. Kaster ExecutorError.

        Returnerer det `_perform()` trenger. Standard er ingenting.
        """
        return None

    @abstractmethod
    def _perform(self, request: ActionRequest, decision: Decision, plan: Any) -> tuple[str, str | None]:
        """Gjør handlingen. Returnerer (norsk setning, hvor det gikk).

        Dette er det eneste steget som rører omverdenen. Alt som kastes her
        blir "ikke utført", og forespørselen prøves aldri igjen.
        """

    # -- den felles flyten --------------------------------------------------

    def execute(
        self,
        request: ActionRequest,
        decision: Decision,
        approval: Approval | None = None,
    ) -> ExecutionResult:
        gate = may_execute(request, decision, approval)
        if not gate.ok:
            return res.refused(request.id, self.name, gate.rule, gate.detail)

        avtrykk = approval.request_fingerprint if approval is not None else None

        try:
            plan = self._prepare(request, decision, approval)
        except ExecutorError as exc:
            return res.failed(
                request.id,
                self.name,
                f"Ikke utført: {exc}",
                rule="setup_error",
                fingerprint=avtrykk,
            )
        except Exception as exc:  # noqa: BLE001 - en ukjent feil skal heller ikke slippe ut
            return res.failed(
                request.id,
                self.name,
                f"Ikke utført: uventet feil før utføring ({type(exc).__name__}).",
                rule="setup_error",
                fingerprint=avtrykk,
            )

        if not self.ledger.claim(request.id):
            return res.already_attempted(
                request.id,
                self.name,
                "Ikke utført: denne forespørselen er forsøkt før. "
                "En handling gjentas aldri. Send inn en ny forespørsel.",
            )

        try:
            detail, target = self._perform(request, decision, plan)
        except Exception as exc:  # noqa: BLE001 - ingenting får slippe ut til den som kalte
            # Boka får IKKE plassen tilbake: vi vet ikke om handlingen gikk
            # halvveis gjennom, og et nytt forsøk kunne gjort den to ganger.
            return res.failed(
                request.id,
                self.name,
                f"Ikke utført: {type(exc).__name__}: {exc}",
                rule="perform_error",
                fingerprint=avtrykk,
            )

        return res.done(request.id, self.name, detail, target=target, fingerprint=avtrykk)


class SimulatedExecutor(Executor):
    """Standardutføreren: later som, gjør ingenting.

    Dette er den riktige utføreren for demoen og for alle handlingstyper vi
    ikke har bygget en ekte kobling til. Den går gjennom nøyaktig samme port
    som den ekte, så en rød sak som venter blir ikke utført her heller.
    """

    name = "simulated"

    def __init__(self, ledger: AttemptLedger | None = None) -> None:
        super().__init__(ledger=ledger)
        # Hva som ble "gjort". Testene og demoen leser denne.
        self.performed: list[str] = []

    def _perform(self, request: ActionRequest, decision: Decision, plan: Any) -> tuple[str, str | None]:
        self.performed.append(request.id)
        return (
            f"Simulert: {request.action_type.value} ble ikke gjort på ekte. "
            "Ingen e-post, ingen penger, ingen nettverkskall.",
            None,
        )
