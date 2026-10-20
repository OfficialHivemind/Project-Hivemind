"""The Roblox client's own log, read as it is written, and never forwarded.

Sober mirrors the Roblox client's FLog to its standard output, and
`act/bootstrap` has always kept that in var/sober.log (truncated at each
launch) -- and nothing read it. It is the one account of the session that
does not come through pixels: the client says when it joined, when the server
connection was made and lost, and it beats a heartbeat every 20 s for as long
as it runs. It says nothing about where the character is; BSS prints no
position (DESIGN 8dz).

WHAT IT SAYS, MEASURED (research `survey`: logscan.py over 18 Sober session
logs, logtiming.py over 11 bot sessions; and on 2026-09-26 over the 17
session logs Sober then kept, 08:10-16:05, scratchpad fieldsense/logscan2.py):

  "[FLog::Output] ! Joining game ... place <id> ..."   the join: a median 9.7 s
        (8.8-11.8) BEFORE the bot's own pixel "in game" verdict, 11 sessions
  "[FLog::Network] Replicator created: 0x..."          connected: 0.22 s after
        the join line in 11 of 11 (Bloxstrap's GameJoinedEntry)
  "[FLog::CreatorOutput] server version: 624"          the BSS build, 17 of 17
  "onSessionHeartbeat"                                 every 20.0 s: 1,371
        gaps over the 17 session logs Sober kept on 2026-09-26, all within
        0.03 s of 20.0 but one, a beat 6.46 s late at 10:37:56 (attempt
        445, the next one 13.54 s after it, so the rhythm held); a line
        reaches the file 0.81-0.99 s after its own time stamp (loglag.py,
        25 lines of the live session; scratchpad fieldsense2/beats.py)
  "Time to disconnect replication data:"               the server connection
        ended (Bloxstrap's GameDisconnectedEntry), with "Sending disconnect
        with reason: N", "Disconnection Notification. Reason: N",
        "Disconnected from server for reason: ... (Kind)" and "Connection
        lost[: AckTimeout ...]" around it
  "leaveUGCGameInternal"                               back to the app shell
  "doTeleport: joinScriptUrl" / "Teleported."          a teleport, which ends
        one server connection on purpose and joins another
  "FATAL: Crash: ... VK_ERROR_SURFACE_LOST"            at every bot teardown
        (15 of the 15 finished bot sessions: the bot closes the nested
        compositor), so a crash line is no sign of trouble by itself

Evidence for the kick path is thin: none of the bot sessions, and none of 397
run logs the survey read, record a disconnect; the survey saw one reason-278
disconnect and one AckTimeout in the owner's own sessions, and their session of
2026-09-26 13:01-14:39 ended "leaveUGCGameInternal", "Time to disconnect",
"Sending disconnect with reason: 285" and "(DisconnectClientInitiated)" within
45 ms when they left the game. So a disconnect here is acted on exactly as the
world vanishing already is (`brain/alive`): the run stops and the relaunch
rejoins. It only makes that certain and immediate.

PRIVACY. The join line carries the server's JobId and address, the join-time
report the account's user id, the teleport lines the join ticket and URL, and
chat and other players' names pass through too. Nothing here keeps or says any
of it: an event carries its kind, its time, a reason code, the place id (the
public game), the BSS build, and a six-character digest of the JobId -- enough
to say "a different server than last time", not enough to find it.
"""
from __future__ import annotations

import calendar
import hashlib
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from ..datapaths import var

LOG = var("sober.log")

# Bloxstrap's ActivityWatcher polls its log once a second, and a line reaches
# var/sober.log 0.81-0.99 s after its own stamp, so reading more often buys
# nothing.
POLL_SECONDS = 1.0
# The heartbeat's period, MEASURED at 20.0 s (1,370 of 1,371 gaps within
# 0.03 s of it, 17 session logs).
HEARTBEAT_SECONDS = 20.0
# ...and how late one may be before it has been missed: the one late beat
# measured (6.46 s, rounded up), the write lag's measured worst (0.99 s,
# rounded up) and one poll. A client that died is therefore called so at most
# 28.5 s after its last beat, which the world guard waits out with the keys
# up (brain/alive CLIENT_WAIT_AT_MOST).
HEARTBEAT_LATE = 6.5 + 1.0 + POLL_SECONDS

# WHICH LOG, ON WINDOWS. The client writes one Player log per launch, and so
# does Roblox's system-tray process, MEASURED 2026-10-26 on Windows 11
# (docs/pending/windows-platform-check.md): a ~6.5 KB Player log every 4 h,
# "AppState/TrayMode", no join and no heartbeat. The newest log at the start
# of a run can therefore be the tray's (if it wrote at that moment), and a
# relaunch inside one run starts a new log. So with `candidates` the reader
# looks again every REPICK_SECONDS and moves to a newer log that holds a
# session (a join or a heartbeat, SESSION_MARKS): at once to one it has never
# judged a session's before, and to any once its own has gone quiet for a
# missed heartbeat or holds no session at all. A log that holds none is never
# moved to, so the tray's cannot take the place of a game that died, and an
# older session's log is never newer than the one being written.
# ponytail: REPICK_SECONDS is a cost choice (one glob of the logs folder),
# not measured; the game's log beats every 20 s, so a wrong first pick is
# put right within a heartbeat and one REPICK_SECONDS.
REPICK_SECONDS = 5.0
REPICK_JUDGE = 4                  # newer logs judged per look, newest first
SESSION_MARKS = (b"! Joining game", b"onSessionHeartbeat")

# THE REASON CODES, for the log line only: nothing decides on them. Roblox's
# own list (https://en.help.roblox.com/hc/en-us/articles/36639955031060)
# refuses a fetch (HTTP 403); these are its texts as the bloxodes catalogue
# quotes them (https://bloxodes.com/catalog/roblox-errors-and-fixes). 285 and
# 278 are the two the survey found in real logs.
REASONS = {
    260: "a problem receiving data", 261: "an error receiving data",
    262: "a problem sending data", 264: "the account joined from another device",
    266: "the connection timed out", 267: "kicked from the game",
    268: "kicked for unexpected client behaviour",
    271: "the server shut down or kicked the client", 272: "a security key mismatch",
    273: "the game was joined from another device",
    274: "the developer shut the server down", 275: "Roblox shut the server down",
    277: "lost connection to the game server", 278: "idle for 20 minutes",
    279: "failed to connect", 280: "the client is out of date",
    282: "disconnected", 285: "the client left", 286: "out of memory",
    288: "the server shut down",
}
# ...AND WHAT THE NEXT START DOES ABOUT ONE (ROADMAP A10, `end_kind`;
# platform/startfails `loss_wait_s` and `online`). Every disconnect since 19 Oct
# (run-1088..1246, docs/pending/disconnect.md):
# "network" -- MEASURED reason 277 twice (run-1210, run-1244), around an
# internet outage on 26 Oct (Sober "Could not resolve hostname", the Telegram
# poller down too); the second was a flap: the start 40 s later never reached
# home (1245), the one 3 min later got in (1246). 266, 279
# and an AckTimeout are ASSUMED to be the same: each names the connection.
# "shutdown" -- MEASURED reason 275 three times (runs 1101, 1129, 1178); the
# rejoin needs a wait (startfails.SHUTDOWN_REJOIN_S). 271/274/288 ASSUMED alike.
# "idle" -- MEASURED reason 278 once (run-1088): the bot's own main thread hung.
NETWORK_REASONS = frozenset({"266", "277", "279"})
SHUTDOWN_REASONS = frozenset({"271", "274", "275", "288"})

# A Roblox line carries its own UTC stamp: "Roblox: 2026-09-26T01:47:29.311Z,
# 23.311403,f382d6c0,6 [FLog::Output] ! Joining game ...".
STAMP = re.compile(r"(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)(\.\d+)?Z")
CHANNEL = re.compile(r"\[(D?FLog::[A-Za-z0-9_]+)\]\s?(.*)$")
PLACE = re.compile(r"\bplace (\d+)")
JOB = re.compile(r"Joining game '([0-9a-fA-F-]{8,})'")
VERSION = re.compile(r"(?i)^server version: (\d+)\s*$")
REASON = re.compile(r"(?:Sending disconnect with reason|Disconnection Notification\. "
                    r"Reason): (\d+)")
KIND = re.compile(r"Disconnected from server for reason: .*\((\w+)\)")


@dataclass(frozen=True)
class ClientEvent:
    """One thing the client log said, with nothing private in it."""
    kind: str          # join, connected, play, version, heartbeat, teleport,
                       # disconnect, lost, reason (a code), why (its name),
                       # leave, crash
    at: float          # the line's own time (epoch), or when it was read
    detail: str = ""   # a place id, a build, a reason code or kind -- never an id

    def describe(self) -> str:
        return f"{self.kind} {self.detail}".strip()


def _epoch(line: str) -> float | None:
    m = STAMP.search(line)
    if not m:
        return None
    y, mo, d, h, mi, s = (int(m.group(i)) for i in range(1, 7))
    frac = float(m.group(7) or 0.0)
    return calendar.timegm((y, mo, d, h, mi, s, 0, 0, 0)) + frac


def parse(line: str, now: float) -> ClientEvent | None:
    """The event in one log line, or None for the thousands that are not."""
    if line.startswith("FATAL: Crash:"):
        return ClientEvent("crash", now)
    m = CHANNEL.search(line)
    if m is None:
        return None
    channel, text = m.group(1), m.group(2).strip()
    at = _epoch(line) or now
    if "onSessionHeartbeat" in text:
        return ClientEvent("heartbeat", at)
    if channel == "FLog::Output" and text.startswith("! Joining game"):
        place = PLACE.search(text)
        job = JOB.search(text)
        server = (hashlib.sha1(job.group(1).encode()).hexdigest()[:6]
                  if job else "")
        return ClientEvent("join", at, f"place {place.group(1) if place else '?'}"
                                       + (f" server #{server}" if server else ""))
    if text.startswith("Replicator created: "):
        return ClientEvent("connected", at)
    if text.startswith("Entered play session"):
        return ClientEvent("play", at)
    v = VERSION.match(text)
    if v and channel == "FLog::CreatorOutput":
        return ClientEvent("version", at, v.group(1))
    if "doTeleport: joinScriptUrl" in text or text.startswith("Teleported."):
        return ClientEvent("teleport", at)
    if text.startswith("Time to disconnect replication data"):
        return ClientEvent("disconnect", at)
    r = REASON.search(text)
    if r:
        return ClientEvent("reason", at, r.group(1))
    k = KIND.search(text)
    if k:
        return ClientEvent("why", at, k.group(1))
    if text.startswith("Connection lost"):
        return ClientEvent("lost", at, "AckTimeout" if "AckTimeout" in text else "")
    if "leaveUGCGameInternal" in text:
        return ClientEvent("leave", at)
    return None


# A SERVER SWITCH THE OWNER MAKES WHILE THEY HAVE THE CONTROLS (Take Over) IS
# NOT THE CLIENT LEAVING (ROADMAP M11). MEASURED run-1034, 2026-10-16: the
# connection ended "reason 285 ... (DisconnectClientInitiated)" at 21:13:00
# and the client joined another server at 21:13:14 -- 14 s -- while the run
# had already stopped to rejoin, and the relaunch took them back to their own
# server. Inside a handover an ending is given SWITCH_WINDOW_S for a join to
# follow; a join in that time is "they moved servers". The window is generous
# because picking a server in the app by hand takes longer than 14 s, and
# nothing is pressed while they hold the controls.
SWITCH_WINDOW_S = 120.0


def moved_servers(ended: "ClientEvent | None", joined: "ClientEvent | None",
                  window: float = SWITCH_WINDOW_S) -> bool:
    """Did `joined` follow the end of the connection within `window` s?"""
    return (ended is not None and joined is not None
            and 0.0 <= joined.at - ended.at <= window)


def await_switch(ended: "ClientEvent", latest_join, *, window: float = SWITCH_WINDOW_S,
                 clock=time.time, sleep=time.sleep,
                 poll: float = POLL_SECONDS) -> "ClientEvent | None":
    """The join that followed `ended` within `window` (`latest_join()` is the
    reader's newest), or None once the window has passed without one."""
    while True:
        joined = latest_join()
        if moved_servers(ended, joined, window):
            return joined
        if clock() > ended.at + window:
            return None
        sleep(poll)


class ClientLog:
    """Tails var/sober.log, keeps the session's state, and says when the
    server connection ends.

    Read-only: the file is opened, read from where it was left, and closed on
    every poll. A truncation (the next launch) or a new file starts over, and
    so does a newer session's log from `candidates()` (REPICK_SECONDS).
    `on_lost(event)` is called once per session when the connection ends
    outside a teleport; `emit(text)` gets the join, the build and the ending,
    for the run log."""

    def __init__(self, path: Path | str = LOG, *, on_lost=None, emit=None,
                 clock=time.time, poll: float = POLL_SECONDS, candidates=None,
                 repick: float = REPICK_SECONDS):
        self.path = Path(path)
        self.on_lost = on_lost
        self.emit = emit or (lambda text: None)
        self.clock = clock
        self.poll_seconds = float(poll)
        self._offset = 0
        self._inode = None
        self._rest = b""
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.lines = 0
        self.problems = 0
        # RE-PICKING (Windows): `candidates()` lists the logs a session may be
        # in (datapaths.client_logs); None keeps the one path (Linux).
        self._candidates = candidates
        self.repick_seconds = float(repick)
        self._next_repick = 0.0
        self._judged: dict[Path, tuple[int, bool]] = {}   # path -> (bytes scanned, a session's?)
        self._known: set[Path] = set()                     # judged a session's log before
        self.repicks = 0
        self._reset()

    def _reset(self) -> None:
        self.joined: ClientEvent | None = None
        self.connected: ClientEvent | None = None
        self.version: str | None = None
        self.heartbeat: float | None = None
        self.heartbeats = 0
        self.ended: ClientEvent | None = None
        self.reason: str | None = None
        self.why: str | None = None
        self.teleporting = False
        self.crashed = False
        self.joins = 0
        self._pending: ClientEvent | None = None
        self._pending_seen = False

    # ---- reading ------------------------------------------------------------
    def poll(self) -> list[ClientEvent]:
        """Read whatever was appended since the last poll."""
        if self._candidates is not None and self.clock() >= self._next_repick:
            self._next_repick = self.clock() + self.repick_seconds
            self._repick()
        try:
            st = os.stat(self.path)
        except OSError:
            return []
        if self._inode is not None and (st.st_ino != self._inode or st.st_size < self._offset):
            self._offset, self._rest = 0, b""
            self._reset()                       # the next launch's log
        self._inode = st.st_ino
        if st.st_size <= self._offset:
            if self._pending is not None:       # nothing more came: say it now
                event, self._pending = self._pending, None
                self._lost(event)
            return []
        try:
            with open(self.path, "rb") as fh:
                fh.seek(self._offset)
                data = fh.read(st.st_size - self._offset)
        except OSError:
            self.problems += 1
            return []
        self._offset += len(data)
        data = self._rest + data
        lines = data.split(b"\n")
        self._rest = lines.pop()                # a line still being written
        now = self.clock()
        events = []
        for raw in lines:
            self.lines += 1
            event = parse(raw.decode("utf-8", "replace"), now)
            if event is not None:
                self._apply(event)
                events.append(event)
        # SAID ONE POLL LATER, so the reason code is in the message: the
        # client writes the leave, "Time to disconnect", "Sending disconnect
        # with reason: 285" and the "(DisconnectClientInitiated)" line over
        # 45 ms (a session of 2026-09-26), which a poll can
        # split. POLL_SECONDS is the whole cost.
        if self._pending is not None and self._pending_seen:
            event, self._pending = self._pending, None
            self._lost(event)
        self._pending_seen = self._pending is not None
        return events

    def _is_session(self, path: Path) -> bool:
        """Does `path` hold a game session's join or heartbeat? Read once from
        where it was last read, so a growing log is never read twice."""
        scanned, found = self._judged.get(path, (0, False))
        if found:
            return True
        try:
            size = os.stat(path).st_size
            if size < scanned:
                scanned = 0                             # rewritten: from the top
            if size > scanned:
                keep = max(len(mark) for mark in SESSION_MARKS)
                with open(path, "rb") as fh:
                    fh.seek(max(0, scanned - keep))     # a mark split by the last read
                    tail = b""
                    while not found:
                        chunk = fh.read(1 << 20)
                        if not chunk:
                            break
                        text = tail + chunk
                        found = any(mark in text for mark in SESSION_MARKS)
                        tail = text[-keep:]
                    scanned = fh.tell()
        except OSError:
            return False
        self._judged[path] = (scanned, found)
        if found:
            self._known.add(path)
        return found

    def _repick(self) -> None:
        """Move to a newer game session's log when one is there: one never
        judged a session's before (a relaunch, or the game's log beside the
        tray's), or any once this one has gone quiet or holds no session."""
        try:
            mine = os.stat(self.path).st_mtime
        except OSError:
            mine = float("-inf")
        try:
            listed = list(self._candidates())
        except Exception:
            self.problems += 1
            return
        newer = []
        for path in listed:
            path = Path(path)
            try:
                mtime = os.stat(path).st_mtime
            except OSError:
                continue
            if path != self.path and mtime > mine:
                newer.append((mtime, path))
        if not newer:
            return
        quiet = (self.clock() - mine > HEARTBEAT_SECONDS + HEARTBEAT_LATE
                 or not self._is_session(self.path))
        for _, path in sorted(newer, reverse=True)[:REPICK_JUDGE]:
            known = path in self._known
            if self._is_session(path) and (quiet or not known):
                self._switch(path)
                return

    def _switch(self, path: Path) -> None:
        self.path = path
        self._offset, self._inode, self._rest = 0, None, b""
        self._reset()
        self.repicks += 1
        self.emit("the client log: reading a newer game session's log now")

    def _apply(self, event: ClientEvent) -> None:
        kind = event.kind
        if kind == "heartbeat":
            self.heartbeat = event.at
            self.heartbeats += 1
            return
        if kind == "join":
            again = self.joined is not None
            self.joins += 1
            self.joined, self.connected, self.ended = event, None, None
            self.reason, self.why, self.teleporting = None, None, False
            # A connection that ended and was joined again in the same read
            # (the start-up read replays the whole log) is not lost now.
            self._pending, self._pending_seen = None, False
            self.emit(f"the Roblox client joined {event.detail}"
                      + (" (after a teleport)" if again else "")
                      + f" at {time.strftime('%H:%M:%S', time.localtime(event.at))}")
        elif kind == "connected":
            self.connected = event
            if self.joined is not None:
                self.emit(f"the client log: connected to the server "
                          f"{event.at - self.joined.at:.2f} s after the join line")
        elif kind == "version":
            if event.detail != self.version:
                self.version = event.detail
                self.emit(f"the client log: Bee Swarm Simulator's server build "
                          f"is {event.detail}")
        elif kind == "teleport":
            self.teleporting = True
            self.emit("the client log: a teleport")
        elif kind == "reason":
            self.reason = event.detail
        elif kind == "why":
            self.why = event.detail
        elif kind in ("disconnect", "lost", "leave"):
            if self.ended is None and self.connected is not None:
                self.ended = event
                if not self.teleporting:
                    self._pending = event
        elif kind == "crash":
            self.crashed = True

    def _lost(self, event: ClientEvent) -> None:
        self.emit(f"the Roblox client says the server connection ended: "
                  f"{self.describe_end()}")
        if self.on_lost is not None:
            try:
                self.on_lost(event)
            except Exception:
                self.problems += 1

    # ---- questions ------------------------------------------------------------
    def heartbeat_age(self, now: float | None = None) -> float | None:
        """Seconds since the last heartbeat's own stamp; None before one."""
        if self.heartbeat is None:
            return None
        return max(0.0, (self.clock() if now is None else now) - self.heartbeat)

    def alive(self, now: float | None = None) -> bool | None:
        """Is the client still running a session? True while the heartbeat is
        on time and the connection has not ended; False once it has ended or
        a beat has been missed; None when no heartbeat has been seen at all
        (no log, or not joined yet), which says nothing either way."""
        if self.ended is not None and not self.teleporting:
            return False
        age = self.heartbeat_age(now)
        if age is None:
            return None
        return age <= HEARTBEAT_SECONDS + HEARTBEAT_LATE

    def end_kind(self) -> str:
        """"network", "shutdown", "idle" or "other" for an ended connection
        (NETWORK_REASONS, SHUTDOWN_REASONS); "" while it has not ended."""
        if self.ended is None:
            return ""
        if self.reason in NETWORK_REASONS or self.ended.detail == "AckTimeout":
            return "network"
        if self.reason in SHUTDOWN_REASONS:
            return "shutdown"
        return "idle" if self.reason == "278" else "other"

    def describe_end(self) -> str:
        if self.ended is None:
            return "it has not ended"
        code = self.reason
        why = ""
        if code and code.isdigit():
            why = f"reason {code}, {REASONS.get(int(code), 'a code with no known meaning')}"
        elif code:
            why = f"reason {code}"
        if self.why:
            why = f"{why} ({self.why})" if why else f"reason {self.why}"
        what = {"disconnect": "the replication was disconnected",
                "lost": f"connection lost{(' (' + self.ended.detail + ')') if self.ended.detail else ''}",
                "leave": "the client left the game"}.get(self.ended.kind, self.ended.kind)
        stamp = time.strftime("%H:%M:%S", time.localtime(self.ended.at))
        return f"{what}{(' — ' + why) if why else ''}, at {stamp}"

    def describe(self) -> str:
        if self.joined is None:
            return (f"client log: no join read yet ({self.lines:,} lines)"
                    if self.lines else "client log: nothing read")
        age = self.heartbeat_age()
        beat = (f"heartbeat {age:.0f}s ago" if age is not None else "no heartbeat yet")
        end = f"; ended — {self.describe_end()}" if self.ended is not None else ""
        # A crash line is written at every bot teardown (see the module
        # docstring), so it is only said, never acted on: one read before
        # this summary is a client that died while the run was still going.
        crash = "; a 'FATAL: Crash' line was read" if self.crashed else ""
        return (f"client log: {self.joined.detail}, build {self.version or '?'}, "
                f"{beat}, {self.heartbeats} beats{end}{crash}")

    # ---- the background reader ---------------------------------------------
    def start(self) -> "ClientLog":
        """Read what is there now, then keep reading once a POLL_SECONDS."""
        try:
            self.poll()
        except Exception:
            self.problems += 1
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, daemon=True,
                                            name="hivemind-clientlog")
            self._thread.start()
        return self

    def _run(self) -> None:
        while not self._stop.wait(self.poll_seconds):
            try:
                self.poll()
            except Exception:
                self.problems += 1               # reading a log never ends a run

    def stop(self) -> None:
        self._stop.set()
