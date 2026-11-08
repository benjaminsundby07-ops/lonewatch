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
from ui.amount import amount_matches, parse_amount
from ui.after_view import build_after_view
from ui.overview import build_overview

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

# -- "Prøv selv" -----------------------------------------------------------
#
# Juryen kan skrive sin egen forespørsel. Den går gjennom NØYAKTIG samme vei
# som de 40 ferdige: _handle() -> sandkasse -> gateway.evaluate() -> vault.
# Det er hele poenget: avgjørelsene er ikke skrevet på forhånd.
#
# Agenten juryens forespørsler kommer fra. Ingen regel leser agent_id.
CUSTOM_AGENT_ID = "jury"

# -- den ekte agenten (MCP) ------------------------------------------------
#
# Samme vei som "Prøv selv", bare med en annen avsender. Kortene merkes med
# source="agent" slik at man i dashbordet ser forskjell på et manusstyrt
# demokort og et kall fra en agent som faktisk kjører. Se docs/EKTE_AGENT.md.
AGENT_SOURCE = "agent"

# agent_id settes HER, ikke av den som kaller. En agent skal ikke kunne
# utgi seg for å være en annen. Ingen regel leser agent_id, men loggen gjør.
AGENT_AGENT_ID = "claude_code"

# Vises i kortet. Ligger her og ikke i agents/scenarios.py, fordi den ekte
# agenten ikke er en av demoens oppdiktede agenter.
AGENT_LABEL = "Ekte agent (Claude Code)"

# Lengdegrenser. Alt brukeren skriver vises i UI, og selv om alt escapes der,
# skal ingen kunne sende inn en roman eller fylle loggen.
MAX_SUMMARY_CHARS = 200
MAX_RECIPIENT_CHARS = 120
MAX_PACKAGE_CHARS = 64

# Kan handlingen angres? Utledet fra HANDLINGEN, ikke fra det brukeren påstår.
# Samme grunn som for recipient_known: om noe kan angres er en egenskap ved
# handlingen, ikke noe den som ber om den skal få bestemme. Verdiene følger
# demodataene i agents/scenarios.py.
REVERSIBLE_BY_ACTION: dict[ActionType, bool] = {
    ActionType.TRANSFER_MONEY: False,
    ActionType.SHARE_DATA: False,
    ActionType.INSTALL_PACKAGE: False,
    ActionType.SEND_EMAIL: False,  # en sendt e-post kan ikke kalles tilbake
    ActionType.READ_DOCUMENT: True,
    ActionType.UPDATE_CALENDAR: True,
}

# Handlinger der et pakkenavn betyr noe.
PACKAGE_ACTIONS = frozenset({ActionType.INSTALL_PACKAGE})

# Handlinger der et beløp betyr noe.
AMOUNT_ACTIONS = frozenset({ActionType.TRANSFER_MONEY})


def _normalize_recipient(value: str) -> str:
    """Gjør mottakere sammenlignbare: små bokstaver, uten ekstra luft.

    "NO12 3456 7890 123", "no12 3456 7890 123" og "NO12 34567890123" skal
    treffe den samme kjente kontoen.
    """
    return re.sub(r"\s+", "", (value or "").strip().lower())


def known_recipient(value: str) -> bool:
    """Står mottakeren på demoens liste over kjente mottakere?

    Listen hentes fra agents/scenarios.py. Den som skriver en forespørsel i
    "Prøv selv" kan ikke påstå at en konto er kjent - det regnes ut her.
    """
    target = _normalize_recipient(value)
    if not target:
        return False
    return target in {_normalize_recipient(r) for r in scenarios.known_recipients()}


# Beløpsregelen ligger i ui/amount.py, sammen med tvillingen sin i
# ui/static/amount.js. Den er IKKE skrevet her, nettopp fordi nettleseren og
# tjeneren maa tolke et skrevet beloep helt likt. Se F1 i docs/REDTEAM.md.


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


class LonewatchAlreadyRunning(RuntimeError):
    """En annen Lonewatch holder allerede loggen."""


def _kort_hash(verdi: Any) -> str | None:
    """Tolv tegn av hashen, slik `verify()` alt gjør med hale-ankeret.

    Hele hashen er 64 tegn og sprenger kolonnen uten å gi leseren noe mer:
    den som skal regne på kjeden leser loggfilen, ikke en tabell på skjermen.
    Tolv tegn er nok til å kjenne igjen en linje, og det er samme lengde som
    topphashen over tabellen - to tall som ser like ut, skal være like lange.
    """
    if not isinstance(verdi, str):
        return None
    return verdi[:12]


class DemoState:
    """Alt nettsiden viser. En instans per kjørende app.

    Å lage en DemoState tar enerett til loggfilen og slipper den først når
    `close()` kalles. Starter du app nr. 2 mot samme logg, feiler den her i
    stedet for å røre en logg som er i bruk. Se F4 i docs/REDTEAM.md.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._log_lock = self._acquire_log_lock()
        # Ved oppstart arkiverer vi IKKE. Å importere ui.app skal ikke endre
        # noe på disken; det var nettopp det som gjorde F4 mulig. Loggen byttes
        # bare ut når noen trykker Nullstill.
        self._start(archive=False)

    # -- oppsett ---------------------------------------------------------

    @staticmethod
    def _acquire_log_lock():
        """Enerett til loggen. Kastes videre som en feil appen kan forklare."""
        try:
            from vault import LogLocked, acquire_log_lock
        except Exception:  # pragma: no cover - avhenger av økt C
            return None
        try:
            return acquire_log_lock()
        except LogLocked as exc:
            raise LonewatchAlreadyRunning(str(exc)) from exc

    def close(self) -> None:
        """Slipper loggen, slik at neste Lonewatch kan starte."""
        with self._lock:
            if self._log_lock is not None:
                self._log_lock.release()
                self._log_lock = None

    def reset(self) -> None:
        """Tilbake til start: tom logg, tom kø, historien ikke spilt.

        Loggen kan ikke tømmes (den skal bare vokse), så i stedet begynner vi
        en ny loggfil. Den gamle blir liggende under nytt navn, og stien til
        den vises i UI, slik at ingen logg forsvinner i det skjulte.

        Dette er en bevisst handling fra brukeren, og det eneste stedet loggen
        blir byttet ut.
        """
        self._start(archive=True)

    def _start(self, archive: bool) -> None:
        with self._lock:
            self.vault, self.vault_error, self.log_archived = self._new_vault(archive)
            self._requests: list[ActionRequest] = scenarios.all_scenarios()
            self._next_index = 0
            self.cards: dict[str, dict[str, Any]] = {}
            self.order: list[str] = []
            self.notices: list[dict[str, Any]] = []
            self.verify_result: dict[str, Any] | None = None
            # (doc_id, agent_id, access) for feller som allerede står i loggen.
            self._fired_traps: set[tuple[str, str, str]] = set()
            # Forespørsler noen har SKREVET, i stedet for å komme fra
            # demodataene: "Prøv selv" og den ekte agenten. Nummerert for seg
            # per kilde, slik at IDene aldri kolliderer.
            self._written_counts: dict[str, int] = {}
            # Forespørslene gateway har sett, i rekkefølge. Brukes bare til å
            # summere overføringer til samme mottaker innenfor tidsvinduet.
            # Den ligger i MINNET og forsvinner ved omstart og Nullstill - se
            # gateway/LIMITS.md.
            self._history: list[ActionRequest] = []
            # Før-listen: tillegg sandkassen har kjørt, og tillegg den ikke har.
            self._scanned: dict[str, dict[str, Any]] = {}
            self._untested: dict[str, dict[str, Any]] = {}
            self.sandbox_error: str | None = None

            self._story = story.binance_inspired()
            self.story_index = 0
            self.story_running = False
            self.story_log: list[dict[str, Any]] = []

    @staticmethod
    def _new_vault(archive: bool):
        """Åpner loggen, og bytter den ut først hvis `archive` er satt.

        Returnerer (vault, feilmelding, stien den gamle loggen ble flyttet til).
        Feiler det (for eksempel manglende nøkkel), sier vi fra i UI i stedet
        for å krasje.
        """
        try:
            from vault import Vault, archive_log, load_log_key, redact_enabled

            # Sjekk nøkkelen FØR vi flytter noe. Kan vi ikke starte en logg,
            # skal den gamle filen bli liggende der den lå.
            load_log_key()
            archived = archive_log() if archive else None
            # Demoen minimerer det den logger. Se vault/LIMITS.md punkt 7 for
            # hva det betyr - og hva det IKKE betyr.
            return Vault(redact=redact_enabled()), None, str(archived) if archived else None
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
        """Hele kjernflyten for én forespørsel: logg, prøv, vurder, logg, plasser.

        "Før"-steget ligger her: skal et tillegg installeres, kjører vi det i
        sandkassen FØR mellomstasjonen bestemmer seg, og rapporten går med inn i
        evaluate(). Rekkefølgen i loggen blir derfor request -> sandbox ->
        decision, som er den rekkefølgen tingene faktisk skjedde i.
        """
        self._append("request", req.model_dump(mode="json"), ts=req.ts)

        report = self._scan(req)
        decision: Decision = evaluate(req, sandbox_report=report, history=self._history)
        self._append("decision", decision.model_dump(mode="json"), ts=decision.ts)
        # Først NÅ legges den i historikken: en forespørsel skal ikke summere
        # seg selv to ganger.
        self._history.append(req)

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
            "sandbox": report.model_dump(mode="json") if report else None,
            "human": None,
            "error": None,
        }
        self.cards[req.id] = card
        self.order.append(req.id)
        return card

    def _scan(self, req: ActionRequest) -> SandboxReport | None:
        """Kjører tillegget i sandkassen hvis vi har det, og logger rapporten.

        Vi kjører ALDRI noe ut fra et navn vi får i en forespørsel. sandbox.scan
        slår navnet opp blant filene i sandbox/packages/, og et navn som ikke
        ligger der gir UnknownPackage uten at det startes en prosess. Da er
        svaret "ikke testet", og new_package-regelen staar alene.
        """
        if req.action_type is not ActionType.INSTALL_PACKAGE:
            return None
        name = (req.package_name or "").strip()
        if not name:
            return None
        try:
            from sandbox import UnknownPackage, scan_cached
        except Exception as exc:  # pragma: no cover - avhenger av økt D
            self.sandbox_error = f"Sandkassen kunne ikke startes: {exc}"
            return None

        try:
            report = scan_cached(name)
        except UnknownPackage:
            # Helt normalt: de fleste tillegg i verden ligger ikke hos oss.
            self._note_untested(name)
            return None
        except Exception as exc:  # pragma: no cover - uventet feil i boksen
            self.sandbox_error = f"Sandkassen feilet for {name}: {exc}"
            return None

        self._record_sandbox(report)
        return report

    def _record_sandbox(self, report: SandboxReport) -> None:
        """Logger rapporten én gang per tillegg og legger den i Før-listen."""
        name = report.package_name
        if name in self._scanned:
            return
        self._scanned[name] = report.model_dump(mode="json")
        self._append("sandbox", report.model_dump(mode="json"), ts=report.ts)
        self.notices.append(
            {
                "kind": "sandbox",
                "title": f"Sandkassen: {name}",
                "detail": report.notes,
                "ts": report.ts.isoformat(),
            }
        )

    def _note_untested(self, package_name: str) -> None:
        """Tillegg sandkassen ikke har en fil for. Ingen scan, ingen kjøring."""
        if package_name in self._untested:
            return
        self._untested[package_name] = {
            "package_name": package_name,
            "tested": False,
            "note": (
                "Sandkassen har ikke dette tillegget, så det ble ikke kjørt. "
                "Ingenting ble installert eller startet."
            ),
        }

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

    # -- "Prøv selv": juryen skriver sin egen forespørsel -----------------

    def submit_custom(
        self,
        action_type: str,
        summary: str = "",
        amount: str = "",
        recipient: str = "",
        package_name: str = "",
        contains_personal_data: bool = False,
        *,
        source: str = "custom",
        agent_id: str = CUSTOM_AGENT_ID,
        id_prefix: str = "custom",
    ) -> dict[str, Any]:
        """Bygger en ActionRequest fra skjemaet og sender den samme vei som de 40.

        Den går gjennom `_handle()`, altså sandkassen, `gateway.evaluate()` og
        loggen - ikke en egen, snillere vei. Det er hele poenget med panelet:
        avgjørelsen er ikke skrevet på forhånd.

        To felt settes av oss, ikke av den som skriver:

        - `recipient_known` regnes ut mot demoens liste over kjente mottakere.
          Ellers kunne man krysset av for at en ukjent konto er kjent, og
          snakket seg forbi `unknown_recipient`.
        - `reversible` kommer fra handlingstypen. Om noe kan angres er en
          egenskap ved handlingen, ikke en påstand fra den som ber om den.

        `summary` er fritt, vises i kortet, og brukes ALDRI i vurderingen.

        `source`, `agent_id` og `id_prefix` er nøkkelordargumenter med
        standardverdier, slik at "Prøv selv" ser helt uendret ut. Den ekte
        agenten (`submit_agent`) bruker den samme veien med en annen avsender,
        nettopp for at det ikke skal finnes to validerings-steder som kan komme
        ut av takt.
        """
        with self._lock:
            try:
                kind = ActionType(action_type)
            except ValueError:
                return {"ok": False, "error": "Ukjent handlingstype."}

            summary = (summary or "").strip()[:MAX_SUMMARY_CHARS]
            recipient_text = (recipient or "").strip()[:MAX_RECIPIENT_CHARS]
            package_text = (package_name or "").strip()[:MAX_PACKAGE_CHARS]

            # Beløp: samme regel som beløpsporten. Ugyldig input gir en pen
            # feilmelding, aldri en krasj.
            amount_value: float | None = None
            raw_amount = (amount or "").strip()
            if kind in AMOUNT_ACTIONS:
                if not raw_amount:
                    # Gateway setter requires_typed_amount ogsaa naar amount
                    # mangler (kjent hull i gateway/LIMITS.md). Da kunne et
                    # roedt kort aldri godkjennes. Vi stopper det her, i
                    # skjemaet - ikke i regelen.
                    return {"ok": False, "error": "En overføring må ha et beløp."}
                ore = parse_amount(raw_amount)
                if ore is None:
                    return {
                        "ok": False,
                        "error": (
                            "Beløpet kunne ikke leses. Skriv for eksempel "
                            "10 000 000 eller 1 234,56."
                        ),
                    }
                amount_value = ore / 100
            elif raw_amount:
                return {"ok": False, "error": "Bare en overføring kan ha et beløp."}

            if kind in PACKAGE_ACTIONS and not package_text:
                return {"ok": False, "error": "Et tillegg må ha et navn."}

            teller = self._written_counts.get(id_prefix, 0) + 1
            self._written_counts[id_prefix] = teller
            req = ActionRequest(
                id=f"{id_prefix}_{teller:04d}",
                ts=datetime.now(timezone.utc),
                agent_id=agent_id,
                action_type=kind,
                summary=summary or "(ingen forklaring)",
                amount=amount_value,
                recipient=recipient_text or None,
                # Regnes ut, ikke oppgis.
                recipient_known=known_recipient(recipient_text),
                reversible=REVERSIBLE_BY_ACTION.get(kind, True),
                contains_personal_data=bool(contains_personal_data),
                package_name=package_text or None,
            )

            try:
                card = self._handle(req, source=source)
            except Exception as exc:  # pragma: no cover - siste skanse
                self._written_counts[id_prefix] = teller - 1
                return {"ok": False, "error": f"Forespørselen kunne ikke behandles: {exc}"}

            return {"ok": True, "card": card}

    def custom_help(self) -> dict[str, Any]:
        """Det skjemaet trenger å vite: handlingstyper og noen kjente mottakere."""
        return {
            "actions": [
                {"value": a.value, "label": scenarios.action_label(a)} for a in ActionType
            ],
            "amount_actions": [a.value for a in AMOUNT_ACTIONS],
            "package_actions": [a.value for a in PACKAGE_ACTIONS],
            # Eksempler, ikke hele listen. Vi skjuler den ikke - poenget er at
            # den er en oppdiktet demoliste, og det staar i UI.
            "known_examples": sorted(scenarios.known_recipients())[:4],
            "known_total": len(scenarios.known_recipients()),
            "limits": {
                "summary": MAX_SUMMARY_CHARS,
                "recipient": MAX_RECIPIENT_CHARS,
                "package_name": MAX_PACKAGE_CHARS,
            },
        }

    # -- den ekte agenten (MCP) ------------------------------------------
    #
    # Tre metoder, og ingen av dem har en egen vurdering, en egen logg eller en
    # egen snillere vei. `submit_agent` er `submit_custom` med en annen
    # avsender; `agent_status` leser bare kortet; `agent_gave_up` skriver en
    # notis i UI og rører ikke loggen.

    def submit_agent(
        self,
        action_type: str,
        summary: str = "",
        amount: str = "",
        recipient: str = "",
        package_name: str = "",
        contains_personal_data: bool = False,
    ) -> dict[str, Any]:
        """Et verktøykall fra en agent som faktisk kjører, inn samme vei som alt annet.

        Nøyaktig samme felt som "Prøv selv", og nøyaktig samme to felt settes av
        oss: `recipient_known` regnes ut mot demoens liste, og `reversible`
        kommer fra handlingstypen. En agent kan ikke oppgi noen av dem, og kan
        heller ikke velge sin egen `agent_id` eller `id`.
        """
        result = self.submit_custom(
            action_type=action_type,
            summary=summary,
            amount=amount,
            recipient=recipient,
            package_name=package_name,
            contains_personal_data=contains_personal_data,
            source=AGENT_SOURCE,
            agent_id=AGENT_AGENT_ID,
            id_prefix="agent",
        )
        if result.get("ok"):
            # Kortet ligger i self.cards, så dette endrer det som vises.
            result["card"]["agent_label"] = AGENT_LABEL
        return result

    def agent_status(self, request_id: str) -> dict[str, Any] | None:
        """Hvor står forespørselen nå? None hvis vi ikke har den.

        Dette er det agenten får lov å spørre om mens den venter. Den får ikke
        regelnavnene: de ville vært en oppskrift på hva som må endres for å
        slippe gjennom neste gang.
        """
        with self._lock:
            card = self.cards.get(request_id)
            if card is None:
                return None
            human = card.get("human") or {}
            return {
                "request_id": request_id,
                "status": card["status"],
                "verdict": card["decision"].get("verdict"),
                "risk": card["decision"].get("risk"),
                "requires_typed_amount": card["decision"].get("requires_typed_amount", False),
                "consequence_text": card["decision"].get("consequence_text"),
                "approved": human.get("approved"),
                "typed_amount": human.get("typed_amount"),
                "seconds_to_decide": human.get("seconds_to_decide"),
                "source": card.get("source"),
            }

    def agent_gave_up(self, request_id: str, waited_seconds: float) -> bool:
        """Agenten sluttet å vente på svar. Returnerer True hvis kortet fortsatt venter.

        Dette skrives IKKE i loggen. Ingen `HumanResponse` har skjedd, og en
        linje som sa "avvist" ville vært en påstand om at et menneske svarte.
        Kortet blir liggende i køen. Notisen er til den som sitter i
        dashbordet: agenten har gitt opp, men saken venter fortsatt på deg.
        """
        with self._lock:
            card = self.cards.get(request_id)
            if card is None or card["status"] != STATUS_WAITING:
                return False
            ventet = max(0, int(waited_seconds))
            self.notices.append(
                {
                    "kind": "agent",
                    "title": "Agenten sluttet å vente",
                    "detail": (
                        f"Den ekte agenten ventet {ventet} s på svar på {request_id} "
                        "og ga opp. Den utførte ingenting. Saken venter fortsatt "
                        "på deg - ingenting er avgjort."
                    ),
                    "ts": datetime.now(timezone.utc).isoformat(),
                }
            )
            return True

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
                if not amount_matches(typed_amount, expected):
                    card["error"] = "Beløpet stemmer ikke. Skriv det nøyaktig som det står."
                    return {"ok": False, "error": card["error"]}
                # Beloepet er allerede bekreftet likt forventet. Vi logger det
                # vi selv tolket, ikke raateksten, saa loggen aldri kan vise et
                # annet tall enn det som ble vurdert.
                ore = parse_amount(typed_amount)
                parsed = ore / 100 if ore is not None else None

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
                "sandbox": None,
            }

            if step.request is not None:
                card = self._handle(step.request, source="story")
                entry["request_id"] = step.request.id
                entry["verdict"] = card["decision"]["verdict"]
            if step.trap is not None:
                self._record_trap(step.trap, traps.ACCESS_READ)
            if step.sandbox_package is not None:
                # Rapporten ble skrevet til loggen da tillegget ble forsøkt
                # installert (steget foer). Her viser vi den bare fram.
                entry["sandbox"] = self._scanned.get(step.sandbox_package)

            self.story_log.append(entry)
            if self.story_index >= len(steps):
                self.story_running = False
            return self.story_snapshot()

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
        """Kaller vault.verify_detail() og oversetter svaret til noe som kan vises.

        `head` er de første tolv tegnene av siste hash. Skriver du den ned et
        sted utenfor maskinen, kan du siden se om loggen er den samme - det er
        det eneste som faktisk fanger en som har både loggen, hale-ankeret og
        nøkkelen. Se vault/LIMITS.md.
        """
        with self._lock:
            if self.vault is None:
                result = {
                    "ok": False,
                    "seq": None,
                    "lines": 0,
                    "text": self.vault_error,
                    "head": None,
                    "reason": "no_vault",
                }
            else:
                detail = self.vault.verify_detail()
                head = detail.head_hash[:12] if detail.head_hash else None
                text = detail.text
                if head:
                    text = f"{text} Siste hash: {head}."
                result = {
                    "ok": detail.ok,
                    "seq": detail.broken_seq,
                    "lines": detail.lines,
                    "text": text,
                    "head": head,
                    "reason": detail.reason,
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
                # Grupperte og prioriterte oppfoelginger, bygget i ui/ fra de
                # samme logglinjene. `items` over er uendret for den som
                # kaller API-et utenom UI.
                "view": build_after_view(self.vault.entries()),
                "note": None,
            }

    def before_list(self) -> dict[str, Any]:
        """"Før"-listen: hva sandkassen prøvde, og hva den ikke kunne prøve.

        Rekkefølgen er den tilleggene dukket opp i, slik at demoen kan peke paa
        et rent og et blokkert tillegg i tur og orden.
        """
        with self._lock:
            scanned = list(self._scanned.values())
            # `not_tested` telles for seg. Det er IKKE clean: sandkassen kjørte
            # tillegget, men det kom aldri i gang, så vi fikk ikke sett etter.
            return {
                "scanned": scanned,
                "untested": list(self._untested.values()),
                "blocked": len([r for r in scanned if r["verdict"] == "blocked"]),
                "clean": len([r for r in scanned if r["verdict"] == "clean"]),
                "not_tested": len([r for r in scanned if r["verdict"] == "not_tested"]),
                "error": self.sandbox_error,
            }

    # -- det skissene trenger, alt fra ekte tilstand -----------------------

    def log_rows(self, limit: int = 200) -> dict[str, Any]:
        """Logglinjene som en tabell: Tid, #, Agent, Kall, Mål, Utfall, Regel, Hash.

        Rett fra `vault.entries()`. Merk at loggen er MINIMERT (se
        vault/LIMITS.md punkt 7), så mottakeren står maskert og agentens egen
        tekst er kastet. Det er loggen slik den faktisk er - ikke en pyntet
        kopi av tilstanden i minnet.
        """
        with self._lock:
            if self.vault is None:
                return {"rows": [], "counts": {"alle": 0, "stoppet": 0, "menneske": 0}}

            entries = self.vault.entries()
            # Forespørslene, slik at en avgjørelse kan vise hvem og hva.
            requests: dict[str, dict[str, Any]] = {}
            for e in entries:
                if e.kind == "request":
                    rid = e.payload.get("id")
                    if isinstance(rid, str):
                        requests[rid] = e.payload

            rows: list[dict[str, Any]] = []
            for e in entries:
                p = e.payload
                if e.kind == "decision":
                    req = requests.get(str(p.get("request_id")), {})
                    rows.append({
                        "seq": e.seq,
                        "ts": e.ts.isoformat(),
                        "agent": scenarios.agent_label(str(req.get("agent_id") or "")),
                        "kall": str(req.get("action_type") or ""),
                        "maal": req.get("recipient") or req.get("package_name")
                                or req.get("source_doc_id") or "",
                        "utfall": p.get("verdict"),
                        "regler": p.get("reasons") or [],
                        "hash": _kort_hash(e.hash),
                        "request_id": p.get("request_id"),
                    })
                elif e.kind == "trap":
                    rows.append({
                        "seq": e.seq,
                        "ts": e.ts.isoformat(),
                        "agent": scenarios.agent_label(str(p.get("agent_id") or "")),
                        "kall": "felle",
                        "maal": p.get("doc_id") or "",
                        "utfall": "trap",
                        "regler": [p.get("trap_id")] if p.get("trap_id") else [],
                        "hash": _kort_hash(e.hash),
                        "request_id": None,
                    })
                elif e.kind == "sandbox":
                    rows.append({
                        "seq": e.seq,
                        "ts": e.ts.isoformat(),
                        "agent": "Sandkassen",
                        "kall": "sandkasse",
                        "maal": p.get("package_name") or "",
                        "utfall": p.get("verdict"),
                        "regler": [],
                        "hash": _kort_hash(e.hash),
                        "request_id": None,
                    })

            rows.reverse()  # nyeste først, som i skissen
            stoppet = len([r for r in rows if r["utfall"] in ("block", "blocked", "trap")])
            menneske = len([r for r in rows if r["utfall"] == "red"])
            return {
                "rows": rows[:limit],
                "counts": {"alle": len(rows), "stoppet": stoppet, "menneske": menneske},
                "truncated": len(rows) > limit,
            }

    def traps_overview(self) -> list[dict[str, Any]]:
        """«Feller i dokumenter»: de oppdiktede dokumentene, og om de har gått av.

        Dokumentene kommer fra agents/traps.py. «Sist rørt» kommer fra det som
        faktisk har skjedd i denne kjøringen, ikke fra en liste.
        """
        with self._lock:
            sist: dict[str, dict[str, Any]] = {}
            for notis in self.notices:
                if notis.get("kind") != "trap":
                    continue
            for request_id in self.order:
                card = self.cards[request_id]
                t = card.get("trap")
                if t:
                    sist[t["doc_id"]] = {"ts": t["ts"], "agent": card["agent_label"]}

            ut = []
            for doc in traps.trapped_docs():
                markers = traps.found_markers(doc)
                ut.append({
                    "doc_id": doc.doc_id,
                    "trap_id": doc.trap_id,
                    "tittel": doc.title,
                    "eier": doc.owner_role,
                    "type": "Skjult instruks" if traps.MARKER_METADATA_KEY in markers
                            else "Usynlig tekst",
                    "intent": doc.intent,
                    "sist": sist.get(doc.doc_id),
                })
            return ut

    def agent_trail(self, request_id: str, limit: int = 6) -> list[dict[str, Any]]:
        """«Dette ledet hit»: hva den samme agenten gjorde rett før.

        Ekte historikk fra kortene, i rekkefølge. Ingen fortelling lagt på.
        """
        with self._lock:
            card = self.cards.get(request_id)
            if card is None:
                return []
            agent_id = card["request"].get("agent_id")
            trail = []
            for rid in self.order:
                c = self.cards[rid]
                if c["request"].get("agent_id") != agent_id:
                    continue
                trail.append({
                    "request_id": rid,
                    "ts": c["request"].get("ts"),
                    "kall": c["request"].get("action_type"),
                    "maal": c["request"].get("recipient") or c["request"].get("package_name")
                            or c["request"].get("source_doc_id") or "",
                    "utfall": c["decision"].get("verdict"),
                    # Hvilken felle, ikke bare at det var en. «felle: true» sier
                    # ingenting den som skal slå opp i loggen kan bruke.
                    "felle": (c.get("trap") or {}).get("trap_id"),
                    "er_denne": rid == request_id,
                })
                if rid == request_id:
                    break
            return trail[-limit:]

    def waiting_for_you(self) -> dict[str, Any] | None:
        """Det mest presserende roede varselet akkurat naa, eller None.

        Rekkefoelgen er fast, saa to like kjoeringer gir samme kort:
          1. hoeyest risiko foerst (high foer medium)
          2. saa stoerste beloep
          3. saa eldste forespoersel

        Alt kommer fra kortene. Ingenting er regnet ut for aa se pent ut.
        """
        with self._lock:
            venter = [
                self.cards[request_id]
                for request_id in self.order
                if self.cards[request_id]["status"] == STATUS_WAITING
            ]
            if not venter:
                return None

            rang = {"high": 0, "medium": 1, "low": 2}

            def noekkel(card: dict[str, Any]) -> tuple[int, float, str]:
                return (
                    rang.get(card["decision"].get("risk"), 9),
                    -float(card["request"].get("amount") or 0),
                    str(card["request"].get("ts") or ""),
                )

            card = sorted(venter, key=noekkel)[0]
            req, dec = card["request"], card["decision"]
            return {
                "request_id": req["id"],
                "agent": card["agent_label"],
                "action": card["action_label"],
                "amount": req.get("amount"),
                "recipient": req.get("recipient"),
                "recipient_known": req.get("recipient_known"),
                "risk": dec.get("risk"),
                "consequence_text": dec.get("consequence_text"),
                "requires_typed_amount": dec.get("requires_typed_amount", False),
                "waiting_total": len(venter),
            }

    def overview(self) -> dict[str, Any]:
        """Tallene til dashbordet, i formen design-handoff/DATASHAPE.md beskriver.

        Alt regnes ut herfra: ingen tall er skrevet inn, og ingenting er hentet
        fra eksempeldataene i bundle.js.
        """
        with self._lock:
            cards = [self.cards[request_id] for request_id in self.order]
            data = build_overview(
                cards=cards,
                before=self.before_list(),
                verify=self.verify_result,
                log_error=self.vault_error,
            )
            # Kortet "Venter paa deg" paa Oversikt. Ekte tilstand, ikke et tall.
            data["waiting"] = self.waiting_for_you()
            return data

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
            # Juryens egne forespørsler, nyeste først. De ligger OGSÅ i listene
            # over: en egen forespørsel som blir rød, står i køen som alle andre.
            custom = [c for c in cards if c["source"] == "custom"]
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
                "custom": list(reversed(custom)),
                "before": self.before_list(),
                "story": self.story_snapshot(),
                "log": {
                    "lines": len(self.vault.entries()) if self.vault else 0,
                    "error": self.vault_error,
                    "last_verify": self.verify_result,
                    # Hvor forrige logg ble lagt da demoen ble nullstilt. Ingenting slettes.
                    "archived": self.log_archived,
                    # Minimeres det vi logger? Vises i "Sjekk loggen", slik at
                    # ingen tror loggen inneholder mer enn den gjør.
                    "redacted": bool(getattr(self.vault, "_redact", False)),
                },
            }
