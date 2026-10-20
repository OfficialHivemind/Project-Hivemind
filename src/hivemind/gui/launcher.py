"""Starting and stopping the bot from the GUI, because Play has to start it.

THE OWNER'S REPORT: the Play button did nothing; Play and Stop must work. They
is right, and the reason is
worth writing down because everything around it already worked.

Start already sent `Command(action=START)` down the socket, `brain/controls`
already handled it, and Stop already worked -- releasing every held key and
ending the run. But all of that talks to a bot that is ALREADY RUNNING. With no
`run_farm.py` process there is nothing on the other end of the socket, so the
press went nowhere and the window said "could not send start — not connected to
the bot" in a corner. Pressing Play on a stopped bot did nothing because nothing
in this project could start one except a terminal.

So this is the missing piece: the GUI's own supervisor for the bot process.

THE SECOND REPORT, 2026-09-23: Start and Stop must work with no developer
around, and start the updated version. The
first version of this launched `scripts/run_farm.py` directly, and a bare
run_farm ends at its first rejoin or crash -- so a bot started from the button
was dead within the hour, while the one started from a terminal ran all night
under `scripts/overnight.sh`, which relaunches it from disk (always the current
code) and survives its crashes. Worse, the button only knew about its OWN
child: pressed while the watchdog was running it would have started a SECOND
farm loop, and two loops on one account fight for the keyboard.

So the button now starts the WATCHDOG, and knows about a watchdog it did not
start through the pidfile the watchdog writes for exactly this purpose:

    Play   nothing running   -> clear STOP, launch scripts/overnight.sh, and
                                watch for the bot to connect
           watchdog alive    -> say so (the bot is joining, or between attempts)
           bot connected     -> send START (which is also resume)
    Stop   anything running  -> touch STOP so the watchdog does not relaunch,
                                send STOP down the socket (the keys), then
                                SIGTERM the watchdog -- its trap asks the farm
                                to stop, which releases every held key -- and
                                make sure it all actually exits

WHAT IT WILL NOT DO, and these are the rules the rest of the project already
follows:

  * It never searches for processes by name. It signals the process it
    started, by the pid it holds, or the pid the watchdog wrote to
    `var/night/watchdog.pid` -- a file OUR script writes, checked alive before
    it is believed. `pkill -f sober` is how you kill the owner's own game while
    they are playing, and nothing here will do it.
  * Stop is a REQUEST FIRST. SIGTERM goes to the watchdog, whose trap touches
    STOP and forwards the request to the farm, whose handler is the clean stop
    path -- it releases every held key before exiting. Only if something is
    still alive after a grace period is the group killed, and that is reported
    as the unclean exit it is.
  * It never starts a second bot. A live watchdog pid, whoever started it,
    refuses the launch.
  * IT REFUSES TO LAUNCH FROM A TEST RUN. This is not hypothetical tidiness:
    wiring Play to this module made `tests/unit/test_run_controls.py` --
    which clicks the Start button -- launch a real `run_farm.py` against the
    owner's live account, while they were playing. It failed only because it
    could not reach a display. A test suite must not be able to start
    something that plays somebody's account, so `start()` checks for pytest
    and declines, and says why.

WHERE THE OUTPUT GOES. The watchdog's own ledger, `var/night/attempts.log`,
one line per attempt, plus `var/night/run-NNN.log` per attempt and
`var/night/current.log` pointing at the live one -- the same places a
terminal start writes, so there is one set of logs to read. `var/gui-run.log`
keeps a header line per press.
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from ..datapaths import var
from ..files import pid_running, process_identity, process_parent

# The script the button runs: the watchdog, which runs `scripts/run_farm.py`
# and relaunches it. Same entry point a terminal would use, so there is no
# second way of starting the bot that could behave differently.
SCRIPT = "scripts/overnight.sh"
# WINDOWS (RL6): the same rules in Python, stopped by files and Ctrl+Break
# instead of POSIX signals (hivemind/watchdog says how).
WINDOWS = os.name == "nt"
if WINDOWS:                                          # pragma: no cover (Windows)
    SCRIPT = "src/hivemind/watchdog.py"
CREATE_NEW_PROCESS_GROUP, CREATE_NO_WINDOW = 0x00000200, 0x08000000
UTF8_ENV = {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}   # as hivemind/watchdog's
# The farm itself, as its command line names it -- what a pid read from
# FARM_LOCK or FARM_PIDFILE must still be running to be believed.
FARM_SCRIPT = "scripts/run_farm.py"
# What the watchdog writes and reads. Kept in the library so the window, the
# tests and the script agree on one spelling.
NIGHT_DIR = ("var", "night")
PIDFILE = "watchdog.pid"
# The watchdog's start time, beside its pidfile rather than in it: the pidfile
# stays one bare number (scripts/overnight.sh says why).
WATCHDOG_START = "watchdog.start"
FARM_PIDFILE = "run_farm.pid"
# Held by every run_farm, however it was started (run_farm SHELL_FARM_LOCK).
FARM_LOCK = "farm.lock"
STOP_FILE = "STOP"

# How long to let a SIGTERM be handled before concluding it was ignored. The
# clean stop path has to release keys, tear down the capture and close the
# nested compositor, then the watchdog has to notice STOP and exit; MEASURED
# at a few seconds for the farm, so this is generous.
GRACE_SECONDS = 25.0

# How long after a launch to keep expecting a socket connection before saying
# it did not come up. The game takes about 40 s to reach the world, and the
# watchdog may wait up to 300 s for memory first.
CONNECT_SECONDS = 120.0


@dataclass
class Launch:
    """What happened when the button was pressed."""
    ok: bool = False
    pid: int | None = None
    log: str = ""
    reason: str = ""

    def describe(self) -> str:
        if self.ok:
            return (f"started the watchdog (pid {self.pid}) — it launches the "
                    f"bot and relaunches it after a rejoin or a crash; attempts "
                    f"are logged in {self.log}")
        return f"could not start the bot: {self.reason}"


# THE WATCHDOG'S REASONS, SHOWN IN THE WINDOW (2026-10-19, the owner's first
# Windows run): Play said only "started the watchdog" four times while
# attempts.log said "game guard: you're playing Roblox (your own)" and "not
# enough memory". These are the ledger lines worth a row in the window.
LEDGER_SAYS = ("game guard", "not enough memory", "waiting for memory", "finished",
               "exited", "another run_farm", "stopping")


def ledger_news(path: Path, offset: int) -> tuple[list[str], int]:
    """New lines of the watchdog's ledger since `offset` worth showing, and
    the new offset. A missing or shrunk file starts over."""
    try:
        size = path.stat().st_size
        if size < offset:
            offset = 0
        with path.open(encoding="utf-8", errors="replace") as f:
            f.seek(offset)
            text = f.read()
            offset = f.tell()
    except OSError:
        return [], offset
    lines = [line.removeprefix("[watchdog] ").removeprefix("[overnight] ").strip()
             for line in text.splitlines()]
    return [line for line in lines if any(k in line for k in LEDGER_SAYS)], offset


def _panic_key() -> str:
    """The panic key as set (`safety.panic_key`), for the messages that name
    it. Imported here, not at the top: the settings module is only needed
    when a stop went wrong."""
    from ..world.settings import panic_key_name
    return panic_key_name()


def last_failure(night: Path) -> str:
    """The newest run log's last 'FAILED:' line (why a start stopped), or ''."""
    try:
        logs = sorted(Path(night).glob("run-*.log"), key=lambda p: p.stat().st_mtime)
        if not logs:
            return ""
        lines = [l.strip() for l in logs[-1].read_text(encoding="utf-8", errors="replace").splitlines()
                 if l.strip().startswith("FAILED:")]
    except OSError:
        return ""
    return lines[-1].removeprefix("FAILED:").strip() if lines else ""


class BotProcess:
    """The bot, as a process this window owns -- or knows of by its pidfile."""

    def __init__(self, root: Path | None = None, script: str = SCRIPT,
                 python: str | None = None, log_path: Path | None = None,
                 popen=subprocess.Popen, clock=time.monotonic,
                 allow_in_tests: bool = False,
                 own_scope: bool | None = None,
                 kill=os.kill, killpg=None, getpgid=None,
                 identity=process_identity, parent=process_parent):
        self.root = Path(root) if root else Path(__file__).resolve().parents[3]
        self.script = script
        # The interpreter running the GUI, which is the project's venv when
        # the GUI was started the normal way. The watchdog picks its own
        # (`.venv/bin/python`); this is kept for the log header and for a
        # `script` that is a python file (the tests' stand-in).
        self.python = python or sys.executable
        self.log_path = Path(log_path) if log_path else var("gui-run.log")
        self._popen = popen
        self.clock = clock
        # THE ONLY WAY A SIGNAL LEAVES THIS CLASS. Injectable so a test can
        # prove what would have been signalled without ever signalling a
        # real pid -- a fake pid of 4242 is somebody's process on some
        # machine.
        # (os.killpg/os.getpgid are looked up here, not as default arguments:
        # those are evaluated at import, and Windows has neither -- RL6.)
        self._kill = kill
        self._killpg = killpg if killpg is not None else getattr(os, "killpg", None)
        self._getpgid = getpgid if getpgid is not None else getattr(os, "getpgid", None)
        # AND THE ONLY WAY A PID IS BELIEVED: what /proc says it is running
        # (hivemind.files.process_identity), injectable for the same reason.
        self._identity = identity
        self._parent = parent
        # Only a test that is specifically testing THIS may launch anything.
        self.allow_in_tests = bool(allow_in_tests)
        # Start the watchdog in a systemd scope of its own (see `_argv`).
        # Unset means yes, except under pytest, whose fakes stand in for the
        # process and must not create a real unit.
        self.own_scope = (bool(own_scope) if own_scope is not None
                          else not os.environ.get("PYTEST_CURRENT_TEST"))
        self.process = None
        self.started_at: float | None = None
        self.launches = 0

    # ---- the watchdog's files -------------------------------------------------
    @property
    def night(self) -> Path:
        return self.root.joinpath(*NIGHT_DIR)

    @property
    def pidfile(self) -> Path:
        return self.night / PIDFILE

    @property
    def stop_file(self) -> Path:
        return self.night / STOP_FILE

    def _alive(self, pid: int) -> bool:
        if WINDOWS:
            # NEVER os.kill(pid, 0) THERE: any signal but the two console
            # events is TerminateProcess(pid, sig) [verified: Python os.kill].
            import psutil
            try:
                return psutil.pid_exists(int(pid))
            except (TypeError, ValueError, OSError):
                return False
        try:
            self._kill(int(pid), 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            # exists, and is NOT OURS: our watchdog and farm run as the owner,
            # so a pid we may not signal is somebody else's (DESIGN 8du)
            return False
        except (TypeError, ValueError, OSError):
            return False

    def watchdog_pid(self) -> int | None:
        """The pid in `var/night/watchdog.pid`, if that process is the watchdog.

        A stale file -- the watchdog was killed outright and never removed
        it -- is ignored, not trusted. ALIVE IS NOT ENOUGH (DESIGN 8du): pids
        wrap in about two days here, and a reused one made Start refuse for
        good and Stop SIGKILL an unrelated process group. So the pid must
        still be running `overnight.sh`, and have started when
        `var/night/watchdog.start` says. The file is left where it is:
        removing it could race a watchdog that is writing a fresh one, and
        both readers of it (this and overnight.sh) check it the same way.

        THE SCRIPT'S NAME, NOT ITS PATH. `cd scripts && ./overnight.sh`
        runs as `bash ./overnight.sh`, which "scripts/overnight.sh" does not
        match -- and a watchdog this missed was stopped as a lone farm: STOP
        never touched, and relaunched 20 s later. The start time is what
        makes the pid certain; the name only has to rule out a stranger.

        AND A FARM'S PARENT, WHEN THE FILE IS NO HELP. overnight.sh is the
        only thing that starts run_farm as its child, so a live farm whose
        parent is running overnight.sh has a watchdog, whatever the pidfile
        says (/proc/<pid>/stat field 4).
        """
        name = Path(self.script).name
        pid = pid_running(self.pidfile, name, identity=self._identity,
                          start_path=self.night / WATCHDOG_START)
        if pid is not None and self._alive(pid):
            return pid
        farm = self.farm_pid()
        parent = self._parent(farm) if farm is not None else None
        if parent is None or parent <= 1:
            return None
        found = self._identity(parent)
        if found is None or name not in found[0] or not self._alive(parent):
            return None
        return parent

    def farm_pid(self) -> int | None:
        """A run_farm that is alive, whoever started it -- or None.

        FARM_LOCK names the farm holding the lock; FARM_PIDFILE names the
        watchdog's current child, which is how a farm from before the lock
        existed is found. Either is believed only while that pid is still
        running scripts/run_farm.py (DESIGN 8du).
        """
        for name in (FARM_LOCK, FARM_PIDFILE):
            pid = pid_running(self.night / name, FARM_SCRIPT,
                              identity=self._identity)
            if pid is not None and self._alive(pid):
                return pid
        return None

    def _same(self, pid: int, start: str) -> bool:
        """Is `pid` still the process that had start time `start`?"""
        found = self._identity(pid)
        return found is not None and (not start or found[1] == start)

    # ---- state --------------------------------------------------------------
    @property
    def pid(self) -> int | None:
        if self.process is not None and self.process.poll() is None:
            return self.process.pid
        return self.watchdog_pid()

    def own_running(self) -> bool:
        """Is the process THIS window started still alive?"""
        return self.process is not None and self.process.poll() is None

    def running(self) -> bool:
        """Is a bot running -- ours, a watchdog started from anywhere, or a
        run_farm started without one (DESIGN 8du)?"""
        return (self.own_running() or self.watchdog_pid() is not None
                or self.farm_pid() is not None)

    def exit_code(self) -> int | None:
        if self.process is None:
            return None
        return self.process.poll()

    def waiting_to_connect(self) -> bool:
        """Launched from here, alive, and not yet long enough to give up on."""
        if not self.own_running() or self.started_at is None:
            return False
        return self.clock() - self.started_at < CONNECT_SECONDS

    def describe_state(self) -> str:
        """One line for the status bar when the socket is down."""
        if self.own_running():
            return (f"the watchdog started from here is running (pid "
                    f"{self.process.pid}) — the bot is joining, or between "
                    f"attempts")
        pid = self.watchdog_pid()
        if pid is not None:
            return (f"a watchdog is running (pid {pid}, started from a "
                    f"terminal) — the bot is joining, or between attempts; "
                    f"Stop here stops it")
        farm = self.farm_pid()
        if farm is not None:
            return (f"a run_farm is running without a watchdog (pid {farm}) "
                    f"— it is joining, or its socket is down; Stop here "
                    f"stops it")
        return "not connected — nothing is running; Start launches the bot"

    # ---- start --------------------------------------------------------------
    def start(self, extra: list[str] | None = None) -> Launch:
        """Launch the watchdog. Refuses to start a second one, or to start at
        all from inside a test run."""
        if os.environ.get("PYTEST_CURRENT_TEST") and not self.allow_in_tests:
            return Launch(ok=False, reason=(
                "refusing to launch the bot from a test run — a test that "
                "plays the owner's account is not a test. Pass "
                "allow_in_tests=True if a test really means to."))
        if self.own_running():
            return Launch(ok=False, pid=self.process.pid,
                          reason=f"a bot is already running (pid {self.process.pid})")
        other = self.watchdog_pid()
        if other is not None:
            return Launch(ok=False, pid=other, reason=(
                f"a bot is already running (watchdog pid {other}, started "
                f"from a terminal) — two farm loops would fight for the "
                f"keyboard; Stop it first if you want a fresh start"))
        farm = self.farm_pid()
        if farm is not None:
            return Launch(ok=False, pid=farm, reason=(
                f"a run_farm is already running without a watchdog (pid "
                f"{farm}) — a second one would close its game; Stop it "
                f"first if you want a fresh start"))
        script = self.root / self.script
        if not script.exists():
            return Launch(ok=False, reason=f"{script} is not there")
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            handle = open(self.log_path, "a", buffering=1, encoding="utf-8")
            handle.write(f"\n=== started from the GUI at "
                         f"{time.strftime('%Y-%m-%d %H:%M:%S')} ===\n")
        except OSError as exc:
            return Launch(ok=False, reason=f"could not open the log: {exc}")
        # A LEFTOVER STOP FILE WOULD END THE NEW WATCHDOG AT ONCE -- it reads
        # the file at the top of its loop. Whoever left it asked the PREVIOUS
        # run to stop, and it did; this press is a new request.
        try:
            self.stop_file.unlink()
            handle.write("removed a leftover STOP file\n")
        except FileNotFoundError:
            pass
        except OSError as exc:
            handle.write(f"could not remove the STOP file: {exc}\n")
        for leftover in ("BREAK", "KEEP"):           # Windows' stop requests (hivemind/watchdog)
            try:
                (self.night / leftover).unlink()
            except OSError:
                pass
        argv = self._argv(script, extra)
        # ITS OWN PROCESS GROUP (below); on Windows a group of its own with a
        # hidden console, which its farm shares, so its Ctrl+Break reaches it.
        group = ({"creationflags": CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW}
                 if WINDOWS else {"start_new_session": True})
        try:
            self.process = self._popen(
                argv, cwd=str(self.root), stdout=handle, stderr=handle,
                stdin=subprocess.DEVNULL,
                **({"env": {**os.environ, **UTF8_ENV}} if WINDOWS else {}),
                # ITS OWN PROCESS GROUP. Without this the bot shares the GUI's
                # group, so a Ctrl-C or a crash in the window would signal the
                # bot mid-walk with keys held down. It also lets Stop kill the
                # whole group as a last resort -- the watchdog, the farm and
                # the nested compositor the farm starts.
                **group)
        except OSError as exc:
            return Launch(ok=False, reason=str(exc))
        self.started_at = self.clock()
        self.launches += 1
        return Launch(ok=True, pid=self.process.pid,
                      log=str(self.night / "attempts.log"))

    def _argv(self, script: Path, extra) -> list[str]:
        """A python file runs under this venv's interpreter; anything else
        (the watchdog) runs as the shell script it is -- in its own scope.

        ITS OWN SCOPE, SO ONE OUT-OF-MEMORY KILL DOES NOT END THE NIGHT.
        MEASURED 2026-09-23 23:36 (the loss audit, verified): the watchdog,
        the farm and the nested compositor were all in the scope of whatever
        started them -- that night, the Claude desktop app's, which has
        `OOMPolicy=stop` and `KillMode=control-group`. The farm runs at
        `oom_score_adj` 400 so the kernel picks IT when memory runs out, and
        the watchdog is written to restart it in twenty seconds; but with
        `stop`, systemd then stops the whole scope, the watchdog included, and
        nothing restarts anything. The journal shows that sequence four times
        on 2026-09-20. A desktop launcher's scope has the same default.

        `systemd-run --user --scope -p OOMPolicy=continue` gives the watchdog
        and everything it starts a scope of their own in which one member can
        be killed without the rest being stopped. It execs in place, so the
        PID this process tracks is the watchdog's own (measured: the scope is
        named after the Popen pid). Without systemd-run, the plain command.
        """
        tail = list(extra or [])
        if script.suffix == ".py":
            python = self.python
            if WINDOWS and Path(python).name.lower() == "pythonw.exe":
                python = str(Path(python).with_name("python.exe"))   # a console, for Ctrl+Break
            return [python, str(script), *tail]
        cmd = ([str(script), *tail] if os.access(script, os.X_OK)
               else ["bash", str(script), *tail])
        runner = shutil.which("systemd-run")
        if runner and self.own_scope:
            return [runner, "--user", "--scope", "--collect", "--quiet",
                    "-p", "OOMPolicy=continue",
                    "--description=Hivemind bot (watchdog and farm)", "--", *cmd]
        return cmd

    # ---- stop ---------------------------------------------------------------
    def stop(self, grace: float = GRACE_SECONDS, sleep=time.sleep,
             keep_game: bool = False) -> str:
        """Ask everything to stop, then make sure it did. Returns what happened.

        `keep_game`: the farm is asked with SIGUSR1 instead (run_farm's
        `ask_keep`, what tools/deploy_keep.sh sends): the same clean stop,
        except that its teardown detaches and writes the kept session, so the
        next start attaches to the same game (platform/api Watchdog; on
        Windows phase 3 makes this a KEEP file). STOP is still set first, so
        the watchdog exits with the farm instead of relaunching it.

        STOP file first, so the watchdog does not relaunch the farm the moment
        it exits. SIGTERM next, to the watchdog: its trap forwards the request
        to the farm, whose handler releases every held key. Killing a bot with
        W held down leaves the character walking into a wall until the
        compositor dies, so the kill is the last resort and is reported as one.
        """
        if WINDOWS:
            return self._stop_windows(grace, sleep, keep_game)
        own = self.own_running()
        pid = self.process.pid if own else self.watchdog_pid()
        # A FARM WITH NO WATCHDOG IS STOPPED TOO (DESIGN 8du): the window now
        # counts one as running, so Stop has to reach it. There is no
        # watchdog to relaunch it, so no STOP file is left for the next one.
        farm_only = False
        if pid is None:
            pid = self.farm_pid()
            farm_only = pid is not None
        if pid is None:
            if self.process is not None:
                return f"the bot had already exited (code {self.exit_code()})"
            return ("no bot is running — nothing was started from here and "
                    "the watchdog's pidfile names nothing alive")
        # WHICH PROCESS, not just which number: a pid that exits during the
        # grace period can be handed to something else before the SIGKILL.
        start = "" if own else (self._identity(pid) or ("", ""))[1]

        def still_there() -> bool:
            if own:
                return self.own_running()
            return self._alive(pid) and self._same(pid, start)

        if not farm_only:
            try:
                self.night.mkdir(parents=True, exist_ok=True)
                self.stop_file.touch()
            except OSError:
                pass

        # THE KEEP-GAME STOP GOES TO THE FARM ITSELF: the watchdog's trap
        # catches only INT and TERM, and bash's default for USR1 is to die.
        target, how = pid, signal.SIGTERM
        if keep_game:
            farm = pid if farm_only else self.farm_pid()
            if farm is not None:
                target, how = farm, signal.SIGUSR1
        kept = how != signal.SIGTERM
        try:
            self._kill(target, how)
        except (ProcessLookupError, PermissionError):
            if own:
                try:
                    self.process.terminate()
                except Exception as exc:
                    return f"could not signal the bot: {exc}"
            else:
                return (f"the {'farm' if farm_only else 'watchdog'} (pid "
                        f"{pid}) was already gone")

        deadline = self.clock() + grace
        while self.clock() < deadline:
            if not still_there():
                code = f" (code {self.exit_code()})" if own else ""
                return (f"the bot stopped cleanly{code} — every held key was "
                        f"released on the way out"
                        + ("" if farm_only else ", and STOP is set so the "
                           "watchdog will not relaunch it")
                        + (" — the game was kept for the next start to attach to"
                           if kept else ""))
            sleep(0.25)

        # Still alive. Say so plainly: this one did NOT release its keys.
        #
        # THE WHOLE GROUP ONLY WHEN IT IS THE WATCHDOG'S OWN (DESIGN 8du). A
        # launch from here leads its own group (start_new_session), and so
        # did tonight's watchdog (pgid 92348 == pid 92348). A watchdog started
        # by `nohup ... &` from a script shares its PARENT's group, and
        # killpg on that took the parent -- and whatever else it had started
        # -- with it. Otherwise: the watchdog, then its farm, by pid alone.
        try:
            leads = own or self._getpgid(pid) == pid
        except (ProcessLookupError, PermissionError, OSError):
            leads = False
        if still_there():
            try:
                if leads:
                    self._killpg(pid, signal.SIGKILL)
                else:
                    farm = None if farm_only else self.farm_pid()
                    self._kill(pid, signal.SIGKILL)
                    if farm is not None and farm != pid:
                        self._kill(farm, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                if own:
                    try:
                        self.process.kill()
                    except Exception:
                        pass
        # AND WAIT FOR IT TO ACTUALLY BE GONE. SIGKILL is asynchronous and
        # `poll()` keeps returning None until the child is reaped, so
        # returning here left `running()` answering True right after a
        # successful kill -- which made the window's buttons lie. Caught by
        # the test that kills a real process that ignores SIGTERM.
        if own:
            try:
                self.process.wait(timeout=5.0)
            except Exception:
                pass
        for _ in range(20):
            if not still_there():
                break
            sleep(0.25)
        return (f"the bot ignored the stop request for {grace:.0f}s and was "
                f"killed — it may have left a key held; the panic key "
                f"({_panic_key()}) releases everything")

    def _stop_windows(self, grace: float, sleep, keep_game: bool) -> str:
        """Windows: no signals to send from here (hivemind/watchdog says why),
        so the requests are files: STOP (no relaunch), BREAK (the watchdog
        sends Ctrl+Break to its farm, whose handler releases every key), KEEP
        (the farm keeps the game). After `grace`, the process tree is killed
        -- never a Roblox in it: the next start's win/session.clear_stale
        ends ours by pid and start time."""
        own = self.own_running()
        pid = self.process.pid if own else self.watchdog_pid()
        farm_only = pid is None and self.farm_pid() is not None
        if pid is None and not farm_only:
            if self.process is not None:
                return f"the bot had already exited (code {self.exit_code()})"
            return ("no bot is running — nothing was started from here and "
                    "the watchdog's pidfile names nothing alive")
        if farm_only:
            pid = self.farm_pid()
        start = "" if own else (self._identity(pid) or ("", ""))[1]

        def still_there() -> bool:
            if own:
                return self.own_running()
            return self._alive(pid) and self._same(pid, start)

        # NO REQUEST FILES FOR A LONE FARM: only the watchdog reads STOP and
        # BREAK, and a KEEP nobody takes would make a LATER Ctrl+Break stop keep
        # its game (run_farm takes KEEP on SIGBREAK; only the GUI's start
        # clears it, a terminal start does not).
        try:
            self.night.mkdir(parents=True, exist_ok=True)
            if not farm_only:
                self.stop_file.touch()
                if keep_game:
                    (self.night / "KEEP").touch()
                (self.night / "BREAK").touch()
        except OSError as exc:
            return f"could not ask the bot to stop: {exc}"
        deadline = self.clock() + grace
        while self.clock() < deadline:
            if not still_there():
                return ("the bot stopped cleanly — every held key was released on the way out"
                        + ("" if farm_only else ", and STOP is set so the watchdog will "
                           "not relaunch it")
                        + (" — the game was kept for the next start to attach to"
                           if keep_game else ""))
            sleep(0.25)
        import psutil
        try:
            root = psutil.Process(int(pid))
            tree = [root] + root.children(recursive=True)
        except psutil.Error:
            tree = []
        for p in tree:
            try:
                if p.name().lower() != "robloxplayerbeta.exe":
                    p.kill()                          # TerminateProcess
            except psutil.Error:
                pass
        for _ in range(20):
            if not still_there():
                break
            sleep(0.25)
        why = ("a run_farm with no watchdog cannot be asked from here on Windows "
               "(Ctrl+Break in its own terminal does it)" if farm_only else
               f"the bot ignored the stop request for {grace:.0f}s")
        return (f"{why} and was killed — it may have left a key held; the panic "
                f"key ({_panic_key()}) releases everything")
