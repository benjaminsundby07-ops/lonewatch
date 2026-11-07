"""Kjoerer hele flyten fra start til slutt i terminalen.

Bruk: python run_demo.py
"""

from __future__ import annotations

from datetime import timedelta

from agents.scenarios import all_scenarios
from contracts import ActionRequest, ActionType, Decision, HumanResponse, SandboxReport, Verdict
from gateway import evaluate
from sandbox import UnknownPackage, scan_cached
from vault import Vault, pseudonymize, redact_enabled

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


def _scan(req: ActionRequest, vault: Vault, seen: set[str]) -> SandboxReport | None:
    """Prøver tillegget i sandkassen før avgjørelsen, og logger rapporten.

    Ingenting kjøres ut fra et navn vi får i en forespørsel: scan_cached slår
    navnet opp blant filene i sandbox/packages/, og et navn som ikke ligger der
    gir UnknownPackage uten at det startes en prosess.
    """
    if req.action_type is not ActionType.INSTALL_PACKAGE:
        return None
    name = (req.package_name or "").strip()
    if not name:
        return None
    try:
        report = scan_cached(name)
    except UnknownPackage:
        return None

    if name not in seen:
        seen.add(name)
        vault.append("sandbox", report.model_dump(mode="json"), ts=report.ts)
    return report


def run(vault: Vault | None = None) -> Vault:
    """Spiller alle scenarioene gjennom mellomstasjonen og logger alt."""
    # Samme minimering som nettsiden. Se vault/LIMITS.md punkt 7.
    vault = vault if vault is not None else Vault(redact=redact_enabled())
    scanned: set[str] = set()
    # Forespørslene gateway har sett. Brukes til å summere overføringer til
    # samme mottaker innenfor tidsvinduet. Ligger i minnet, som i appen.
    history: list[ActionRequest] = []

    for req in all_scenarios():
        vault.append("request", req.model_dump(mode="json"), ts=req.ts)
        report = _scan(req, vault, scanned)
        decision = evaluate(req, sandbox_report=report, history=history)
        vault.append("decision", decision.model_dump(mode="json"), ts=decision.ts)
        history.append(req)

        print(LINE)
        print(f"{req.id}  {req.agent_id}  {req.action_type.value}")
        print(f"  agenten sier : {req.summary}")
        print(f"  avgjørelse   : {decision.verdict.value.upper()}  (risiko {decision.risk.value})")
        print(f"  regler       : {', '.join(decision.reasons) or 'ingen'}")
        print(f"  konsekvens   : {decision.consequence_text}")
        if req.action_type is ActionType.INSTALL_PACKAGE:
            if report is None:
                print("  sandkassen   : har ikke dette tillegget, ingenting ble kjørt")
            else:
                print(f"  sandkassen   : {report.verdict} - {report.notes}")

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
    minimert = "ja" if redact_enabled() else "nei (LONEWATCH_REDACT er av)"
    print(f"Logg: {len(vault)} linjer   dataminimering: {minimert}")
    broken = vault.verify()
    if broken is None:
        print("Sjekk av logg: OK, ingen linjer er endret.")
        return 0
    print(f"Sjekk av logg: FEIL, første ødelagte linje er seq={broken}.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
