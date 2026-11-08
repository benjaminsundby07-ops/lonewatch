"""Én gang, og bare én gang. Boka over hva som er forsøkt.

En utfører som gjentar seg selv er farligere enn en som feiler. To betalinger
i stedet for én er ikke en halv feil, det er en ny handling ingen har
godkjent. Derfor merkes en forespørsel som forsøkt FØR handlingen gjøres, ikke
etter.

Det betyr at en handling som feilet heller ikke kan prøves på nytt. Det er et
bevisst valg: når et SMTP-kall brekker, vet vi ikke om meldingen gikk ut eller
ikke. Da er det tryggere å si "ikke utført, og ingen prøver igjen" enn å
risikere to e-poster. Et menneske må sende inn en ny forespørsel, som får sin
egen vurdering og sin egen godkjenning.

Boka lever i minnet så lenge prosessen lever. Se executor/LIMITS.md.
"""

from __future__ import annotations

import threading


class AttemptLedger:
    """Hvilke request_id som er forsøkt. Trådsikker."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._seen: set[str] = set()

    def claim(self, request_id: str) -> bool:
        """Tar plassen for en forespørsel. True første gang, False siden.

        Låsen gjør at to tråder som kaller samtidig ikke begge får True.
        """
        with self._lock:
            if request_id in self._seen:
                return False
            self._seen.add(request_id)
            return True

    def attempted(self, request_id: str) -> bool:
        with self._lock:
            return request_id in self._seen

    def release(self, request_id: str) -> None:
        """Gir plassen tilbake. Brukes BARE når ingenting kan ha skjedd ute.

        Utføreren kaller denne hvis handlingen ble avvist av porten eller
        stoppet før det eneste stedet som rører omverdenen. Den kalles aldri
        etter et mislykket forsøk.
        """
        with self._lock:
            self._seen.discard(request_id)

    def clear(self) -> None:
        with self._lock:
            self._seen.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._seen)
