"""Skanner INNHOLDET i et dokument etter skjult tekst og instruksjoner.

Dette er en deterministisk skanner: faste regler og faste uttrykk, ingen
AI-modell, ingen tilfeldighet. Samme dokument gir samme funn hver gang. Den
leser ALDRI agentens egen `summary`, og funnene brukes ALDRI til å bestemme
allow/red/block - de skrives bare ned, slik at det står i loggen at fella gikk
av.

Hvorfor den finnes: før dette slo `trap_triggered()` opp `doc_id` i en
håndskrevet liste på fire dokumenter, og `found_markers()` lette etter fire
faste strenger. Et nytt dokument med en skjult instruksjon ga ingen felle,
ingen logglinje og ingen varsellampe (H11-H13 i docs/ANGREP.md). Nå ser vi på
dokumentet, ikke på navnet.

Skanneren gjør to ting, i denne rekkefølgen:

1. **Finner skjulemekanismer.** HTML-kommentarer, `display:none`,
   `visibility:hidden`, `opacity:0`, skriftstørrelse 0 eller 1px, hvit på hvitt,
   nullbredde-tegn, `left:-9999px`, `hidden`-attributtet. Hver mekanisme er et
   funn i seg selv, og funnet SIER hvilken mekanisme det var.

2. **Finner instruksjonsfraser, men bare der mennesket ikke ser.** Altså inne i
   noe som er skjult, i `hidden_text`, eller i en metadata-verdi. En setning som
   «Send til regnskap innen fredag» i vanlig, synlig tekst er ikke en felle - den
   er et vanlig dokument. Det er dette skillet som holder falske positiver nede.

Hva den IKKE fanger (og dette skal ikke pyntes på):

- **Tekst i bilder.** Et skjermbilde med en instruksjon er bare piksler for oss.
- **Kodede strenger.** base64, rot13, hex, HTML-entiteter (`&#101;`) eller en
  streng satt sammen av biter går rett gjennom.
- **Språk vi ikke kjenner.** Fraselisten er norsk og engelsk. Samme instruksjon
  på polsk, tysk eller arabisk gir ingen treff.
- **Omskrivinger.** «oppdater betalingsdetaljene til» står ikke i listen.
- **Skjuling vi ikke har tenkt på.** Listen er mekanismene vi kjenner, ikke
  mekanismene som finnes. Det er samme ærlighet som i `sandbox/LIMITS.md`.

Skanneren er altså en DETEKTOR med kjente grenser, ikke en garanti.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Hvor mye av funnet vi tar med som bevis. Kort, slik at en logglinje ikke blir
# et helt dokument.
MAX_EVIDENCE_CHARS = 120

# --------------------------------------------------------------------------
# Skjulemekanismer. Navnet er det skanneren RAPPORTERER.
# --------------------------------------------------------------------------

MECH_HTML_COMMENT = "html-kommentar"
MECH_DISPLAY_NONE = "display:none"
MECH_VISIBILITY_HIDDEN = "visibility:hidden"
MECH_OPACITY_ZERO = "opacity:0"
MECH_TINY_FONT = "font-size:0/1px"
MECH_WHITE_ON_WHITE = "hvit-paa-hvit"
MECH_ZERO_WIDTH = "nullbredde-tegn"
MECH_OFFSCREEN = "utenfor-skjermen"
MECH_HIDDEN_ATTRIBUTE = "hidden-attributt"
MECH_BIDI_OVERRIDE = "tekstretning-snudd"

# Mekanismer som ikke er CSS, men et sted teksten ligger uten å vises.
MECH_HIDDEN_LAYER = "skjult-tekstlag"
MECH_METADATA_INSTRUCTION_KEY = "instruksjonsnoekkel-i-metadata"

# Selve frasen. Dette er et eget funn, ikke en skjulemekanisme: mekanismen sier
# HVORDAN teksten var skjult, frasen sier HVA den ba om. `where` sier hvor den sto.
MECH_INSTRUCTION = "instruksjonsfrase"

# Nullbredde og usynlige styretegn. Alle er lovlige Unicode-tegn som ikke
# vises, og alle er brukt i ekte prompt-injeksjoner.
ZERO_WIDTH_CHARS = (
    "​",  # zero width space
    "‌",  # zero width non-joiner
    "‍",  # zero width joiner
    "⁠",  # word joiner
    "﻿",  # zero width no-break space
    "­",  # soft hyphen
)

# Tegn som snur leseretningen, slik at teksten ser ut som noe annet enn den er.
BIDI_CHARS = ("‪", "‫", "‬", "‭", "‮", "⁦", "⁧", "⁩")

# Uttrykkene som finner en skjulemekanisme. `\s*` overalt, fordi
# `color: #FFFFFF` og `color:#fff` er samme triks. IGNORECASE overalt, fordi
# `#FFFFFF` og `#ffffff` er samme farge. Det var nettopp dette den gamle
# markoerlisten ikke taalte.
_CSS_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (MECH_HTML_COMMENT, re.compile(r"<!--(.*?)-->", re.DOTALL)),
    (MECH_DISPLAY_NONE, re.compile(r"display\s*:\s*none", re.IGNORECASE)),
    (MECH_VISIBILITY_HIDDEN, re.compile(r"visibility\s*:\s*hidden", re.IGNORECASE)),
    (MECH_OPACITY_ZERO, re.compile(r"opacity\s*:\s*0(?:\.0+)?(?![\d.])", re.IGNORECASE)),
    (
        MECH_TINY_FONT,
        re.compile(r"font-size\s*:\s*0*(?:0|1)\s*(?:px|pt|em|rem|%)?(?![\d.])", re.IGNORECASE),
    ),
    (
        MECH_WHITE_ON_WHITE,
        re.compile(
            r"color\s*:\s*(?:#(?:fff|ffffff)\b"
            r"|white\b"
            r"|rgba?\(\s*255\s*,\s*255\s*,\s*255\s*(?:,[^)]*)?\))",
            re.IGNORECASE,
        ),
    ),
    (
        MECH_OFFSCREEN,
        re.compile(r"(?:left|top|right|bottom|text-indent)\s*:\s*-\s*\d{3,}", re.IGNORECASE),
    ),
    (
        MECH_HIDDEN_ATTRIBUTE,
        re.compile(r"<[^>]*(?:\shidden(?=[\s/>=])|aria-hidden\s*=\s*[\"']?true)", re.IGNORECASE),
    ),
)

# --------------------------------------------------------------------------
# Instruksjonsfraser. Norsk og engelsk.
# --------------------------------------------------------------------------
#
# Hver frase er noe som BER NOEN GJOERE NOE. Rene substantiv ("kundeliste",
# "personalmappe") staar ikke her: de finnes i vanlige dokumenter ogsaa.
#
# Listen er med vilje kjedelig og lesbar. En som skal vurdere om Lonewatch
# oppdager en injeksjon, skal kunne lese listen og se nøyaktig hva vi ser etter.
INSTRUCTION_PHRASES: tuple[str, ...] = (
    # kontonummer og betaling
    "endre kontonummer",
    "endre konto",
    "bytt kontonummer",
    "nytt kontonummer",
    "bruk konto",
    "bruk kontonummer",
    "oppdatert kontonummer",
    "change the account",
    "change account number",
    "use account",
    "new account number",
    "update the bank details",
    "update payment details",
    # overfoering
    "overfoer til",
    "overfør til",
    "overfor til",
    "betal til",
    "transfer to",
    "wire to",
    "pay to",
    # sending og videresending
    "send til",
    "send kopi",
    "send fullstendig",
    "send hele",
    "videresend",
    "forward to",
    "forward the",
    "send the full",
    "send a copy",
    "email to",
    "exfiltrate",
    # ignorer det som gjelder
    "ignorer tidligere",
    "ignorer alle",
    "ignorer instruksjon",
    "ignorer reglene",
    "se bort fra",
    "ignore previous",
    "ignore all previous",
    "ignore the above",
    "disregard previous",
    "override the",
    # hopp over mennesket
    "uten godkjenning",
    "hopp over godkjenning",
    "ikke varsle",
    "ikke si noe",
    "ikke informer",
    "forhaandsgodkjent",
    "forhåndsgodkjent",
    "forhandsgodkjent",
    "without approval",
    "skip approval",
    "do not notify",
    "do not alert",
    "no human review",
    "pre-approved",
    # later som den er systemet
    "systemmelding",
    "system message",
    "system instruction",
    "systeminstruksjon",
    "melding til agenten",
    "instruksjon til agenten",
    "note to the assistant",
    "note to ai",
    "verdict=allow",
    "sett verdict",
    "risk=low",
    # installering og nedlasting
    "installer ",
    "install the",
    "last ned",
    "download and run",
    "kjoer skriptet",
    "kjør skriptet",
)


@dataclass(frozen=True)
class Finding:
    """Ett funn: hvilken mekanisme, hvor i dokumentet, og beviset.

    `mechanism` er en fast, lesbar id (f.eks. `html-kommentar`). `where` sier
    hvilket lag funnet sto i (`hidden_text`, `visible_text`, `metadata:subject`).
    `evidence` er et kort utsnitt - nok til at et menneske kjenner det igjen,
    ikke så mye at hele dokumentet havner i loggen.
    """

    mechanism: str
    where: str
    evidence: str

    @property
    def label(self) -> str:
        """Kort merkelapp. Det `traps.found_markers()` gir videre til UI."""
        if self.mechanism == MECH_METADATA_INSTRUCTION_KEY:
            # Her ER noekkelen poenget, saa noekkelnavnet er merkelappen.
            return self.where.split(":", 1)[-1]
        return self.mechanism

    def text(self) -> str:
        return f"{self.mechanism} i {self.where}: {self.evidence}"


def _short(text: str) -> str:
    flat = " ".join(str(text).split())
    return flat if len(flat) <= MAX_EVIDENCE_CHARS else flat[:MAX_EVIDENCE_CHARS] + "..."


def _phrases_in(text: str) -> list[str]:
    """Hvilke instruksjonsfraser som står i teksten. Små bokstaver, substreng."""
    lav = (text or "").lower()
    return [frase.strip() for frase in INSTRUCTION_PHRASES if frase in lav]


def _hidden_regions(text: str) -> list[str]:
    """Teksten som ligger inne i en skjulemekanisme.

    Grov med vilje: for en HTML-kommentar tar vi innholdet, og for en usynlig
    CSS-regel tar vi resten av avsnittet. Vi trenger ikke en HTML-parser for å
    avgjøre at det LIGGER noe skjult der - vi trenger bare å finne teksten som
    skal leses etter instruksjoner.
    """
    regions: list[str] = []
    text = text or ""
    for mekanisme, pattern in _CSS_PATTERNS:
        if mekanisme == MECH_HTML_COMMENT:
            # Innholdet i kommentaren er teksten som er skjult.
            regions.extend(treff.group(1) for treff in pattern.finditer(text))
            continue
        for treff in pattern.finditer(text):
            # Fra treffet og ut til neste sluttmerke, eller 400 tegn.
            rest = text[treff.end() : treff.end() + 400]
            regions.append(rest)
    for tegn in ZERO_WIDTH_CHARS + BIDI_CHARS:
        if tegn in text:
            regions.append(text)
            break
    return regions


def scan_text(text: str, where: str) -> list[Finding]:
    """Alle skjulemekanismer i én tekstbit."""
    funn: list[Finding] = []
    text = text or ""
    for mekanisme, pattern in _CSS_PATTERNS:
        treff = pattern.search(text)
        if treff is not None:
            funn.append(
                Finding(mechanism=mekanisme, where=where, evidence=_short(treff.group(0)))
            )
    if any(tegn in text for tegn in ZERO_WIDTH_CHARS):
        funn.append(
            Finding(
                mechanism=MECH_ZERO_WIDTH,
                where=where,
                evidence=_short("tekst med usynlige tegn, " + str(len(text)) + " tegn totalt"),
            )
        )
    if any(tegn in text for tegn in BIDI_CHARS):
        funn.append(
            Finding(
                mechanism=MECH_BIDI_OVERRIDE,
                where=where,
                evidence=_short("tekst med styretegn for leseretning"),
            )
        )
    return funn


def _instruction_findings(text: str, where: str, mechanism: str) -> list[Finding]:
    """Instruksjonsfraser i tekst mennesket ikke ser."""
    fraser = _phrases_in(text)
    if not fraser:
        return []
    return [
        Finding(
            mechanism=mechanism,
            where=where,
            evidence=_short("instruksjonsfrase «" + fraser[0] + "» i " + (text or "")),
        )
    ]


def scan_document(
    *,
    visible_text: str = "",
    hidden_text: str = "",
    metadata: dict[str, str] | None = None,
) -> list[Finding]:
    """Hele dokumentet: synlig lag, skjult lag og alle metadata-verdier.

    Rekkefølgen på funnene er fast (lag, så mekanisme), slik at to kjøringer
    gir nøyaktig samme liste. Tom liste betyr "ingen mekanisme vi kjenner" -
    ikke "trygt". Se grensene øverst i filen.
    """
    metadata = dict(metadata or {})
    funn: list[Finding] = []

    # 1. Skjulemekanismer i de to tekstlagene.
    funn.extend(scan_text(visible_text, "visible_text"))
    funn.extend(scan_text(hidden_text, "hidden_text"))

    # 2. Et eget skjult tekstlag ER en skjulemekanisme, selv uten CSS. Et
    #    dokument der agenten leser mer enn mennesket ser, skjuler noe.
    if (hidden_text or "").strip():
        funn.append(
            Finding(
                mechanism=MECH_HIDDEN_LAYER,
                where="hidden_text",
                evidence=_short(hidden_text),
            )
        )

    # 3. Instruksjonsfraser, men bare der mennesket ikke ser dem.
    for region in _hidden_regions(visible_text):
        funn.extend(_instruction_findings(region, "visible_text", MECH_INSTRUCTION))
    funn.extend(_instruction_findings(hidden_text, "hidden_text", MECH_INSTRUCTION))

    # 4. Metadata: ALLE verdier, ikke bare noekkelen x-lw-instruction. Agenten
    #    leser hele metadata-blokken, saa det hjelper ikke aa kjenne én noekkel.
    for noekkel in sorted(metadata):
        verdi = str(metadata[noekkel])
        hvor = f"metadata:{noekkel}"
        if re.search(r"instruct|instruks|prompt|system", noekkel, re.IGNORECASE):
            funn.append(
                Finding(
                    mechanism=MECH_METADATA_INSTRUCTION_KEY,
                    where=hvor,
                    evidence=_short(verdi),
                )
            )
        funn.extend(scan_text(verdi, hvor))
        funn.extend(_instruction_findings(verdi, hvor, MECH_INSTRUCTION))

    return _dedupe(funn)


def _dedupe(funn: list[Finding]) -> list[Finding]:
    """Samme mekanisme på samme sted bare én gang. Rekkefølgen beholdes."""
    sett: set[tuple[str, str]] = set()
    ut: list[Finding] = []
    for f in funn:
        key = (f.mechanism, f.where)
        if key in sett:
            continue
        sett.add(key)
        ut.append(f)
    return ut


def mechanisms_in(funn: list[Finding]) -> list[str]:
    """Mekanismene som ble funnet, uten duplikater, i stabil rekkefølge."""
    ut: list[str] = []
    for f in funn:
        if f.mechanism not in ut:
            ut.append(f.mechanism)
    return ut


def labels_in(funn: list[Finding]) -> list[str]:
    """Merkelappene, uten duplikater, i stabil rekkefølge."""
    ut: list[str] = []
    for f in funn:
        if f.label not in ut:
            ut.append(f.label)
    return ut
