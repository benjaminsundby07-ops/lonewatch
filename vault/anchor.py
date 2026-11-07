"""Hale-anker: en liten fil som husker hvor langt loggen var.

Hash-kjeden oppdager at en linje er endret eller fjernet fra MIDTEN. Den
oppdager ikke at noen kutter bort de SISTE linjene: det som staar igjen er
fortsatt en perfekt kjede fra linje 0, og en leser som bare har filen ser
ingenting galt.

Ankeret ligger ved siden av loggen (`<logg>.head`) og sier tre ting: hvor mange
linjer loggen hadde, hva siste `seq` var, og hva siste hash var. Det er signert
med HMAC-SHA256, saa det ikke kan endres uten noekkelen.

Noekkelen er AVLEDET fra loggnoekkelen med HKDF, ikke den samme. Samme
noekkelmateriale skal ikke brukes til to ting: krypteringen beskytter innholdet,
signaturen beskytter ankeret.

Filen er ren tekst med vilje. Hele poenget er at noen skal kunne lese siste hash
og sammenligne den med noe utenfor maskinen - det er den eneste varianten som
faktisk lukker hullet. Se vault/LIMITS.md.
"""

from __future__ import annotations

import hmac
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from contracts import canonical_json

ANCHOR_SUFFIX = ".head"
ANCHOR_VERSION = 1

# Skiller signeringsnøkkelen fra krypteringsnøkkelen. Endres denne, blir alle
# eksisterende ankere ugyldige - det er med vilje.
HKDF_INFO = b"lonewatch-head-anchor-v1"

# Feltene signaturen dekker, i fast rekkefølge.
SIGNED_FIELDS = ("version", "seq", "hash", "lines", "ts")


class AnchorInvalid(RuntimeError):
    """Ankerfilen finnes, men kan ikke stoles paa."""


@dataclass(frozen=True)
class Anchor:
    """Det ankeret sier om loggen."""

    version: int
    seq: int
    hash: str
    lines: int
    ts: str


def anchor_path(log: str | Path) -> Path:
    """Ankerfilen som hører til en loggfil."""
    target = Path(log)
    return target.with_name(target.name + ANCHOR_SUFFIX)


def derive_anchor_key(log_key: bytes) -> bytes:
    """Signeringsnøkkel avledet fra loggnøkkelen. Aldri den samme."""
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=HKDF_INFO,
    ).derive(log_key)


def _signature(key: bytes, body: dict) -> str:
    payload = canonical_json({field: body[field] for field in SIGNED_FIELDS})
    return hmac.new(key, payload.encode("utf-8"), sha256).hexdigest()


def write_anchor(
    log: str | Path,
    key: bytes,
    seq: int,
    head_hash: str,
    lines: int,
    ts: datetime | None = None,
) -> Path:
    """Skriver ankeret atomisk: midlertidig fil, fsync, os.replace.

    Atomisk fordi alternativet er en halvskrevet ankerfil etter et krasj, og da
    ville verifiseringen ropt «endret» om noe som bare var avbrutt.
    """
    target = anchor_path(log)
    stamp = (ts or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
    body = {
        "version": ANCHOR_VERSION,
        "seq": int(seq),
        "hash": str(head_hash),
        "lines": int(lines),
        "ts": stamp,
    }
    body["sig"] = _signature(key, body)

    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps(body, ensure_ascii=False, sort_keys=True))
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, target)

    # Selve navnebyttet maa ogsaa naa disken, ellers kan et strømbrudd gi oss
    # den gamle filen tilbake.
    try:
        dir_fd = os.open(str(target.parent), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except OSError:  # pragma: no cover - ikke alle filsystemer tillater dette
        pass
    return target


def read_anchor(log: str | Path, key: bytes) -> Anchor | None:
    """Leser ankeret.

    None betyr at det ikke finnes. En ankerfil som finnes men ikke kan stoles
    paa gir AnchorInvalid - vi later aldri som den ikke var der.
    """
    target = anchor_path(log)
    if not target.exists():
        return None

    try:
        body = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AnchorInvalid(f"Ankerfilen {target.name} kan ikke leses: {exc}") from exc

    if not isinstance(body, dict):
        raise AnchorInvalid(f"Ankerfilen {target.name} har feil form.")
    missing = [f for f in (*SIGNED_FIELDS, "sig") if f not in body]
    if missing:
        raise AnchorInvalid(f"Ankerfilen {target.name} mangler felt: {', '.join(missing)}")

    try:
        expected = _signature(key, body)
    except (TypeError, ValueError) as exc:
        raise AnchorInvalid(f"Ankerfilen {target.name} har felt av feil type.") from exc

    if not hmac.compare_digest(expected, str(body["sig"])):
        raise AnchorInvalid(
            f"Signaturen i {target.name} stemmer ikke. Ankeret er endret, "
            "eller skrevet med en annen nøkkel."
        )

    if int(body["version"]) != ANCHOR_VERSION:
        raise AnchorInvalid(
            f"Ankerfilen {target.name} er versjon {body['version']}, vi kjenner {ANCHOR_VERSION}."
        )

    return Anchor(
        version=int(body["version"]),
        seq=int(body["seq"]),
        hash=str(body["hash"]),
        lines=int(body["lines"]),
        ts=str(body["ts"]),
    )


def move_anchor(old_log: str | Path, new_log: str | Path) -> Path | None:
    """Flytter ankeret sammen med loggen sin. Brukes naar demoen arkiverer.

    Blir ankeret liggende igjen, ville den nye, tomme loggen arvet et anker som
    sa at den skulle hatt linjer - og verifiseringen ville ropt «kuttet» om en
    logg som bare var ny.
    """
    source = anchor_path(old_log)
    if not source.exists():
        return None
    target = anchor_path(new_log)
    source.rename(target)
    return target


def delete_anchor(log: str | Path) -> bool:
    """Fjerner ankeret hvis det finnes. Returnerer om noe ble fjernet."""
    target = anchor_path(log)
    if not target.exists():
        return False
    target.unlink()
    return True
