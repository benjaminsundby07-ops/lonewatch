"""Tester for sandkassen.

De viktigste testene her er ikke at rapporten ser riktig ut, men at tillegget
faktisk ikke kommer ut: `test_naar_aldri_det_ekte_nettverket` setter opp en
ekte lytter på localhost og sjekker at ingen koblet seg til den.
"""

from __future__ import annotations

import socket
import time
from datetime import timezone

import pytest

import sandbox
from contracts import SandboxReport
from sandbox import fake_home

HARMLOSE = ("pdf-helper", "date-utils")
MISTENKELIGE = {
    "free-ai-boost": "telemetry.free-ai-boost.invalid:443",
    "env-sync-helper": "sync.env-helper.invalid:80",
}


# ----------------------------------------------------------- demotilleggene

@pytest.mark.parametrize("navn", HARMLOSE)
def test_harmlose_tillegg_gir_clean(navn):
    rapport = sandbox.scan(navn)
    assert rapport.verdict == "clean"
    assert rapport.attempted_network is False
    assert rapport.destinations == []
    assert rapport.package_name == navn


@pytest.mark.parametrize("navn,adresse", sorted(MISTENKELIGE.items()))
def test_mistenkelige_tillegg_gir_blocked_med_riktig_adresse(navn, adresse):
    rapport = sandbox.scan(navn)
    assert rapport.verdict == "blocked"
    assert rapport.attempted_network is True
    assert adresse in rapport.destinations


def test_mistenkelige_tillegg_blir_tatt_for_agnfilene():
    rapport = sandbox.scan("free-ai-boost")
    assert "ssh" in rapport.notes
    rapport = sandbox.scan("env-sync-helper")
    assert "miljofilen" in rapport.notes


def test_rapporten_foelger_kontrakten():
    rapport = sandbox.scan("pdf-helper")
    assert isinstance(rapport, SandboxReport)
    assert rapport.ts.tzinfo is not None
    assert rapport.ts.utcoffset() == timezone.utc.utcoffset(None)
    assert rapport.verdict in ("clean", "blocked")


def test_alle_fire_demotillegg_finnes():
    tilgjengelige = sandbox.available_packages()
    for navn in sandbox.DEMO_PACKAGES:
        assert navn in tilgjengelige


@pytest.mark.parametrize("navn", ["finnes-ikke", "../contracts", "sandbox/runner", "", "Store-Bokstaver"])
def test_ukjent_pakkenavn_blir_avvist(navn):
    with pytest.raises(sandbox.UnknownPackage):
        sandbox.scan(navn)


# ----------------------------------------------------------- tidsgrensen

def test_tidsgrensen_virker():
    start = time.monotonic()
    rapport = sandbox.scan(sandbox.HANGING_PACKAGE, timeout_s=1.5)
    brukt = time.monotonic() - start

    assert rapport.verdict == "blocked"
    assert "tidsgrensen" in rapport.notes
    # Den skal stoppes av oss, ikke av at tillegget gir seg (det gjør det aldri).
    assert brukt < 12.0


def test_tidsgrensen_dreper_prosessen_men_beholder_hendelsene():
    """Et tillegg som prøver nettverket og SÅ henger skal fortsatt bli
    rapportert med adressen. Hendelsene skrives fortløpende nettopp for
    dette."""
    kilde = (
        "import socket, time\n"
        "def run():\n"
        "    try:\n"
        "        socket.create_connection(('sent.tillegg.invalid', 8080), timeout=1)\n"
        "    except OSError:\n"
        "        pass\n"
        "    while True:\n"
        "        time.sleep(0.05)\n"
    )
    rapport = sandbox.run_plugin_source("sent-tillegg", kilde, timeout_s=2.0)
    assert rapport.verdict == "blocked"
    assert rapport.attempted_network is True
    assert "sent.tillegg.invalid:8080" in rapport.destinations
    assert "tidsgrensen" in rapport.notes


# ----------------------------------------------------------- ekte nettverk

def test_naar_aldri_det_ekte_nettverket():
    """Den viktigste testen: en ekte lytter på localhost, et tillegg som gjør
    sitt beste for å nå den, og null tilkoblinger."""
    lytter = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    lytter.bind(("127.0.0.1", 0))
    lytter.listen(1)
    lytter.settimeout(2.0)
    port = lytter.getsockname()[1]

    kilde = f"""
import socket, urllib.request

PORT = {port}

def run():
    forsok = []
    # 1. vanlig create_connection
    try:
        s = socket.create_connection(("127.0.0.1", PORT), timeout=1)
        s.sendall(b"kom gjennom 1")
        forsok.append("create_connection KOM GJENNOM")
    except BaseException as exc:
        forsok.append("create_connection stoppet")
    # 2. raa socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.connect(("127.0.0.1", PORT))
        s.sendall(b"kom gjennom 2")
        forsok.append("socket KOM GJENNOM")
    except BaseException as exc:
        forsok.append("socket stoppet")
    # 3. socket rett fra C-modulen
    try:
        import _socket
        s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
        s.connect(("127.0.0.1", PORT))
        forsok.append("_socket KOM GJENNOM")
    except BaseException as exc:
        forsok.append("_socket stoppet")
    # 4. http
    try:
        urllib.request.urlopen(f"http://127.0.0.1:{{PORT}}/", timeout=1)
        forsok.append("http KOM GJENNOM")
    except BaseException as exc:
        forsok.append("http stoppet")
    return forsok
"""
    try:
        rapport = sandbox.run_plugin_source("nettverkstest", kilde, timeout_s=15.0)
        assert rapport.attempted_network is True
        assert f"127.0.0.1:{port}" in rapport.destinations
        assert rapport.verdict == "blocked"

        # Ingen rakk å koble seg til. accept() skal gå i tidsgrensen.
        with pytest.raises((TimeoutError, socket.timeout)):
            lytter.accept()
    finally:
        lytter.close()


# ----------------------------------------------------------- resten av boksen

def test_tillegget_far_ikke_lese_utenfor_boksen(tmp_path):
    hemmelig = tmp_path / "ekte-fil-utenfor-boksen.txt"
    hemmelig.write_text("denne skal tillegget ikke se", encoding="utf-8")

    kilde = (
        "def run():\n"
        f"    return open({str(hemmelig)!r}, encoding='utf-8').read()\n"
    )
    rapport = sandbox.run_plugin_source("filtest", kilde, timeout_s=10.0)
    assert rapport.verdict == "blocked"
    assert "utenfor boksen" in rapport.notes
    assert hemmelig.read_text(encoding="utf-8") == "denne skal tillegget ikke se"


def test_tillegget_far_ikke_skrive_utenfor_boksen(tmp_path):
    maal = tmp_path / "skal-ikke-bli-laget.txt"
    kilde = (
        "def run():\n"
        f"    open({str(maal)!r}, 'w').write('hei')\n"
    )
    rapport = sandbox.run_plugin_source("skrivetest", kilde, timeout_s=10.0)
    assert rapport.verdict == "blocked"
    assert not maal.exists()


def test_tillegget_far_ikke_starte_programmer():
    kilde = (
        "import os, subprocess\n"
        "def run():\n"
        "    svar = []\n"
        "    for kall in (lambda: os.system('echo nei'),\n"
        "                 lambda: subprocess.Popen(['echo', 'nei']),\n"
        "                 lambda: os.fork()):\n"
        "        try:\n"
        "            kall()\n"
        "            svar.append('KOM GJENNOM')\n"
        "        except BaseException:\n"
        "            svar.append('stoppet')\n"
        "    return svar\n"
    )
    rapport = sandbox.run_plugin_source("prosesstest", kilde, timeout_s=10.0)
    assert rapport.verdict == "blocked"
    assert "starte" in rapport.notes
    assert "KOM GJENNOM" not in rapport.notes


def test_tillegget_ser_den_falske_hjemmemappen():
    kilde = (
        "import os\n"
        "def run():\n"
        "    hjem = os.path.expanduser('~')\n"
        "    return sorted(os.listdir(hjem))\n"
    )
    rapport = sandbox.run_plugin_source("hjemmetest", kilde, timeout_s=10.0)
    # Å liste den falske hjemmemappen er lov, så dette er clean.
    assert rapport.verdict == "clean"


def test_tillegget_far_ikke_importere_lonewatch():
    kilde = (
        "def run():\n"
        "    import contracts\n"
        "    return 'KOM GJENNOM'\n"
    )
    rapport = sandbox.run_plugin_source("importtest", kilde, timeout_s=10.0)
    assert "KOM GJENNOM" not in rapport.notes
    assert "ModuleNotFoundError" in rapport.notes


def test_noklene_til_lonewatch_foelger_ikke_med_inn():
    kilde = (
        "import os\n"
        "def run():\n"
        "    return [n for n in os.environ if 'LONEWATCH' in n.upper()]\n"
    )
    rapport = sandbox.run_plugin_source("miljotest", kilde, timeout_s=10.0)
    assert "LONEWATCH" not in rapport.notes.upper()
    assert rapport.verdict == "clean"


def test_et_tillegg_som_krasjer_blir_rapportert():
    kilde = "def run():\n    raise RuntimeError('noe gikk galt')\n"
    rapport = sandbox.run_plugin_source("krasjtest", kilde, timeout_s=10.0)
    assert "krasjet" in rapport.notes
    # En krasj alene er ikke mistenkelig: tillegget kom ingen vei.
    assert rapport.verdict == "clean"


# ----------------------------------------------------------- de falske filene

def test_alle_agnfiler_finnes_i_den_falske_hjemmemappen():
    for rel in fake_home.BAIT:
        assert rel in fake_home.FAKE_FILES


def test_de_falske_filene_sier_at_de_er_falske():
    for rel in fake_home.BAIT:
        innhold = fake_home.FAKE_FILES[rel]
        assert "FALSK" in innhold, rel


def test_den_falske_hjemmemappen_blir_bygget(tmp_path):
    hjem = fake_home.build(tmp_path / "hjem")
    for rel in fake_home.FAKE_FILES:
        assert (hjem / rel).is_file()
    agn = fake_home.bait_map(hjem)
    assert len(agn) == len(fake_home.BAIT)
    for sti in agn:
        assert sti.startswith(str(hjem.resolve()))


def test_boksen_ryddes_opp_etter_skanning():
    import tempfile
    from pathlib import Path

    foer = {p.name for p in Path(tempfile.gettempdir()).glob("lonewatch-*")}
    sandbox.scan("date-utils")
    etter = {p.name for p in Path(tempfile.gettempdir()).glob("lonewatch-*")}
    assert etter <= foer


# ----------------------------------------------------------- kjente omveier
#
# Disse testene er omveiene vi faktisk fant da vi prøvde å bryte ut av vår egen
# sandkasse. Alle fem virket før de ble stengt, og den femte fikk en ekte
# tilkobling ut på internett. De står her for at de ikke skal åpne seg igjen.

OMVEIER = {
    # ctypes kan kalle rett på operativsystemet og gå rundt alt vi gjør i Python.
    "ctypes": "import ctypes\nctypes.CDLL(None).socket(2, 1, 0)",
    # os.open ER posix.open. Byttet vi bare navnet i os, sto posix åpen.
    "posix_open": "import posix\nposix.open('/etc/hosts', 0)",
    # io er bare et skall rundt C-modulen _io.
    "io_core_fileio": "import _io\n_io.FileIO('/etc/hosts')",
    "io_core_open": "import _io\n_io.open('/etc/hosts')",
    # Fersk import av _socket ga en usperret socket-modul.
    "fersk_socket": (
        "import sys\n"
        "del sys.modules['_socket']\n"
        "import _socket\n"
        "s = _socket.socket(2, 1, 0)\n"
        "s.connect(('1.1.1.1', 80))"
    ),
    # Samme sak etter at tillegget har tømt sys.meta_path.
    "meta_path_tommes": "import sys\nsys.meta_path.clear()\nimport ctypes",
}


@pytest.mark.parametrize("navn,angrep", sorted(OMVEIER.items()))
def test_kjente_omveier_er_stengt(navn, angrep):
    kilde = "def run():\n    try:\n        " + angrep.replace("\n", "\n        ") + (
        "\n        return 'KOM GJENNOM'\n"
        "    except BaseException as exc:\n"
        "        return 'stoppet: %s' % type(exc).__name__\n"
    )
    rapport = sandbox.run_plugin_source("omvei-" + navn, kilde, timeout_s=15.0)
    assert "KOM GJENNOM" not in rapport.notes, f"{navn} kom gjennom: {rapport.notes}"
    assert rapport.verdict == "blocked", rapport.notes


def test_standardbiblioteket_blir_ikke_tatt_for_en_omvei():
    """pathlib gjør "try: import nt" på macOS, og uuid prøver seg på ctypes.
    Et harmlost tillegg som bruker dem skal fortsatt bli clean."""
    kilde = (
        "import pathlib, uuid, json, datetime\n"
        "def run():\n"
        "    return {'sti': str(pathlib.Path('.').resolve().name),\n"
        "            'uuid': str(uuid.uuid5(uuid.NAMESPACE_DNS, 'lonewatch'))}\n"
    )
    rapport = sandbox.run_plugin_source("standardbibliotek", kilde, timeout_s=15.0)
    assert rapport.verdict == "clean", rapport.notes
