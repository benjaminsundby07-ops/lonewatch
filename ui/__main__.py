"""Starter nettsiden. Bruk: python -m ui"""

from __future__ import annotations

import os
import sys

import uvicorn


def main() -> int:
    # Importer appen HER, ikke inne i uvicorn, slik at vi kan forklare
    # tydelig hvis en annen Lonewatch alt holder loggen (F4 i docs/REDTEAM.md).
    try:
        from ui.app import app
    except Exception as exc:
        from ui.state import LonewatchAlreadyRunning

        if isinstance(exc, LonewatchAlreadyRunning):
            print(f"Lonewatch starter ikke: {exc}", file=sys.stderr)
            print(
                "Loggen er ikke rørt. Stopp den som kjører, eller sett "
                "LONEWATCH_LOG_PATH til en annen fil.",
                file=sys.stderr,
            )
            return 1
        raise

    uvicorn.run(
        app,
        host=os.environ.get("LONEWATCH_HOST", "127.0.0.1"),
        port=int(os.environ.get("LONEWATCH_PORT", "8000")),
        reload=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
