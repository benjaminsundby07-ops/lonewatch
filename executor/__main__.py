"""Manuell kjøring: start postfangeren, send en godkjent e-post, vis filen.

    python -m executor

Dette er den samme veien en ekte handling går, bortsett fra at postfangeren
står der bedriftens postserver ville stått. Fire forespørsler kjøres:

    1. allow                    -> sendes
    2. red som venter           -> ikke sendt
    3. red som er godkjent      -> sendes
    4. allow, men endret etter  -> ikke sendt

Til slutt listes .eml-filene som faktisk ligger på disk. Det skal være to.

Ingenting her går på nettet: postfangeren lytter på 127.0.0.1 på en port
operativsystemet velger.
"""

from __future__ import annotations

import argparse
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from contracts import ActionRequest, ActionType, Decision, HumanResponse, Risk, Verdict

from .approval import seal
from .mailcatcher import MailCatcher
from .result import ExecutionResult
from .smtp import SmtpConfig, SmtpExecutor

TS = datetime(2026, 11, 8, 9, 0, tzinfo=timezone.utc)


def _request(req_id: str, recipient: str, summary: str) -> ActionRequest:
    return ActionRequest(
        id=req_id,
        ts=TS,
        agent_id="kundeservice",
        action_type=ActionType.SEND_EMAIL,
        summary=summary,
        recipient=recipient,
    )


def _decision(req: ActionRequest, verdict: Verdict, risk: Risk, text: str) -> Decision:
    return Decision(
        request_id=req.id,
        ts=req.ts,
        verdict=verdict,
        risk=risk,
        reasons=[],
        consequence_text=text,
    )


def _human(req_id: str, approved: bool) -> HumanResponse:
    return HumanResponse(
        request_id=req_id,
        ts=TS + timedelta(seconds=40),
        employee_pseudonym="emp_1a2b",
        approved=approved,
        seconds_to_decide=40.0,
    )


def _show(label: str, result: ExecutionResult) -> None:
    merke = "UTFORT    " if result.executed else "IKKE GJORT"
    print(f"  [{merke}] {label}")
    print(f"               status={result.status.value} regel={result.rule or '-'}")
    print(f"               {result.detail}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m executor")
    parser.add_argument(
        "--dir",
        default=None,
        help="mappen .eml-filene legges i (standard: en midlertidig mappe)",
    )
    args = parser.parse_args(argv)

    maildrop = Path(args.dir) if args.dir else Path(tempfile.mkdtemp(prefix="lonewatch-post-"))

    with MailCatcher(directory=maildrop) as catcher:
        host, port = catcher.address
        print(f"Postfangeren lytter paa {host}:{port}")
        print(f"Meldinger lagres i {catcher.directory.resolve()}\n")

        # Oppsettet peker paa postfangeren. allow_remote staar paa False:
        # utforeren ville nektet aa sende noe annet sted.
        config = SmtpConfig(host=host, port=port)
        utforer = SmtpExecutor(config=config)

        print("1) allow - e-post til en kjent mottaker")
        req1 = _request("req_demo_1", "oline.dahl@nordlys.no", "Svar paa sak 4411: skaden er registrert.")
        dec1 = _decision(req1, Verdict.ALLOW, Risk.LOW, "E-posten sendes til en kjent mottaker.")
        _show("allow", utforer.execute(req1, dec1, seal(req1, dec1)))

        print("\n2) red som venter paa et menneske")
        req2 = _request("req_demo_2", "ukjent@eksempel.invalid", "Sender kundelisten til ny samarbeidspartner.")
        dec2 = _decision(req2, Verdict.RED, Risk.HIGH, "Mottakeren er ukjent. Noen maa se paa dette.")
        _show("red, venter", utforer.execute(req2, dec2, seal(req2, dec2)))

        print("\n3) samme sak, etter at et menneske godkjente den")
        _show("red, godkjent", utforer.execute(req2, dec2, seal(req2, dec2, _human(req2.id, True))))

        print("\n4) allow, men mottakeren er byttet etter godkjenningen")
        req4 = _request("req_demo_4", "kjent@nordlys.no", "Rutinemelding.")
        dec4 = _decision(req4, Verdict.ALLOW, Risk.LOW, "E-posten sendes til en kjent mottaker.")
        godkjenning = seal(req4, dec4)
        endret = req4.model_copy(update={"recipient": "angriper@eksempel.invalid"})
        _show("endret innhold", utforer.execute(endret, dec4, godkjenning))

        print("\n.eml-filer paa disk:")
        filer = catcher.eml_files()
        for path in filer:
            print(f"  {path}  ({path.stat().st_size} byte)")
        if not filer:
            print("  ingen")

        print(f"\nForventet 2 filer, fant {len(filer)}.")
        if filer:
            print("\nForste fil, de forste linjene:")
            for line in filer[0].read_text(encoding="utf-8").splitlines()[:12]:
                print(f"  {line}")
        return 0 if len(filer) == 2 else 1


if __name__ == "__main__":
    raise SystemExit(main())
