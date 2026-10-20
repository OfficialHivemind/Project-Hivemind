"""The socket between the bot and the GUI.

They have to be separate processes. The bot lives inside the nested Hyprland it
drives and holds a virtual keyboard; the GUI must stay in the KDE session where
the owner can actually see and click it. So they talk over a unix socket in
newline-delimited JSON -- one event per line, the format `telemetry.events`
already produces.

Why plain blocking sockets in threads rather than asyncio: the GUI needs a
reader thread regardless, because Qt owns its own event loop and will not share
one. Making the bot side asyncio too would mean bridging two loops for no gain.
A queue and a writer thread is less code and fails in more obvious ways.

Design rules that matter here:

  * a dead GUI must never stall the bot. Sends go to a bounded queue and are
    DROPPED when it fills, because the alternative -- blocking the agent mid-walk
    because nobody is reading a log -- is far worse than losing a log line.
  * a dead bot must never hang the GUI. The client reconnects on its own and
    reports connection state rather than raising.
  * the bot runs fine with no GUI attached at all. Nothing here is required for
    the agent to play.

WINDOWS (RL6): CPython has no AF_UNIX there [verified: cpython gh-77589], so
the same lines go over TCP on 127.0.0.1, an ephemeral port. Any local user
can connect to a loopback port, so the server writes "<port> <token>" to the
endpoint file (in the per-user runtime dir, 0600 where that means anything)
and a client's FIRST line must be that token, compared in constant time,
before it is sent anything or heard; anything else is closed. Linux keeps
its unix socket, byte for byte.
"""
from __future__ import annotations

import hmac
import os
import queue
import secrets
import socket
import threading
import time
from pathlib import Path
from typing import Callable

from ..telemetry.events import Event, from_json

DEFAULT_SOCKET = str(Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) /
                     "hivemind.sock")
TCP = os.name == "nt"                       # see WINDOWS above
if TCP:                                     # pragma: no cover (Windows)
    from ..datapaths import runtime_dir
    DEFAULT_SOCKET = str(runtime_dir() / "hivemind.endpoint")
TOKEN_WAIT_S = 5.0                          # how long a TCP client has to say its token


def read_endpoint(path) -> tuple[int, str] | None:
    """(port, token) from a TCP endpoint file, or None."""
    try:
        port, token = Path(path).read_text().split()
        return int(port), token
    except (OSError, ValueError):
        return None
QUEUE_LIMIT = 512

# How many distinct state rows to keep for replay. Seventeen fields, a handful
# of metrics and a few quests is well under this; the cap is only here so that
# a runaway emitter cannot turn a snapshot into a memory leak.
SNAPSHOT_LIMIT = 200          # ~a few seconds of chatter; see the drop rule above


def connect(path: str | None = None, timeout: float = 3.0) -> socket.socket:
    """A connected socket to the bot, as a one-shot client (scripts/
    telegram_alerts): the unix socket, or on Windows loopback TCP with the
    token already said. OSError when no bot is listening."""
    path = path or DEFAULT_SOCKET                   # read now: tests repoint it
    if TCP:
        found = read_endpoint(path)
        if found is None:
            raise FileNotFoundError(path)
        s = socket.create_connection(("127.0.0.1", found[0]), timeout=timeout)
        s.sendall((found[1] + "\n").encode())
        return s
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        s.settimeout(timeout)
        s.connect(path)
    except OSError:
        s.close()
        raise
    return s


class EventServer:
    """Bot side. Broadcasts events; receives answers from the GUI."""

    def __init__(self, path: str = DEFAULT_SOCKET,
                 on_message: Callable[[Event], None] | None = None):
        self.path = path
        self.on_message = on_message
        self._clients: list[socket.socket] = []
        self._lock = threading.Lock()
        self._q: queue.Queue[str] = queue.Queue(maxsize=QUEUE_LIMIT)
        self._stop = threading.Event()
        self._sock: socket.socket | None = None
        self.dropped = 0
        # THE LAST OF EACH KIND OF STATE, REPLAYED TO WHOEVER CONNECTS NEXT.
        #
        # Most of what the GUI draws arrives ONCE: the quest list is read at
        # startup, the field ranking and the plan are emitted at the start of a
        # cycle, and a cycle is fifteen minutes long. A GUI that attaches after
        # those have gone past therefore draws nothing at all, and the owner
        # sees an application full of empty panels while the bot is plainly
        # working -- which is exactly what happened: "none of these tabs are
        # showing for ne", with the honey counter in the same window ticking up.
        #
        # So the server remembers the latest of each thing worth redrawing and
        # hands it to a new client. Keyed so that a second field row replaces
        # the first rather than accumulating, and capped, because this is a
        # snapshot of the present and not a history.
        self._latest: dict[str, str] = {}

    def start(self) -> "EventServer":
        if TCP:
            return self._start_tcp()
        # A stale socket file from a crashed run would make bind() fail, and the
        # GUI would silently connect to nothing. Remove it only if no one is
        # listening, so we can never clobber a live server.
        if os.path.exists(self.path):
            probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                probe.connect(self.path)
                probe.close()
                raise RuntimeError(f"a server is already listening on {self.path}")
            except (ConnectionRefusedError, FileNotFoundError):
                os.unlink(self.path)
            finally:
                probe.close()

        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.bind(self.path)
        self._sock.listen(4)
        self._sock.settimeout(0.5)
        threading.Thread(target=self._accept_loop, daemon=True).start()
        threading.Thread(target=self._write_loop, daemon=True).start()
        return self

    def _start_tcp(self) -> "EventServer":
        from ..files import atomic_write
        found = read_endpoint(self.path)
        if found is not None:
            try:
                socket.create_connection(("127.0.0.1", found[0]), timeout=0.5).close()
                raise RuntimeError(f"a server is already listening on port {found[0]} "
                                   f"({self.path})")
            except OSError:
                pass                                 # stale: replaced below
        self._token = secrets.token_hex(16)
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(4)
        self._sock.settimeout(0.5)
        atomic_write(self.path, f"{self._sock.getsockname()[1]} {self._token}\n", mode=0o600)
        threading.Thread(target=self._accept_loop, daemon=True).start()
        threading.Thread(target=self._write_loop, daemon=True).start()
        return self

    def _admit(self, conn: socket.socket) -> None:
        """TCP: the client's first line must be our token; else it is closed
        having been sent and told nothing."""
        buf, deadline = b"", time.monotonic() + TOKEN_WAIT_S
        while b"\n" not in buf and len(buf) <= 256 and time.monotonic() < deadline:
            try:
                chunk = conn.recv(256)
            except (socket.timeout, TimeoutError):
                continue
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
        line, _, rest = buf.partition(b"\n")
        if not hmac.compare_digest(line.strip(), self._token.encode()):
            conn.close()
            return
        self._welcome(conn, rest)

    def _accept_loop(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._sock.accept()
            except (socket.timeout, TimeoutError):
                continue
            except OSError:
                return
            # A timeout is REQUIRED, not a nicety. Without one the reader thread
            # blocks in recv() forever, and CPython defers the real close() of a
            # descriptor another thread is using -- so stop() would close the
            # socket object without ever sending FIN, and an attached GUI would
            # go on believing the bot was alive. MEASURED: the reconnect test
            # hung on exactly this.
            conn.settimeout(0.5)
            if TCP:
                threading.Thread(target=self._admit, args=(conn,), daemon=True).start()
                continue
            self._welcome(conn)

    def _welcome(self, conn: socket.socket, buf: bytes = b"") -> None:
        """A client let in: the snapshot, then its reader."""
        with self._lock:
            self._clients.append(conn)
            snapshot = list(self._latest.values())
        # Straight down the socket rather than through the queue: a client
        # that has just arrived should see the current state before the
        # next live event, and the queue is shared with every other client.
        for line in snapshot:
            try:
                conn.sendall((line + "\n").encode())
            except OSError:
                break
        threading.Thread(target=self._read_loop, args=(conn, buf),
                         daemon=True).start()

    def _read_loop(self, conn: socket.socket, buf: bytes = b"") -> None:
        while not self._stop.is_set():
            try:
                chunk = conn.recv(4096)
            except (socket.timeout, TimeoutError):
                continue          # idle client; loop so _stop is honoured
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                event = from_json(line.decode("utf-8", "replace"))
                if event is not None and self.on_message:
                    self.on_message(event)
        with self._lock:
            if conn in self._clients:
                self._clients.remove(conn)
        conn.close()

    def _write_loop(self) -> None:
        while not self._stop.is_set():
            try:
                line = self._q.get(timeout=0.3)
            except queue.Empty:
                continue
            data = (line + "\n").encode()
            with self._lock:
                dead = []
                for c in self._clients:
                    try:
                        c.sendall(data)
                    except OSError:
                        dead.append(c)
                for c in dead:
                    self._clients.remove(c)
                    c.close()

    # What a newcomer needs to draw the panels, and what it does not. Frames
    # are excluded on purpose: they are 20 a second and the live view has its
    # own path. Logs and thoughts are a stream, not a state -- except the plan
    # thought, which is what tells the goal web what is being done now.
    # "shadow_price", not "price" (DESIGN 8du): that is ShadowPrice.kind, and
    # the old spelling matched nothing, so a window opened mid-run had an
    # empty Economy tab for up to a minute (brain/dashboard EVERY_SECONDS).
    REPLAYABLE = {"status", "metric", "considered", "field", "quest", "belief",
                  "planter", "timer", "expiry", "shadow_price", "task",
                  # the stream's field vote, so a stream window opened mid-trip
                  # still has the ballot the bot published at its start (8dv)
                  "chat_ballot"}

    def _remember(self, event: Event, line: str) -> None:
        kind = getattr(event, "kind", "")
        if kind == "thought" and getattr(event, "topic", "") != "plan":
            return
        if kind != "thought" and kind not in self.REPLAYABLE:
            return
        # Keyed so the newest of each row wins: one entry per metric name, per
        # field, per price, per quest STEP, rather than a growing pile. A price
        # is named by its `resource` and a quest row by `giver` AND `step`;
        # without those every price shared one key and each quest kept only
        # its last requirement (DESIGN 8du).
        key = "|".join(str(part) for part in (
            kind,
            getattr(event, "name", ""),
            getattr(event, "giver", ""),
            getattr(event, "step", ""),
            getattr(event, "resource", ""),
            getattr(event, "id", ""),
            getattr(event, "topic", ""),
        ))
        with self._lock:
            if len(self._latest) < SNAPSHOT_LIMIT or key in self._latest:
                self._latest[key] = line

    def send(self, event: Event) -> bool:
        """Queue an event. False means it was dropped; never blocks."""
        line = event.to_json()
        self._remember(event, line)
        try:
            self._q.put_nowait(line)
            return True
        except queue.Full:
            self.dropped += 1
            return False

    @property
    def client_count(self) -> int:
        with self._lock:
            return len(self._clients)

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            for c in self._clients:
                c.close()
            self._clients.clear()
        if self._sock:
            self._sock.close()
        if os.path.exists(self.path):
            try:
                os.unlink(self.path)
            except OSError:
                pass

    def __enter__(self): return self.start()
    def __exit__(self, *exc): self.stop()


class EventClient:
    """GUI side. Reconnects by itself and never raises at the caller."""

    def __init__(self, path: str = DEFAULT_SOCKET,
                 on_event: Callable[[Event], None] | None = None,
                 on_state: Callable[[bool], None] | None = None,
                 retry_s: float = 2.0):
        self.path = path
        self.on_event = on_event
        self.on_state = on_state
        self.retry_s = retry_s
        self.connected = False
        self._sock: socket.socket | None = None
        self._stop = threading.Event()

    def start(self) -> "EventClient":
        threading.Thread(target=self._loop, daemon=True).start()
        return self

    def _set_state(self, value: bool) -> None:
        if value != self.connected:
            self.connected = value
            if self.on_state:
                self.on_state(value)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                if TCP:
                    found = read_endpoint(self.path)
                    if found is None:
                        raise FileNotFoundError(self.path)
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.settimeout(1.0)
                    s.connect(("127.0.0.1", found[0]))
                    s.sendall((found[1] + "\n").encode())
                else:
                    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                    s.settimeout(1.0)
                    s.connect(self.path)
                self._sock = s
                self._set_state(True)
                buf = b""
                while not self._stop.is_set():
                    try:
                        chunk = s.recv(8192)
                    except (socket.timeout, TimeoutError):
                        continue
                    if not chunk:
                        break
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        event = from_json(line.decode("utf-8", "replace"))
                        if event is not None and self.on_event:
                            self.on_event(event)
            except (OSError, ConnectionRefusedError, FileNotFoundError):
                pass
            finally:
                self._set_state(False)
                if self._sock:
                    self._sock.close()
                    self._sock = None
            if not self._stop.is_set():
                time.sleep(self.retry_s)

    def send(self, event: Event) -> bool:
        """Send an answer back to the bot. False if not currently connected."""
        s = self._sock
        if s is None:
            return False
        try:
            s.sendall((event.to_json() + "\n").encode())
            return True
        except OSError:
            return False

    def stop(self) -> None:
        self._stop.set()
        if self._sock:
            self._sock.close()
