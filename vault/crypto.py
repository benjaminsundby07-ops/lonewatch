"""Nøkler og kryptering for loggen.

Nøkkelen leses ALLTID fra miljøvariabel. Det finnes ingen stille standardnøkkel:
mangler nøkkelen, stopper vi med en tydelig feilmelding.
"""

from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken

ENV_LOG_KEY = "LONEWATCH_LOG_KEY"
ENV_PSEUDONYM_KEY = "LONEWATCH_PSEUDONYM_KEY"


class VaultError(RuntimeError):
    """Alt som går galt i vault."""


class VaultKeyError(VaultError):
    """Nøkkelen mangler eller er ugyldig."""


class VaultDecryptError(VaultError):
    """En linje på disk kunne ikke dekrypteres med nøkkelen vi har."""


def _require_env(name: str, hint: str) -> str:
    raw = os.environ.get(name, "").strip()
    if not raw:
        raise VaultKeyError(
            f"Miljøvariabelen {name} mangler. Loggen kan ikke åpnes uten nøkkel.\n"
            f"Lag en nøkkel slik:  {hint}"
        )
    return raw


def load_log_key() -> bytes:
    """Fernet-nøkkel for loggfilen, fra LONEWATCH_LOG_KEY."""
    raw = _require_env(ENV_LOG_KEY, f"export {ENV_LOG_KEY}=$(python -m vault.gen_key)")
    return validate_log_key(raw.encode("utf-8"))


def validate_log_key(key: bytes) -> bytes:
    """Sjekker at nøkkelen faktisk er en Fernet-nøkkel før vi bruker den."""
    try:
        Fernet(key)
    except Exception as exc:  # ugyldig lengde eller ugyldig base64
        raise VaultKeyError(
            f"{ENV_LOG_KEY} er ikke en gyldig Fernet-nøkkel (32 byte, urlsafe base64). "
            f"Lag en ny med: python -m vault.gen_key"
        ) from exc
    return key


def new_log_key() -> str:
    """Ny tilfeldig Fernet-nøkkel som tekst."""
    return Fernet.generate_key().decode("ascii")


def load_pseudonym_key() -> bytes:
    """HMAC-nøkkel for pseudonymer, fra LONEWATCH_PSEUDONYM_KEY.

    Her er alt som er lenger enn 16 tegn greit; det er en HMAC-nøkkel, ikke Fernet.
    """
    raw = _require_env(
        ENV_PSEUDONYM_KEY, f"export {ENV_PSEUDONYM_KEY}=$(python -m vault.gen_key --pseudonym)"
    )
    if len(raw) < 16:
        raise VaultKeyError(
            f"{ENV_PSEUDONYM_KEY} er for kort (minst 16 tegn). "
            f"Lag en ny med: python -m vault.gen_key --pseudonym"
        )
    return raw.encode("utf-8")


def new_pseudonym_key() -> str:
    """Ny tilfeldig HMAC-nøkkel som hex-tekst."""
    return os.urandom(32).hex()


def table_fernet() -> Fernet:
    """Fernet for navn-til-kode-tabellen, utledet av pseudonym-nøkkelen.

    Utledning: urlsafe_base64(sha256(pseudonym_key)). Da trenger admin bare én nøkkel
    for både pseudonymisering og tabellen.
    """
    derived = hashlib.sha256(load_pseudonym_key()).digest()
    return Fernet(base64.urlsafe_b64encode(derived))


def encrypt_line(fernet: Fernet, plaintext: str) -> str:
    """Én linje klartekst -> én linje chiffertekst (uten linjeskift)."""
    return fernet.encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_line(fernet: Fernet, token: str) -> str:
    """Én linje chiffertekst -> klartekst. Feiler hvis linjen er endret."""
    try:
        return fernet.decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError, ValueError) as exc:
        raise VaultDecryptError("Linjen kunne ikke dekrypteres (endret, eller feil nøkkel).") from exc
