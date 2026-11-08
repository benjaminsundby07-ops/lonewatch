"""Det låste agentoppsettet: Claude Code med bare Lonewatch-verktøyene.

Det store hullet i demoen er at Claude Code har sine egne verktøy - Bash,
filer, nett, git - og ingen av dem går gjennom Lonewatch. Vi kan ikke tvinge
trafikk gjennom mellomstasjonen på nettverksnivå. Det vi kan, er å starte
agenten med et oppsett der de andre verktøyene ikke finnes.

Denne filen lager to ting:

1. `.claude/settings.json` i agent-mappen: en Claude Code-innstillingsfil som
   tillater `mcp__lonewatch__*` og nekter de innebygde verktøyene.
2. Kommandolinjen `agent_gateway.start_agent` bruker, der de samme listene
   står som flagg - fordi flagg virker selv om innstillingsfilen blir ignorert
   (den blir det i en mappe Claude Code ikke har fått tillit til, se under).

**Dette er klientkonfigurasjon, ikke en sikkerhetsgrense.** Den som kan kjøre
kode på maskinen kan slette filen, droppe flagget eller starte `claude` uten
startskriptet. Les `agent_gateway/LIMITS.md` punkt 1 før du sier noe om dette
i en demo.

Alt her er målt mot Claude Code **2.1.241**. Flaggene under finnes i
`claude --help` i den versjonen; vi gjetter ikke på flagg vi ikke har sett.
"""

from __future__ import annotations

import json
import stat
from pathlib import Path

from agent_gateway.tools import TOOL_SPECS

ROOT = Path(__file__).resolve().parent.parent

# Navnet MCP-tjeneren har i .mcp.json (agent_gateway/oppsett.py).
MCP_SERVER_NAME = "lonewatch"

SETTINGS_REL = "/".join((".claude", "settings.json"))
MCP_REL = ".mcp.json"

# Linjen `.gitignore` må ha. Innstillingsfilen inneholder ingen nøkkel, men den
# er maskinspesifikk (absolutte stier) og hører ikke i git.
GITIGNORE_LINE = SETTINGS_REL

# Prefikset Claude Code gir MCP-verktøy: mcp__<tjener>__<verktoey>.
ALLOW_SERVER = f"mcp__{MCP_SERVER_NAME}"
ALLOW_TOOLS: tuple[str, ...] = tuple(
    f"{ALLOW_SERVER}__{spec.name}" for spec in TOOL_SPECS
)

# De innebygde verktøyene vi nekter. Rekkefølgen er gruppert etter hva de gjør,
# slik at et menneske kan lese listen og se at ingenting mangler.
DENY_TOOLS: tuple[str, ...] = (
    # kjøre kode
    "Bash",
    "BashOutput",
    "KillShell",
    # skrive filer
    "Edit",
    "Write",
    "MultiEdit",
    "NotebookEdit",
    # lese filer og lete
    "Read",
    "Glob",
    "Grep",
    # ut av maskinen
    "WebFetch",
    "WebSearch",
    # starte flere agenter, som ville hatt sine egne verktøy
    "Task",
    "Agent",
    # resten av det innebygde settet
    "TodoWrite",
    "ExitPlanMode",
    # Innebygde MCP-tjenere som `--strict-mcp-config` IKKE tar bort. Funnet ved
    # prøvekjøring: `/mcp` viste `claude-in-chrome` med 22 verktøy (navigere,
    # kjøre JavaScript, fylle skjemaer) rett utenom Lonewatch. Nektes ved
    # tjenernavn, og Chrome-integrasjonen slås i tillegg av med --no-chrome.
    "mcp__claude-in-chrome",
    "mcp__computer-use",
)

# Navn vi ber om å nekte, men som IKKE finnes i Claude Code 2.1.241. Da skriver
# claude «Permission deny rule "MultiEdit" matches no known tool». Advarselen er
# riktig, og vi lar navnet stå: en senere versjon kan ha verktøyet igjen, og en
# nekt for noe som ikke finnes koster ingenting. Testen pinner at vi VET dette.
UKJENTE_I_2_1_241: tuple[str, ...] = ("MultiEdit",)

# `manual` står i listen `claude --help` gir for --permission-mode. Den betyr at
# ingenting godkjennes automatisk: alt utenfor allow-listen må et menneske si ja
# til i agentens terminal.
PERMISSION_MODE = "manual"

# Hvilke innstillingskilder Claude Code får lese. `project` er den genererte
# filen. `user` (~/.claude/settings.json) og `local` er med vilje utenfor: en
# allow-regel for Bash der ville åpnet hullet igjen uten at noen så det.
SETTING_SOURCES = "project"


def build_settings() -> dict:
    """Innholdet i `.claude/settings.json`. Ingen nøkler, ingen stier."""
    return {
        "permissions": {
            "defaultMode": PERMISSION_MODE,
            "allow": [ALLOW_SERVER, *ALLOW_TOOLS],
            "deny": list(DENY_TOOLS),
            # Agenten skal ikke få lese utenfor mappen. Tom med vilje.
            "additionalDirectories": [],
        },
        # Bare den MCP-tjeneren vi selv genererte. Står det en annen tjener i
        # .mcp.json, blir den ikke slått på av seg selv.
        "enableAllProjectMcpServers": False,
        "enabledMcpjsonServers": [MCP_SERVER_NAME],
        # En hook er et sted å kjøre et skript fra. Av.
        "disableAllHooks": True,
    }


def build_claude_argv(
    *,
    root: Path = ROOT,
    claude: str = "claude",
    extra: list[str] | None = None,
) -> list[str]:
    """Kommandolinjen som starter agenten låst.

    Hvert flagg finnes i `claude --help` i 2.1.241:

    - `--settings <fil>`          les den genererte innstillingsfilen
    - `--setting-sources project` ikke les dine egne eller lokale innstillinger
    - `--strict-mcp-config`       bare MCP-tjenere fra --mcp-config
    - `--mcp-config <fil>`        og det er vår .mcp.json
    - `--permission-mode manual`  ingenting godkjennes automatisk
    - `--tools ""`                ta bort HELE det innebygde verktøysettet
    - `--allowed-tools ...`       bare de fire Lonewatch-verktøyene
    - `--disallowed-tools ...`    og nekt de innebygde ved navn i tillegg

    De tre siste er med vilje overlappende. `--tools ""` er den som faktisk
    fjerner verktøyene (målt: agenten svarer at den ikke har noen), mens
    allow/deny-listene er det et menneske kan lese i `claude /status` og i
    filen. Fjerner noen én av dem, står de to andre igjen.

    Listene sendes som ETT komma-skilt argument hver, ikke som flere ord.
    `--allowed-tools`, `--disallowed-tools` og `--tools` tar flere verdier, og
    en liste med mellomrom spiser det som kommer etter seg på kommandolinjen -
    også en oppgavetekst. Det er målt, ikke antatt.
    """
    settings_path = Path(root) / SETTINGS_REL
    mcp_path = Path(root) / MCP_REL
    argv = [
        claude,
        "--settings",
        str(settings_path),
        "--setting-sources",
        SETTING_SOURCES,
        "--strict-mcp-config",
        "--mcp-config",
        str(mcp_path),
        # Claude in Chrome er en innebygd MCP-tjener som --strict-mcp-config
        # ikke rører. Av med den, i tillegg til nekt-regelen i DENY_TOOLS.
        "--no-chrome",
        "--permission-mode",
        PERMISSION_MODE,
        # Tom streng: «disable all tools» i det innebygde settet.
        "--tools",
        "",
        "--allowed-tools",
        ",".join(ALLOW_TOOLS),
        "--disallowed-tools",
        ",".join(DENY_TOOLS),
    ]
    if extra:
        argv.extend(extra)
    return argv


def gitignore_has_line(root: Path = ROOT) -> bool:
    """Står innstillingsfilen i .gitignore? Vi leser filen, vi gjetter ikke."""
    gitignore = Path(root) / ".gitignore"
    if not gitignore.exists():
        return False
    linjer = {ln.strip() for ln in gitignore.read_text(encoding="utf-8").splitlines()}
    return GITIGNORE_LINE in linjer


def write_settings(root: Path = ROOT) -> dict[str, object]:
    """Skriver `.claude/settings.json` og returnerer hva som skjedde.

    Returverdien inneholder ingen hemmeligheter: filen har ingen nøkler i seg.
    """
    path = Path(root) / SETTINGS_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(build_settings(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    mode: int | None
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError:  # pragma: no cover - avhenger av filsystemet
        mode = None
    return {
        "settings_file": str(path),
        "mode": mode,
        "ignored": gitignore_has_line(root),
        "allow": list(ALLOW_TOOLS),
        "deny": list(DENY_TOOLS),
    }


def summary_lines(root: Path = ROOT) -> list[str]:
    """Den norske forklaringen på hva som er låst og hva som ikke er det.

    Både `oppsett.py` og `start_agent.py` skriver den, slik at det står det
    samme uansett hvor du leser det.
    """
    return [
        "Låst agentoppsett (klientkonfigurasjon, IKKE en sikkerhetsgrense):",
        f"  Tillatt:  {', '.join(ALLOW_TOOLS)}",
        f"  Nektet:   {', '.join(DENY_TOOLS)}",
        "  Hele det innebygde verktøysettet er tatt bort med --tools \"\".",
        "  Bare MCP-tjeneren i .mcp.json leses (--strict-mcp-config).",
        "  Ingenting godkjennes automatisk (--permission-mode manual).",
        "",
        "Dette låser IKKE:",
        "  - en agent som alt kan kjøre kode på maskinen. Den kan slette",
        f"    {SETTINGS_REL}, droppe flaggene eller starte `claude` selv.",
        "  - noe som helst på nettverksnivå. Trafikk tvinges ikke gjennom",
        "    Lonewatch; agenten velger fortsatt frivillig å bruke verktøyene.",
        "  - innstillinger en bedrift har satt sentralt (managed policy). De",
        "    gjelder uansett hva vi skriver her.",
        "Se agent_gateway/LIMITS.md punkt 1.",
    ]
