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

«Bryt loggen» ligger i vault.tamper_demo og importeres derfra, ikke herfra:
    from vault.tamper_demo import run_attack
    run_attack("endre" | "slett" | "kutt" | "full") -> TamperResult
    python -m vault.tamper_demo --attack kutt
Den angriper en KOPI; den ekte loggen roeres aldri. `full` blir ærlig IKKE
oppdaget - se LIMITS punkt 12. Den er ikke re-eksportert her, fordi en pakke som
importerer sin egen CLI-modul faar den kjoert to ganger av `python -m`.

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
from vault import anchor
from vault.anchor import AnchorInvalid, anchor_path, read_anchor, write_anchor
from vault.store import (
    DEFAULT_LOG_PATH,
    ENV_LOG_PATH,
    ENV_REDACT,
    LogLock,
    LogLocked,
    Vault,
    VerifyResult,
    acquire_log_lock,
    archive_log,
    lock_path,
    log_path,
    redact_enabled,
)

__all__ = [
    "ADMIN_ROLE",
    "DEFAULT_LOG_PATH",
    "ENV_LOG_KEY",
    "ENV_LOG_PATH",
    "ENV_REDACT",
    "ENV_PSEUDONYM_KEY",
    "LogLock",
    "LogLocked",
    "NotAuthorized",
    "Vault",
    "VaultDecryptError",
    "VaultError",
    "VaultKeyError",
    "VerifyResult",
    "AnchorInvalid",
    "anchor",
    "anchor_path",
    "read_anchor",
    "write_anchor",
    "acquire_log_lock",
    "archive_log",
    "build_after_actions",
    "format_nok",
    "load_log_key",
    "lock_path",
    "log_path",
    "mask_recipient",
    "new_log_key",
    "new_pseudonym_key",
    "pseudonymize",
    "redact_enabled",
    "redact_payload",
    "register_employee",
    "reveal",
]
