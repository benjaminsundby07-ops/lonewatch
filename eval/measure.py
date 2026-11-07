"""Måler regelsettet mot en uavhengig testmengde.

    python -m eval.measure                      # tests/data/blind_set_1.json
    python -m eval.measure --set <fil.json>
    python -m eval.measure --markdown           # klar til å lime inn i docs/MALING.md

Forskjellen fra `gateway/evaluation.py`: der har samme person skrevet både
reglene og testmengden, så den måler bare at koden gjør det vi mente. Settene
her er skrevet av noen som IKKE hadde sett reglene, og merkelappene
(`bor_stoppes`, `usikker`, `hvorfor`) er deres vurdering, ikke vår.

«Stoppet» betyr `red` eller `block`: begge krever at noe annet enn agenten
skjer før handlingen går gjennom.

Forespørslene kjøres uten `sandbox_report`. Sandkassen kan bare uttale seg om
tillegg den har en fil for, og det har den ikke for noen av navnene i et
blindsett. Målingen gjelder altså reglene alene.

Kjøringen er deterministisk: ingen klokke, ingen tilfeldighet, ingen nettverk.
Samme fil gir samme tall hver gang.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from contracts import ActionRequest, Verdict
from gateway import evaluate

DEFAULT_SET = Path(__file__).resolve().parents[1] / "tests" / "data" / "blind_set_1.json"

# Feltene som er menneskelige merkelapper, ikke en del av ActionRequest.
LABEL_FIELDS = ("bor_stoppes", "usikker", "hvorfor")


@dataclass(frozen=True)
class Case:
    """Én forespørsel med merkelappen den kom med."""

    request: ActionRequest
    should_stop: bool
    uncertain: bool
    why: str


@dataclass
class Report:
    """Resultatet av én måling."""

    name: str
    total: int = 0
    caught: list[Case] = field(default_factory=list)
    missed: list[Case] = field(default_factory=list)
    correct_pass: list[Case] = field(default_factory=list)
    false_alarms: list[Case] = field(default_factory=list)
    uncertain_stopped: list[Case] = field(default_factory=list)
    uncertain_passed: list[Case] = field(default_factory=list)
    verdicts: dict[str, int] = field(default_factory=dict)

    @property
    def dangerous_total(self) -> int:
        return len(self.caught) + len(self.missed)

    @property
    def harmless_total(self) -> int:
        return len(self.correct_pass) + len(self.false_alarms)

    @property
    def uncertain_total(self) -> int:
        return len(self.uncertain_stopped) + len(self.uncertain_passed)


def load_cases(path: Path) -> list[Case]:
    """Leser settet. Merkelappene skilles fra feltene ActionRequest kjenner."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    cases: list[Case] = []
    for row in raw:
        fields = {k: v for k, v in row.items() if k not in LABEL_FIELDS}
        cases.append(
            Case(
                request=ActionRequest(**fields),
                should_stop=bool(row.get("bor_stoppes")),
                uncertain=bool(row.get("usikker")),
                why=str(row.get("hvorfor", "")),
            )
        )
    return cases


def measure(cases: list[Case], name: str = "blind_set_1") -> Report:
    """Kjører hele settet gjennom gateway.evaluate() og teller."""
    report = Report(name=name, total=len(cases))
    report.verdicts = {v.value: 0 for v in Verdict}

    for case in cases:
        decision = evaluate(case.request)
        report.verdicts[decision.verdict.value] += 1
        stopped = decision.verdict is not Verdict.ALLOW

        if case.uncertain:
            (report.uncertain_stopped if stopped else report.uncertain_passed).append(case)
        elif case.should_stop:
            (report.caught if stopped else report.missed).append(case)
        else:
            (report.false_alarms if stopped else report.correct_pass).append(case)

    return report


def _lines(report: Report, case: Case) -> str:
    d = evaluate(case.request)
    regler = ", ".join(d.reasons) or "ingen"
    return f"  {case.request.id}  {d.verdict.value:5}  [{regler}]\n      {case.why}"


def format_report(report: Report) -> str:
    r = report
    out = [
        f"Testmengde: {r.name}   ({r.total} forespørsler)",
        "-" * 72,
        f"Farlige (bor_stoppes, ikke usikre) : {r.dangerous_total}",
        f"  stoppet (red/block)              : {len(r.caught)}",
        f"  sluppet gjennom                  : {len(r.missed)}",
        f"Harmløse (ikke usikre)             : {r.harmless_total}",
        f"  riktig gjennom                   : {len(r.correct_pass)}",
        f"  falske alarmer                   : {len(r.false_alarms)}",
        f"Usikre (telles for seg)            : {r.uncertain_total}",
        f"  stoppet                          : {len(r.uncertain_stopped)}",
        f"  sluppet gjennom                  : {len(r.uncertain_passed)}",
        "-" * 72,
        "Avgjørelser: " + ", ".join(f"{k}={v}" for k, v in r.verdicts.items()),
    ]
    if r.missed:
        out += ["", "SLUPPET GJENNOM (merket farlig):"] + [_lines(r, c) for c in r.missed]
    if r.false_alarms:
        out += ["", "FALSKE ALARMER (merket harmløs):"] + [_lines(r, c) for c in r.false_alarms]
    if r.uncertain_passed:
        out += ["", "USIKRE som slapp gjennom:"] + [_lines(r, c) for c in r.uncertain_passed]
    if r.uncertain_stopped:
        out += ["", "USIKRE som ble stoppet:"] + [_lines(r, c) for c in r.uncertain_stopped]
    return "\n".join(out)


def format_markdown(report: Report) -> str:
    r = report
    rows = [
        f"| Farlige (ikke usikre) | {r.dangerous_total} | |",
        f"| &nbsp;&nbsp;stoppet | {len(r.caught)} | red eller block |",
        f"| &nbsp;&nbsp;sluppet gjennom | {len(r.missed)} | "
        + (", ".join(c.request.id for c in r.missed) or "&mdash;")
        + " |",
        f"| Harmløse (ikke usikre) | {r.harmless_total} | |",
        f"| &nbsp;&nbsp;riktig gjennom | {len(r.correct_pass)} | |",
        f"| &nbsp;&nbsp;falske alarmer | {len(r.false_alarms)} | "
        + (", ".join(c.request.id for c in r.false_alarms) or "&mdash;")
        + " |",
        f"| Usikre | {r.uncertain_total} | |",
        f"| &nbsp;&nbsp;stoppet | {len(r.uncertain_stopped)} | "
        + (", ".join(c.request.id for c in r.uncertain_stopped) or "&mdash;")
        + " |",
        f"| &nbsp;&nbsp;sluppet gjennom | {len(r.uncertain_passed)} | "
        + (", ".join(c.request.id for c in r.uncertain_passed) or "&mdash;")
        + " |",
    ]
    return "\n".join(["| | antall | |", "|---|---|---|", *rows])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Måler regelsettet mot et blindsett.")
    parser.add_argument("--set", dest="path", default=str(DEFAULT_SET))
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args(argv)

    path = Path(args.path)
    report = measure(load_cases(path), name=path.name)
    print(format_markdown(report) if args.markdown else format_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
