"""Den låste loggen.

MIDLERTIDIG (skjelett): alt ligger bare i minnet, ingenting krypteres og ingenting
skrives til disk. Hash-kjeden er ekte (den kommer fra contracts), så verify() oppdager
endringer i det som ligger i minnet. Men en omstart sletter alt.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from contracts import GENESIS_HASH, LogEntry, LogKind, make_log_entry, verify_chain


def pseudonymize(employee_id: str) -> str:
    """Gir 'emp_xxxx'. Samme ansatt gir alltid samme pseudonym.

    MIDLERTIDIG: ingen nøkkel. Dette er bare en hash, saa den kan knekkes ved aa
    prøve seg frem. Skal senere bruke LONEWATCH_PSEUDONYM_KEY.
    """
    digest = hashlib.sha256(employee_id.encode("utf-8")).hexdigest()
    return f"emp_{digest[:4]}"


class Vault:
    """Logg som bare vokser. Hver linje peker på forrige via hash."""

    def __init__(self) -> None:
        self._entries: list[LogEntry] = []

    def append(self, kind: LogKind, payload: dict[str, Any], ts: datetime | None = None) -> LogEntry:
        """Legger en ny linje nederst og returnerer den."""
        entry = make_log_entry(
            seq=len(self._entries),
            ts=ts if ts is not None else datetime.now(timezone.utc),
            kind=kind,
            payload=payload,
            prev_hash=self._entries[-1].hash if self._entries else GENESIS_HASH,
        )
        self._entries.append(entry)
        return entry

    def verify(self) -> int | None:
        """seq til første ødelagte linje, ellers None."""
        return verify_chain(self._entries)

    def entries(self) -> list[LogEntry]:
        """Kopi av loggen, slik at ingen kan endre den innenfra."""
        return list(self._entries)

    def __len__(self) -> int:
        return len(self._entries)
