"""Kjør sandkassen for hånd:

    python -m sandbox              # alle demotilleggene
    python -m sandbox nordlys-mail-connector-patch
"""

from __future__ import annotations

import sys

try:
    from . import DEMO_PACKAGES, UnknownPackage, available_packages, scan
except RuntimeError as exc:  # for gammel Python - si fra, ikke krasj stille
    print(f"Sandkassen startet ikke: {exc}", file=sys.stderr)
    raise SystemExit(1) from None


def main(argv: list[str]) -> int:
    navn = argv[1:] or list(DEMO_PACKAGES)
    for pakke in navn:
        try:
            rapport = scan(pakke)
        except UnknownPackage as exc:
            print(f"  {pakke}: {exc}")
            print(f"  Kjente tillegg: {', '.join(available_packages())}")
            return 1
        merke = {"clean": "OK    ", "blocked": "STOPP ", "not_tested": "?     "}[rapport.verdict]
        print(f"{merke} {pakke:<18} {rapport.verdict}")
        if rapport.destinations:
            print(f"         adresser: {', '.join(rapport.destinations)}")
        print(f"         {rapport.notes}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
