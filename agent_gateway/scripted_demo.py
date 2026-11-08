"""Reserven: samme flyt som den ekte agenten, men manusstyrt og uten agent.

Bruk:
    python -m agent_gateway.scripted_demo

Hvorfor denne finnes: en ekte Claude Code-agent velger selv om og når den
kaller et verktøy. Den kan la være, den kan velge Bash i stedet, og den kan
oppføre seg ulikt to ganger på rad. På en scene er det en risiko. Denne filen
kjører NØYAKTIG samme kode som den ekte agenten går gjennom - bare med manus i
stedet for en modell:

    manus -> agent_gateway.tools.run_action()   <- samme funksjon som MCP-verktøyene
          -> ui/app.py sine agent-endepunkter   <- samme validering og samme svar
          -> DemoState.submit_agent()           <- samme kø og samme kort
          -> gateway.evaluate()                 <- de ekte reglene
          -> vault.append()                     <- den ekte låste loggen

Det eneste som er byttet ut:
  * modellen      -> en liste med seks handlinger, i samme rekkefølge hver gang
  * mennesket     -> et manus som svarer i dashbordet (og først med feil beløp)
  * klokken       -> en teller, slik at to minutters venting tar et øyeblikk
  * MCP og HTTP   -> direkte funksjonskall. Protokollen er ikke det vi viser her.

Den trenger ingenting satt opp: den lager sine egne nøkler i minnet og skriver
loggen i en midlertidig mappe, så den kan kjøre samtidig som appen og kan ikke
ødelegge en logg du alt har. Ingen nettverkskall, ingen API-nøkkel, ingen
modell. Ingen penger flyttes, ingen e-post sendes, ingenting installeres.

Hva den IKKE viser: at MCP-protokollen virker (det er
`tests/test_agent_mcp_live.py`), og at en ekte agent velger å bruke verktøyene
(det kan ingen love - se `agent_gateway/LIMITS.md` punkt 1).
"""

from __future__ import annotations

import os
import secrets
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from agent_gateway import tools

LINE = "-" * 72
UKJENT_KONTO = "NO93 8601 1117 947"


# ---------------------------------------------------------------------------
# Et miljø som alltid virker: egne nøkler, egen midlertidig logg.
# ---------------------------------------------------------------------------


def prepare_env(tmpdir: str) -> None:
    """Setter nøkler og stier FØR ui/ importeres.

    Loggen legges i en midlertidig mappe. Da tar vi ikke låsen fra en app som
    kjører, og vi rører ikke loggen noen alt har skrevet.
    """
    from vault.crypto import new_log_key, new_pseudonym_key

    os.environ["LONEWATCH_LOG_PATH"] = str(Path(tmpdir) / "lonewatch_log.jsonl")
    os.environ["LONEWATCH_PSEUDONYM_TABLE"] = str(Path(tmpdir) / "pseudonyms.enc")
    os.environ["LONEWATCH_LOG_KEY"] = new_log_key()
    os.environ["LONEWATCH_PSEUDONYM_KEY"] = new_pseudonym_key()
    # Broen i ui/app.py er av uten denne. Nøkkelen lever bare i denne prosessen.
    os.environ["LONEWATCH_AGENT_KEY"] = secrets.token_urlsafe(32)


# ---------------------------------------------------------------------------
# Klienten: de tre kallene, rett inn i appens egne endepunkter.
# ---------------------------------------------------------------------------


class InProcessClient:
    """Samme tre kall som `LonewatchClient`, uten HTTP.

    Vi kaller endepunktfunksjonene i `ui/app.py` direkte, og får dermed den
    samme valideringen (`AgentSubmitIn` med `extra="forbid"`) og det samme
    svaret agenten ville fått over nettet - inkludert at et blokkert kall ikke
    får regelnavnene med tilbake.
    """

    def __init__(self, state: Any | None = None) -> None:
        from ui import app as uiapp

        self._app = uiapp
        # Endepunktene leser modulvariabelen `state` i ui/app.py. Vi bytter den
        # bare ut mens vårt eget kall står på, og setter den tilbake etterpå,
        # slik at en test kan kjøre demoen med sin egen kø uten å flytte appens.
        self.state = state if state is not None else uiapp.state

    def _kall(self, fn: Callable[[], Any]) -> Any:
        gammel = self._app.state
        self._app.state = self.state
        try:
            return fn()
        finally:
            self._app.state = gammel

    def submit(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._kall(lambda: self._app.api_agent_submit(self._app.AgentSubmitIn(**payload)))

    def status(self, request_id: str) -> dict[str, Any]:
        return self._kall(lambda: self._app.api_agent_status(request_id))

    def abandon(self, request_id: str, waited_seconds: float) -> dict[str, Any]:
        return self._kall(
            lambda: self._app.api_agent_abandon(
                request_id, self._app.AgentAbandonIn(waited_seconds=waited_seconds)
            )
        )


# ---------------------------------------------------------------------------
# Mennesket og klokken: manus, ikke tilfeldigheter.
# ---------------------------------------------------------------------------


@dataclass
class ScriptedHuman:
    """Mennesket i dashbordet, med manus.

    `after_polls` er hvor mange ganger agenten skal ha spurt før mennesket
    svarer. `wrong_amount_first` lar oss vise det som er hele poenget med det
    røde kortet: feil beløp godkjenner ingenting.
    """

    client: InProcessClient
    log: Callable[[str], None]
    approve: bool | None = None
    typed_amount: str | None = None
    wrong_amount_first: str | None = None
    after_polls: int = 1
    polls: int = 0
    done: bool = False
    # Hvert svar mennesket ga, slik at testene kan se hva som faktisk skjedde.
    answers: list[dict[str, Any]] = field(default_factory=list)

    request_id: str = ""

    def sleep(self, _seconds: float) -> None:
        """Kalles av `run_action` mellom hvert statusspørsmål. Her skjer manuset."""
        self.polls += 1
        if self.done or self.approve is None or self.polls < self.after_polls:
            return

        if self.wrong_amount_first is not None:
            svar = self.client.state.respond(
                self.request_id, True, self.wrong_amount_first, 9.0
            )
            self.answers.append({"typed": self.wrong_amount_first, "ok": bool(svar.get("ok"))})
            self.log(
                f"    mennesket skriver {self.wrong_amount_first!r} -> "
                f"{svar.get('error') or 'godkjent'}"
            )
            self.wrong_amount_first = None
            return

        svar = self.client.state.respond(
            self.request_id, self.approve, self.typed_amount, 12.0
        )
        self.answers.append({"typed": self.typed_amount, "ok": bool(svar.get("ok"))})
        if svar.get("ok"):
            handling = "godkjenner" if self.approve else "avviser"
            skrevet = f" (skrev {self.typed_amount!r})" if self.typed_amount else ""
            self.log(f"    mennesket {handling} kortet{skrevet}")
            self.done = True
        else:  # pragma: no cover - manuset er riktig
            self.log(f"    mennesket fikk nei: {svar.get('error')}")


@dataclass
class FakeClock:
    """Teller sekunder i stedet for å vente på dem."""

    now: float = 0.0
    step: float = 2.0

    def __call__(self) -> float:
        verdi = self.now
        self.now += self.step
        return verdi


# ---------------------------------------------------------------------------
# Manuset: seks handlinger som viser allow, rødt godkjent, rødt avvist, block,
# sandkassen og at agenten gir opp.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Beat:
    overskrift: str
    poeng: str
    tool_name: str
    felt: dict[str, Any]
    # Hva mennesket gjør: None = ingen er der.
    approve: bool | None = None
    typed_amount: str | None = None
    wrong_amount_first: str | None = None
    forventet: str = ""


SCRIPT: tuple[Beat, ...] = (
    Beat(
        overskrift="1. Vanlig arbeid",
        poeng="Det som er ufarlig skal ikke stoppes. Ellers slutter folk å bruke det.",
        tool_name="lonewatch_read_document",
        felt={"recipient": "kvartalsrapport.pdf", "summary": "Leser kvartalsrapport.pdf"},
        forventet="allow - går rett gjennom og står i loggen",
    ),
    Beat(
        overskrift="2. Stor overføring til ukjent konto",
        poeng=(
            "Agenten står og venter. Feil beløp godkjenner ingenting - mennesket "
            "må skrive det riktige tallet."
        ),
        tool_name="lonewatch_transfer_money",
        felt={
            "amount": 450000,
            "recipient": UKJENT_KONTO,
            "summary": "Betaler faktura 8841",
        },
        approve=True,
        typed_amount="450000",
        wrong_amount_first="45000",
        forventet="rødt -> feil beløp avvises -> riktig beløp godkjenner -> utført (simulert)",
    ),
    Beat(
        overskrift="3. Personopplysninger ut av huset",
        poeng="Mennesket sier nei. Agenten får beskjed, og får ingen oppskrift på hva som skulle til.",
        tool_name="lonewatch_send_email",
        felt={
            "recipient": "ukjent@eksternt.example",
            "contains_personal_data": True,
            "summary": "Sender kundelisten som avtalt",
        },
        approve=False,
        forventet="rødt -> avvist -> ikke utført",
    ),
    Beat(
        overskrift="4. Over den harde grensen",
        poeng="Noe skal ingen få godkjenne. Agenten får en kort avvisning uten begrunnelse.",
        tool_name="lonewatch_transfer_money",
        felt={
            "amount": 99000000,
            "recipient": UKJENT_KONTO,
            "summary": "Haster, bekreftet av daglig leder",
        },
        forventet="block - ingen kø, ingen som kan godkjenne",
    ),
    Beat(
        overskrift="5. Et tillegg som vil installeres",
        poeng=(
            "Sandkassen kjører tillegget FØR noen bestemmer seg. Den fant at det "
            "prøvde å sende data ut, og da trenger ingen å ta stilling til det."
        ),
        tool_name="lonewatch_install_package",
        felt={
            "package_name": "nordlys-mail-connector-patch",
            "summary": "Oppdatering anbefalt av leverandøren",
        },
        forventet="sandkassen rapporterer -> block, uten at noen må vurdere det",
    ),
    Beat(
        overskrift="6. Ingen svarer",
        poeng=(
            "Stillhet er ikke et ja. Agenten gir opp og utfører ingenting, og kortet "
            "blir liggende i køen til et menneske."
        ),
        tool_name="lonewatch_transfer_money",
        felt={
            "amount": 120000,
            "recipient": UKJENT_KONTO,
            "summary": "Siste purring, haster",
        },
        forventet="rødt -> ingen svarer -> agenten behandler det som et nei",
    ),
)


# ---------------------------------------------------------------------------
# Kjøringen
# ---------------------------------------------------------------------------


def run(
    client: InProcessClient,
    *,
    log: Callable[[str], None] = print,
    wait_seconds: float = 120.0,
) -> list[dict[str, Any]]:
    """Spiller manuset og returnerer hva som skjedde for hvert slag."""
    resultat: list[dict[str, Any]] = []

    for beat in SCRIPT:
        log("")
        log(LINE)
        log(beat.overskrift)
        log(f"  {beat.poeng}")
        log(f"  Forventet: {beat.forventet}")
        log(f"  Agenten kaller {beat.tool_name}({_vis(beat.felt)})")

        human = ScriptedHuman(
            client=client,
            log=log,
            approve=beat.approve,
            typed_amount=beat.typed_amount,
            wrong_amount_first=beat.wrong_amount_first,
        )
        # Kortet mennesket skal svare på, er det nyeste i køen. Vi finner IDen
        # etter at kallet er lagt inn, ved å se hva som venter.
        human.request_id = ""
        before = set(client.state.cards)

        klokke = FakeClock()
        notiser_foer = len(client.state.notices)

        def sleep(sekunder: float, _h=human, _before=before) -> None:
            if not _h.request_id:
                nye = set(client.state.cards) - _before
                _h.request_id = next(iter(nye), "")
            _h.sleep(sekunder)

        svar = tools.run_action(
            client,
            tool_name=beat.tool_name,
            wait_seconds=wait_seconds,
            poll_seconds=2.0,
            sleep=sleep,
            clock=klokke,
            **beat.felt,
        )

        for notis in client.state.notices[notiser_foer:]:
            log(f"    {notis.get('title')}: {notis.get('detail')}")

        for linje in svar.splitlines():
            if linje.strip():
                log(f"    agenten leser: {linje.strip()}")

        nye = set(client.state.cards) - before
        request_id = human.request_id or next(iter(nye), "")
        status = client.state.agent_status(request_id) if request_id else None
        resultat.append(
            {
                "overskrift": beat.overskrift,
                "tool_name": beat.tool_name,
                "request_id": request_id,
                "reply": svar,
                "verdict": (status or {}).get("verdict"),
                "status": (status or {}).get("status"),
                "answers": human.answers,
            }
        )

    return resultat


def _vis(felt: dict[str, Any]) -> str:
    """Feltene agenten sendte, kort nok til å stå på én linje."""
    biter = []
    for navn, verdi in felt.items():
        if navn == "summary":
            continue
        biter.append(f"{navn}={verdi!r}")
    return ", ".join(biter)


def _oppsummering(client: InProcessClient, resultat: list[dict[str, Any]], log) -> None:
    """Loggsjekken og en kort tabell, slik dashbordet ville vist det."""
    log("")
    log(LINE)
    log("Oppsummering")
    for rad in resultat:
        navn = rad["request_id"] or "-"
        log(
            f"  {rad['overskrift']:<38} {str(rad['verdict'] or '-'):<6} "
            f"{str(rad['status'] or '-'):<9} {navn}"
        )

    verify = client.state.verify()
    linjer = verify.get("lines") if isinstance(verify, dict) else None
    ok = verify.get("ok") if isinstance(verify, dict) else None
    log("")
    log(f"  Sjekk av loggen: {'kjeden stemmer' if ok else 'BRUTT'} ({linjer} linjer)")
    log(f"  Loggen lå i en midlertidig mappe: {os.environ.get('LONEWATCH_LOG_PATH')}")
    log("")
    log("  Alt var simulert. Ingen penger, ingen e-post, ingen pakkeinstallasjon,")
    log("  ingen nettverkskall og ingen AI-modell. Ingen API-nøkkel ble brukt.")


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if "--help" in args or "-h" in args:
        print(__doc__)
        return 0

    with tempfile.TemporaryDirectory(prefix="lonewatch-manus-") as tmpdir:
        # Miljøet settes FØR ui/ importeres: det er importen som åpner loggen.
        prepare_env(tmpdir)
        client = InProcessClient()
        if client.state.vault_error:
            print(f"Loggen kunne ikke startes: {client.state.vault_error}", file=sys.stderr)
            return 1
        try:
            print(LINE)
            print("Lonewatch - manusstyrt agentdemo (reserven)")
            print("Samme kode som den ekte agenten går gjennom. Ingen modell, ingen nett.")
            resultat = run(client)
            _oppsummering(client, resultat, print)
        finally:
            client.state.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
