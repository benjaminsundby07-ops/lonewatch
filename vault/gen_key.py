"""Skriver ut en ny nøkkel. Nøkkelen havner ALDRI i koden eller i loggen.

Bruk:
    export LONEWATCH_LOG_KEY=$(python -m vault.gen_key)
    export LONEWATCH_PSEUDONYM_KEY=$(python -m vault.gen_key --pseudonym)
    export LONEWATCH_HUMAN_KEY=$(python -m vault.gen_key --human)
    python -m vault.gen_key --both     # alle tre, klar til aa limes inn i terminalen

Menneskenoekkelen (--human) er den som godkjenner et roedt kort. Den hoerer
ikke til loggen, men den lages her fordi det er her noekler lages. Den skal
ALDRI vaere den samme som LONEWATCH_AGENT_KEY: da kunne agenten godkjent sine
egne forespoersler. Se ui/human_key.py og ui/LIMITS.md.
"""

from __future__ import annotations

import secrets
import sys

from vault.crypto import ENV_LOG_KEY, ENV_PSEUDONYM_KEY, new_log_key, new_pseudonym_key

# Menneskenoekkelen eies av ui/human_key.py. Navnet staar her for at
# `--both` skal kunne skrive en ferdig `export`-linje.
ENV_HUMAN_KEY = "LONEWATCH_HUMAN_KEY"


def new_human_key() -> str:
    """Ny tilfeldig menneskenoekkel. Ikke en Fernet-noekkel: den krypterer ingenting."""
    return secrets.token_urlsafe(32)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv

    if "--help" in args or "-h" in args:
        print(__doc__)
        return 0
    if "--both" in args:
        print(f"export {ENV_LOG_KEY}={new_log_key()}")
        print(f"export {ENV_PSEUDONYM_KEY}={new_pseudonym_key()}")
        print(f"export {ENV_HUMAN_KEY}={new_human_key()}")
        return 0
    if "--human" in args:
        print(new_human_key())
        return 0
    if "--pseudonym" in args:
        print(new_pseudonym_key())
        return 0
    print(new_log_key())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
