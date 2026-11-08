"""Koden som kjører INNE i delprosessen, sammen med tillegget.

Denne filen importeres aldri av resten av Lonewatch. Den startes som et skript:

    python -I -B sandbox/harness.py <config.json> <events.jsonl>

Rekkefølgen er viktig og er grunnen til at filen ser ut som den gjør:

    1. vi tar vare på de ekte funksjonene (open, os.open, socket) for oss selv
    2. vi leser oppsettet og kilden til tillegget MENS vi fortsatt har tilgang
    3. vi setter opp sperrene
    4. vi legger SNARER der de ekte funksjonene lå, og tømmer resten
    5. først DA kjører vi tillegget
    6. etterpå sjekker vi at sperrene fortsatt står der vi satte dem

Sperrene:
    nettverk  - socket er byttet ut med en som bare skriver ned adressen og sier nei
    filer     - lesing og skriving utenfor boksen avvises, agnfiler skrives ned
    prosesser - tillegget får ikke starte et nytt program som ville hatt nettverk

Hver sperre er en LUKNING (closure): den holder de ekte funksjonene i sine egne
celler, ikke i modulens globale ordbok. Grunnen er veien `open.__globals__`:
den ordboken kan et tillegg lese, og der lå før `_REAL_BUILTINS_OPEN`. Nå ligger
det en snare der i stedet - et objekt som skriver ned forsøket og nekter. Det er
fortsatt en bom og ikke en vegg: `open.__closure__` er en annen vei til samme
sted, og den stoppes bare av den statiske sjekken i `sandbox/static_check.py`.
Python-isolasjon i samme prosess kan ikke gjøres sikker. Se `sandbox/LIMITS.md`.

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

# Navnet tillegget kjører under. Brukes til å skille tilleggets egne importer
# fra standardbibliotekets.
PLUGIN_MODULE_NAME = "lonewatch_plugin"

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


# ---------------------------------------------------------------- hendelser

def _make_recorder(handle, max_text_chars: int):
    """Lager skriveren til hendelsesfilen, med filen i en lukning.

    Ligger filobjektet i modulens globale ordbok, kan et tillegg som naar den
    ordboken skrive sine EGNE hendelser inn i rapporten om seg selv. Her holder
    skriveren filen for seg selv, og `json.dumps` er hentet inn som en lokal
    variabel, slik at skriveren ikke er avhengig av globale navn vi tømmer.
    """
    dumps = json.dumps

    def record(kind: str, data: dict | None = None) -> None:
        """Skriver én hendelse. Feiler aldri: en sperre må ikke kunne krasje."""
        try:
            handle.write(dumps({"kind": kind, "data": data or {}}, ensure_ascii=False) + "\n")
            handle.flush()
        except Exception:
            pass

    def short(text: object) -> str:
        s = str(text)
        return s if len(s) <= max_text_chars else s[:max_text_chars] + "..."

    return record, short


# ---------------------------------------------------------------- snarer

def _make_tripwire(record):
    """Lager snareklassen. Den står der de ekte funksjonene lå.

    En snare skriver ned at noen strakk seg etter den, og nekter. Den holder
    bare sitt eget navn - skriveren ligger i lukningen til metodene, ikke i et
    felt noen kan lese av objektet (`__slots__`, ingen `__dict__`).

    Dette er en SNARE, ikke en vegg. Den beviser ikke at tillegget ikke kom
    videre; den gjør at den kjente veien blir SETT. Det er forskjellen på en
    rapport som sier `clean` fordi ingenting skjedde, og en som sier `clean`
    fordi ingenting ble forsøkt.
    """

    class _Tripwire:
        __slots__ = ("navn",)

        def __init__(self, navn: str) -> None:
            object.__setattr__(self, "navn", navn)

        def _trip(self, how: str):
            record("guard_bypass", {"name": self.navn, "how": how})
            raise PermissionError(
                13, f"Lonewatch sandkasse: {self.navn} er ikke tilgjengelig for et tillegg"
            )

        def __call__(self, *args, **kwargs):
            self._trip("kall")

        def __getitem__(self, key):
            self._trip(f"oppslag[{key!r}]")

        def __setitem__(self, key, value):
            self._trip(f"skriving[{key!r}]")

        def __getattr__(self, name):
            self._trip(f"attributt .{name}")

        def __iter__(self):
            self._trip("gjennomgang")

        def __repr__(self) -> str:
            return f"<lonewatch-snare {object.__getattribute__(self, 'navn')}>"

    return _Tripwire


def _seal_globals(record) -> None:
    """Bytter ut alt farlig i modulens globale ordbok med snarer.

    Sperrene er lukninger og trenger ikke disse navnene lenger. Det eneste som
    leser dem etter dette er et tillegg som har funnet veien til ordboken -
    altså nøyaktig det vi vil se.
    """
    tripwire = _make_tripwire(record)
    g = globals()
    navn = [n for n in g if n.startswith("_REAL_")] + [
        "_io_core",
        "_OS_CORE",
        "_make_recorder",
        "_make_tripwire",
        "_seal_globals",
        "_install_network_guard",
        "_install_process_guard",
        "_install_file_guard",
        "_install_import_guard",
        "_check_guards",
        "main",
    ]
    for n in navn:
        if n in g:
            g[n] = tripwire(n)


# ---------------------------------------------------------------- nettverk

def _address_text(address: object, short) -> str:
    """Gjør en adresse om til "vert:port", uansett hvilken form den kom i."""
    if isinstance(address, (tuple, list)) and len(address) >= 2:
        return f"{address[0]}:{address[1]}"
    if isinstance(address, bytes):
        return address.decode("utf-8", "replace")
    return short(address)


def _blocked_error(what: str) -> OSError:
    # OSError er det samme som socket.error, så vanlig nettverkskode fanger den
    # og tror den mistet dekningen. Det er med vilje: tillegget skal ikke lett
    # kunne se forskjell på "sperret" og "nettet er nede".
    return OSError(101, f"Lonewatch sandkasse: nettverk er sperret ({what})")


def _install_network_guard(record, short) -> dict:
    import socket

    def adresse(value: object) -> str:
        return _address_text(value, short)

    class _BlockedSocket:
        """Står der socket.socket sto. Kobler aldri til noe."""

        def __init__(self, family=-1, type=-1, proto=-1, fileno=None):
            self.family, self.type, self.proto = family, type, proto
            record("network_socket", {"family": str(family), "type": str(type)})

        # Forsøk på å komme ut.
        def connect(self, address):
            record("network_connect", {"destination": adresse(address)})
            raise _blocked_error("connect")

        def connect_ex(self, address):
            record("network_connect", {"destination": adresse(address)})
            return 101

        def sendto(self, data, *args):
            destination = args[-1] if args else "ukjent"
            record("network_send", {"destination": adresse(destination), "bytes": len(data or b"")})
            raise _blocked_error("sendto")

        def sendall(self, *args, **kwargs):
            record("network_send", {"destination": "ikke tilkoblet", "bytes": 0})
            raise _blocked_error("sendall")

        send = sendall

        def recv(self, *args, **kwargs):
            raise _blocked_error("recv")

        def bind(self, address):
            record("network_bind", {"destination": adresse(address)})
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

    def blocked_lookup(name: str):
        def guard(*args, **kwargs):
            destination = adresse(args[:2] if len(args) >= 2 else (args[0] if args else "ukjent"))
            record("network_lookup", {"destination": destination, "call": name})
            raise _blocked_error(name)

        return guard

    def blocked_connect(*args, **kwargs):
        address = args[0] if args else kwargs.get("address", "ukjent")
        record("network_connect", {"destination": adresse(address)})
        raise _blocked_error("create_connection")

    socket.socket = _BlockedSocket
    socket.SocketType = _BlockedSocket
    socket.create_connection = blocked_connect
    socket.create_server = blocked_lookup("create_server")
    for name in ("getaddrinfo", "gethostbyname", "gethostbyname_ex", "gethostbyaddr", "getnameinfo"):
        if hasattr(socket, name):
            setattr(socket, name, blocked_lookup(name))

    # Ett lag under: et tillegg som henter socket rett fra C-modulen skal også
    # treffe veggen.
    try:
        import _socket

        _socket.socket = _BlockedSocket
        for name in ("getaddrinfo", "gethostbyname"):
            if hasattr(_socket, name):
                setattr(_socket, name, blocked_lookup(name))
    except Exception:
        pass

    return {"socket_class": _BlockedSocket}


# ---------------------------------------------------------------- filer

def _install_file_guard(record, short, cfg: dict) -> dict:
    """Setter opp filsperren. De ekte funksjonene blir lukninger, ikke globale."""
    real_open = _REAL_BUILTINS_OPEN
    real_os_open = _REAL_OS_OPEN
    real_fileio = _REAL_FILEIO
    real_open_code = _REAL_OPEN_CODE
    io_core = _io_core
    os_core = _OS_CORE

    realpath = os.path.realpath
    fspath = os.fspath
    sep = os.sep
    o_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC

    bait = dict(cfg.get("bait", {}))
    read_roots = tuple(cfg.get("read_roots", ()))
    write_roots = tuple(cfg.get("write_roots", ()))
    seen_bait: set[str] = set()

    def under(path: str, root: str) -> bool:
        return path == root or path.startswith(root.rstrip(sep) + sep)

    def check_path(path: object, write: bool, call: str) -> None:
        """Sier nei hvis stien er utenfor boksen, og skriver ned agnlesing."""
        if isinstance(path, int):  # allerede åpen fil, ikke en sti
            return
        try:
            resolved = realpath(fspath(path))
        except Exception:
            return

        label = bait.get(resolved)
        if label is not None and resolved not in seen_bait:
            seen_bait.add(resolved)
            record("secret_read", {"path": resolved, "label": label, "write": write})

        roots = write_roots if write else read_roots
        if any(under(resolved, root) for root in roots):
            return

        record("denied_file", {"path": resolved, "call": call, "write": write})
        raise PermissionError(13, f"Lonewatch sandkasse: ingen tilgang utenfor boksen ({call})")

    def guarded_open(file, mode="r", *args, **kwargs):
        write = any(ch in str(mode) for ch in ("w", "a", "x", "+"))
        check_path(file, write, "open")
        return real_open(file, mode, *args, **kwargs)

    def guarded_os_open(path, flags, *args, **kwargs):
        write = bool(flags & o_flags)
        check_path(path, write, "os.open")
        return real_os_open(path, flags, *args, **kwargs)

    def guarded_listing(name: str, real):
        def guard(path=".", *args, **kwargs):
            check_path(path, False, name)
            return real(path, *args, **kwargs)

        return guard

    def guarded_mutation(name: str, real):
        def guard(path, *args, **kwargs):
            check_path(path, True, name)
            return real(path, *args, **kwargs)

        return guard

    guarded_fileio = None
    if real_fileio is not None:

        class _GuardedFileIO(real_fileio):
            """Står der _io.FileIO sto. Samme fil, men stien sjekkes først."""

            def __init__(self, file, mode="r", closefd=True, opener=None):
                check_path(file, any(ch in str(mode) for ch in ("w", "a", "x", "+")), "FileIO")
                super().__init__(file, mode, closefd=closefd, opener=opener)

        guarded_fileio = _GuardedFileIO

    def guarded_open_code(path):
        check_path(path, False, "open_code")
        return real_open_code(path)

    builtins.open = guarded_open
    io.open = guarded_open
    if io_core is not None:
        io_core.open = guarded_open
        if guarded_fileio is not None:
            io_core.FileIO = guarded_fileio
            io.FileIO = guarded_fileio
        if real_open_code is not None:
            io_core.open_code = guarded_open_code
            io.open_code = guarded_open_code

    # `os` OG `posix`: os.open ER posix.open, så begge navnene må byttes.
    for module in (os, os_core):
        if module is None:
            continue
        if hasattr(module, "open"):
            module.open = guarded_os_open
        for name in ("listdir", "scandir"):
            if hasattr(module, name):
                setattr(module, name, guarded_listing(name, getattr(module, name)))
        for name in (
            "remove", "unlink", "rmdir", "mkdir", "makedirs",
            "rename", "replace", "chmod", "truncate",
        ):
            if hasattr(module, name):
                setattr(module, name, guarded_mutation(name, getattr(module, name)))

    return {"open": guarded_open, "os_open": guarded_os_open}


# ---------------------------------------------------------------- prosesser

def _install_process_guard(record, short) -> dict:
    """Et nytt program ville hatt sitt eget, usperrede nettverk. Derfor nei."""

    def blocked_process(name: str):
        def guard(*args, **kwargs):
            first = args[0] if args else kwargs.get("args", "ukjent")
            record("denied_process", {"call": name, "target": short(first)})
            raise PermissionError(13, f"Lonewatch sandkasse: får ikke starte programmer ({name})")

        return guard

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
                setattr(module, name, blocked_process("os." + name))
    try:
        import _posixsubprocess

        _posixsubprocess.fork_exec = blocked_process("subprocess")
    except Exception:
        pass
    try:
        import subprocess

        subprocess.Popen = blocked_process("subprocess.Popen")
        subprocess.run = blocked_process("subprocess.run")
    except Exception:
        pass
    return {}


# ---------------------------------------------------------------- import

def _install_import_guard(record) -> dict:
    """To lag: en finner i sys.meta_path og en sperre i __import__ selv.
    Et tillegg som tømmer sys.meta_path treffer fortsatt __import__."""
    real_import = _REAL_IMPORT

    def import_is_blocked(root: str) -> bool:
        if root in _NEVER_IMPORT:
            return True
        return root in _NEVER_REIMPORT and root not in sys.modules

    def deny_import(root: str, how: str, requester: str) -> ImportError:
        # Et standardbibliotek som prøver seg forsiktig ("try: import ctypes") er
        # ikke tillegget som angriper oss. Vi skriver det ned, men det er ikke nok
        # til å stoppe tillegget. Bare tilleggets EGNE importer teller.
        from_plugin = requester in (PLUGIN_MODULE_NAME, "?")
        record(
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
            if import_is_blocked(root):
                # Her vet vi ikke hvem som spurte, så vi antar det verste.
                raise deny_import(root, "meta_path", "?")
            return None  # la de vanlige finnerne ta resten

    def guarded_import(name, globals=None, locals=None, fromlist=(), level=0):
        root = name.split(".")[0] if level == 0 else name
        if root and import_is_blocked(root):
            requester = "?"
            if isinstance(globals, dict):
                requester = str(globals.get("__name__", "?"))
            raise deny_import(root, "__import__", requester)
        return real_import(name, globals, locals, fromlist, level)

    sys.meta_path.insert(0, _ImportGuard)
    builtins.__import__ = guarded_import
    return {"import": guarded_import, "import_guard": _ImportGuard}


# ---------------------------------------------------------------- grenser

def _apply_resource_limits(cfg: dict) -> None:
    """Hard bremse i tillegg til klokka utenfor. Best effort: ikke alle
    grenser finnes på alle maskiner, og en manglende grense skal ikke stoppe
    skanningen."""
    try:
        import resource
    except Exception:
        return
    cpu = int(cfg.get("cpu_seconds", 8))
    for name, value in (("RLIMIT_CPU", cpu), ("RLIMIT_FSIZE", int(cfg.get("max_file_bytes", 2_000_000)))):
        limit = getattr(resource, name, None)
        if limit is None:
            continue
        try:
            resource.setrlimit(limit, (value, value))
        except Exception:
            pass


# ---------------------------------------------------------------- etterpå

def _check_guards(record, installed: dict) -> bool:
    """Står sperrene fortsatt der vi satte dem?

    Dette er det eneste BEVISET rapporten har for å si `clean`. Fins ikke
    `guards_intact` i hendelsene, sier rapporten `not_tested` - vi fikk ikke
    sett ferdig etter. Se sandbox/report.py.
    """
    brutt: list[str] = []
    if builtins.open is not installed.get("open"):
        brutt.append("builtins.open")
    if builtins.__import__ is not installed.get("import"):
        brutt.append("builtins.__import__")
    if os.open is not installed.get("os_open"):
        brutt.append("os.open")
    socket_module = sys.modules.get("socket")
    if socket_module is not None and getattr(socket_module, "socket", None) is not installed.get(
        "socket_class"
    ):
        brutt.append("socket.socket")
    if installed.get("import_guard") not in sys.meta_path:
        brutt.append("sys.meta_path")

    if brutt:
        record("guard_tampered", {"guard": ", ".join(brutt)})
        return False
    record("guards_intact", {"checked": "open, __import__, os.open, socket, meta_path"})
    return True


# ---------------------------------------------------------------- kjøring

def main(argv: list[str]) -> int:
    config_path, events_path = argv[1], argv[2]

    with _REAL_BUILTINS_OPEN(config_path, encoding="utf-8") as fh:
        cfg = json.load(fh)
    events = _REAL_BUILTINS_OPEN(events_path, "a", encoding="utf-8")

    record, short = _make_recorder(events, int(cfg.get("max_text_chars", 300)))

    # Kilden leses nå, mens vi fortsatt får lese utenfor boksen.
    with _REAL_BUILTINS_OPEN(cfg["plugin_path"], encoding="utf-8") as fh:
        source = fh.read()

    plugin_path = cfg["plugin_path"]
    package_name = cfg.get("package_name", "")

    _apply_resource_limits(cfg)
    installed: dict = {}
    installed.update(_install_network_guard(record, short))
    installed.update(_install_process_guard(record, short))
    installed.update(_install_file_guard(record, short, cfg))
    installed.update(_install_import_guard(record))  # helt sist: de andre importerer selv

    record("start", {"package": package_name})

    # Tillegget skal ikke få se hvor hendelsesfilen eller oppsettet ligger.
    sys.argv = ["lonewatch_plugin"]

    # Harness-et kjører som __main__, og der lå de ekte funksjonene. Uten dette
    # holder det med
    #     sys.modules["__main__"]._REAL_BUILTINS_OPEN("/etc/passwd")
    # for å gå rundt hele filsperren.
    sys.modules.pop("__main__", None)

    # Alt vi trenger ETTER at ordboken er tømt, må være en lokal variabel nå.
    check_guards = _check_guards

    # Og nå snarene: alt farlig i den globale ordboken byttes ut. Sperrene over
    # er lukninger og trenger ikke navnene lenger, så `open.__globals__` gir
    # ikke lenger de ekte funksjonene - bare noe som skriver ned at noen spurte.
    _seal_globals(record)

    builtins_dict = builtins.__dict__
    namespace = {
        "__name__": PLUGIN_MODULE_NAME,
        "__file__": plugin_path,
        "__builtins__": builtins_dict,
    }
    try:
        code = compile(source, f"<tillegg:{package_name}>", "exec")
        exec(code, namespace)
        entry = namespace.get("run")
        if callable(entry):
            record("result", {"value": short(repr(entry()))})
        else:
            record("no_entry_point", {})
    except BaseException as exc:  # også SystemExit: tillegget får ikke bestemme sluttkoden
        record("plugin_error", {"type": type(exc).__name__, "message": short(exc)})

    # Sjekken må ligge ETTER tillegget: den sier om vi kan stole på det vi så.
    check_guards(record, installed)

    record("done", {})
    try:
        events.close()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
