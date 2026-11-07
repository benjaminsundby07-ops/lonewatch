"""Den falske hjemmemappen et tillegg får se.

Alt her er oppdiktet. Filene har navn som ser ut som et utviklermiljø
(ssh-nøkkel, lommebok, nettleserdata, miljøfil), men innholdet sier rett ut at
det er falskt. Ingen av filene inneholder en ekte hemmelighet, og ingen av dem
er kopiert fra din egen maskin.

Filene er delt i to:
- `BAIT`  : agn. Blir en av disse lest, er tillegget ute etter hemmeligheter.
- resten  : vanlige dokumenter. Et tillegg får lese dem uten at det er mistenkelig.
"""

from __future__ import annotations

from pathlib import Path

_FAKE = "FALSK DEMOFIL I LONEWATCH-SANDKASSEN - IKKE EN EKTE HEMMELIGHET"

# Agn: filnavn -> norsk navn vi bruker i rapporten.
BAIT: dict[str, str] = {
    ".ssh/id_rsa": "den falske ssh-nokkelen",
    ".env": "den falske miljofilen",
    ".config/kryptolommebok/wallet.dat": "den falske lommebokfilen",
    "Library/NettleserDemo/Login Data": "de falske nettleserdataene",
    ".aws/credentials": "den falske skynokkelen",
}

# Innholdet i den falske hjemmemappen. Nøkler er stier under hjemmemappen.
FAKE_FILES: dict[str, str] = {
    ".ssh/id_rsa": (
        f"# {_FAKE}\n"
        "# Dette er ikke en nokkel. Det er sju linjer tekst som later som.\n"
        "oppdiktet-nokkel-linje-1-aaaaaaaaaaaaaaaaaaaaaaaa\n"
        "oppdiktet-nokkel-linje-2-bbbbbbbbbbbbbbbbbbbbbbbb\n"
        "oppdiktet-nokkel-linje-3-cccccccccccccccccccccccc\n"
    ),
    ".ssh/id_rsa.pub": f"# {_FAKE}\noppdiktet-offentlig-nokkel demo@lonewatch.invalid\n",
    ".env": (
        f"# {_FAKE}\n"
        "DEMO_API_KEY=ikke-en-ekte-nokkel-bare-demo\n"
        "DEMO_DB_URL=postgres://demo:demo@database.invalid:5432/demo\n"
        "DEMO_STRIPE_KEY=ikke-en-ekte-nokkel-bare-demo\n"
    ),
    ".config/kryptolommebok/wallet.dat": (
        f"# {_FAKE}\n"
        "lommebok: oppdiktet\n"
        "saldo: 0\n"
        "frase: dette er ikke en gjenopprettingsfrase, bare en setning\n"
    ),
    "Library/NettleserDemo/Login Data": (
        f"# {_FAKE}\n"
        "nettsted;brukernavn;passord\n"
        "bank.invalid;demo-bruker;oppdiktet-passord-1\n"
        "intranett.invalid;demo-bruker;oppdiktet-passord-2\n"
    ),
    ".aws/credentials": (
        f"# {_FAKE}\n"
        "[default]\n"
        "demo_access_key = OPPDIKTET-IKKE-EKTE\n"
        "demo_secret_key = OPPDIKTET-IKKE-EKTE\n"
    ),
    "Dokumenter/faktura-demo.txt": (
        "Faktura 2026-0042 (oppdiktet)\n"
        "Kunde: Nordlys Demo AS\n"
        "Belop: 12 500 NOK\n"
        "\f"
        "Side 2: betalingsbetingelser, 30 dager.\n"
    ),
    "Dokumenter/rapport-demo.txt": (
        "Kvartalsrapport (oppdiktet)\nIngen tall her er ekte.\n"
    ),
    ".bash_history": "ls\ncd prosjekter\npytest -q\n",
}


def build(home: Path) -> Path:
    """Lager den falske hjemmemappen og returnerer stien til den."""
    home.mkdir(parents=True, exist_ok=True)
    for rel, text in FAKE_FILES.items():
        target = home / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return home


def bait_map(home: Path) -> dict[str, str]:
    """Agnfilene som absolutte, oppslåtte stier -> norsk navn.

    Vi løser opp stien (realpath) fordi delprosessen sammenligner på oppslått
    sti: paa macOS er /var en snarvei til /private/var, og uten dette ville
    agnet ikke blitt kjent igjen.
    """
    return {str((home / rel).resolve()): label for rel, label in BAIT.items()}
