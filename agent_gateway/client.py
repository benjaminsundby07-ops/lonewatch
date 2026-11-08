"""HTTP-klienten mot den kjørende Lonewatch-appen. Bare standardbiblioteket.

Hvorfor `urllib` og ikke en pakke: dette er tre kall mot 127.0.0.1. En ekstra
avhengighet i MCP-tjeneren er en ekstra ting som kan mangle på demodagen.

Klienten tolker ingenting. Den sender JSON, leser JSON og lar den som kalte
avgjøre hva svaret betyr.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from agent_gateway.config import HEADER_KEY

# Lokale kall. Appen svarer med en gang paa alt utenom status, som ogsaa svarer
# med en gang: det er MCP-tjeneren som venter, ikke HTTP-kallet.
DEFAULT_TIMEOUT = 10.0


class LonewatchUnavailable(RuntimeError):
    """Appen svarer ikke. Da har agenten ingen mellomstasjon, og skal ikke få gjøre noe."""


class LonewatchRefused(RuntimeError):
    """Appen svarte, men slapp oss ikke inn (feil nøkkel, eller endepunktet er av)."""


class LonewatchClient:
    """Tre kall: send inn, spør om status, si at vi ga opp å vente."""

    def __init__(self, base_url: str, key: str, timeout: float = DEFAULT_TIMEOUT) -> None:
        self.base_url = base_url.rstrip("/")
        self._key = key
        self._timeout = timeout

    # -- selve kallet ----------------------------------------------------

    def _call(self, method: str, path: str, body: dict[str, Any] | None) -> dict[str, Any]:
        url = self.base_url + path
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {HEADER_KEY: self._key}
        if data is not None:
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                return json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403, 503):
                raise LonewatchRefused(self._explain(exc)) from exc
            raise LonewatchUnavailable(
                f"Lonewatch svarte {exc.code} på {path}: {self._explain(exc)}"
            ) from exc
        except urllib.error.URLError as exc:
            raise LonewatchUnavailable(
                f"Fikk ikke kontakt med Lonewatch på {self.base_url} ({exc.reason}). "
                "Kjører appen?"
            ) from exc
        except (TimeoutError, OSError) as exc:  # pragma: no cover - nettverksflaks
            raise LonewatchUnavailable(f"Lonewatch svarte ikke i tid: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise LonewatchUnavailable(f"Lonewatch svarte noe som ikke var JSON: {exc}") from exc

    @staticmethod
    def _explain(exc: urllib.error.HTTPError) -> str:
        """Feilteksten appen sendte, hvis den sendte en."""
        try:
            payload = json.loads(exc.read() or b"{}")
        except Exception:
            return exc.reason or str(exc.code)
        detail = payload.get("detail")
        if isinstance(detail, str) and detail:
            return detail
        return exc.reason or str(exc.code)

    # -- de tre kallene --------------------------------------------------

    def submit(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Sender en forespørsel inn i mellomstasjonen."""
        return self._call("POST", "/api/agent/submit", payload)

    def status(self, request_id: str) -> dict[str, Any]:
        """Hvor står en rød forespørsel nå? Svarer med en gang, venter ikke."""
        return self._call(
            "GET", "/api/agent/status/" + urllib.parse.quote(request_id, safe=""), None
        )

    def abandon(self, request_id: str, waited_seconds: float) -> dict[str, Any]:
        """Sier til appen at agenten sluttet å vente.

        Dette er IKKE et svar fra et menneske, og skrives derfor ikke i loggen.
        Det blir en notis i dashbordet, slik at den som sitter der ser at kortet
        fortsatt venter på dem selv om agenten har gitt opp.
        """
        return self._call(
            "POST",
            "/api/agent/abandon/" + urllib.parse.quote(request_id, safe=""),
            {"waited_seconds": waited_seconds},
        )
