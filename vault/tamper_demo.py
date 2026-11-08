"""«Bryt loggen»: angrip en KOPI av loggen og se at verifiseringen sier fra.

Hele poenget med en laast logg er en paastand: «ingen kan endre dette i det
skjulte». En paastand er lett aa si og vanskelig aa tro paa. Denne modulen gjoer
den etterproevbar. Den utfoerer fire angrep og lar den EKSISTERENDE
verifiseringen (`Vault.verify_detail()` i vault/store.py, og hale-ankeret i
vault/anchor.py) svare. Det skrives ingen ny, lettere sjekk her: en sjekk laget
for en demo ville kunne pynte paa svaret, og da beviser demoen ingenting.

Den ekte loggen roeres ALDRI. Loggfilen og hale-ankeret kopieres til en
midlertidig mappe, angrepet skjer paa kopien, og mappen slettes etterpaa. Vi
tar fingeravtrykk (sha256 + stoerrelse) av den ekte loggen og ankeret FOER og
ETTER, og stopper med en feil hvis noe har flyttet seg. Modulen aapner filen
den ekte loggen ligger i kun for lesing.

Fire angrep, og tre av dem skal oppdages:

  endre  Angriperen har noekkelen. Han dekrypterer én linje midt i loggen,
         skriver om utfallet (f.eks. fra «roed» til «tillatt»), krypterer paa
         nytt - men regner IKKE hash-kjeden paa nytt. Kjeden avsloerer linjen.
  slett  Én linje midt i loggen fjernes. Da staar neste linje paa feil plass,
         og kjeden avsloerer gapet.
  kutt   De siste linjene kuttes bort. Dette ser hash-kjeden IKKE: det som
         staar igjen er fortsatt en perfekt kjede fra linje 0. Hale-ankeret
         fanger det, fordi det husker hvor langt loggen var.
  full   Angriperen har noekkelen OG regner om hele kjeden OG signerer et nytt
         anker. Da sier verifiseringen at loggen er i orden - og det er det
         ærlige svaret. Loggen kan ikke oppdage dette alene. Det er ikke en
         feil i koden, det er grensen som staar i vault/LIMITS.md punkt 1 og
         12: siste hash maa skrives ned UTENFOR maskinen.

CLI:
    python -m vault.tamper_demo --attack endre
    python -m vault.tamper_demo --attack full --json
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable

from cryptography.fernet import Fernet

from contracts import GENESIS_HASH, LogEntry, make_log_entry
from vault.anchor import AnchorInvalid, anchor_path, derive_anchor_key, read_anchor, write_anchor
from vault.crypto import VaultError, decrypt_line, encrypt_line, load_log_key, validate_log_key
from vault.store import Vault, log_path

# Navnene brukeren skriver paa kommandolinjen er norske, slik resten av det
# brukervendte er. Koden bruker dem som noekler, ikke som tekst.
ATTACK_ENDRE = "endre"
ATTACK_SLETT = "slett"
ATTACK_KUTT = "kutt"
ATTACK_FULL = "full"
ATTACKS: tuple[str, ...] = (ATTACK_ENDRE, ATTACK_SLETT, ATTACK_KUTT, ATTACK_FULL)

ATTACK_TITLES: dict[str, str] = {
    ATTACK_ENDRE: "Endre innholdet i én linje midt i loggen",
    ATTACK_SLETT: "Slette én linje midt i loggen",
    ATTACK_KUTT: "Kutte bort de siste linjene",
    ATTACK_FULL: "Skrive om hele kjeden og ankeret (grensen)",
}

# Hva vi VENTER at verifiseringen skal svare. `full` staar med False fordi det
# er sant, ikke fordi noe mangler. Testene bruker den samme tabellen, slik at en
# dag der `full` plutselig blir oppdaget ogsaa er en dag der denne maa endres.
ATTACK_EXPECT_DETECTED: dict[str, bool] = {
    ATTACK_ENDRE: True,
    ATTACK_SLETT: True,
    ATTACK_KUTT: True,
    ATTACK_FULL: False,
}

# Hvor mange linjer angrepet trenger for aa vaere det det sier det er. «Midt i
# loggen» krever at det finnes en midte: med to linjer er enhver linje enten
# den foerste eller den siste.
ATTACK_MIN_LINES: dict[str, int] = {
    ATTACK_ENDRE: 3,
    ATTACK_SLETT: 3,
    ATTACK_KUTT: 2,
    ATTACK_FULL: 1,
}

# Hvor mange linjer `kutt` tar. To, fordi én kunne forveksles med et avbrudd
# mellom linjen og ankeret (LIMITS punkt 1, siste kulepunkt). To kan ikke det.
KUTT_LINES = 2

_VERDICT_NO: dict[str, str] = {"red": "rød", "block": "blokkert", "allow": "tillatt"}

# Ærlig forklaring paa hvert utfall, i klartekst. `VerifyResult.text` sier HVA
# som er galt; dette sier hva det betyr for den som ser paa.
_DETECTED_NOTE = (
    "Verifiseringen er den samme koden som kjøres ellers i Lonewatch "
    "(Vault.verify_detail). Den fikk ingen hjelp av demoen."
)

_FULL_NOTE = (
    "Dette er den dokumenterte grensen, ikke en feil.\n"
    "Angriperen hadde loggnøkkelen, regnet hash-kjeden på nytt fra linjen han "
    "endret og helt ut, og signerte et nytt hale-anker. Signeringsnøkkelen er "
    "avledet fra loggnøkkelen, så den som kan lese loggen kan også signere "
    "ankeret.\n"
    "Resultatet er en logg som er internt perfekt. Verifiseringen svarer «i "
    "orden», og det er riktig svar: alt den kan se, stemmer.\n"
    "Det som faktisk fanger dette, er siste hash skrevet ned UTENFOR maskinen - "
    "på papir, i en annen maskin, i et objektlager med object lock, eller lest "
    "opp i et møte. Sammenlign det du skrev ned med hashen under, og avviket "
    "er synlig med øyet.\n"
    "Står i vault/LIMITS.md punkt 1 og 12."
)


class TamperDemoError(RuntimeError):
    """Demoen kan ikke kjøres ærlig, så den kjører ikke.

    Brukes naar loggen mangler, er tom, er for kort for angrepet, eller ikke
    verifiserer FOER vi gjoer noe. Vi gjetter aldri og vi later aldri som.
    """


@dataclass(frozen=True)
class Fingerprint:
    """Nok til aa se om en fil har flyttet seg: navn, sha256 og stoerrelse."""

    name: str
    sha256: str
    size: int

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "sha256": self.sha256, "size": self.size}


@dataclass(frozen=True)
class TamperResult:
    """Hele svaret fra ett angrep, klart til aa vises i en terminal eller et UI."""

    attack: str
    title: str
    what_we_did: str
    detected: bool
    expected_detected: bool
    as_documented: bool
    broken_seq: int | None
    reason: str
    verify_text: str
    explanation: str
    lines_before: int
    lines_after: int
    head_hash_before: str | None
    head_hash_after: str | None
    anchor_before: dict[str, Any] | None
    anchor_after: dict[str, Any] | None
    real_log_untouched: bool
    real_log_before: dict[str, Any] = field(default_factory=dict)
    real_log_after: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Flat dict, trygg aa sende gjennom json.dumps i et endepunkt."""
        return {
            "attack": self.attack,
            "title": self.title,
            "what_we_did": self.what_we_did,
            "detected": self.detected,
            "expected_detected": self.expected_detected,
            "as_documented": self.as_documented,
            "broken_seq": self.broken_seq,
            "reason": self.reason,
            "verify_text": self.verify_text,
            "explanation": self.explanation,
            "lines_before": self.lines_before,
            "lines_after": self.lines_after,
            "head_hash_before": self.head_hash_before,
            "head_hash_after": self.head_hash_after,
            "anchor_before": self.anchor_before,
            "anchor_after": self.anchor_after,
            "real_log_untouched": self.real_log_untouched,
            "real_log_before": self.real_log_before,
            "real_log_after": self.real_log_after,
        }


# ---------------------------------------------------------------------------
# fingeravtrykk av den ekte loggen
# ---------------------------------------------------------------------------


def _fingerprint(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    data = path.read_bytes()
    return Fingerprint(name=path.name, sha256=sha256(data).hexdigest(), size=len(data)).to_dict()


def fingerprint_real(path: str | Path | None = None) -> dict[str, Any]:
    """Fingeravtrykk av loggen og ankeret, slik de ligger naa.

    Ligger utenfor `run_attack()` med vilje, slik at en test kan ta det samme
    avtrykket selv og sammenligne uten aa stole paa svaret fra demoen.
    """
    real = Path(path) if path is not None else log_path()
    return {"log": _fingerprint(real), "anchor": _fingerprint(anchor_path(real))}


def _anchor_view(log: Path, anchor_key: bytes) -> dict[str, Any] | None:
    """Det ankeret sier, som dict. En ugyldig ankerfil skjules ikke."""
    try:
        anchor = read_anchor(log, anchor_key)
    except AnchorInvalid as exc:
        return {"invalid": True, "detail": str(exc)}
    if anchor is None:
        return None
    return {"seq": anchor.seq, "hash": anchor.hash, "lines": anchor.lines, "ts": anchor.ts}


# ---------------------------------------------------------------------------
# lese og skrive kopien
# ---------------------------------------------------------------------------


def _read_lines(copy: Path) -> list[str]:
    return copy.read_text(encoding="utf-8").splitlines()


def _write_lines(copy: Path, lines: list[str]) -> None:
    copy.write_text(("\n".join(lines) + "\n") if lines else "", encoding="utf-8")


def _decrypt_entries(lines: list[str], fernet: Fernet) -> list[LogEntry]:
    """Linjene som LogEntry. Kalles bare etter at kopien har verifisert ok."""
    return [LogEntry.model_validate(json.loads(decrypt_line(fernet, line))) for line in lines]


def _serialize(entry: LogEntry) -> str:
    """Samme serialisering som Vault._write_disk, slik at kopien ser ekte ut."""
    return json.dumps(entry.model_dump(mode="json"), sort_keys=True)


# ---------------------------------------------------------------------------
# hvilken linje angriperen ville gaatt etter
# ---------------------------------------------------------------------------


def _flip_verdict(entry: LogEntry, want: str) -> str | None:
    """Skriv om utfallet i en avgjoerelse, hvis det er `want` i dag."""
    if entry.kind != "decision" or entry.payload.get("verdict") != want:
        return None
    entry.payload["verdict"] = "allow"
    return f"utfallet fra «{_VERDICT_NO[want]}» til «tillatt»"


def _flip_approved(entry: LogEntry) -> str | None:
    """Skriv om menneskets nei til et ja."""
    if entry.kind != "human" or entry.payload.get("approved") is not False:
        return None
    entry.payload["approved"] = True
    return "menneskets svar fra «ikke godkjent» til «godkjent»"


def _shrink_amount(entry: LogEntry) -> str | None:
    """Skriv ned beloepet i en forespoersel til én krone."""
    if entry.kind != "request" or not isinstance(entry.payload.get("amount"), (int, float)):
        return None
    old = entry.payload["amount"]
    entry.payload["amount"] = 1.0
    return f"beløpet fra {old} til 1"


# Rekkefoelgen er hva en angriper faktisk ville vaert ute etter, mest
# interessante foerst: et roedt varsel som ble tillatt er den dyreste loegnen
# loggen kan fortelle. Hvert ledd proeves over HELE loggen foer vi gaar videre,
# slik at vi ikke tar et beloep naermere midten framfor en roed avgjoerelse.
_TARGET_PREFERENCE: tuple[Callable[[LogEntry], str | None], ...] = (
    lambda entry: _flip_verdict(entry, "red"),
    lambda entry: _flip_verdict(entry, "block"),
    _flip_approved,
    _shrink_amount,
)


def _middle_order(count: int) -> list[int]:
    """Indekser fra midten og utover, uten foerste og siste linje.

    Angrepene heter «midt i loggen». Foerste linje er lett aa se at mangler
    (seq=0 skulle vaert der), og siste linje er halen, som er et eget angrep.

    Med faerre enn tre linjer finnes det ingen midte. Da faller vi tilbake til
    alle linjene, fortsatt naermest midten foerst. Det gjelder bare `full`, som
    er det eneste angrepet som ikke krever en midte (ATTACK_MIN_LINES).
    """
    inner = list(range(1, count - 1)) or list(range(count))
    mid = (count - 1) / 2
    return sorted(inner, key=lambda i: (abs(i - mid), i))


def _pick_target(entries: list[LogEntry]) -> tuple[int, str]:
    """Finner linjen som er verdt aa skrive om, naermest midten, og gjoer det.

    Payloaden til den valgte linjen er endret naar denne returnerer. Hvilken
    linje som velges, staar i `_TARGET_PREFERENCE`.
    """
    order = _middle_order(len(entries))
    for rewrite in _TARGET_PREFERENCE:
        for idx in order:
            change = rewrite(entries[idx])
            if change is not None:
                return idx, change

    # Ingen avgjørelse, intet menneskesvar og intet beløp midt i loggen. Vi
    # finner ikke paa at det var noe der: vi legger inn et utfall som ikke
    # fantes, og sier det rett ut.
    idx = order[0]
    entries[idx].payload["verdict"] = "allow"
    return idx, "la inn utfallet «tillatt» i en linje som ikke hadde noe utfall"


# ---------------------------------------------------------------------------
# de fire angrepene
# ---------------------------------------------------------------------------


def _attack_endre(copy: Path, fernet: Fernet, anchor_key: bytes) -> str:
    """Skriv om én linje og krypter paa nytt, men la hashene staa.

    Dette er angriperen som har noekkelen, men som ikke har tenkt paa at hver
    linje har en hash som dekker innholdet.
    """
    lines = _read_lines(copy)
    entries = _decrypt_entries(lines, fernet)
    idx, change = _pick_target(entries)

    # Bare den ene linjen skrives om. `hash` og `prev_hash` staar urørt - det
    # er hele angrepet: innholdet passer ikke lenger til hashen sin.
    lines[idx] = encrypt_line(fernet, _serialize(entries[idx]))
    _write_lines(copy, lines)
    return (
        f"Dekrypterte linje seq={entries[idx].seq} ({entries[idx].kind}), endret {change}, "
        "og krypterte den på nytt - uten å regne ut hash-kjeden på nytt. "
        "Ankeret ble ikke rørt."
    )


def _attack_slett(copy: Path, fernet: Fernet, anchor_key: bytes) -> str:
    """Fjern én linje midt i loggen helt ut av filen."""
    lines = _read_lines(copy)
    entries = _decrypt_entries(lines, fernet)
    idx = _middle_order(len(entries))[0]
    gone = entries[idx]

    del lines[idx]
    _write_lines(copy, lines)
    return (
        f"Slettet linje seq={gone.seq} ({gone.kind}) helt ut av filen. "
        f"Loggen gikk fra {len(entries)} til {len(lines)} linjer. "
        "Ankeret ble ikke rørt."
    )


def _attack_kutt(copy: Path, fernet: Fernet, anchor_key: bytes) -> str:
    """Kutt bort de siste linjene. Det hash-kjeden alene ikke kan se."""
    lines = _read_lines(copy)
    cut = min(KUTT_LINES, len(lines) - 1)
    kept = lines[:-cut]
    _write_lines(copy, kept)
    return (
        f"Kuttet de {cut} siste linjene bort. Loggen gikk fra {len(lines)} til "
        f"{len(kept)} linjer. Ankeret ble ikke rørt - og det er ankeret som ser "
        "dette, for det som står igjen er fortsatt en perfekt kjede fra linje 0."
    )


def _attack_full(copy: Path, fernet: Fernet, anchor_key: bytes) -> str:
    """Hele kjeden og ankeret regnet om. Grensen, utfoert.

    Angriperen har loggnoekkelen. Da har han ogsaa signeringsnoekkelen til
    ankeret, fordi den er avledet fra den samme noekkelen (LIMITS punkt 1).
    """
    lines = _read_lines(copy)
    entries = _decrypt_entries(lines, fernet)

    idx, change = _pick_target(entries)

    # Fra den endrede linjen og ut: ny hash hver gang, med forrige hash som
    # peker. Resultatet er en kjede som er like gyldig som den ekte.
    rebuilt: list[LogEntry] = list(entries[:idx])
    prev = rebuilt[-1].hash if rebuilt else GENESIS_HASH
    for entry in entries[idx:]:
        fresh = make_log_entry(
            seq=entry.seq, ts=entry.ts, kind=entry.kind, payload=entry.payload, prev_hash=prev
        )
        rebuilt.append(fresh)
        prev = fresh.hash

    _write_lines(copy, [encrypt_line(fernet, _serialize(entry)) for entry in rebuilt])

    # Og ankeret signeres paa nytt, slik at det peker paa den nye halen.
    last = rebuilt[-1]
    write_anchor(copy, anchor_key, last.seq, last.hash, len(rebuilt), ts=last.ts)
    return (
        f"Dekrypterte hele loggen, endret {change} på linje seq={rebuilt[idx].seq} "
        f"({rebuilt[idx].kind}), regnet hash-kjeden på nytt fra den linjen og helt ut, "
        "krypterte alt på nytt, og signerte et nytt hale-anker med nøkkelen som er "
        "avledet fra loggnøkkelen."
    )


_ATTACK_FUNCS: dict[str, Callable[[Path, Fernet, bytes], str]] = {
    ATTACK_ENDRE: _attack_endre,
    ATTACK_SLETT: _attack_slett,
    ATTACK_KUTT: _attack_kutt,
    ATTACK_FULL: _attack_full,
}


# ---------------------------------------------------------------------------
# kjoeringen
# ---------------------------------------------------------------------------


def _require_log(real: Path, attack: str) -> int:
    """Feiler lukket hvis loggen ikke finnes, er tom, eller er for kort."""
    if not real.exists():
        raise TamperDemoError(
            f"Loggen {real} finnes ikke. «Bryt loggen» angriper en kopi av en ekte "
            "logg, og det finnes ingen å kopiere. Kjør demoen først."
        )
    try:
        lines = [line for line in real.read_text(encoding="utf-8").splitlines() if line.strip()]
    except OSError as exc:
        raise TamperDemoError(f"Loggen {real} kan ikke leses: {exc}") from exc

    if not lines:
        raise TamperDemoError(
            f"Loggen {real} er tom. Det er ingenting å bryte. Kjør demoen først."
        )

    needed = ATTACK_MIN_LINES[attack]
    if len(lines) < needed:
        raise TamperDemoError(
            f"Loggen {real} har {len(lines)} linje(r). Angrepet «{attack}» trenger minst "
            f"{needed} for å være det det sier det er, så vi gjør det ikke."
        )
    return len(lines)


def run_attack(
    attack: str,
    path: str | Path | None = None,
    key: bytes | str | None = None,
) -> TamperResult:
    """Utfoer ett angrep paa en KOPI av loggen og la verifiseringen svare.

    attack: «endre», «slett», «kutt» eller «full».
    path:   loggfilen. Standard: LONEWATCH_LOG_PATH, ellers lonewatch_log.jsonl.
    key:    Fernet-noekkel. Standard: LONEWATCH_LOG_KEY.

    Den ekte loggen og det ekte ankeret roeres aldri. Kaster TamperDemoError
    hvis demoen ikke kan kjoeres ærlig.
    """
    if attack not in ATTACKS:
        raise TamperDemoError(
            f"Ukjent angrep «{attack}». Gyldige: {', '.join(ATTACKS)}."
        )

    real = Path(path) if path is not None else log_path()
    try:
        raw_key = (
            load_log_key()
            if key is None
            else validate_log_key(key.encode("utf-8") if isinstance(key, str) else key)
        )
    except VaultError as exc:
        # Vi pakker den ikke bort - vi stopper, med samme beskjed.
        raise TamperDemoError(str(exc)) from exc

    _require_log(real, attack)
    fernet = Fernet(raw_key)
    anchor_key = derive_anchor_key(raw_key)

    real_before = fingerprint_real(real)

    workdir = Path(tempfile.mkdtemp(prefix="lonewatch-bryt-"))
    try:
        # Samme filnavn som den ekte, slik at ankerstien (<logg>.head) blir
        # regnet ut paa noeyaktig samme maate.
        copy = workdir / real.name
        shutil.copy2(real, copy)
        source_anchor = anchor_path(real)
        if source_anchor.exists():
            shutil.copy2(source_anchor, anchor_path(copy))

        # FOER: kopien skal stemme. Gjoer den ikke det, er det den ekte loggen
        # som har et problem, og da ville demoen tatt æren for noe andre gjorde.
        before = Vault(path=copy, key=raw_key).verify_detail()
        if not before.ok:
            raise TamperDemoError(
                "Kopien av loggen stemmer ikke FØR angrepet "
                f"({before.reason}: {before.text}). Da kan ikke demoen vise noe ærlig, "
                "så den stopper. Sjekk den ekte loggen."
            )
        anchor_before = _anchor_view(copy, anchor_key)

        what_we_did = _ATTACK_FUNCS[attack](copy, fernet, anchor_key)

        # ETTER: en fersk leser som bare har filen. En ny Vault leser og
        # dekrypterer alt fra disk, saa ingenting fra foer henger igjen i minnet.
        after = Vault(path=copy, key=raw_key).verify_detail()
        anchor_after = _anchor_view(copy, anchor_key)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    real_after = fingerprint_real(real)
    untouched = real_after == real_before
    if not untouched:
        # Skal aldri skje: vi aapner den ekte loggen bare for lesing. Men hvis
        # det skjer, er det det viktigste denne modulen kan si.
        raise TamperDemoError(
            f"Den ekte loggen {real} eller ankeret er ENDRET under demoen. "
            f"Før: {real_before}. Etter: {real_after}. Dette er en feil i "
            "vault/tamper_demo.py og må rettes før demoen brukes."
        )

    detected = not after.ok
    expected = ATTACK_EXPECT_DETECTED[attack]
    explanation = after.text if detected else _FULL_NOTE if attack == ATTACK_FULL else after.text

    return TamperResult(
        attack=attack,
        title=ATTACK_TITLES[attack],
        what_we_did=what_we_did,
        detected=detected,
        expected_detected=expected,
        as_documented=detected == expected,
        broken_seq=after.broken_seq,
        reason=after.reason,
        verify_text=after.text,
        explanation=explanation,
        lines_before=before.lines,
        lines_after=after.lines,
        head_hash_before=before.head_hash,
        head_hash_after=after.head_hash,
        anchor_before=anchor_before,
        anchor_after=anchor_after,
        real_log_untouched=untouched,
        real_log_before=real_before,
        real_log_after=real_after,
    )


def run_all(
    path: str | Path | None = None, key: bytes | str | None = None
) -> list[TamperResult]:
    """Alle fire angrepene, i rekkefoelge. Hvert paa sin egen kopi."""
    return [run_attack(attack, path=path, key=key) for attack in ATTACKS]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _short(value: str | None, chars: int = 16) -> str:
    """Hash forkortet, slik at den kan leses opp. Full verdi finnes i --json."""
    if not value:
        return "(ingen)"
    return value[:chars] + "…" if len(value) > chars else value


def _anchor_line(view: dict[str, Any] | None) -> str:
    if view is None:
        return "(ingen ankerfil)"
    if view.get("invalid"):
        return f"UGYLDIG: {view['detail']}"
    return f"{view['lines']} linjer, siste seq={view['seq']}, hash={_short(view['hash'])}"


def format_result(result: TamperResult) -> str:
    """Resultatet som noe et menneske kan lese i en terminal."""
    out: list[str] = []
    out.append("=" * 72)
    out.append(f"BRYT LOGGEN - angrep «{result.attack}»")
    out.append(result.title)
    out.append("=" * 72)
    out.append("")
    out.append("Dette gjorde vi (på en KOPI, aldri den ekte loggen):")
    for line in result.what_we_did.split("\n"):
        out.append(f"  {line}")
    out.append("")

    if result.detected:
        out.append("  >>> OPPDAGET <<<")
        out.append("")
        out.append(f"  Verifiseringen sier: {result.verify_text}")
        if result.broken_seq is not None:
            out.append(f"  Linje som ble pekt ut: seq={result.broken_seq}")
        out.append(f"  Årsakskode: {result.reason}")
        out.append("")
        for line in _DETECTED_NOTE.split("\n"):
            out.append(f"  {line}")
    else:
        out.append("  >>> IKKE OPPDAGET - og det er det ærlige svaret <<<")
        out.append("")
        out.append(f"  Verifiseringen sier: {result.verify_text}")
        out.append(f"  Årsakskode: {result.reason}")
        out.append("")
        for line in result.explanation.split("\n"):
            out.append(f"  {line}")

    out.append("")
    out.append("Tall før og etter:")
    out.append(f"  Linjer:       {result.lines_before} -> {result.lines_after}")
    out.append(
        f"  Siste hash:   {_short(result.head_hash_before)} -> {_short(result.head_hash_after)}"
    )
    out.append(f"  Anker før:    {_anchor_line(result.anchor_before)}")
    out.append(f"  Anker etter:  {_anchor_line(result.anchor_after)}")
    out.append("")

    forventet = "som dokumentert" if result.as_documented else "IKKE som dokumentert"
    out.append(
        f"Forventet oppdaget: {'ja' if result.expected_detected else 'nei'}. "
        f"Faktisk: {'ja' if result.detected else 'nei'}. ({forventet})"
    )

    log_fp = result.real_log_before.get("log") or {}
    anchor_fp = result.real_log_before.get("anchor") or {}
    status = "uendret" if result.real_log_untouched else "ENDRET - FEIL"
    out.append("")
    out.append(f"Den ekte loggen: {status}.")
    out.append(
        f"  {log_fp.get('name', '(mangler)')}  "
        f"sha256={_short(log_fp.get('sha256'))}  {log_fp.get('size', 0)} byte"
    )
    out.append(
        f"  {anchor_fp.get('name', '(ingen anker)')}  "
        f"sha256={_short(anchor_fp.get('sha256'))}  {anchor_fp.get('size', 0)} byte"
    )
    out.append("=" * 72)
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m vault.tamper_demo",
        description=(
            "Bryt loggen: angrip en kopi av den låste loggen og se at den "
            "eksisterende verifiseringen sier fra. Den ekte loggen røres aldri."
        ),
    )
    parser.add_argument(
        "--attack",
        choices=(*ATTACKS, "alle"),
        default=ATTACK_ENDRE,
        help="hvilket angrep. «alle» kjører de fire etter hverandre.",
    )
    parser.add_argument(
        "--path",
        default=None,
        help="loggfilen. Standard: LONEWATCH_LOG_PATH, ellers lonewatch_log.jsonl.",
    )
    parser.add_argument("--json", action="store_true", help="skriv rått JSON i stedet for tekst.")
    args = parser.parse_args(argv)

    try:
        results = (
            run_all(path=args.path)
            if args.attack == "alle"
            else [run_attack(args.attack, path=args.path)]
        )
    except TamperDemoError as exc:
        # Feiler lukket: ingen halvveis demo, ingen gjetting.
        print(f"Stoppet: {exc}", file=sys.stderr)
        return 2

    if args.json:
        payload = [result.to_dict() for result in results]
        print(json.dumps(payload if len(payload) > 1 else payload[0], ensure_ascii=False, indent=2))
        return 0

    print("\n\n".join(format_result(result) for result in results))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI
    raise SystemExit(main())
