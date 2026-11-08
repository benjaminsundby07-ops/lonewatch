"""Postfangeren: en liten SMTP-server som lagrer det den får som .eml-filer.

Dette er mottakeren i demoen. Den tar imot e-post slik en ekte postserver gjør,
men sender ingenting videre noe sted: hver melding blir en fil på disk som du
kan åpne i et e-postprogram eller i en tekstredigerer.

    python -m executor.mailcatcher --dir maildrop --port 8025

Den krever ingen pakker utover det som følger med Python, og den krever ikke
internett. `smtpd` i standardbiblioteket ville vært det enkle valget, men den
er fjernet fra Python 3.12, og `aiosmtpd` er en ny avhengighet. Protokollen vi
trenger er liten nok til å skrive selv: EHLO, MAIL FROM, RCPT TO, DATA, QUIT.

Serveren binder seg BARE til loopback. Det er en hard sperre uten
miljøvariabel, fordi en åpen postserver på et nett er et problem for noen
andre enn den som startet den.
"""

from __future__ import annotations

import argparse
import ipaddress
import os
import socketserver
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email import message_from_string
from email.message import EmailMessage
from email.policy import default as default_policy
from pathlib import Path

GREETING = "lonewatch-postfanger"

# Grenser. En postfanger som kan fylle disken er en sårbarhet, ikke et verktøy.
MAX_MESSAGE_BYTES = 1_000_000
MAX_LINE_BYTES = 8192
MAX_RECIPIENTS = 50
HANDLER_TIMEOUT_S = 30.0


@dataclass(frozen=True)
class CaughtMail:
    """Én melding slik den kom inn."""

    path: Path
    envelope_from: str
    recipients: tuple[str, ...]
    raw: str

    def parsed(self) -> EmailMessage:
        """Meldingen lest av standardbiblioteket.

        Vi tolker ikke headerne selv. En lang header brytes over flere linjer
        (avtrykket vårt er 64 tegn og blir alltid brutt), og en egen tolkning
        ville lest den feil.
        """
        return message_from_string(self.raw, policy=default_policy)

    def header(self, name: str) -> str | None:
        """Verdien til en header, brettet ut til én linje.

        En lang header brytes over flere linjer paa veien (avtrykket vaart er
        64 tegn og blir alltid brutt). Her settes den sammen igjen, slik en
        e-postleser ville gjort.
        """
        value = self.parsed().get(name)
        return None if value is None else " ".join(str(value).split())

    @property
    def body(self) -> str:
        message = self.parsed()
        if message.is_multipart():
            return "".join(str(part.get_content()) for part in message.walk() if not part.is_multipart())
        return str(message.get_content())


def _angle(value: str) -> str:
    """'MAIL FROM:<a@b.no>' -> 'a@b.no'. Tar også imot uten vinkelparenteser."""
    text = value.strip()
    start, end = text.find("<"), text.rfind(">")
    if 0 <= start < end:
        return text[start + 1 : end].strip()
    return text.split()[0].strip() if text.split() else ""


@dataclass
class _Envelope:
    sender: str = ""
    recipients: list[str] = field(default_factory=list)

    def reset(self) -> None:
        self.sender = ""
        self.recipients = []


class _Handler(socketserver.StreamRequestHandler):
    timeout = HANDLER_TIMEOUT_S

    @property
    def catcher(self) -> MailCatcher:
        return self.server.catcher  # type: ignore[attr-defined]

    def _say(self, line: str) -> None:
        self.wfile.write(line.encode("utf-8", "replace") + b"\r\n")
        self.wfile.flush()

    def _read_line(self) -> str | None:
        raw = self.rfile.readline(MAX_LINE_BYTES)
        if not raw:
            return None
        return raw.decode("utf-8", "replace").rstrip("\r\n")

    def handle(self) -> None:
        envelope = _Envelope()
        self._say(f"220 {GREETING}")
        while True:
            try:
                line = self._read_line()
            except OSError:
                return
            if line is None:
                return
            verb, _, rest = line.partition(" ")
            verb = verb.upper()

            if verb in ("EHLO", "HELO"):
                envelope.reset()
                if verb == "EHLO":
                    self._say(f"250-{GREETING}")
                    self._say(f"250-SIZE {MAX_MESSAGE_BYTES}")
                    self._say("250 8BITMIME")
                else:
                    self._say(f"250 {GREETING}")
            elif verb == "MAIL":
                envelope.reset()
                envelope.sender = _angle(rest.partition(":")[2])
                self._say("250 OK")
            elif verb == "RCPT":
                if len(envelope.recipients) >= MAX_RECIPIENTS:
                    self._say("452 for mange mottakere")
                    continue
                envelope.recipients.append(_angle(rest.partition(":")[2]))
                self._say("250 OK")
            elif verb == "DATA":
                if not envelope.recipients:
                    self._say("503 ingen mottaker oppgitt")
                    continue
                self._say("354 send meldingen, avslutt med <CRLF>.<CRLF>")
                raw, too_big = self._read_data()
                if too_big:
                    self._say("552 meldingen er for stor")
                else:
                    mail = self.catcher._store(envelope.sender, tuple(envelope.recipients), raw)
                    self._say(f"250 OK lagret som {mail.path.name}")
                envelope.reset()
            elif verb == "RSET":
                envelope.reset()
                self._say("250 OK")
            elif verb == "NOOP":
                self._say("250 OK")
            elif verb == "QUIT":
                self._say("221 ha det")
                return
            elif verb == "":
                self._say("500 tom kommando")
            else:
                self._say(f"502 {verb} er ikke støttet")

    def _read_data(self) -> tuple[str, bool]:
        """Leser meldingen til linjen med bare et punktum.

        Vi leser HELE meldingen til terminatoren selv når den er for stor, slik
        at vi kan svare 552 og holde forbindelsen i orden. Et punktum som er
        doblet av avsenderen (punktum-stuffing) gjøres om til ett igjen.
        """
        lines: list[str] = []
        total = 0
        too_big = False
        while True:
            try:
                raw = self.rfile.readline(MAX_LINE_BYTES)
            except OSError:
                return "\n".join(lines), too_big
            if not raw:
                return "\n".join(lines), too_big
            line = raw.decode("utf-8", "replace").rstrip("\r\n")
            if line == ".":
                return "\n".join(lines), too_big
            if line.startswith(".."):
                line = line[1:]
            total += len(raw)
            if total > MAX_MESSAGE_BYTES:
                too_big = True
                continue
            lines.append(line)

    def handle_timeout(self) -> None:
        return

    def log_message(self, *_: object) -> None:  # pragma: no cover
        return


class _Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address: tuple[str, int], catcher: MailCatcher) -> None:
        self.catcher = catcher
        super().__init__(address, _Handler)


class MailCatcher:
    """SMTP-server på loopback som lagrer hver melding som en .eml-fil.

    Brukes som en kontekst:

        with MailCatcher(directory="maildrop") as catcher:
            ...   # catcher.port er porten den fikk
    """

    def __init__(
        self,
        directory: str | os.PathLike[str],
        host: str = "127.0.0.1",
        port: int = 0,
    ) -> None:
        if not _is_loopback(host):
            raise ValueError(
                f"Postfangeren binder seg bare til loopback, ikke {host!r}. "
                "En åpen postserver på nettet er ikke en del av dette prosjektet."
            )
        self.directory = Path(directory)
        self._host = host
        self._port = port
        self._server: _Server | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._messages: list[CaughtMail] = []
        self._counter = 0

    # -- start og stopp -----------------------------------------------------

    def start(self) -> MailCatcher:
        if self._server is not None:
            return self
        self.directory.mkdir(parents=True, exist_ok=True)
        self._server = _Server((self._host, self._port), self)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="lonewatch-postfanger",
            daemon=True,
        )
        self._thread.start()
        return self

    def stop(self) -> None:
        server, thread = self._server, self._thread
        self._server, self._thread = None, None
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=5)

    def __enter__(self) -> MailCatcher:
        return self.start()

    def __exit__(self, *_: object) -> None:
        self.stop()

    # -- hva den har fanget -------------------------------------------------

    @property
    def address(self) -> tuple[str, int]:
        if self._server is None:
            return (self._host, self._port)
        host, port = self._server.server_address[:2]
        return (str(host), int(port))

    @property
    def port(self) -> int:
        return self.address[1]

    @property
    def messages(self) -> list[CaughtMail]:
        with self._lock:
            return list(self._messages)

    def eml_files(self) -> list[Path]:
        return sorted(self.directory.glob("*.eml"))

    def clear(self) -> None:
        with self._lock:
            self._messages = []

    # -- selve lagringen ----------------------------------------------------

    def _store(self, sender: str, recipients: tuple[str, ...], raw: str) -> CaughtMail:
        """Skriver meldingen til disk. Kalles fra en tråd per forbindelse.

        Filen skrives først til et midlertidig navn og flyttes på plass med
        os.replace, slik at ingen kan lese en halv .eml-fil.
        """
        with self._lock:
            self._counter += 1
            seq = self._counter
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        path = self.directory / f"{stamp}-{seq:04d}.eml"
        tmp = path.with_suffix(".eml.part")
        # Filen inneholder NØYAKTIG det som kom inn over DATA, uten noe vi har
        # lagt til. Konvoluttens avsender og mottaker holdes utenfor filen og
        # ligger i CaughtMail: de hører til leveringen, ikke til meldingen.
        tmp.write_text(raw if raw.endswith("\n") else raw + "\n", encoding="utf-8")
        os.replace(tmp, path)
        mail = CaughtMail(path=path, envelope_from=sender, recipients=recipients, raw=raw)
        with self._lock:
            self._messages.append(mail)
        return mail


def _is_loopback(host: str) -> bool:
    name = (host or "").strip().strip("[]").lower()
    if name in ("localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"):
        return True
    try:
        return ipaddress.ip_address(name).is_loopback
    except ValueError:
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m executor.mailcatcher",
        description="Liten SMTP-server som lagrer mottatt e-post som .eml-filer.",
    )
    parser.add_argument("--dir", default="maildrop", help="mappen .eml-filene legges i")
    parser.add_argument("--host", default="127.0.0.1", help="må være loopback")
    parser.add_argument("--port", type=int, default=8025)
    args = parser.parse_args(argv)

    catcher = MailCatcher(directory=args.dir, host=args.host, port=args.port)
    with catcher:
        host, port = catcher.address
        # flush: utskriften skal komme fram med én gang også når den leses
        # av et annet program eller skrives til en fil.
        print(f"Postfangeren lytter på {host}:{port}", flush=True)
        print(f"Meldinger lagres i {catcher.directory.resolve()}", flush=True)
        print("Avslutt med Ctrl-C.", flush=True)
        seen = 0
        try:
            while True:
                # Ingen travel venting: vi venter på tråden, og skriver ut når
                # noe har kommet inn.
                threading.Event().wait(0.5)
                meldinger = catcher.messages
                for mail in meldinger[seen:]:
                    print(
                        f"  mottatt -> {mail.path.name}  ({len(mail.recipients)} mottaker(e))",
                        flush=True,
                    )
                seen = len(meldinger)
        except KeyboardInterrupt:
            print("\nStopper.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
