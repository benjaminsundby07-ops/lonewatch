"""Loggen: en fil som bare vokser, kryptert linje for linje.

Hver linje er én LogEntry fra contracts, serialisert til JSON og deretter kryptert med
Fernet FØR den skrives. Hash-kjeden ligger inne i klartekstet, saa den som har nøkkelen
kan bevise at ingen linje er endret, og den som ikke har nøkkelen ser ingenting.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows har ikke fcntl
    fcntl = None

from cryptography.fernet import Fernet

from contracts import GENESIS_HASH, LogEntry, LogKind, compute_entry_hash, make_log_entry, verify_chain
from vault.anchor import AnchorInvalid, derive_anchor_key, move_anchor, read_anchor, write_anchor
from vault.crypto import VaultDecryptError, decrypt_line, encrypt_line, load_log_key, validate_log_key
from vault.redaction import redact_payload

ENV_LOG_PATH = "LONEWATCH_LOG_PATH"
DEFAULT_LOG_PATH = Path("lonewatch_log.jsonl")

# Dataminimering. `Vault(redact=...)` er fortsatt av som standard, slik at den
# som lager en Vault direkte faar full payload og ingen overraskelser. Men
# DEMOEN (ui/ og run_demo.py) spør denne, og den er PÅ med mindre noen sier noe
# annet: en logg skal ikke inneholde mer persondata enn den trenger.
#
# Hvorfor en miljøvariabel og ikke bare hardkodet på: under en demo er det verdt
# noe å kunne slå den av og vise forskjellen på den samme loggen med og uten
# minimering. `LONEWATCH_REDACT=0` gjør det.
ENV_REDACT = "LONEWATCH_REDACT"
_REDACT_OFF = {"0", "false", "no", "nei", "off", "av"}


def redact_enabled() -> bool:
    """Skal demoen minimere det den logger? Paa med mindre noen slaar det av."""
    raw = os.environ.get(ENV_REDACT)
    if raw is None:
        return True
    return raw.strip().lower() not in _REDACT_OFF


def log_path() -> Path:
    """Hvor loggfilen ligger. Kan overstyres med LONEWATCH_LOG_PATH."""
    return Path(os.environ.get(ENV_LOG_PATH) or DEFAULT_LOG_PATH)


def _utc(ts: datetime | None) -> datetime:
    """Alt lagres i UTC, slik at en linje ser likt ut før og etter en tur om disk."""
    if ts is None:
        return datetime.now(timezone.utc)
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


class LogLocked(RuntimeError):
    """Noen andre holder allerede loggen. Vi roerer den ikke."""


class LogLock:
    """Enerett til loggfilen saa lenge dette objektet lever.

    Hvorfor: `Vault` regner `seq` ut fra det den har i minnet. To prosesser mot
    samme fil skriver derfor over hverandres linjer og knekker kjeden
    (LIMITS punkt 6). Og siden nullstilling gir loggen nytt navn, kan en prosess
    nr. 2 rekke aa arkivere loggen en kjoerende prosess fortsatt skriver til -
    det var F4 i docs/REDTEAM.md.

    Laasen ligger paa en egen `.lock`-fil ved siden av loggen, ikke paa loggen
    selv: loggfilen bytter navn naar den arkiveres, og en laas foelger filen,
    ikke navnet.

    Laasen varer bare saa lenge prosessen lever. Dreper du prosessen, slipper
    operativsystemet den. Den beskytter derfor mot to kjoerende Lonewatch, ikke
    mot en fil som ligger paa et delt disk-omraade.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._fh = None
        if fcntl is None:  # pragma: no cover - bare paa Windows
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        fh = path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            fh.close()
            raise LogLocked(
                f"Loggen {path.name.removesuffix('.lock')} er allerede i bruk av en "
                "annen Lonewatch. Stopp den som kjorer forst - vi rorer ikke loggen na."
            ) from exc
        fh.seek(0)
        fh.truncate()
        fh.write(f"{os.getpid()}\n")
        fh.flush()
        self._fh = fh

    def release(self) -> None:
        """Slipper laasen. Trygt aa kalle flere ganger."""
        fh, self._fh = self._fh, None
        if fh is None:
            return
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except OSError:  # pragma: no cover - filen kan vaere borte
            pass
        fh.close()

    def __enter__(self) -> "LogLock":
        return self

    def __exit__(self, *exc_info) -> None:
        self.release()


def lock_path(path: str | Path | None = None) -> Path:
    """Laasefilen som hoerer til en loggfil."""
    target = Path(path) if path is not None else log_path()
    return target.with_name(target.name + ".lock")


def acquire_log_lock(path: str | Path | None = None) -> LogLock:
    """Tar enerett til loggen, eller kaster LogLocked.

    Kall denne FOER archive_log(): en prosess som ikke faar lov til aa kjoere
    skal ikke rekke aa flytte loggen til en som kjoerer.
    """
    return LogLock(lock_path(path))


def archive_log(path: str | Path | None = None, ts: datetime | None = None) -> Path | None:
    """Flytter loggfilen til side slik at neste Vault() starter paa en tom logg.

    Brukes naar demoen nullstilles: en logg som bare vokser kan ikke tømmes,
    saa i stedet begynner vi en ny fil. Den gamle blir liggende under nytt navn
    (lonewatch_log.<tidsstempel>.jsonl), slik at ingenting forsvinner i det skjulte.

    Returnerer stien den gamle loggen ble flyttet til, eller None hvis det ikke
    fantes noen logg aa ta vare paa.
    """
    target = Path(path) if path is not None else log_path()
    if not target.exists() or target.stat().st_size == 0:
        return None

    stamp = _utc(ts).strftime("%Y%m%dT%H%M%SZ")
    # Flere nullstillinger samme sekund skal ikke skrive over hverandre.
    candidate = target.with_suffix(f".{stamp}{target.suffix}")
    counter = 2
    while candidate.exists():
        candidate = target.with_suffix(f".{stamp}-{counter}{target.suffix}")
        counter += 1

    target.rename(candidate)
    # Ankeret maa følge loggen sin. Blir det liggende igjen, ville den nye,
    # tomme loggen arvet et anker som sa at den skulle hatt linjer.
    move_anchor(target, candidate)
    return candidate


# Hvorfor verifiseringen svarte som den gjorde. `verify()` gir bare et
# sekvensnummer; dette er for den som skal vise noe til et menneske.
VERIFY_TEXTS: dict[str, str] = {
    "ok": "Loggen stemmer. {lines} linjer, ingen er endret.",
    "ok_empty": "Loggen er tom.",
    "ok_one_unanchored": (
        "Loggen stemmer. {lines} linjer. Siste linje har ikke rukket inn i "
        "hale-ankeret ennå - det skjer hvis noe stoppet mellom de to skrivingene."
    ),
    "unreadable_line": "Linje {seq} kan ikke leses med denne nøkkelen.",
    "chain": "Loggen er endret. Første ødelagte linje er seq={seq}.",
    "memory_vs_disk": "Loggen på disk er ikke den vi har skrevet. Første avvik er seq={seq}.",
    "log_truncated": (
        "Loggen er kortere enn hale-ankeret sier. {anchor_lines} linjer skulle vært der, "
        "{lines} er igjen: noen har kuttet halen."
    ),
    "unanchored_lines": (
        "{extra} linjer er lagt til uten at hale-ankeret ble oppdatert. "
        "Første linje uten dekning er seq={seq}."
    ),
    "anchor_missing": (
        "Hale-ankeret mangler, men loggen har {lines} linjer. Enten er ankeret slettet, "
        "eller så er loggen laget før ankeret fantes. Kjeden stemmer, men vi kan ikke "
        "se om noen har kuttet halen."
    ),
    "anchor_bad_signature": "Hale-ankeret kan ikke stoles på: {detail}",
    "anchor_hash_mismatch": (
        "Hale-ankeret peker på en annen siste linje enn den som ligger der. "
        "Halen er byttet ut. Forventet hash fra seq={seq}."
    ),
}


@dataclass(frozen=True)
class VerifyResult:
    """Hele svaret fra en verifisering, ikke bare sekvensnummeret.

    `Vault.verify()` returnerer fortsatt `int | None` slik CLAUDE.md krever.
    Denne er for den som skal vise noe: den sier HVORFOR, og den gir siste hash
    slik at et menneske kan sammenligne den med noe utenfor maskinen.
    """

    ok: bool
    broken_seq: int | None
    reason: str
    text: str
    lines: int
    head_hash: str | None


class Vault:
    """Logg som bare vokser. Hver linje peker paa forrige via hash.

    path:   loggfilen. Standard: LONEWATCH_LOG_PATH, ellers lonewatch_log.jsonl.
    key:    Fernet-nøkkel. Standard: LONEWATCH_LOG_KEY (mangler den, stopper vi).
    redact: True = kjør payload gjennom redact_payload() før den logges.
    """

    def __init__(
        self,
        path: str | Path | None = None,
        key: bytes | str | None = None,
        *,
        redact: bool = False,
    ) -> None:
        self._path = Path(path) if path is not None else log_path()
        if key is None:
            raw_key = load_log_key()
        else:
            raw_key = validate_log_key(key.encode("utf-8") if isinstance(key, str) else key)
        self._fernet = Fernet(raw_key)
        # Signeringsnøkkelen til hale-ankeret er AVLEDET fra loggnøkkelen, ikke
        # den samme. Se vault/anchor.py.
        self._anchor_key = derive_anchor_key(raw_key)
        self._redact = redact
        self._entries: list[LogEntry] = self._read_disk()[0]

    # ---------- grensesnittet resten av Lonewatch bruker ----------

    def append(self, kind: LogKind, payload: dict[str, Any], ts: datetime | None = None) -> LogEntry:
        """Legger en ny linje nederst, skriver den kryptert til disk, returnerer den."""
        body = redact_payload(kind, payload) if self._redact else payload
        entry = make_log_entry(
            seq=len(self._entries),
            ts=_utc(ts),
            kind=kind,
            payload=json.loads(json.dumps(body, default=str)),
            prev_hash=self._entries[-1].hash if self._entries else GENESIS_HASH,
        )
        self._write_disk(entry)
        self._entries.append(entry)
        # Ankeret skrives ETTER linjen, med vilje. Krasjer vi imellom, er loggen
        # én linje foran ankeret, og det kan vi kjenne igjen som et avbrudd.
        # Motsatt rekkefølge ville gitt et anker som peker på en linje som ikke
        # finnes - og det er ikke til å skille fra at noen har kuttet halen.
        self._write_anchor()
        return entry

    def _write_anchor(self) -> None:
        if not self._entries:
            return
        last = self._entries[-1]
        write_anchor(
            self._path, self._anchor_key, last.seq, last.hash, len(self._entries), ts=last.ts
        )

    def head_hash(self) -> str | None:
        """Hashen til siste linje, eller None hvis loggen er tom.

        Dette er tallet som er verdt å vise fram: skriver du det ned et sted
        utenfor maskinen, kan du siden se om loggen er den samme.
        """
        return self._entries[-1].hash if self._entries else None

    def verify(self) -> int | None:
        """seq til første ødelagte linje, ellers None.

        Grensesnittet i CLAUDE.md. `verify_detail()` gir det samme svaret med
        en forklaring og siste hash.
        """
        return self.verify_detail().broken_seq

    def verify_detail(self) -> VerifyResult:
        """Hele svaret: om det stemmer, hvorfor, hvor mange linjer, siste hash.

        Leser og dekrypterer hele filen paa nytt og sjekker, i denne rekkefølgen:

        1. en linje som ikke kan dekrypteres
        2. en kjede som ikke stemmer (verify_chain)
        3. at det vi har i minnet er likt det som staar paa disk
        4. hale-ankeret: at ingen har kuttet bort de SISTE linjene

        Rekkefølgen er med vilje. De tre første peker paa NØYAKTIG hvilken linje
        som er gal. Ankeret vet bare at halen er feil, saa det svarer sist - da
        fanger det bare det de andre sa var greit.
        """
        disk, first_unreadable = self._read_disk()

        if first_unreadable is not None:
            # En linje som ikke kan dekrypteres: posisjonen i filen er seq'en den skulle hatt.
            broken_chain = verify_chain(disk[:first_unreadable])
            seq = broken_chain if broken_chain is not None else first_unreadable
            reason = "chain" if broken_chain is not None else "unreadable_line"
            return self._fail(reason, seq, disk)

        broken = verify_chain(disk)
        if broken is not None:
            return self._fail("chain", broken, disk)

        for entry in self._entries:
            if entry.seq >= len(disk) or disk[entry.seq].hash != entry.hash:
                return self._fail("memory_vs_disk", entry.seq, disk)
            if entry.hash != compute_entry_hash(
                entry.seq, entry.ts, entry.kind, entry.payload, entry.prev_hash
            ):
                return self._fail("memory_vs_disk", entry.seq, disk)

        return self._check_anchor(disk)

    # ---------- hale-anker ----------

    def _check_anchor(self, disk: list[LogEntry]) -> VerifyResult:
        """Siste sjekk: har noen kuttet bort halen?

        Hash-kjeden kan ikke se det. Fjerner du de tre siste linjene, er resten
        fortsatt en perfekt kjede fra linje 0.
        """
        try:
            anchor = read_anchor(self._path, self._anchor_key)
        except AnchorInvalid as exc:
            return self._fail("anchor_bad_signature", 0, disk, detail=str(exc))

        if anchor is None:
            if not disk:
                return self._ok("ok_empty", disk)
            return self._fail("anchor_missing", 0, disk)

        if len(disk) < anchor.lines:
            # Ankeret kan ALDRI vaere foran loggen av seg selv: det skrives
            # etter linjen. Er det foran, mangler det linjer.
            return self._fail("log_truncated", len(disk), disk, anchor_lines=anchor.lines)

        extra = len(disk) - anchor.lines
        if extra > 1:
            # Hver append skriver ankeret, saa mer enn én uanker-linje er ikke
            # et avbrudd - det er linjer som er lagt til utenom.
            return self._fail("unanchored_lines", anchor.lines, disk, extra=extra)

        if anchor.seq >= len(disk) or disk[anchor.seq].hash != anchor.hash:
            return self._fail("anchor_hash_mismatch", anchor.seq, disk)

        if extra == 1:
            # Krasj mellom linjen og ankeret. Kjeden over har alt bekreftet at
            # den ekstra linjen henger riktig paa, saa dette er trygt.
            return self._ok("ok_one_unanchored", disk)

        return self._ok("ok", disk)

    # ---------- svar ----------

    def _ok(self, reason: str, disk: list[LogEntry]) -> VerifyResult:
        head = disk[-1].hash if disk else None
        return VerifyResult(
            ok=True,
            broken_seq=None,
            reason=reason,
            text=VERIFY_TEXTS[reason].format(lines=len(disk)),
            lines=len(disk),
            head_hash=head,
        )

    def _fail(self, reason: str, seq: int, disk: list[LogEntry], **extra: Any) -> VerifyResult:
        head = disk[-1].hash if disk else None
        return VerifyResult(
            ok=False,
            broken_seq=seq,
            reason=reason,
            text=VERIFY_TEXTS[reason].format(seq=seq, lines=len(disk), **extra),
            lines=len(disk),
            head_hash=head,
        )

    def entries(self) -> list[LogEntry]:
        """Kopi av loggen, slik at ingen kan endre den innenfra."""
        return list(self._entries)

    def __len__(self) -> int:
        return len(self._entries)

    @property
    def path(self) -> Path:
        return self._path

    # ---------- disk ----------

    def _write_disk(self, entry: LogEntry) -> None:
        if self._path.parent and not self._path.parent.exists():
            self._path.parent.mkdir(parents=True, exist_ok=True)
        line = encrypt_line(self._fernet, json.dumps(entry.model_dump(mode="json"), sort_keys=True))
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
            fh.flush()
            os.fsync(fh.fileno())

    def _read_disk(self) -> tuple[list[LogEntry], int | None]:
        """(linjene vi klarte aa lese, posisjonen til første uleselige linje)."""
        if not self._path.exists():
            return [], None

        out: list[LogEntry] = []
        with self._path.open("r", encoding="utf-8") as fh:
            for i, raw in enumerate(fh):
                raw = raw.strip()
                if not raw:
                    return out, i
                try:
                    out.append(LogEntry.model_validate(json.loads(decrypt_line(self._fernet, raw))))
                except (VaultDecryptError, json.JSONDecodeError, ValueError):
                    return out, i
        return out, None
