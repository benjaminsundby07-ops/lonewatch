"""Skriver ut en ny nøkkel. Nøkkelen havner ALDRI i koden eller i loggen.

Bruk:
    export LONEWATCH_LOG_KEY=$(python -m vault.gen_key)
    export LONEWATCH_PSEUDONYM_KEY=$(python -m vault.gen_key --pseudonym)
    python -m vault.gen_key --both     # begge, klar til aa limes inn i terminalen
"""

from __future__ import annotations

import sys

from vault.crypto import ENV_LOG_KEY, ENV_PSEUDONYM_KEY, new_log_key, new_pseudonym_key


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv

    if "--help" in args or "-h" in args:
        print(__doc__)
        return 0
    if "--both" in args:
        print(f"export {ENV_LOG_KEY}={new_log_key()}")
        print(f"export {ENV_PSEUDONYM_KEY}={new_pseudonym_key()}")
        return 0
    if "--pseudonym" in args:
        print(new_pseudonym_key())
        return 0
    print(new_log_key())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
