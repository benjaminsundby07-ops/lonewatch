"""Setter opp boksen, starter delprosessen og henter hendelsene ut igjen.

Oppsettet per skanning:

    <boks>/home/      falsk hjemmemappe (HOME peker hit)
    <boks>/work/      arbeidsmappe (cwd peker hit)
    <boks>/tmp/       TMPDIR
    <styring>/        oppsett, kilden til tillegget og hendelsesfilen

Styringsmappen ligger UTENFOR boksen med vilje. Harness-et leser den før
sperrene settes opp, og etter det er den utenfor rekkevidde: et tillegg som
prøver å lese hendelsesfilen eller endre agnlisten får PermissionError.

Delprosessen startes med `python -I`, som gjør tre ting vi er ute etter:
mappen til skriptet kommer ikke på sys.path (tillegget kan ikke importere
Lonewatch), brukerens site-packages er borte, og alle PYTHON*-miljøvariabler
blir ignorert. Miljøet bygges fra null, så ingen av nøklene til Lonewatch
følger med inn.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from contracts import SandboxReport

from . import config, fake_home
from .report import build_report

HARNESS = Path(__file__).with_name("harness.py")
PACKAGES_DIR = Path(__file__).with_name("packages")


class UnknownPackage(ValueError):
    """Pakkenavnet finnes ikke blant demotilleggene."""


@dataclass(frozen=True)
class SandboxRun:
    """Rapporten pluss de raa hendelsene fra delprosessen.

    SandboxReport er det mellomstasjonen og UI-et skal se. Hendelsene er for
    oss: de inneholder blant annet hva tillegget RETURNERTE, og det er tekst
    tillegget selv har skrevet. Den teksten skal aldri havne i `notes`, som et
    menneske leser. Testene bruker hendelsene for aa sjekke at et tillegg som
    forsoker aa bryte ut faktisk ikke kom gjennom.
    """

    report: SandboxReport
    events: list[dict] = field(default_factory=list)

    def result_value(self) -> str:
        """Det tillegget returnerte fra run(), som tekst. Tom hvis det krasjet."""
        for event in self.events:
            if event.get("kind") == "result":
                return str(event.get("data", {}).get("value", ""))
        return ""

    def kinds(self) -> list[str]:
        return [str(event.get("kind", "")) for event in self.events]


def available_packages() -> list[str]:
    """Alle tillegg som ligger i sandbox/packages/, med bindestrek i navnet."""
    return sorted(
        path.stem.replace("_", "-")
        for path in PACKAGES_DIR.glob("*.py")
        if not path.name.startswith("_")
    )


def package_path(package_name: str) -> Path:
    """Pakkenavn -> fil. Avviser alt som ikke er et kjedelig navn."""
    if not config.PACKAGE_NAME_PATTERN.match(package_name or ""):
        raise UnknownPackage(f"Ugyldig pakkenavn: {package_name!r}")
    path = PACKAGES_DIR / (package_name.replace("-", "_") + ".py")
    # Dobbeltsjekk mot stier som peker ut av mappen, selv om mønsteret
    # over allerede stopper punktum og skråstrek.
    if path.parent.resolve() != PACKAGES_DIR.resolve() or not path.is_file():
        raise UnknownPackage(f"Ukjent tillegg: {package_name}")
    return path


def _build_env(home: Path, tmp: Path) -> dict[str, str]:
    """Et minimalt miljø. Bygget fra null, ikke kopiert fra vårt eget."""
    env = {
        "HOME": str(home),
        "USERPROFILE": str(home),  # samme idé på Windows
        "TMPDIR": str(tmp),
        "TMP": str(tmp),
        "TEMP": str(tmp),
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "USER": "demo",
        "LOGNAME": "demo",
    }
    if os.name == "nt":  # python nekter å starte uten denne på Windows
        for key in ("SYSTEMROOT", "COMSPEC"):
            if key in os.environ:
                env[key] = os.environ[key]
    return env


def _read_events(events_path: Path) -> list[dict]:
    """Leser hendelsesfilen. Siste linje kan være halv hvis prosessen ble
    drept midt i et skriv, og da hopper vi over den."""
    events: list[dict] = []
    try:
        text = events_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return events
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            event.setdefault("data", {})
            events.append(event)
    return events


def _kill_tree(proc: subprocess.Popen) -> None:
    """Dreper hele prosessgruppen. Delprosessen får sin egen gruppe
    (start_new_session), så dette treffer aldri vår egen prosess."""
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


def run_in_box(
    package_name: str,
    source: str,
    timeout_s: float | None = None,
) -> SandboxRun:
    """Kjører kildekoden til et tillegg i boksen. Gir rapport OG hendelser."""
    timeout = config.DEFAULT_TIMEOUT_S if timeout_s is None else float(timeout_s)

    box = Path(tempfile.mkdtemp(prefix="lonewatch-boks-"))
    control = Path(tempfile.mkdtemp(prefix="lonewatch-styring-"))
    try:
        home = fake_home.build(box / "home")
        work = box / "work"
        tmp = box / "tmp"
        work.mkdir()
        tmp.mkdir()

        plugin_path = control / "tillegg.py"
        plugin_path.write_text(source, encoding="utf-8")
        events_path = control / "hendelser.jsonl"
        events_path.touch()

        # Lesing er lov i boksen og i Python-installasjonen (ellers kan ikke
        # tillegget importere noe som helst). Skriving er bare lov i boksen.
        read_roots = sorted(
            {
                str(box.resolve()),
                *(
                    str(Path(p).resolve())
                    for p in (sys.prefix, sys.base_prefix, sys.exec_prefix, sys.base_exec_prefix)
                ),
                str(Path(os.__file__).parent.resolve()),
            }
        )
        settings = {
            "package_name": package_name,
            "plugin_path": str(plugin_path),
            "bait": fake_home.bait_map(home),
            "read_roots": read_roots,
            "write_roots": [str(box.resolve())],
            "cpu_seconds": int(math.ceil(timeout)) + config.CPU_SECONDS_SLACK,
            "max_file_bytes": config.MAX_FILE_BYTES,
            "max_text_chars": config.MAX_TEXT_CHARS,
        }
        settings_path = control / "oppsett.json"
        settings_path.write_text(json.dumps(settings), encoding="utf-8")

        proc = subprocess.Popen(
            [sys.executable, "-I", "-B", str(HARNESS), str(settings_path), str(events_path)],
            cwd=str(work),
            env=_build_env(home, tmp),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            start_new_session=True,
        )
        timed_out = False
        try:
            _, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            _kill_tree(proc)
            _, stderr = proc.communicate()

        events = _read_events(events_path)
        report = build_report(
            package_name,
            events,
            timed_out=timed_out,
            timeout_s=timeout,
            returncode=proc.returncode,
            stderr=stderr or "",
        )
        return SandboxRun(report=report, events=events)
    finally:
        shutil.rmtree(box, ignore_errors=True)
        shutil.rmtree(control, ignore_errors=True)


def run_plugin_source(
    package_name: str,
    source: str,
    timeout_s: float | None = None,
) -> SandboxReport:
    """Som run_in_box(), men gir bare rapporten.

    scan() bruker denne etter aa ha lest filen. Den er ogsaa inngangen testene
    bruker naar de vil proeve noe som ikke ligger i sandbox/packages/.
    """
    return run_in_box(package_name, source, timeout_s=timeout_s).report


def scan(package_name: str, timeout_s: float | None = None) -> SandboxReport:
    """Kjører et av demotilleggene i boksen og sier clean eller blocked."""
    path = package_path(package_name)
    return run_plugin_source(package_name, path.read_text(encoding="utf-8"), timeout_s=timeout_s)
