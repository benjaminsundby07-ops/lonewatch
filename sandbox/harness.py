"""Koden som kjører INNE i delprosessen, sammen med tillegget.

Denne filen importeres aldri av resten av Lonewatch. Den startes som et skript:

    python -I -B sandbox/harness.py <config.json> <events.jsonl>

Rekkefølgen er viktig og er grunnen til at filen ser ut som den gjør:

    1. vi tar vare på de ekte funksjonene (open, os.open, socket) for oss selv
    2. vi leser oppsettet og kilden til tillegget MENS vi fortsatt har tilgang
    3. vi setter opp sperrene
    4. foerst DA kjører vi tillegget

Sperrene:
    nettverk  - socket er byttet ut med en som bare skriver ned adressen og sier nei
    filer     - lesing og skriving utenfor boksen avvises, agnfiler skrives ned
    prosesser - tillegget får ikke starte et nytt program som ville hatt nettverk

Alt tillegget gjør skrives som én JSON-linje per hendelse til hendelsesfilen.
Den filen ligger utenfor boksen, så tillegget kan ikke lese eller endre den.
Vi skriver fortløpende og tømmer bufferet hver gang, slik at hendelsene finnes
også når delprosessen blir drept av tidsgrensen.
"""

from __future__ import annotations

import builtins
import io
import json
import os
import sys

# Fanget før noen sperre settes opp. Alt harness-et selv gjør går gjennom disse,
# så våre egne filskriv blir aldri stoppet av våre egne sperrer.
_REAL_BUILTINS_OPEN = builtins.open
_REAL_IO_OPEN = io.open
_REAL_OS_OPEN = os.open
_REAL_IMPORT = builtins.__import__

# `io` er bare et skall rundt C-modulen `_io`. Sperrer vi bare `io`, kommer et
# tillegg utenom med `import _io`. Derfor tar vi vare på begge lagene.
try:
    import _io as _io_core

    _REAL_FILEIO = _io_core.FileIO
    _REAL_OPEN_CODE = getattr(_io_core, "open_code", None)
except Exception:  # pragma: no cover - _io finnes i alle CPython-er vi bryr oss om
    _io_core = None
    _REAL_FILEIO = None
    _REAL_OPEN_CODE = None

# Samme sak for `os`: den henter alt fra `posix` (eller `nt`). Begge må sperres.
_OS_CORE = sys.modules.get("posix") or sys.modules.get("nt")

_events = None
_cfg: dict = {}
_read_roots: tuple[str, ...] = ()
_write_roots: tuple[str, ...] = ()
_bait: dict[str, str] = {}
_seen_bait: set[str] = set()


# ---------------------------------------------------------------- hendelser

def _short(text: object) -> str:
    s = str(text)
    limit = int(_cfg.get("max_text_chars", 300))
    return s if len(s) <= limit else s[:limit] + "..."


def _record(kind: str, data: dict | None = None) -> None:
    """Skriver én hendelse. Feiler aldri: en sperre må ikke kunne krasje."""
    if _events is None:
        return
    try:
        _events.write(json.dumps({"kind": kind, "data": data or {}}, ensure_ascii=False) + "\n")
        _events.flush()
    except Exception:
        pass


# ---------------------------------------------------------------- nettverk

def _address_text(address: object) -> str:
    """Gjør en adresse om til "vert:port", uansett hvilken form den kom i."""
    if isinstance(address, (tuple, list)) and len(address) >= 2:
        return f"{address[0]}:{address[1]}"
    if isinstance(address, bytes):
        return address.decode("utf-8", "replace")
    return _short(address)


def _blocked_error(what: str) -> OSError:
    # OSError er det samme som socket.error, så vanlig nettverkskode fanger den
    # og tror den mistet dekningen. Det er med vilje: tillegget skal ikke lett
    # kunne se forskjell på "sperret" og "nettet er nede".
    return OSError(101, f"Lonewatch sandkasse: nettverk er sperret ({what})")


class _BlockedSocket:
    """Står der socket.socket sto. Kobler aldri til noe."""

    def __init__(self, family=-1, type=-1, proto=-1, fileno=None):
        self.family, self.type, self.proto = family, type, proto
        _record("network_socket", {"family": str(family), "type": str(type)})

    # Forsøk på å komme ut.
    def connect(self, address):
        _record("network_connect", {"destination": _address_text(address)})
        raise _blocked_error("connect")

    def connect_ex(self, address):
        _record("network_connect", {"destination": _address_text(address)})
        return 101

    def sendto(self, data, *args):
        destination = args[-1] if args else "ukjent"
        _record("network_send", {"destination": _address_text(destination), "bytes": len(data or b"")})
        raise _blocked_error("sendto")

    def sendall(self, *args, **kwargs):
        _record("network_send", {"destination": "ikke tilkoblet", "bytes": 0})
        raise _blocked_error("sendall")

    send = sendall

    def recv(self, *args, **kwargs):
        raise _blocked_error("recv")

    def bind(self, address):
        _record("network_bind", {"destination": _address_text(address)})
        raise _blocked_error("bind")

    def listen(self, *args):
        raise _blocked_error("listen")

    def accept(self):
        raise _blocked_error("accept")

    # Resten er ufarlig og finnes bare for at vanlig kode ikke skal krasje
    # paa en annen maate enn den vi vil vise.
    def settimeout(self, *args):
        return None

    def setsockopt(self, *args, **kwargs):
        return None

    def getsockopt(self, *args, **kwargs):
        return 0

    def setblocking(self, *args):
        return None

    def fileno(self):
        return -1

    def makefile(self, *args, **kwargs):
        raise _blocked_error("makefile")

    def close(self):
        return None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def _blocked_lookup(name: str):
    def guard(*args, **kwargs):
        destination = _address_text(args[:2] if len(args) >= 2 else (args[0] if args else "ukjent"))
        _record("network_lookup", {"destination": destination, "call": name})
        raise _blocked_error(name)

    return guard


def _blocked_connect(*args, **kwargs):
    address = args[0] if args else kwargs.get("address", "ukjent")
    _record("network_connect", {"destination": _address_text(address)})
    raise _blocked_error("create_connection")


def _install_network_guard() -> None:
    import socket

    socket.socket = _BlockedSocket
    socket.SocketType = _BlockedSocket
    socket.create_connection = _blocked_connect
    socket.create_server = _blocked_lookup("create_server")
    for name in ("getaddrinfo", "gethostbyname", "gethostbyname_ex", "gethostbyaddr", "getnameinfo"):
        if hasattr(socket, name):
            setattr(socket, name, _blocked_lookup(name))

    # Ett lag under: et tillegg som henter socket rett fra C-modulen skal også
    # treffe veggen.
    try:
        import _socket

        _socket.socket = _BlockedSocket
        for name in ("getaddrinfo", "gethostbyname"):
            if hasattr(_socket, name):
                setattr(_socket, name, _blocked_lookup(name))
    except Exception:
        pass


# ---------------------------------------------------------------- filer

def _resolve(path: object) -> str:
    return os.path.realpath(os.fspath(path))


def _under(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def _check_path(path: object, write: bool, call: str) -> None:
    """Sier nei hvis stien er utenfor boksen, og skriver ned agnlesing."""
    if isinstance(path, int):  # allerede åpen fil, ikke en sti
        return
    try:
        resolved = _resolve(path)
    except Exception:
        return

    label = _bait.get(resolved)
    if label is not None and resolved not in _seen_bait:
        _seen_bait.add(resolved)
        _record("secret_read", {"path": resolved, "label": label, "write": write})

    roots = _write_roots if write else _read_roots
    if any(_under(resolved, root) for root in roots):
        return

    _record("denied_file", {"path": resolved, "call": call, "write": write})
    raise PermissionError(13, f"Lonewatch sandkasse: ingen tilgang utenfor boksen ({call})")


def _guarded_open(file, mode="r", *args, **kwargs):
    write = any(ch in str(mode) for ch in ("w", "a", "x", "+"))
    _check_path(file, write, "open")
    return _REAL_BUILTINS_OPEN(file, mode, *args, **kwargs)


def _guarded_os_open(path, flags, *args, **kwargs):
    write = bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC))
    _check_path(path, write, "os.open")
    return _REAL_OS_OPEN(path, flags, *args, **kwargs)


def _guarded_listing(name: str, real):
    def guard(path=".", *args, **kwargs):
        _check_path(path, False, name)
        return real(path, *args, **kwargs)

    return guard


def _guarded_mutation(name: str, real):
    def guard(path, *args, **kwargs):
        _check_path(path, True, name)
        return real(path, *args, **kwargs)

    return guard


class _GuardedFileIO(_REAL_FILEIO if _REAL_FILEIO is not None else object):
    """Står der _io.FileIO sto. Samme fil, men stien sjekkes først."""

    def __init__(self, file, mode="r", closefd=True, opener=None):
        _check_path(file, any(ch in str(mode) for ch in ("w", "a", "x", "+")), "FileIO")
        super().__init__(file, mode, closefd=closefd, opener=opener)


def _guarded_open_code(path):
    _check_path(path, False, "open_code")
    return _REAL_OPEN_CODE(path)


def _install_file_guard() -> None:
    builtins.open = _guarded_open
    io.open = _guarded_open
    if _io_core is not None:
        _io_core.open = _guarded_open
        if _REAL_FILEIO is not None:
            _io_core.FileIO = _GuardedFileIO
            io.FileIO = _GuardedFileIO
        if _REAL_OPEN_CODE is not None:
            _io_core.open_code = _guarded_open_code
            io.open_code = _guarded_open_code

    # `os` OG `posix`: os.open ER posix.open, så begge navnene må byttes.
    for module in (os, _OS_CORE):
        if module is None:
            continue
        if hasattr(module, "open"):
            module.open = _guarded_os_open
        for name in ("listdir", "scandir"):
            if hasattr(module, name):
                setattr(module, name, _guarded_listing(name, getattr(module, name)))
        for name in (
            "remove", "unlink", "rmdir", "mkdir", "makedirs",
            "rename", "replace", "chmod", "truncate",
        ):
            if hasattr(module, name):
                setattr(module, name, _guarded_mutation(name, getattr(module, name)))


# ---------------------------------------------------------------- prosesser

def _blocked_process(name: str):
    def guard(*args, **kwargs):
        first = args[0] if args else kwargs.get("args", "ukjent")
        _record("denied_process", {"call": name, "target": _short(first)})
        raise PermissionError(13, f"Lonewatch sandkasse: får ikke starte programmer ({name})")

    return guard


def _install_process_guard() -> None:
    """Et nytt program ville hatt sitt eget, usperrede nettverk. Derfor nei."""
    names = (
        "system", "fork", "forkpty", "posix_spawn", "posix_spawnp", "popen",
        "execv", "execve", "execvp", "execvpe", "execl", "execle", "execlp",
        "spawnv", "spawnve", "spawnvp", "spawnl", "spawnle",
    )
    for module in (os, _OS_CORE):
        if module is None:
            continue
        for name in names:
            if hasattr(module, name):
                setattr(module, name, _blocked_process("os." + name))
    try:
        import _posixsubprocess

        _posixsubprocess.fork_exec = _blocked_process("subprocess")
    except Exception:
        pass
    try:
        import subprocess

        subprocess.Popen = _blocked_process("subprocess.Popen")
        subprocess.run = _blocked_process("subprocess.run")
    except Exception:
        pass


# ---------------------------------------------------------------- import

# Moduler et tillegg aldri får hente inn. `ctypes` er den viktigste: med den
# kan et tillegg kalle rett på operativsystemet og gå rundt alt vi har gjort
# over, fordi sperrene våre bare ligger i Python.
_NEVER_IMPORT = frozenset({"ctypes", "_ctypes"})

# Moduler et tillegg får BRUKE (de ligger ferdig sperret i sys.modules), men
# ikke hente inn på nytt. Trikset vi stenger er:
#     del sys.modules["_socket"]; import _socket   -> fersk, usperret modul
# Bare kjernemodulen som finnes på DENNE maskinen. Tar vi med begge, vil
# `pathlib` sin helt vanlige "try: import nt" på macOS se ut som et angrep.
_NEVER_REIMPORT = frozenset({
    "_socket", "socket", "subprocess", "_posixsubprocess",
    "multiprocessing", "_multiprocessing",
    "nt" if os.name == "nt" else "posix",
})

# Navnet tillegget kjører under. Brukes til å skille tilleggets egne importer
# fra standardbibliotekets.
PLUGIN_MODULE_NAME = "lonewatch_plugin"


def _import_is_blocked(root: str) -> bool:
    if root in _NEVER_IMPORT:
        return True
    return root in _NEVER_REIMPORT and root not in sys.modules


def _deny_import(root: str, how: str, requester: str) -> ImportError:
    # Et standardbibliotek som prøver seg forsiktig ("try: import ctypes") er
    # ikke tillegget som angriper oss. Vi skriver det ned, men det er ikke nok
    # til å stoppe tillegget. Bare tilleggets EGNE importer teller.
    from_plugin = requester in (PLUGIN_MODULE_NAME, "?")
    _record(
        "denied_import" if from_plugin else "denied_import_internal",
        {"module": root, "how": how, "requester": requester},
    )
    return ImportError(f"Lonewatch sandkasse: modulen {root!r} er sperret")


class _ImportGuard:
    """Ligger først i sys.meta_path. Blir bare spurt om moduler som ikke
    allerede ligger i sys.modules - altså nettopp de ferske importene."""

    @staticmethod
    def find_spec(fullname, path=None, target=None):
        root = fullname.split(".")[0]
        if _import_is_blocked(root):
            # Her vet vi ikke hvem som spurte, så vi antar det verste.
            raise _deny_import(root, "meta_path", "?")
        return None  # la de vanlige finnerne ta resten


def _guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
    root = name.split(".")[0] if level == 0 else name
    if root and _import_is_blocked(root):
        requester = "?"
        if isinstance(globals, dict):
            requester = str(globals.get("__name__", "?"))
        raise _deny_import(root, "__import__", requester)
    return _REAL_IMPORT(name, globals, locals, fromlist, level)


def _install_import_guard() -> None:
    """To lag: en finner i sys.meta_path og en sperre i __import__ selv.
    Et tillegg som tømmer sys.meta_path treffer fortsatt __import__."""
    sys.meta_path.insert(0, _ImportGuard)
    builtins.__import__ = _guarded_import


# ---------------------------------------------------------------- grenser

def _apply_resource_limits() -> None:
    """Hard bremse i tillegg til klokka utenfor. Best effort: ikke alle
    grenser finnes på alle maskiner, og en manglende grense skal ikke stoppe
    skanningen."""
    try:
        import resource
    except Exception:
        return
    cpu = int(_cfg.get("cpu_seconds", 8))
    for name, value in (("RLIMIT_CPU", cpu), ("RLIMIT_FSIZE", int(_cfg.get("max_file_bytes", 2_000_000)))):
        limit = getattr(resource, name, None)
        if limit is None:
            continue
        try:
            resource.setrlimit(limit, (value, value))
        except Exception:
            pass


# ---------------------------------------------------------------- kjøring

def main(argv: list[str]) -> int:
    global _events, _cfg, _read_roots, _write_roots, _bait

    config_path, events_path = argv[1], argv[2]

    with _REAL_BUILTINS_OPEN(config_path, encoding="utf-8") as fh:
        _cfg = json.load(fh)
    _events = _REAL_BUILTINS_OPEN(events_path, "a", encoding="utf-8")

    # Kilden leses nå, mens vi fortsatt får lese utenfor boksen.
    with _REAL_BUILTINS_OPEN(_cfg["plugin_path"], encoding="utf-8") as fh:
        source = fh.read()

    _bait = dict(_cfg.get("bait", {}))
    _write_roots = tuple(_cfg.get("write_roots", ()))
    _read_roots = tuple(_cfg.get("read_roots", ()))

    _apply_resource_limits()
    _install_network_guard()
    _install_process_guard()
    _install_file_guard()
    _install_import_guard()  # helt sist: de andre sperrene importerer selv

    _record("start", {"package": _cfg.get("package_name", "")})

    # Tillegget skal ikke få se hvor hendelsesfilen eller oppsettet ligger.
    sys.argv = ["lonewatch_plugin"]

    namespace = {
        "__name__": "lonewatch_plugin",
        "__file__": _cfg["plugin_path"],
        "__builtins__": builtins.__dict__,
    }
    try:
        code = compile(source, f"<tillegg:{_cfg.get('package_name', '')}>", "exec")
        exec(code, namespace)
        entry = namespace.get("run")
        if callable(entry):
            _record("result", {"value": _short(repr(entry()))})
        else:
            _record("no_entry_point", {})
    except BaseException as exc:  # også SystemExit: tillegget får ikke bestemme sluttkoden
        _record("plugin_error", {"type": type(exc).__name__, "message": _short(exc)})

    _record("done", {})
    try:
        _events.close()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
