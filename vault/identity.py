"""Pseudonymisering: loggen ser aldri navnet paa en ansatt.

pseudonymize() er en enveis funksjon (HMAC-SHA256 med hemmelig nøkkel). Den skriver
ingenting noe sted. Skal noen kunne gaa tilbake fra kode til person, maa personen
først registreres i navn-til-kode-tabellen, og tabellen leses bare av reveal()
med role == "admin".
"""

from __future__ import annotations

import hmac
import json
import os
from hashlib import sha256
from pathlib import Path

from vault.crypto import VaultError, decrypt_line, encrypt_line, load_pseudonym_key, table_fernet

ENV_TABLE_PATH = "LONEWATCH_PSEUDONYM_TABLE"
DEFAULT_TABLE_PATH = Path("lonewatch_pseudonyms.enc")
ADMIN_ROLE = "admin"


class NotAuthorized(VaultError):
    """Noen uten admin-rolle prøvde aa slaa opp et pseudonym."""


def table_path() -> Path:
    """Hvor navn-til-kode-tabellen ligger."""
    return Path(os.environ.get(ENV_TABLE_PATH) or DEFAULT_TABLE_PATH)


def pseudonymize(employee_id: str) -> str:
    """Gir 'emp_xxxx'. Samme ansatt gir alltid samme pseudonym.

    4 hex fra HMAC-SHA256 med nøkkel fra LONEWATCH_PSEUDONYM_KEY. Uten nøkkelen kan
    ingen regne seg frem til pseudonymet, og pseudonymet kan ikke regnes tilbake.
    """
    digest = hmac.new(load_pseudonym_key(), employee_id.encode("utf-8"), sha256).hexdigest()
    return f"emp_{digest[:4]}"


def _load_table() -> dict[str, str]:
    """Leser og dekrypterer tabellen. Bare reveal() og register_employee() kaller denne."""
    path = table_path()
    if not path.exists():
        return {}
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        return {}
    data = json.loads(decrypt_line(table_fernet(), raw))
    return {str(k): str(v) for k, v in data.items()}


def _save_table(table: dict[str, str]) -> None:
    path = table_path()
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(encrypt_line(table_fernet(), json.dumps(table, sort_keys=True)), encoding="utf-8")


def register_employee(employee_id: str) -> str:
    """Legger en ansatt i navn-til-kode-tabellen og returnerer pseudonymet.

    Dette er et admin-steg (onboarding), ikke noe som skjer i den vanlige flyten.
    """
    pseudonym = pseudonymize(employee_id)
    table = _load_table()
    table[pseudonym] = employee_id
    _save_table(table)
    return pseudonym


def reveal(pseudonym: str, role: str) -> str | None:
    """Admin-funksjon: hvem er 'emp_xxxx'?

    Krever role == "admin" OG pseudonym-nøkkelen OG at personen er registrert.
    Returnerer None hvis pseudonymet ikke finnes i tabellen.
    """
    if role != ADMIN_ROLE:
        raise NotAuthorized(
            f"Rollen '{role}' kan ikke slaa opp pseudonymer. Bare '{ADMIN_ROLE}' kan det."
        )
    return _load_table().get(pseudonym)
