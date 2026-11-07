"""Den laaste loggen: kryptert, hash-kjedet, pseudonymisert.

Alt som skjer i Lonewatch havner her:
    vault.append(kind, payload) -> LogEntry      (kryptert linje paa disk)
    vault.verify() -> int | None                 (seq til første ødelagte linje)
    pseudonymize(employee_id) -> "emp_xxxx"      (loggen ser aldri navn)
    archive_log() -> Path | None                 (flytter loggen til side, sletter aldri)

Nøkler leses fra miljøvariabler og finnes ikke i koden:
    LONEWATCH_LOG_KEY        Fernet-nøkkel for loggfilen
    LONEWATCH_PSEUDONYM_KEY  HMAC-nøkkel for pseudonymer
    python -m vault.gen_key --both     # lager begge

Ærlige begrensninger: se vault/LIMITS.md.
"""

from __future__ import annotations

from vault.after import build_after_actions, format_nok
from vault.crypto import (
    ENV_LOG_KEY,
    ENV_PSEUDONYM_KEY,
    VaultDecryptError,
    VaultError,
    VaultKeyError,
    load_log_key,
    new_log_key,
    new_pseudonym_key,
)
from vault.identity import ADMIN_ROLE, NotAuthorized, pseudonymize, register_employee, reveal
from vault.redaction import mask_recipient, redact_payload
from vault.store import DEFAULT_LOG_PATH, ENV_LOG_PATH, Vault, archive_log, log_path

__all__ = [
    "ADMIN_ROLE",
    "DEFAULT_LOG_PATH",
    "ENV_LOG_KEY",
    "ENV_LOG_PATH",
    "ENV_PSEUDONYM_KEY",
    "NotAuthorized",
    "Vault",
    "VaultDecryptError",
    "VaultError",
    "VaultKeyError",
    "archive_log",
    "build_after_actions",
    "format_nok",
    "load_log_key",
    "log_path",
    "mask_recipient",
    "new_log_key",
    "new_pseudonym_key",
    "pseudonymize",
    "redact_payload",
    "register_employee",
    "reveal",
]
