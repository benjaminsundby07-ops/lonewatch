"""Kjoerer hele flyten fra start til slutt i terminalen.

Bruk: python run_demo.py
"""

from __future__ import annotations

from datetime import timedelta

from agents.scenarios import all_scenarios
from contracts import ActionRequest, Decision, HumanResponse, Verdict
from gateway import evaluate
from vault import Vault, pseudonymize

LINE = "-" * 72


def _fake_human_response(req: ActionRequest, decision: Decision) -> HumanResponse:
    """MIDLERTIDIG: det finnes ingen UI ennå, så demoen svarer nei for mennesket."""
    return HumanResponse(
        request_id=req.id,
        ts=decision.ts + timedelta(seconds=12),
        employee_pseudonym=pseudonymize("ansatt-007"),
        approved=False,
        typed_amount=None,
        seconds_to_decide=12.0,
    )


def run(vault: Vault | None = None) -> Vault:
    """Spiller alle scenarioene gjennom mellomstasjonen og logger alt."""
    vault = vault if vault is not None else Vault()

    for req in all_scenarios():
        vault.append("request", req.model_dump(mode="json"), ts=req.ts)
        decision = evaluate(req)
        vault.append("decision", decision.model_dump(mode="json"), ts=decision.ts)

        print(LINE)
        print(f"{req.id}  {req.agent_id}  {req.action_type.value}")
        print(f"  agenten sier : {req.summary}")
        print(f"  avgjørelse   : {decision.verdict.value.upper()}  (risiko {decision.risk.value})")
        print(f"  regler       : {', '.join(decision.reasons) or 'ingen'}")
        print(f"  konsekvens   : {decision.consequence_text}")

        if decision.verdict is Verdict.ALLOW:
            print("  -> gjennomført (simulert)")
        elif decision.verdict is Verdict.RED:
            human = _fake_human_response(req, decision)
            vault.append("human", human.model_dump(mode="json"), ts=human.ts)
            svar = "godkjent" if human.approved else "avvist"
            print(f"  -> satt i kø, menneske ({human.employee_pseudonym}) {svar} etter "
                  f"{human.seconds_to_decide:.0f} s")
        else:
            print("  -> avvist av mellomstasjonen")

    return vault


def main() -> int:
    vault = run()

    print(LINE)
    print(f"Logg: {len(vault)} linjer")
    broken = vault.verify()
    if broken is None:
        print("Sjekk av logg: OK, ingen linjer er endret.")
        return 0
    print(f"Sjekk av logg: FEIL, første ødelagte linje er seq={broken}.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
