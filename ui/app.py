"""FastAPI-appen. Én nettside, ingen byggesteg, ren HTML/CSS/JS.

Appen inneholder ingen regler. Den spoer gateway og vault, og viser svaret.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import threading
import time
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from ui.human_key import (
    ENV_HUMAN_KEY,
    HUMAN_KEY_HEADER,
    HumanKeyOff,
    HumanKeyRefused,
    check_human_key,
    is_configured,
)
from ui.state import (
    MAX_PACKAGE_CHARS,
    MAX_RECIPIENT_CHARS,
    MAX_SUMMARY_CHARS,
    DemoState,
    minimized_overview,
    minimized_snapshot,
)
from vault.tamper_demo import ATTACK_TITLES, ATTACKS, TamperDemoError, run_attack

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="Lonewatch", docs_url=None, redoc_url=None)
state = DemoState()

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# -- grenser ---------------------------------------------------------------
#
# To tak og en fartsgrense, og ingen av tallene er plukket fordi de ser pene ut.
#
# 1. KROPPSSTOERRELSE (her). Den stoerste lovlige kroppen appen tar imot er
#    "Prøv selv"-skjemaet: `action_type` 40 tegn + `summary` 200 + `amount` 64 +
#    `recipient` 120 + `package_name` 64 + en bool, altsaa under 600 byte med
#    JSON-rammen rundt. Feltgrensene staar i ui/state.py og haandheves av
#    pydantic uansett - men FOER pydantic ser noe, har hele kroppen alt ligget i
#    minnet. Det er A10 i docs/ANGREP2.md: 3 MB soepel i et felt ingen leser ble
#    tatt imot med 200.
#
#    64 KB er ~110 ganger den stoerste lovlige kroppen. Hvorfor saa romslig:
#    hvert norsk tegn kan bli 6 byte som \uXXXX i JSON, og et nytt felt skal
#    ikke treffe grensen foer det treffer pydantic. Og hvorfor ikke mer: 64 KB
#    er under én enkelt TCP-vindusfylling, saa en kropp som naar grensen er
#    avvist foer den rekker aa koste noe. Tallet gjelder ALLE ruter, ogsaa
#    /api/agent/submit.
#
# 2. ANTALL KORT: `MAX_CARDS` i ui/state.py (200). Begrunnelsen staar der.
# 3. FARTSGRENSE paa /api/agent/submit: `AGENT_SUBMITS_PER_MINUTE` nedenfor.

MAX_BODY_BYTES = 64 * 1024

MAX_BODY_TEXT = (
    "Forespørselen er for stor. Lonewatch tar imot kropper på opptil 64 KB; "
    "det største lovlige skjemaet er under 1 KB. Grensen står i ui/app.py."
)


class BodySizeLimit:
    """ASGI-middleware: avviser for store kropper med 413 foer appen ser dem.

    Ren ASGI og ikke `@app.middleware("http")` med vilje. Starlettes
    `BaseHTTPMiddleware` pakker svaret om i en stroem, og det brekker
    `FileResponse` - nettsiden og designfilene ble levert halve
    (`IncompleteRead`). En grense skal ikke kunne gjoere appen daarligere enn
    den var.

    To sjekker, fordi `Content-Length` er noe KLIENTEN oppgir:

      1. Er hodet satt og for stort, svarer vi UMIDDELBART og leser ikke
         kroppen i det hele tatt. Det er det billigste neiet: byte vi aldri
         leser, koster oss ingenting. Prisen staar aapent i docs/ANGREP2.md:
         en klient som fortsatt holder paa aa sende 3 MB naar svaret kommer,
         ser et avbrutt samband og ikke en pen 413. Den eneste som sender 3 MB
         hit er en angriper; det stoerste LOVLIGE skjemaet er under 1 KB.
      2. Er hodet borte (`Transfer-Encoding: chunked`) eller loeyer det, leser
         vi kroppen selv - bare til én byte over grensen - og sender den videre
         nedover hvis den holdt. En grense som bare leser et hode, er ingen
         grense.

    Kroppen bufres bare for kall som HAR en kropp. En GET gaar rett gjennom,
    uendret, slik at statiske filer leveres som foer.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        if scope.get("method", "GET") in ("GET", "HEAD", "OPTIONS"):
            await self.app(scope, receive, send)
            return

        hoder = {k.decode("latin-1").lower(): v for k, v in scope.get("headers", [])}
        raw = hoder.get("content-length")
        if raw is not None:
            try:
                if int(raw) > MAX_BODY_BYTES:
                    await self._refuse(send)
                    return
            except ValueError:
                await self._refuse(send)
                return

        biter: list[bytes] = []
        lest = 0
        while True:
            melding = await receive()
            if melding["type"] != "http.request":
                # http.disconnect: klienten ga opp. La appen under se det.
                biter = []
                break
            bit = melding.get("body") or b""
            lest += len(bit)
            if lest > MAX_BODY_BYTES:
                await self._refuse(send)
                return
            biter.append(bit)
            if not melding.get("more_body", False):
                break

        kropp = b"".join(biter)
        sendt = False

        async def replay():
            nonlocal sendt
            if sendt:
                return {"type": "http.disconnect"}
            sendt = True
            return {"type": "http.request", "body": kropp, "more_body": False}

        await self.app(scope, replay, send)

    @staticmethod
    async def _refuse(send) -> None:
        kropp = json.dumps({"detail": MAX_BODY_TEXT}).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(kropp)).encode("latin-1")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": kropp})


app.add_middleware(BodySizeLimit)


# -- menneskenoekkelen -----------------------------------------------------
#
# ALT som gjelder "bare et menneske kan godkjenne" staar i denne blokken.
# Noekkelen selv, og hvorfor den er atskilt fra agentnoekkelen, staar i
# ui/human_key.py. Her er bare porten.


def _human_gate(hva: str = ""):
    """Lager porten foran EN rute. Samme mekanisme for alle rutene.

    Alle vaktene i filen kommer herfra, og det er med vilje: er det bare én
    sammenligning, kan ikke én rute havne paa en snillere variant av den.
    Mekanismen er `ui.human_key.check_human_key()`, altsaa `hmac.compare_digest`
    mot noeklene i `LONEWATCH_HUMAN_KEY`.

    Fail closed: er `LONEWATCH_HUMAN_KEY` ikke satt, svarer ruten 503 og gjoer
    ingenting. Agentnoekkelen gjelder ingen av dem - den staar i `.mcp.json`,
    altsaa i en fil agenten selv leser.

    `hva` er setningen den som blir nektet faar foerst, og den sier hvilken
    HANDLING som ble stoppet - ikke noe om noekkelen. En som trykker
    «Nullstill» skal ikke lese en beskjed om roede kort.
    """

    def guard(request: Request) -> str:
        given = request.headers.get(HUMAN_KEY_HEADER) or ""
        try:
            return check_human_key(given)
        except HumanKeyOff as exc:
            raise HTTPException(
                status_code=503, detail=f"{hva} {exc}".strip()
            ) from exc
        except HumanKeyRefused as exc:
            raise HTTPException(
                status_code=403, detail=f"{hva} {exc}".strip()
            ) from exc

    return guard


# Porten foran godkjenningen. Beskjeden er den `ui/human_key.py` skriver selv.
_human_guard = _human_gate()

# Porten foran ALT som styrer demoen: «Spill av hendelsen», «Nullstill»,
# «Prøv selv», stroemmen og «Bryt loggen».
#
# Hvorfor de ogsaa: hver av dem SKRIVER i loggen eller endrer koeen. Ett
# uautentisert `POST /api/reset` arkiverte loggen og toemte en koe der et roedt
# kort ventet paa et menneske (H4 i docs/ANGREP.md, A12 i docs/ANGREP2.md), og
# ett uautentisert `POST /api/custom` kunne naa utfoere en `allow` paa ekte
# (H25). At appen binder 127.0.0.1 var hele forsvaret, og «ingen andre kjoerer
# noe paa denne maskinen» er ikke et forsvar i et prosjekt hvis hele poeng er
# at en agent kjoerer paa denne maskinen.
_demo_guard = _human_gate(
    "Denne handlingen styrer demoen og krever menneskenøkkelen: "
    "lås opp øverst i Godkjenning først."
)


class CustomIn(BaseModel):
    """En forespørsel juryen har skrevet i "Prøv selv".

    Lengdegrensene staar her OG i ui/state.py: her for aa avvise det som er
    aapenbart for stort foer vi gjoer noe, der fordi state.py ogsaa kalles
    direkte fra tester og kan ikke stole paa at noen har validert foerst.

    Merk hva som IKKE staar her: `recipient_known` og `reversible`. De regnes
    ut i integrasjonslaget. Den som skriver en forespørsel skal ikke kunne
    paastaa at en ukjent konto er kjent.
    """

    action_type: str = Field(max_length=40)
    summary: str = Field(default="", max_length=MAX_SUMMARY_CHARS)
    amount: str = Field(default="", max_length=64)
    recipient: str = Field(default="", max_length=MAX_RECIPIENT_CHARS)
    package_name: str = Field(default="", max_length=MAX_PACKAGE_CHARS)
    contains_personal_data: bool = False


class RespondIn(BaseModel):
    """Svaret fra mennesket.

    `extra="forbid"` og ingen `seconds_to_decide`: betenkningstiden måles av
    TJENEREN, fra kortet ble lagt i køen til svaret kom. Et felt som ble
    stilltiende ignorert ville sett ut som om klienten fortsatt bestemte
    tallet; nå svarer endepunktet 422 på et forsøk. Se H2 i docs/ANGREP.md.
    """

    model_config = ConfigDict(extra="forbid")

    request_id: str
    approved: bool
    typed_amount: str | None = None


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


def _unlocked(request: Request) -> bool:
    """Har den som spoer menneskenoekkelen? Ja/nei, ingen feil.

    Brukes bare av `/api/state`, som skal svare BEGGE veier - en side som ikke
    kan tegne noe foer noen har logget inn, viser ikke at det er en
    mellomstasjon her i det hele tatt. Alle andre ruter bruker `_human_gate`,
    som nekter.
    """
    try:
        check_human_key(request.headers.get(HUMAN_KEY_HEADER) or "")
        return True
    except (HumanKeyOff, HumanKeyRefused):
        return False


@app.get("/api/state")
def api_state(request: Request) -> dict:
    """Alt nettsiden trenger - i to nivaaer, etter om noen har laast opp.

    UTEN menneskenoekkelen: `minimized_snapshot()`, altsaa en allowliste med
    tellere, status, risiko og en MASKERT mottaker (samme maskering loggen
    bruker). Ingen `summary`, ingen `decision.reasons`, ingen konsekvenstekst,
    ingen sandkasserapporter, ingen filstier.

    MED: hele snapshotet, som foer. Mennesket som skal vurdere en sak maa se
    hele mottakeren og hvilke regler som slo til - det er hele poenget.

    Dette er A1 i docs/ANGREP2.md. Begrunnelsen for valget staar over
    `minimized_snapshot` i ui/state.py.
    """
    full = state.snapshot()
    if _unlocked(request):
        return {**full, "locked": False}
    return minimized_snapshot(full)


@app.post("/api/feed/step")
def api_feed_step(_: str = Depends(_demo_guard)) -> dict:
    """Slipper neste forespoersel fra demodataene gjennom mellomstasjonen.

    Bak menneskenoekkelen: ruten SKRIVER i loggen, og en `allow` herfra gaar
    til utfoereren. Se `_demo_guard`.
    """
    card = state.step_feed()
    return {"card": card, "state": {**state.snapshot(), "locked": False}}


@app.get("/api/human")
def api_human() -> dict:
    """Kan noe godkjennes akkurat naa? Nettsiden spoer for aa vise laasen.

    Svarer bare ja/nei og navnet paa hodet noekkelen skal staa i. Ingen
    noekkel, ingen lengde, ingen antydning om verdien.
    """
    return {
        "configured": is_configured(),
        "header": HUMAN_KEY_HEADER,
        "env": ENV_HUMAN_KEY,
    }


@app.post("/api/human/check")
def api_human_check(operator: str = Depends(_human_guard)) -> dict:
    """Stemmer noekkelen? Brukes av innloggingsfeltet, gjoer ingenting annet.

    Svarer med pseudonymet som vil staa i loggen, slik at den som logger inn
    ser hvem loggen kommer til aa si at det var.
    """
    return {"ok": True, "pseudonym": state.operator_pseudonym(operator)}


@app.post("/api/respond")
def api_respond(body: RespondIn, operator: str = Depends(_human_guard)) -> dict:
    """Mennesket godkjenner eller avviser en roed forespoersel.

    `operator` kommer fra menneskenoekkelen, ikke fra kroppen: den som svarer
    skal ikke kunne skrive hvem de er. Betenkningstiden regnes i `state`.
    """
    result = state.respond(
        request_id=body.request_id,
        approved=body.approved,
        typed_amount=body.typed_amount,
        operator=operator,
    )
    return {**result, "state": {**state.snapshot(), "locked": False}}


@app.post("/api/custom")
def api_custom(body: CustomIn, _: str = Depends(_demo_guard)) -> dict:
    """"Prøv selv": juryens egen forespørsel gjennom samme vei som de 40.

    Bak menneskenoekkelen (H25 i docs/ANGREP.md): en `allow` herfra utfoeres
    paa ekte, og med `LONEWATCH_EXECUTOR=smtp` ble det en ekte e-post fra et
    uautentisert kall. Se `_demo_guard`.
    """
    result = state.submit_custom(
        action_type=body.action_type,
        summary=body.summary,
        amount=body.amount,
        recipient=body.recipient,
        package_name=body.package_name,
        contains_personal_data=body.contains_personal_data,
    )
    return {**result, "state": {**state.snapshot(), "locked": False}}


@app.get("/api/custom/help")
def api_custom_help() -> dict:
    """Handlingstyper og eksempler paa kjente mottakere, til skjemaet."""
    return state.custom_help()


@app.get("/api/log")
def api_log() -> dict:
    """Logglinjene som tabell, pluss fellene i dokumentene.

    Alt kommer fra loggen og fra agents/traps.py. Ingenting er regnet ut for
    aa se pent ut.
    """
    return {"log": state.log_rows(), "traps": state.traps_overview()}


@app.get("/api/trail/{request_id}")
def api_trail(request_id: str) -> dict:
    """«Dette ledet hit»: hva samme agent gjorde rett foer."""
    return {"trail": state.agent_trail(request_id)}


@app.get("/api/overview")
def api_overview(request: Request) -> dict:
    """Tallene til dashbordet, regnet fra tilstanden og loggen.

    Samme form som LONEWATCH_DATA i design-handoff/, saa svaret kan sendes
    rett inn i Lonewatch.setData(...).

    Svarer BEGGE veier, som `/api/state`: tellere og status er hele poenget med
    en forside, og en Oversikt som er tom foer noen logger inn viser ikke at det
    er en mellomstasjon her. Uten menneskenoekkelen gaar svaret gjennom
    `minimized_overview()`: kortet «Venter paa deg» mister konsekvensteksten,
    regelnavnene og hele kontonummeret. Ruten SKRIVER ingenting, saa den trenger
    ingen `_demo_guard`.
    """
    data = state.overview()
    if _unlocked(request):
        return {**data, "locked": False}
    return minimized_overview(data)


@app.get("/api/verify")
def api_verify() -> dict:
    """Sjekk loggen: kaller vault.verify()."""
    return state.verify()


@app.get("/api/after")
def api_after() -> dict:
    """Etter-listen fra vault.after.build_after_actions, hvis den finnes."""
    return state.after_actions()


@app.post("/api/story/start")
def api_story_start(_: str = Depends(_demo_guard)) -> dict:
    """«Spill av hendelsen». Bak menneskenoekkelen: den skriver i loggen."""
    return {"story": state.story_start(), "state": {**state.snapshot(), "locked": False}}


@app.post("/api/story/step")
def api_story_step(_: str = Depends(_demo_guard)) -> dict:
    """Neste steg i hendelsen. Bak menneskenoekkelen, samme grunn."""
    return {"story": state.story_step(), "state": {**state.snapshot(), "locked": False}}


@app.get("/api/story")
def api_story() -> dict:
    return state.story_snapshot()


@app.post("/api/reset")
def api_reset(_: str = Depends(_demo_guard)) -> dict:
    """Nullstiller demoen: ny logg, tom koe, historien ikke spilt.

    Bak menneskenoekkelen (H4 i docs/ANGREP.md, A12 i docs/ANGREP2.md). Ruten
    SLETTER ingenting - den gamle loggen arkiveres under nytt navn - men en
    uautentisert «start ny logg og toem koeen»-knapp er et problem i seg selv:
    et roedt kort som ventet paa et menneske forsvinner ut av koeen.
    """
    state.reset()
    # Nullstill betyr nullstill: ogsaa fartsgrensen for agentene.
    reset_rate_limit()
    return {**state.snapshot(), "locked": False}


# -- Bryt loggen -----------------------------------------------------------
#
# Fire knapper i Etter-fanen. Hver av dem kjoerer et ekte angrep paa en KOPI av
# loggen og lar den vanlige verifiseringen svare. All logikken ligger i
# `vault/tamper_demo.py` - denne ruten bygger ingenting og vurderer ingenting,
# den sender `run_attack(attack).to_dict()` videre.
#
# Bak menneskenoekkelen. Ruten leser og dekrypterer hele loggen og roerer
# loggnoekkelen; den hoerer ikke til paa et aapent endepunkt, selv om den ikke
# endrer noe. Den ekte loggen og det ekte ankeret roeres aldri -
# `tamper_demo.run_attack` tar fingeravtrykk foer og etter og KASTER hvis de
# ikke er like.


class TamperIn(BaseModel):
    """Hvilket angrep. `extra="forbid"`: ingen sti og ingen noekkel fra kroppen.

    Det er poenget med at modellen bare har ett felt: den som kaller skal ikke
    kunne peke demoen paa en annen fil eller sende inn sin egen loggnoekkel.
    Begge hentes fra miljoeet, som alt annet i Lonewatch.
    """

    model_config = ConfigDict(extra="forbid")

    attack: str = Field(max_length=16)


@app.get("/api/tamper")
def api_tamper_list() -> dict:
    """Hvilke angrep finnes, og hva heter de? Til aa tegne de fire knappene.

    Aapen med vilje: dette er fire norske titler fra `ATTACK_TITLES`, ingen
    loggdata og ingen noekkel. Selve angrepet (POST) krever noekkelen.
    """
    return {
        "attacks": [{"attack": a, "title": ATTACK_TITLES[a]} for a in ATTACKS]
    }


# Absolutte stier i en feilmelding som gaar til en nettleser.
#
# Funnet av `tests/attack2/test_attack_tamper_route.py` mens ruten ble skrevet:
# `TamperDemoError` navngir loggfilen med full sti («Loggen /Users/.../
# lonewatch_log.jsonl finnes ikke»). Det er riktig i en terminal, der den som
# leser ER den som eier filen. I et HTTP-svar er det en sti ut til den som
# spoer, og `tests/attack2/test_attack_infoleak.py` krever at ingen rute gir
# en slik. Vi endrer ikke `vault/tamper_demo.py` (den eies ikke herfra og
# terminalmeldingen er riktig der) - vi kutter stien ned til filnavnet paa vei
# ut. Filnavnet er nok til aa forstaa beskjeden; mappen er ikke.
_ABS_PATH = re.compile(r"(?<![\w.])/(?:[^\s/]+/)+([^\s/]+)")


def _no_paths(text: str) -> str:
    """Bytter absolutte stier mot bare filnavnet."""
    return _ABS_PATH.sub(lambda m: m.group(1), text)


@app.post("/api/tamper")
def api_tamper(body: TamperIn, _: str = Depends(_demo_guard)) -> dict:
    """Kjoerer ett angrep paa en kopi av loggen og svarer med hele resultatet.

    `TamperDemoError` blir 409: demoen kan ikke kjoeres ærlig akkurat naa -
    loggen er tom, for kort for angrepet, eller stemmer ikke FOER vi begynner.
    Det er ikke en feil i ruten, og det er ikke en 500: det er et «nei, ikke
    naa», og teksten fra `tamper_demo` sier hvorfor paa norsk. Stien kuttes
    bort paa vei ut - se `_no_paths`.
    """
    try:
        return run_attack(body.attack).to_dict()
    except TamperDemoError as exc:
        raise HTTPException(status_code=409, detail=_no_paths(str(exc))) from exc


# -- den ekte agenten (MCP) -------------------------------------------------
#
# ALT som gjelder broen mot en agent som faktisk kjører, står i denne blokken,
# samlet med vilje: resten av filen skal se ut som før, og dette skal være
# enkelt å lese, flytte eller fjerne. Se docs/EKTE_AGENT.md og
# agent_gateway/LIMITS.md.
#
# Tre valg som ikke er pyntet på:
#
# 1. Endepunktene er AV uten en delt hemmelighet. `LONEWATCH_AGENT_KEY` må
#    være satt i terminalen som kjører appen, ellers svarer de 503. Da kan
#    ingen annen prosess på maskinen legge noe i godkjenningskøen ved et uhell.
# 2. Bare kall fra 127.0.0.1 slipper inn, uansett hva appen er bundet til.
#    Setter noen LONEWATCH_HOST=0.0.0.0, er dette siste skanse.
# 3. Agenten får ikke regelnavnene tilbake. De ville vært en oppskrift på hva
#    som må endres for å slippe gjennom neste gang.

ENV_AGENT_KEY = "LONEWATCH_AGENT_KEY"
AGENT_KEY_HEADER = "X-Lonewatch-Agent-Key"

# Adresser vi regner som "denne maskinen".
LOOPBACK = frozenset({"127.0.0.1", "::1", "localhost"})


class AgentSubmitIn(BaseModel):
    """Et verktøykall fra en agent som faktisk kjører.

    `extra="forbid"` er poenget her: sender agenten med `recipient_known`,
    `reversible`, `agent_id` eller `id`, får den 422 i stedet for at feltet blir
    stilltiende brukt eller stilltiende ignorert. De fire feltene finnes ikke i
    modellen, og de regnes ut i ui/state.py.
    """

    model_config = ConfigDict(extra="forbid")

    action_type: str = Field(max_length=40)
    summary: str = Field(default="", max_length=MAX_SUMMARY_CHARS)
    amount: str = Field(default="", max_length=64)
    recipient: str = Field(default="", max_length=MAX_RECIPIENT_CHARS)
    package_name: str = Field(default="", max_length=MAX_PACKAGE_CHARS)
    contains_personal_data: bool = False


class AgentAbandonIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    waited_seconds: float = Field(default=0.0, ge=0, le=86400)


def _agent_guard(request: Request) -> None:
    """Slipper bare inn lokale kall med riktig delt hemmelighet."""
    expected = (os.environ.get(ENV_AGENT_KEY) or "").strip()
    if not expected:
        raise HTTPException(
            status_code=503,
            detail=(
                "Broen mot en ekte agent er av. Sett LONEWATCH_AGENT_KEY i "
                "terminalen som kjører appen, og start den på nytt."
            ),
        )

    host = request.client.host if request.client else ""
    if host not in LOOPBACK:
        raise HTTPException(
            status_code=403,
            detail="Broen svarer bare på kall fra denne maskinen (127.0.0.1).",
        )

    given = request.headers.get(AGENT_KEY_HEADER) or ""
    if not hmac.compare_digest(given.encode("utf-8"), expected.encode("utf-8")):
        raise HTTPException(status_code=403, detail="Feil eller manglende nøkkel.")


# -- fartsgrense paa /api/agent/submit -------------------------------------
#
# H27 i docs/ANGREP.md: en agent kan sende saa mange forespoersler den vil. 40
# kall fyller godkjenningskoeen, og mennesket maa gjennom alle for aa finne den
# ene som betyr noe. Det er tjenestenekt mot MENNESKET, ikke mot appen, og
# `MAX_CARDS` alene stopper det ikke - taket kan fylles i ett rykk.
#
# 30 per minutt per agentnoekkel. Hvorfor 30:
#   - manusdemoen (`agent_gateway/scripted_demo.py`) har 6 slag, og en ekte
#     Claude Code-agent i en demo gjoer en haandfull kall. 30 er langt over
#     alt legitimt vi har maalt.
#   - 30 i minuttet er fortsatt raskere enn et menneske kan lese kort, saa
#     grensen er et tak mot aa FYLLE koeen, ikke en koe-kontroll. Den som
#     holder noekkelen og venter, naar fortsatt `MAX_CARDS`. Det er taket som
#     stopper det der, og de to henger sammen med vilje.
#
# Vinduet er et glidende minutt per noekkel, holdt i minnet. Noekkelen selv
# lagres ALDRI: vi teller paa sha256 av den. Det staar ingen noekkel i dette
# ordboket, heller ikke i en feilsoekingsdump av prosessen.
AGENT_SUBMITS_PER_MINUTE = 30
RATE_WINDOW_SECONDS = 60.0

_rate_lock = threading.Lock()
_rate_hits: dict[str, list[float]] = {}


def _rate_key(given: str) -> str:
    return hashlib.sha256(given.encode("utf-8")).hexdigest()[:16]


def reset_rate_limit() -> None:
    """Toemmer fartsgrensen. Brukes av tester og av `/api/reset`.

    Uten denne ville en test som sender 31 kall gjoere alle senere tester i
    samme prosess avhengige av rekkefoelgen.
    """
    with _rate_lock:
        _rate_hits.clear()


def _rate_guard(request: Request) -> None:
    """Teller kall per agentnoekkel i et glidende minutt. 429 over grensen.

    Ligger paa HTTP-ruten og ikke i `ui/state.py`, fordi agentnoekkelen er et
    HTTP-begrep. Det betyr ogsaa, ærlig sagt, at en kaller i SAMME prosess
    (manusdemoen kaller `api_agent_submit()` rett) ikke telles. Den som kan
    kalle funksjonen direkte har alt kjoeringsrett i prosessen, og da er
    fartsgrensen ikke det som beskytter noe. Taket `MAX_CARDS` gjelder ogsaa
    der, fordi det staar i `ui/state.py`.
    """
    noekkel = _rate_key(request.headers.get(AGENT_KEY_HEADER) or "")
    naa = time.monotonic()
    with _rate_lock:
        treff = [t for t in _rate_hits.get(noekkel, ()) if naa - t < RATE_WINDOW_SECONDS]
        if len(treff) >= AGENT_SUBMITS_PER_MINUTE:
            _rate_hits[noekkel] = treff
            eldste = min(treff)
            vent = max(1, int(RATE_WINDOW_SECONDS - (naa - eldste)) + 1)
            raise HTTPException(
                status_code=429,
                detail=(
                    f"For mange forespørsler. Grensen er {AGENT_SUBMITS_PER_MINUTE} "
                    f"per minutt per agentnøkkel. Prøv igjen om {vent} sekunder. "
                    "Grensen finnes for at en agent ikke skal kunne fylle "
                    "godkjenningskøen slik at det ene kortet som betyr noe blir "
                    "borte i mengden."
                ),
                headers={"Retry-After": str(vent)},
            )
        treff.append(naa)
        _rate_hits[noekkel] = treff


def _lw_name(request_id: str) -> str:
    """Samme visningsnavn som nettsiden bruker, slik at agenten og mennesket
    snakker om det samme kortet. Serie 8 er den ekte agenten."""
    prefix, _, number = str(request_id).partition("_")
    serie = {"req": 1, "story": 2, "agent": 8, "custom": 9}.get(prefix)
    if serie is None or not number.isdigit():
        return str(request_id)
    return f"LW-{serie}{number.zfill(3)[-3:]}"


def _agent_view(request_id: str, card_or_status: dict) -> dict:
    """Det agenten får se. Regelnavnene (`reasons`) er ikke med."""
    verdict = card_or_status.get("verdict")
    ut = {
        "ok": True,
        "request_id": request_id,
        "name": _lw_name(request_id),
        "status": card_or_status.get("status"),
        "verdict": verdict,
        "risk": card_or_status.get("risk"),
        "requires_typed_amount": card_or_status.get("requires_typed_amount", False),
    }
    if verdict == "block":
        # Kort avvisning. Konsekvensteksten navngir hva som slo til, og det
        # ville vært et tips om hvordan den kan omgås.
        ut["consequence_text"] = None
    else:
        ut["consequence_text"] = card_or_status.get("consequence_text")
    return ut


@app.get("/api/agent/ping")
def api_agent_ping(_: None = Depends(_agent_guard)) -> dict:
    """Kommer MCP-tjeneren inn? Brukes til å feilsøke oppsettet, gjør ingenting."""
    return {"ok": True, "app": "lonewatch"}


@app.post("/api/agent/submit")
def api_agent_submit(
    body: AgentSubmitIn,
    _: None = Depends(_agent_guard),
    __: None = Depends(_rate_guard),
) -> dict:
    """Et verktøykall fra en ekte agent, inn samme vei som "Prøv selv".

    Fartsgrensen staar ETTER noekkelsjekken med vilje: en kaller uten gyldig
    noekkel skal ikke kunne bruke opp kvoten til en som har den.
    """
    result = state.submit_agent(
        action_type=body.action_type,
        summary=body.summary,
        amount=body.amount,
        recipient=body.recipient,
        package_name=body.package_name,
        contains_personal_data=body.contains_personal_data,
    )
    if not result.get("ok"):
        # Forespørselen holdt ikke formelt. Den er ikke vurdert, og det sier vi.
        return {"ok": False, "error": result.get("error")}

    card = result["card"]
    request_id = card["request"]["id"]
    return _agent_view(request_id, {**card["decision"], "status": card["status"]})


@app.get("/api/agent/status/{request_id}")
def api_agent_status(request_id: str, _: None = Depends(_agent_guard)) -> dict:
    """Hvor står en rød forespørsel nå? Svarer med en gang, venter aldri."""
    status = state.agent_status(request_id)
    if status is None:
        return {"ok": False, "error": "Finner ikke forespørselen."}
    ut = _agent_view(request_id, status)
    ut["approved"] = status.get("approved")
    ut["typed_amount"] = status.get("typed_amount")
    return ut


@app.post("/api/agent/abandon/{request_id}")
def api_agent_abandon(
    request_id: str, body: AgentAbandonIn, _: None = Depends(_agent_guard)
) -> dict:
    """Agenten sluttet å vente. Blir en notis i UI - ingenting i loggen.

    Ingen `HumanResponse` har skjedd, så loggen skal ikke si at noen svarte.
    Kortet blir liggende i køen og venter fortsatt på et menneske.
    """
    noted = state.agent_gave_up(request_id, body.waited_seconds)
    return {"ok": True, "noted": noted}
