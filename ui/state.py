"""Tilstanden bak nettsiden. Alt ligger i minnet og nullstilles når appen starter.

Denne modulen eier ingen regler. Den kaller gateway.evaluate() og vault.append()
slik de er beskrevet i CLAUDE.md, og lager ingen egne varianter av noe som helst.
Hvis gateway eller vault bare er skjelettet, bruker vi skjelettet.
"""

from __future__ import annotations

import re
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from agents import scenarios, story, traps
from contracts import (
    ActionRequest,
    ActionType,
    Decision,
    HumanResponse,
    SandboxReport,
    TrapEvent,
    Verdict,
)
from gateway import evaluate

# Den som sitter ved skjermen i demoen. Navnet forlater aldri denne filen:
# det som logges er pseudonymet.
DEMO_EMPLOYEE_ID = "ansatt-007"

STATUS_ALLOW = "allow"
STATUS_WAITING = "waiting"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_BLOCKED = "blocked"

# Hvor mange harmløse linjer vi viser i den rolige listen.
CALM_LIMIT = 40


def _digits(text: str) -> str:
    return re.sub(r"[^0-9]", "", text)


def amount_matches(typed: str, expected: float | None) -> bool:
    """Sjekker at mennesket skrev riktig beløp.

    Vi godtar mellomrom, punktum og "kr", fordi folk skriver beløp på mange måter.
    Vi godtar ikke et annet tall. Poenget med å skrive beløpet er at man skal se det.
    """
    if expected is None:
        return False
    written = _digits(typed or "")
    if not written:
        return False
    return int(written) == int(round(expected))


def _import_after():
    """Henter vault.after.build_after_actions hvis økt C har laget den.

    Returnerer (funksjon, None) eller (None, forklaring på norsk).
    """
    try:
        from vault import after as after_module  # type: ignore[attr-defined]
    except Exception:
        return None, "kommer"
    builder = getattr(after_module, "build_after_actions", None)
    if builder is None:
        return None, "kommer"
    return builder, None


class DemoState:
    """Alt nettsiden viser. En instans per kjørende app."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.reset()

    # -- oppsett ---------------------------------------------------------

    def reset(self) -> None:
        """Tilbake til start: tom logg, tom kø, historien ikke spilt.

        Loggen kan ikke tømmes (den skal bare vokse), så i stedet begynner vi
        en ny loggfil. Den gamle blir liggende under nytt navn, og stien til
        den vises i UI, slik at ingen logg forsvinner i det skjulte.
        """
        with self._lock:
            self.vault, self.vault_error, self.log_archived = self._new_vault()
            self._requests: list[ActionRequest] = scenarios.all_scenarios()
            self._next_index = 0
            self.cards: dict[str, dict[str, Any]] = {}
            self.order: list[str] = []
            self.notices: list[dict[str, Any]] = []
            self.verify_result: dict[str, Any] | None = None
            # (doc_id, agent_id, access) for feller som allerede står i loggen.
            self._fired_traps: set[tuple[str, str, str]] = set()

            self._story = story.binance_inspired()
            self.story_index = 0
            self.story_running = False
            self.story_log: list[dict[str, Any]] = []

    @staticmethod
    def _new_vault():
        """Starter en fersk logg.

        Returnerer (vault, feilmelding, stien den gamle loggen ble flyttet til).
        Feiler det (for eksempel manglende nøkkel), sier vi fra i UI i stedet
        for å krasje.
        """
        try:
            from vault import Vault, archive_log, load_log_key

            # Sjekk nøkkelen FØR vi flytter noe. Kan vi ikke starte en logg,
            # skal den gamle filen bli liggende der den lå.
            load_log_key()
            archived = archive_log()
            return Vault(), None, str(archived) if archived else None
        except Exception as exc:  # pragma: no cover - avhenger av økt C
            return None, f"Loggen kunne ikke startes: {exc}", None

    def _pseudonym(self) -> str:
        try:
            from vault import pseudonymize

            return pseudonymize(DEMO_EMPLOYEE_ID)
        except Exception:  # pragma: no cover - avhenger av økt C
            return "emp_ukjent"

    def _append(self, kind: str, payload: dict[str, Any], ts: datetime | None = None) -> None:
        """Skriver til loggen. Finnes ikke loggen, hopper vi over og UI sier fra."""
        if self.vault is None:
            return
        self.vault.append(kind, payload, ts=ts)  # type: ignore[arg-type]

    # -- behandling av én forespørsel ------------------------------------

    def _handle(self, req: ActionRequest, source: str) -> dict[str, Any]:
        """Hele kjernflyten for én forespørsel: logg, vurder, logg, plasser."""
        self._append("request", req.model_dump(mode="json"), ts=req.ts)

        decision: Decision = evaluate(req)
        self._append("decision", decision.model_dump(mode="json"), ts=decision.ts)

        # I historien er fellene egne steg, slik at de kommer på skjermen når
        # fortellingen sier det. Da skal ikke forespørselen logge dem en gang til.
        trap = None if source == "story" else self._maybe_trap(req)

        if decision.verdict is Verdict.ALLOW:
            status = STATUS_ALLOW
        elif decision.verdict is Verdict.RED:
            status = STATUS_WAITING
        else:
            status = STATUS_BLOCKED

        card = {
            "request": req.model_dump(mode="json"),
            "decision": decision.model_dump(mode="json"),
            "status": status,
            "source": source,
            "agent_label": scenarios.agent_label(req.agent_id),
            "action_label": scenarios.action_label(req.action_type),
            "trap": trap.model_dump(mode="json") if trap else None,
            "human": None,
            "error": None,
        }
        self.cards[req.id] = card
        self.order.append(req.id)
        return card

    def _maybe_trap(self, req: ActionRequest) -> TrapEvent | None:
        """Gikk det av en felle i dokumentet forespørselen kom fra?"""
        if not req.source_doc_id:
            return None
        access = (
            traps.ACCESS_READ
            if req.action_type is ActionType.READ_DOCUMENT
            else traps.ACCESS_SEND
        )
        event = traps.trap_triggered(
            req.source_doc_id, req.agent_id, access=access, ts=req.ts
        )
        if event is None:
            return None
        self._record_trap(event, access)
        return event

    def _record_trap(self, event: TrapEvent, access: str) -> None:
        """Skriver fella til loggen. Samme dokument, agent og handling bare én gang."""
        key = (event.doc_id, event.agent_id, access)
        if key in self._fired_traps:
            return
        self._fired_traps.add(key)
        self._append("trap", event.model_dump(mode="json"), ts=event.ts)
        self.notices.append(
            {
                "kind": "trap",
                "title": "Felle gikk av",
                "detail": event.what_happened,
                "ts": event.ts.isoformat(),
            }
        )

    # -- den rolige strømmen --------------------------------------------

    def step_feed(self) -> dict[str, Any] | None:
        """Slipper neste forespørsel fra demodataene gjennom mellomstasjonen.

        Returnerer kortet, eller None når alle 40 er behandlet.
        """
        with self._lock:
            if self._next_index >= len(self._requests):
                return None
            req = self._requests[self._next_index]
            self._next_index += 1
            return self._handle(req, source="feed")

    @property
    def feed_done(self) -> bool:
        return self._next_index >= len(self._requests)

    # -- svaret fra mennesket --------------------------------------------

    def respond(
        self,
        request_id: str,
        approved: bool,
        typed_amount: str | None = None,
        seconds_to_decide: float = 0.0,
    ) -> dict[str, Any]:
        """Mennesket godkjenner eller avviser en rød forespørsel."""
        with self._lock:
            card = self.cards.get(request_id)
            if card is None:
                return {"ok": False, "error": "Finner ikke forespørselen."}
            if card["status"] != STATUS_WAITING:
                return {"ok": False, "error": "Denne er allerede besvart."}

            decision = card["decision"]
            expected = card["request"].get("amount")
            parsed: float | None = None

            if approved and decision.get("requires_typed_amount"):
                if not amount_matches(typed_amount or "", expected):
                    card["error"] = "Beløpet stemmer ikke. Skriv det nøyaktig som det står."
                    return {"ok": False, "error": card["error"]}
                parsed = float(int(_digits(typed_amount or "")))

            card["error"] = None
            human = HumanResponse(
                request_id=request_id,
                ts=datetime.now(timezone.utc),
                employee_pseudonym=self._pseudonym(),
                approved=approved,
                typed_amount=parsed,
                seconds_to_decide=max(0.0, float(seconds_to_decide)),
            )
            self._append("human", human.model_dump(mode="json"), ts=human.ts)
            card["human"] = human.model_dump(mode="json")
            card["status"] = STATUS_APPROVED if approved else STATUS_REJECTED
            return {"ok": True, "card": card}

    # -- historien --------------------------------------------------------

    def story_start(self) -> dict[str, Any]:
        """Nullstiller historien og gjør den klar til å spilles."""
        with self._lock:
            self.story_index = 0
            self.story_running = True
            self.story_log = []
            return self.story_snapshot()

    def story_step(self) -> dict[str, Any]:
        """Spiller ett steg av binance_inspired og returnerer hva som skjedde."""
        with self._lock:
            steps = self._story.steps
            if self.story_index >= len(steps):
                self.story_running = False
                return self.story_snapshot()

            step = steps[self.story_index]
            self.story_index += 1

            entry: dict[str, Any] = {
                "at_second": step.at_second,
                "kind": step.kind,
                "title": step.title,
                "detail": step.detail,
                "request_id": None,
            }

            if step.request is not None:
                card = self._handle(step.request, source="story")
                entry["request_id"] = step.request.id
                entry["verdict"] = card["decision"]["verdict"]
            if step.trap is not None:
                self._record_trap(step.trap, traps.ACCESS_READ)
            if step.sandbox is not None:
                self._log_story_sandbox(step.sandbox)

            self.story_log.append(entry)
            if self.story_index >= len(steps):
                self.story_running = False
            return self.story_snapshot()

    def _log_story_sandbox(self, report: SandboxReport) -> None:
        self._append("sandbox", report.model_dump(mode="json"), ts=report.ts)
        mal = "forsøkte å sende data ut" if report.attempted_network else "gjorde ingen forsøk"
        self.notices.append(
            {
                "kind": "sandbox",
                "title": "Sandkassen",
                "detail": (
                    f"{report.package_name} {mal}. "
                    f"Mål: {', '.join(report.destinations) or 'ingen'}. "
                    f"Resultat: {report.verdict}. {report.notes}"
                ),
                "ts": report.ts.isoformat(),
            }
        )

    def story_snapshot(self) -> dict[str, Any]:
        steps = self._story.steps
        done = self.story_index >= len(steps)
        next_at = steps[self.story_index].at_second if not done else None
        last_at = self.story_log[-1]["at_second"] if self.story_log else 0
        return {
            "story_id": self._story.story_id,
            "title": self._story.title,
            "subtitle": self._story.subtitle,
            "duration_seconds": self._story.duration_seconds,
            "total_steps": len(steps),
            "index": self.story_index,
            "running": self.story_running,
            "done": done,
            "next_at_second": next_at,
            "current_second": last_at,
            "log": list(self.story_log),
        }

    # -- loggen -----------------------------------------------------------

    def verify(self) -> dict[str, Any]:
        """Kaller vault.verify() og oversetter svaret til noe som kan vises."""
        with self._lock:
            if self.vault is None:
                result = {"ok": False, "seq": None, "lines": 0, "text": self.vault_error}
            else:
                broken = self.vault.verify()
                lines = len(self.vault.entries())
                if broken is None:
                    result = {
                        "ok": True,
                        "seq": None,
                        "lines": lines,
                        "text": f"Loggen stemmer. {lines} linjer, ingen er endret.",
                    }
                else:
                    result = {
                        "ok": False,
                        "seq": broken,
                        "lines": lines,
                        "text": f"Loggen er endret. Første ødelagte linje er seq={broken}.",
                    }
            result["checked_at"] = datetime.now(timezone.utc).isoformat()
            self.verify_result = result
            return result

    def after_actions(self) -> dict[str, Any]:
        """Etter-listen fra vault.after, eller en tom liste med teksten 'kommer'."""
        with self._lock:
            builder, missing = _import_after()
            if builder is None:
                return {"available": False, "items": [], "note": missing}
            if self.vault is None:
                return {"available": False, "items": [], "note": self.vault_error or "kommer"}
            try:
                actions = builder(self.vault.entries())
            except Exception as exc:  # pragma: no cover - avhenger av økt C
                return {"available": False, "items": [], "note": f"Etter-listen feilet: {exc}"}
            return {
                "available": True,
                "items": [a.model_dump(mode="json") for a in actions],
                "note": None,
            }

    # -- alt nettsiden trenger i ett kall ---------------------------------

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            cards = [self.cards[request_id] for request_id in self.order]
            waiting = [c for c in cards if c["status"] == STATUS_WAITING]
            blocked = [c for c in cards if c["status"] == STATUS_BLOCKED]
            calm = [c for c in cards if c["status"] == STATUS_ALLOW]
            answered = [
                c for c in cards if c["status"] in (STATUS_APPROVED, STATUS_REJECTED)
            ]
            return {
                "company": scenarios.COMPANY,
                "waiting": list(reversed(waiting)),
                "blocked": list(reversed(blocked)),
                "answered": list(reversed(answered)),
                "calm": list(reversed(calm))[:CALM_LIMIT],
                "calm_total": len(calm),
                "notices": list(reversed(self.notices))[:12],
                "feed": {
                    "done": self.feed_done,
                    "seen": self._next_index,
                    "total": len(self._requests),
                },
                "story": self.story_snapshot(),
                "log": {
                    "lines": len(self.vault.entries()) if self.vault else 0,
                    "error": self.vault_error,
                    "last_verify": self.verify_result,
                    # Hvor forrige logg ble lagt da demoen ble nullstilt. Ingenting slettes.
                    "archived": self.log_archived,
                },
            }
