"""Tester for reserven og for oppsettet: det som skal virke uten en agent.

Reserven (`agent_gateway/scripted_demo.py`) er det vi viser hvis en ekte agent
ikke oppfører seg. Da må den virke hver gang, og den må gå gjennom den SAMME
koden som agenten - ellers viser vi noe annet enn det vi sier vi viser.

Testene her sjekker tre ting:
  1. at manuset ender i de avgjørelsene vi lover i docs/EKTE_AGENT.md
  2. at ingenting i manuset er avhengig av oppsett, nøkler eller nett
  3. at `python -m agent_gateway.oppsett` lager det den skal, og at nøkkelen
     aldri kommer ut av filene den skrev
"""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from agent_gateway import oppsett, scripted_demo

pytest.importorskip("fastapi")

# Hva hvert slag i manuset skal ende på. Står her, ikke i modulen, slik at en
# endring i manuset må bekreftes her.
FORVENTET = [
    ("1. Vanlig arbeid", "allow", "allow"),
    ("2. Stor overføring til ukjent konto", "red", "approved"),
    ("3. Personopplysninger ut av huset", "red", "rejected"),
    ("4. Over den harde grensen", "block", "blocked"),
    ("5. Et tillegg som vil installeres", "block", "blocked"),
    ("6. Ingen svarer", "red", "waiting"),
]


@pytest.fixture()
def ren_app():
    """Appens egen tilstand, nullstilt. Loggen ligger i testens tmp-mappe.

    Vi lager ikke en ny `DemoState`: appen har alt en, og to av dem kan ikke
    holde den samme loggen samtidig - det er med vilje (`LonewatchAlreadyRunning`).
    """
    from ui import app as uiapp

    uiapp.state.reset()
    return uiapp.state


@pytest.fixture()
def manus(ren_app):
    """Hele manuset spilt en gang, med linjene det skrev."""
    linjer: list[str] = []
    client = scripted_demo.InProcessClient(state=ren_app)
    resultat = scripted_demo.run(client, log=linjer.append)
    return client, resultat, linjer


# ---------------------------------------------------------------------------
# manuset ender der vi sier det ender
# ---------------------------------------------------------------------------


def test_manuset_gir_samme_seks_avgjoerelser_hver_gang(manus):
    _, resultat, _ = manus
    faktisk = [(r["overskrift"], r["verdict"], r["status"]) for r in resultat]
    assert faktisk == FORVENTET


def test_feil_beloep_godkjenner_ingenting_og_riktig_beloep_gjoer_det(manus):
    _, resultat, _ = manus
    svar = resultat[1]["answers"]
    # Først feil beløp (avvist), så riktig (godtatt). Rekkefølgen er poenget.
    assert [(a["typed"], a["ok"]) for a in svar] == [("45000", False), ("450000", True)]
    assert "GODKJENT" in resultat[1]["reply"]
    assert "450000 kr" in resultat[1]["reply"]


def test_det_blokkerte_kallet_faar_ingen_regelnavn(manus):
    _, resultat, _ = manus
    svar = resultat[3]["reply"]
    assert "BLOKKERT" in svar
    for regel in ("hard_limit", "amount_over_limit", "recipient_unknown", "sandbox_blocked"):
        assert regel not in svar


def test_agenten_som_ga_opp_lot_kortet_ligge_og_skrev_ingenting(manus):
    client, resultat, _ = manus
    siste = resultat[5]
    assert "INGEN SVARTE" in siste["reply"]
    # Kortet venter fortsatt på et menneske, og ingen HumanResponse er skrevet.
    assert client.state.agent_status(siste["request_id"])["status"] == "waiting"
    rader = client.state.log_rows()["rows"]
    menneskesvar = [r for r in rader if r.get("kind") == "human"]
    assert all(r.get("request_id") != siste["request_id"] for r in menneskesvar)


def test_loggen_stemmer_etter_hele_manuset(manus):
    client, _, _ = manus
    verify = client.state.verify()
    assert verify["ok"] is True
    assert verify["lines"] > 0


def test_sandkassen_kjoerte_tillegget_foer_avgjoerelsen(manus):
    _, _, linjer = manus
    tekst = "\n".join(linjer)
    assert "Sandkassen: nordlys-mail-connector-patch" in tekst
    # Etterligningen skal ha PRØVD å sende data, uten at noe ble sendt.
    assert "ingenting ble sendt" in tekst


def test_hvert_slag_sier_hva_agenten_leste(manus):
    _, resultat, linjer = manus
    assert sum(1 for ln in linjer if "agenten leser:" in ln) >= len(resultat)
    # Og hver gang står det at det er simulert, der noe "ble utført".
    for rad in resultat:
        if "UTFØRT (simulert)" in rad["reply"]:
            assert "simulering" in rad["reply"]


# ---------------------------------------------------------------------------
# reserven er ikke avhengig av oppsett
# ---------------------------------------------------------------------------


def test_kommandoen_virker_i_en_terminal_uten_noe_oppsatt(tmp_path):
    """Hele poenget med reserven: `python -m agent_gateway.scripted_demo` alene.

    Vi starter den som en egen prosess med ALLE LONEWATCH_*-variabler fjernet,
    slik en som bare har klonet mappen ville hatt det. Den skal lage sine egne
    nøkler, sin egen midlertidige logg, og spille alle seks slagene.
    """
    import os
    import subprocess
    import sys

    env = {k: v for k, v in os.environ.items() if not k.startswith("LONEWATCH_")}
    env["PYTHONPATH"] = str(Path(oppsett.ROOT))
    # Ingen API-nøkkel skal være i miljøet når vi påstår at den ikke trengs.
    env.pop("ANTHROPIC_API_KEY", None)

    ferdig = subprocess.run(
        [sys.executable, "-m", "agent_gateway.scripted_demo"],
        cwd=str(oppsett.ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )

    assert ferdig.returncode == 0, ferdig.stderr
    ut = ferdig.stdout
    for overskrift, verdict, status in FORVENTET:
        assert overskrift in ut
        assert f"{verdict:<6} {status:<9}" in ut
    assert "kjeden stemmer" in ut
    assert "Ingen API-nøkkel ble brukt." in ut

    # Den midlertidige loggen skal ikke ligge igjen.
    for linje in ut.splitlines():
        if "midlertidig mappe:" in linje:
            sti = Path(linje.split("midlertidig mappe:")[1].strip())
            assert not sti.exists()
            assert not sti.parent.exists()
            break
    else:  # pragma: no cover - linjen skrives alltid
        pytest.fail("demoen sa ikke hvor loggen laa")


def test_manuset_apner_ingen_socket(ren_app, monkeypatch):
    """Ingen del av flyten skal ut på nettet - heller ikke til 127.0.0.1."""
    import socket

    def nekt(*_a, **_k):  # pragma: no cover - skal aldri kalles
        raise AssertionError("Reserven forsøkte å åpne en socket.")

    monkeypatch.setattr(socket, "socket", nekt)
    monkeypatch.setattr(socket, "create_connection", nekt)

    client = scripted_demo.InProcessClient(state=ren_app)
    resultat = scripted_demo.run(client, log=lambda _ln: None)
    assert len(resultat) == len(FORVENTET)


# ---------------------------------------------------------------------------
# oppsettet
# ---------------------------------------------------------------------------


def test_oppsettet_lager_begge_filene_og_holder_noekkelen_for_seg(tmp_path):
    svar = oppsett.setup(root=tmp_path, python="/sti/til/python", env_source={})

    env_fil = tmp_path / ".lonewatch-agent-env"
    mcp_fil = tmp_path / ".mcp.json"
    assert env_fil.exists() and mcp_fil.exists()
    assert set(svar["created"]) == set(oppsett.KEYS)
    assert svar["kept"] == []

    # Returverdien skal kunne skrives ut uten å lekke noe.
    tekst = json.dumps(svar)
    for linje in env_fil.read_text(encoding="utf-8").splitlines():
        if "=" in linje and not linje.startswith("#"):
            verdi = linje.partition("=")[2]
            assert verdi and verdi not in tekst


def test_oppsettet_skriver_den_samme_agentnoekkelen_i_mcp_filen(tmp_path):
    oppsett.setup(root=tmp_path, python="/sti/til/python", env_source={})

    fra_env = oppsett.read_env_file(tmp_path / ".lonewatch-agent-env")
    mcp = json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))
    server = mcp["mcpServers"]["lonewatch"]

    assert server["env"]["LONEWATCH_AGENT_KEY"] == fra_env["LONEWATCH_AGENT_KEY"]
    assert server["command"] == "/sti/til/python"
    assert server["args"] == ["-m", "agent_gateway"]
    assert server["env"]["LONEWATCH_AGENT_URL"].startswith("http://127.0.0.1")
    assert server["env"]["PYTHONPATH"] == str(tmp_path)


def test_oppsettet_kjoert_to_ganger_beholder_noeklene(tmp_path):
    """Ellers ville en ny kjøring gjort loggen du alt har skrevet uleselig."""
    oppsett.setup(root=tmp_path, python="/p", env_source={})
    foerst = oppsett.read_env_file(tmp_path / ".lonewatch-agent-env")

    svar = oppsett.setup(root=tmp_path, python="/p", env_source={})
    etterpaa = oppsett.read_env_file(tmp_path / ".lonewatch-agent-env")

    assert foerst == etterpaa
    assert set(svar["kept"]) == set(oppsett.KEYS)
    assert svar["created"] == []


def test_oppsettet_tar_vare_paa_noekler_som_alt_staar_i_miljoeet(tmp_path):
    fra_miljo = {"LONEWATCH_AGENT_KEY": "en-noekkel-som-alt-fins-xxxxxxxx"}
    svar = oppsett.setup(root=tmp_path, python="/p", env_source=fra_miljo)

    assert "LONEWATCH_AGENT_KEY" in svar["kept"]
    mcp = json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))
    assert (
        mcp["mcpServers"]["lonewatch"]["env"]["LONEWATCH_AGENT_KEY"]
        == fra_miljo["LONEWATCH_AGENT_KEY"]
    )


def test_oppsettet_rorer_ikke_andre_mcp_tjenere(tmp_path):
    (tmp_path / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"noe-annet": {"command": "x"}}}), encoding="utf-8"
    )
    oppsett.setup(root=tmp_path, python="/p", env_source={})

    mcp = json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))
    assert mcp["mcpServers"]["noe-annet"] == {"command": "x"}
    assert "lonewatch" in mcp["mcpServers"]


def test_en_odelagt_mcp_fil_blir_skrevet_paa_nytt(tmp_path):
    (tmp_path / ".mcp.json").write_text("{ dette er ikke json", encoding="utf-8")
    oppsett.setup(root=tmp_path, python="/p", env_source={})

    mcp = json.loads((tmp_path / ".mcp.json").read_text(encoding="utf-8"))
    assert "lonewatch" in mcp["mcpServers"]


def test_begge_filene_er_bare_lesbare_for_deg(tmp_path):
    oppsett.setup(root=tmp_path, python="/p", env_source={})
    for navn in (".lonewatch-agent-env", ".mcp.json"):
        modus = stat.S_IMODE((tmp_path / navn).stat().st_mode)
        assert modus & (stat.S_IRGRP | stat.S_IROTH) == 0


def test_begge_filene_staar_i_prosjektets_gitignore():
    """Hemmeligheter skal ikke kunne committes ved et uhell."""
    linjer = {
        ln.strip()
        for ln in (Path(oppsett.ROOT) / ".gitignore").read_text(encoding="utf-8").splitlines()
    }
    assert ".mcp.json" in linjer
    assert ".lonewatch-agent-env" in linjer


def test_oppsettet_sier_fra_hvis_en_fil_ikke_er_ignorert(tmp_path):
    svar = oppsett.setup(root=tmp_path, python="/p", env_source={})
    # tmp_path har ingen .gitignore, saa begge skal rapporteres som IKKE ignorert.
    assert svar["env_ignored"] is False
    assert svar["mcp_ignored"] is False
