"""Det låste agentoppsettet: hva det inneholder, og hva som ikke lover noe.

Testene her måler tre ting:

1. at det genererte oppsettet faktisk har tillat- og nekt-listene i seg
2. at filen er gitignorert og får 0600
3. at startskriptet bygger den kommandolinjen vi tror den bygger - uten å
   starte `claude`

Det testene IKKE kan måle: at Claude Code faktisk respekterer oppsettet. Det er
en annen prosess, og det må prøves for hånd. Prosedyren står i
`docs/EKTE_AGENT.md`. Vi måler at VI sender det riktige, ikke at mottakeren
gjør det riktige med det.
"""

from __future__ import annotations

import json
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from agent_gateway import laas, start_agent
from agent_gateway.tools import TOOL_SPECS

REPO = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# innholdet i den genererte filen
# ---------------------------------------------------------------------------


def test_oppsettet_tillater_bare_lonewatch_verktoeyene():
    settings = laas.build_settings()
    tillatt = settings["permissions"]["allow"]

    # Alle fire verktøyene, med MCP-prefikset Claude Code bruker.
    for spec in TOOL_SPECS:
        assert f"mcp__lonewatch__{spec.name}" in tillatt

    # Og ingenting annet enn lonewatch står i allow-listen.
    for navn in tillatt:
        assert navn.startswith("mcp__lonewatch")


def test_oppsettet_nekter_de_innebygde_verktoeyene():
    deny = laas.build_settings()["permissions"]["deny"]
    for navn in (
        "Bash",
        "Edit",
        "Write",
        "MultiEdit",
        "NotebookEdit",
        "WebFetch",
        "WebSearch",
    ):
        assert navn in deny, navn
    # Og de andre veiene ut: lesing, leting, og å starte en ny agent som ville
    # hatt sine egne verktøy.
    for navn in ("Read", "Glob", "Grep", "Task", "Agent", "BashOutput", "KillShell"):
        assert navn in deny, navn


def test_ingen_noekkel_i_det_laaste_oppsettet():
    """Innstillingsfilen leses av agenten. Da skal det ikke stå en nøkkel i den."""
    tekst = json.dumps(laas.build_settings())
    for forbudt in ("LONEWATCH_AGENT_KEY", "LONEWATCH_HUMAN_KEY", "LONEWATCH_LOG_KEY"):
        assert forbudt not in tekst


def test_bare_vaar_egen_mcp_tjener_slaas_paa():
    settings = laas.build_settings()
    assert settings["enableAllProjectMcpServers"] is False
    assert settings["enabledMcpjsonServers"] == ["lonewatch"]
    # En hook er et sted å kjøre et skript fra, altså en vei rundt nekt-listen.
    assert settings["disableAllHooks"] is True


def test_ingenting_godkjennes_automatisk():
    assert laas.build_settings()["permissions"]["defaultMode"] == "manual"
    assert "--permission-mode" in laas.build_claude_argv()
    argv = laas.build_claude_argv()
    assert argv[argv.index("--permission-mode") + 1] == "manual"
    # bypassPermissions ville slaatt av hele spoersmaalet.
    for farlig in (
        "--dangerously-skip-permissions",
        "--allow-dangerously-skip-permissions",
        "bypassPermissions",
        "acceptEdits",
        "dontAsk",
    ):
        assert farlig not in argv


# ---------------------------------------------------------------------------
# filen paa disken
# ---------------------------------------------------------------------------


def test_filen_skrives_med_0600_og_gyldig_json(tmp_path):
    (tmp_path / ".gitignore").write_text(laas.GITIGNORE_LINE + "\n", encoding="utf-8")
    resultat = laas.write_settings(tmp_path)

    path = Path(str(resultat["settings_file"]))
    assert path == tmp_path / ".claude" / "settings.json"
    assert json.loads(path.read_text(encoding="utf-8")) == laas.build_settings()
    assert resultat["mode"] == stat.S_IRUSR | stat.S_IWUSR
    assert resultat["ignored"] is True


def test_oppsettet_merker_at_filen_ikke_er_gitignorert(tmp_path):
    """Står ikke linjen i .gitignore, skal vi si det - ikke anta det."""
    (tmp_path / ".gitignore").write_text("noe-helt-annet\n", encoding="utf-8")
    assert laas.write_settings(tmp_path)["ignored"] is False


def test_det_ekte_repoet_har_linjen_i_gitignore():
    assert laas.gitignore_has_line(REPO) is True


def test_git_regner_filen_som_ignorert():
    """Line-for-linje-sjekken over er vår. Dette er gits egen mening."""
    kjoert = subprocess.run(
        ["git", "check-ignore", "-q", laas.SETTINGS_REL],
        cwd=REPO,
        capture_output=True,
    )
    if kjoert.returncode == 128:  # pragma: no cover - ikke et git-repo
        pytest.skip("ikke et git-repo")
    assert kjoert.returncode == 0


def test_det_laaste_oppsettet_er_ikke_sjekket_inn():
    """Filen er maskinspesifikk. Den skal ikke ligge i treet."""
    kjoert = subprocess.run(
        ["git", "ls-files", "--error-unmatch", laas.SETTINGS_REL],
        cwd=REPO,
        capture_output=True,
    )
    assert kjoert.returncode != 0


# ---------------------------------------------------------------------------
# kommandolinjen - uten aa starte claude
# ---------------------------------------------------------------------------


def test_kommandolinjen_laaser_verktoeyene(tmp_path):
    argv = start_agent.build_command(root=tmp_path, claude="claude")

    assert argv[0] == "claude"

    def verdi(flagg):
        return argv[argv.index(flagg) + 1]

    # Hele det innebygde settet tas bort. Tom streng = «disable all tools».
    assert "--tools" in argv
    assert verdi("--tools") == ""

    # Bare de fire verktøyene er tillatt, som ETT komma-skilt argument.
    tillatt = verdi("--allowed-tools").split(",")
    assert tillatt == list(laas.ALLOW_TOOLS)
    assert all(navn.startswith("mcp__lonewatch__") for navn in tillatt)

    # Og de innebygde nektes ved navn i tillegg.
    nektet = verdi("--disallowed-tools").split(",")
    assert nektet == list(laas.DENY_TOOLS)
    assert "Bash" in nektet

    # Bare vårt eget MCP-oppsett.
    assert "--strict-mcp-config" in argv
    assert verdi("--mcp-config") == str(tmp_path / ".mcp.json")
    assert verdi("--settings") == str(tmp_path / ".claude" / "settings.json")
    # Dine egne og de lokale innstillingene leses ikke: en allow-regel for Bash
    # der ville aapnet hullet igjen uten at noen saa det.
    assert verdi("--setting-sources") == "project"


def test_innebygde_mcp_tjenere_nektes_ved_navn():
    """Funnet ved prøvekjøring: claude-in-chrome (22 verktøy) var tilkoblet."""
    deny = laas.build_settings()["permissions"]["deny"]
    assert "mcp__claude-in-chrome" in deny
    assert "mcp__computer-use" in deny


def test_kommandolinjen_slaar_av_chrome_integrasjonen(tmp_path):
    argv = start_agent.build_command(root=tmp_path, claude="claude")
    assert "--no-chrome" in argv
    assert "--chrome" not in argv


def test_listene_sendes_som_ett_argument_hver(tmp_path):
    """Målt, ikke antatt: `--allowed-tools a b c` spiser det som kommer etter.

    `--allowed-tools`, `--disallowed-tools` og `--tools` tar flere verdier i
    Claude Code 2.1.241. En liste med mellomrom ville slukt en oppgavetekst som
    sto bak på kommandolinjen. Derfor ett komma-skilt argument per flagg.
    """
    argv = start_agent.build_command(root=tmp_path)
    for flagg in ("--allowed-tools", "--disallowed-tools"):
        i = argv.index(flagg)
        assert " " not in argv[i + 1]
        # Neste element etter verdien er et flagg, eller det er slutten.
        assert i + 2 == len(argv) or argv[i + 2].startswith("--")


def test_vi_vet_at_multiedit_ikke_finnes_i_denne_versjonen():
    """MultiEdit står i nekt-listen, men finnes ikke i Claude Code 2.1.241.

    `claude` svarer da «Permission deny rule "MultiEdit" matches no known tool».
    Advarselen er riktig. Vi lar navnet stå - en senere versjon kan ha verktøyet
    igjen - men vi later ikke som vi ikke vet det.
    """
    assert "MultiEdit" in laas.DENY_TOOLS
    assert "MultiEdit" in laas.UKJENTE_I_2_1_241


def test_startskriptet_sier_hva_som_mangler(tmp_path):
    assert sorted(start_agent.missing_files(tmp_path)) == sorted(
        [laas.MCP_REL, laas.SETTINGS_REL]
    )
    (tmp_path / ".mcp.json").write_text("{}", encoding="utf-8")
    laas.write_settings(tmp_path)
    assert start_agent.missing_files(tmp_path) == []


def test_vis_starter_ingenting(capsys, monkeypatch):
    """`--vis` skal skrive kommandolinjen og ikke kalle execvp."""

    def nekt(*a, **kw):  # pragma: no cover - skal aldri kalles
        raise AssertionError("startskriptet startet noe under --vis")

    monkeypatch.setattr(start_agent.os, "execvp", nekt)
    monkeypatch.setattr(start_agent.os, "chdir", nekt)
    assert start_agent.main(["--vis"]) == 0
    ut = capsys.readouterr().out
    assert "--tools" in ut
    assert "ingenting ble startet" in ut


def test_meldingen_sier_hva_som_IKKE_er_laast(capsys, monkeypatch):
    """Den norske meldingen skal være ærlig, ikke selge noe."""
    monkeypatch.setattr(start_agent.os, "execvp", lambda *a, **kw: None)
    monkeypatch.setattr(start_agent.os, "chdir", lambda *a, **kw: None)
    start_agent.main(["--vis"])
    ut = capsys.readouterr().out
    assert "ikke en sikkerhetsgrense" in ut.lower()
    assert "nettverksnivå" in ut
    assert "kjøre kode" in ut


def test_hjelpeteksten_sier_at_den_ikke_starter_noe(capsys):
    assert start_agent.main(["--help"]) == 0
    ut = capsys.readouterr().out
    assert "Ingenting startes med mindre du kjører kommandoen" in ut


def test_startskriptet_kan_kjoeres_som_modul():
    """`python -m agent_gateway.start_agent --vis` skal ikke starte claude."""
    kjoert = subprocess.run(
        [sys.executable, "-m", "agent_gateway.start_agent", "--vis"],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert "--strict-mcp-config" in kjoert.stdout
    assert "ingenting ble startet" in kjoert.stdout


# ---------------------------------------------------------------------------
# oppsettet som helhet, i en midlertidig kopi
# ---------------------------------------------------------------------------


def test_oppsettet_lager_det_laaste_oppsettet(tmp_path, monkeypatch):
    """`python -m agent_gateway.oppsett` skal skrive filen, uten å lekke noe."""
    from agent_gateway import oppsett

    (tmp_path / ".gitignore").write_text(
        ".lonewatch-agent-env\n.mcp.json\n" + laas.GITIGNORE_LINE + "\n",
        encoding="utf-8",
    )
    resultat = oppsett.setup(root=tmp_path, python=sys.executable, env_source={})

    assert resultat["settings_ignored"] is True
    assert resultat["settings_mode"] == stat.S_IRUSR | stat.S_IWUSR
    path = Path(str(resultat["settings_file"]))
    assert path.exists()

    # Ingen av de fire nøklene står i returverdien eller i innstillingsfilen.
    noekler = {
        navn: verdi
        for navn, verdi in oppsett.read_env_file(tmp_path / ".lonewatch-agent-env").items()
    }
    assert len(noekler) == 4
    tekst = json.dumps(resultat) + path.read_text(encoding="utf-8")
    for verdi in noekler.values():
        assert verdi not in tekst
