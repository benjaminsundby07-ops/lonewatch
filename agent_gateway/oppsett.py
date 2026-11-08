"""Setter opp broen mot en ekte agent, slik at ingen trenger å lime inn en nøkkel.

Bruk:
    python -m agent_gateway.oppsett

Den lager tre nøkler (hvis de ikke finnes alt), skriver dem i to filer som
begge ligger i `.gitignore`, og skriver ut de to kommandoene du skal kjøre:

    .lonewatch-agent-env   nøklene appen trenger. Du gjør `source` på den.
    .mcp.json              MCP-oppsettet Claude Code leser. Samme agentnøkkel.

Grunnen til at dette finnes: oppskriften «lag en nøkkel, lim den inn på to
steder» er det folk gjør feil, og en nøkkel som skal limes inn er en nøkkel som
havner i et chatlogg eller en commit. Her skrives den aldri ut på skjermen.

Kjører du den to ganger, beholdes nøklene du alt har. Loggen du har skrevet
kan fortsatt leses, og MCP-oppsettet fortsetter å stemme med appen.

Dette er IKKE en API-nøkkel. Lonewatch snakker ikke med noen AI-modell, og
hverken appen, MCP-tjeneren eller denne filen trenger `ANTHROPIC_API_KEY`.
Nøklene her er lokale hemmeligheter mellom appen og MCP-tjeneren på din maskin.
"""

from __future__ import annotations

import json
import os
import secrets
import stat
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".lonewatch-agent-env"
MCP_FILE = ROOT / ".mcp.json"
SERVER_NAME = "lonewatch"

# Nøklene vi tar ansvar for, og hvordan hver av dem lages.
KEYS = ("LONEWATCH_LOG_KEY", "LONEWATCH_PSEUDONYM_KEY", "LONEWATCH_AGENT_KEY")

DEFAULT_URL = "http://127.0.0.1:8000"
DEFAULT_WAIT = "120"


def _new_value(name: str) -> str:
    """En ny nøkkel av riktig slag. Loggnøklene har et format vault/ bestemmer."""
    if name == "LONEWATCH_LOG_KEY":
        from vault.crypto import new_log_key

        return new_log_key()
    if name == "LONEWATCH_PSEUDONYM_KEY":
        from vault.crypto import new_pseudonym_key

        return new_pseudonym_key()
    return secrets.token_urlsafe(32)


def read_env_file(path: Path) -> dict[str, str]:
    """Leser `export NAVN=verdi`-linjer. Ukjente linjer hoppes over."""
    if not path.exists():
        return {}
    funnet: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("export "):
            line = line[len("export ") :]
        navn, sep, verdi = line.partition("=")
        if sep and navn.strip() in KEYS:
            funnet[navn.strip()] = verdi.strip().strip("'\"")
    return funnet


def _write_private(path: Path, text: str) -> None:
    """Skriver filen og tar bort lesetilgang for alle andre enn deg."""
    path.write_text(text, encoding="utf-8")
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600
    except OSError:  # pragma: no cover - avhenger av filsystemet
        pass


def _gitignored(name: str, root: Path = ROOT) -> bool:
    """Står filen i .gitignore? Vi gjetter ikke: vi leser filen."""
    gitignore = root / ".gitignore"
    if not gitignore.exists():
        return False
    linjer = {ln.strip() for ln in gitignore.read_text(encoding="utf-8").splitlines()}
    return name in linjer


def build_mcp_config(existing: dict | None, *, agent_key: str, python: str, root: Path) -> dict:
    """MCP-oppsettet, med andre tjenere i filen urørt."""
    data = dict(existing or {})
    servers = dict(data.get("mcpServers") or {})
    servers[SERVER_NAME] = {
        "command": python,
        "args": ["-m", "agent_gateway"],
        "env": {
            "LONEWATCH_AGENT_KEY": agent_key,
            "LONEWATCH_AGENT_URL": DEFAULT_URL,
            "LONEWATCH_AGENT_WAIT_SECONDS": DEFAULT_WAIT,
            "PYTHONPATH": str(root),
        },
    }
    data["mcpServers"] = servers
    return data


def setup(
    *,
    root: Path = ROOT,
    python: str | None = None,
    env_source: dict[str, str] | None = None,
) -> dict[str, object]:
    """Gjør jobben. Returnerer hva som ble laget og hva som ble beholdt.

    Returverdien inneholder ALDRI nøklene selv - bare navnene deres. Det er
    med vilje: den som kaller skal kunne skrive ut resultatet uten å lekke noe.
    """
    env_file = root / ".lonewatch-agent-env"
    mcp_file = root / ".mcp.json"
    python = python or sys.executable

    fra_fil = read_env_file(env_file)
    fra_miljo = env_source if env_source is not None else dict(os.environ)

    verdier: dict[str, str] = {}
    beholdt: list[str] = []
    laget: list[str] = []
    for navn in KEYS:
        gammel = (fra_fil.get(navn) or fra_miljo.get(navn) or "").strip()
        if gammel:
            verdier[navn] = gammel
            beholdt.append(navn)
        else:
            verdier[navn] = _new_value(navn)
            laget.append(navn)

    _write_private(
        env_file,
        "# Lonewatch - lokale nokler. Ligger i .gitignore. Bruk: source "
        f"{env_file.name}\n"
        "# Dette er IKKE en API-nokkel, og ingenting her snakker med en AI-modell.\n"
        + "".join(f"export {navn}={verdier[navn]}\n" for navn in KEYS),
    )

    gammelt_mcp = None
    if mcp_file.exists():
        try:
            gammelt_mcp = json.loads(mcp_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            gammelt_mcp = None  # Ubrukelig fil. Vi skriver en ny.
    _write_private(
        mcp_file,
        json.dumps(
            build_mcp_config(gammelt_mcp, agent_key=verdier["LONEWATCH_AGENT_KEY"],
                             python=python, root=root),
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
    )

    return {
        "env_file": str(env_file),
        "mcp_file": str(mcp_file),
        "python": python,
        "created": laget,
        "kept": beholdt,
        "env_ignored": _gitignored(env_file.name, root),
        "mcp_ignored": _gitignored(mcp_file.name, root),
    }


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if "--help" in args or "-h" in args:
        print(__doc__)
        return 0

    resultat = setup()

    print("Oppsettet er klart.\n")
    print(f"  {resultat['env_file']}   nøklene (ikke i git)")
    print(f"  {resultat['mcp_file']}              MCP-oppsettet (ikke i git)")
    if resultat["kept"]:
        print(f"\nBeholdt nøkler du alt hadde: {', '.join(resultat['kept'])}")
    if resultat["created"]:
        print(f"Laget nye nøkler: {', '.join(resultat['created'])}")
    print("Ingen nøkkel skrives ut her. De står bare i de to filene.")

    for fil, ignorert in (("env_file", "env_ignored"), ("mcp_file", "mcp_ignored")):
        if not resultat[ignorert]:
            print(
                f"\nADVARSEL: {Path(str(resultat[fil])).name} står ikke i .gitignore. "
                "Legg den inn FØR du committer."
            )

    try:
        import mcp  # noqa: F401
    except ModuleNotFoundError:
        print(
            f"\nADVARSEL: pakken `mcp` mangler i {resultat['python']}. "
            "Kjør: pip install -r requirements.txt"
        )

    print("\nGjør dette, i denne rekkefølgen:\n")
    print("  1)  source .lonewatch-agent-env")
    print("  2)  python -m ui                       # la den stå og kjøre")
    print("  3)  åpne http://127.0.0.1:8000 og la fanen stå åpen")
    print("  4)  i et NYTT terminalvindu: claude")
    print('  5)  si til agenten: "Betal faktura 8841: 450 000 kr til')
    print('      NO93 8601 1117 947. Bruk Lonewatch-verktøyene."')
    print("\nDu trenger ingen API-nøkkel. Se docs/EKTE_AGENT.md.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
