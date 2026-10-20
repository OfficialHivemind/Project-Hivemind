"""The watchdog in Python: scripts/overnight.sh's rules, for Windows (RL6).

overnight.sh keeps the farm running all night and survives its crashes; it
is bash, and its stop is POSIX signals (a TERM trap, SIGUSR1 for keep-the-
game). Windows has neither bash nor those signals -- os.kill(pid, SIGTERM)
there is TerminateProcess, so no handler runs and a held key stays held
[verified: Python os.kill docs]. This carries overnight.sh over rule for rule
(the plan, section 3 "Watchdog"); read that script for the WHY of each, it
is not repeated here:

  * the pidfile and its start-time file; a live watchdog refuses a second;
  * HIVEMIND_SESSION_STARTED once, HIVEMIND_ATTEMPT per run;
  * run-N.log numbering of any width, continued; current.log repointed
    (a symlink -- skipped where Windows refuses one without Developer Mode);
  * the game-guard gate (a game of his STOPS the watchdog) and the memory
    gate (our model unloaded first; a kept game's footprint not asked for);
  * exit codes 0 (relaunch unless --cycles), 3 (session limit: stop),
    4 (another farm holds the lock: retry), 5 (the owner's game: STOP);
  * three deaths under FAST seconds in a row: LONG_GAP; a nap a stop cuts short;
  * the night report after each attempt.
Dropped: oom_score_adj (no Windows equivalent).

STOPPING ON WINDOWS. The farm runs in a process group of its own
(CREATE_NEW_PROCESS_GROUP), and the stop is CTRL_BREAK_EVENT to that group,
which run_farm handles as SIGBREAK exactly like SIGTERM (finish the step,
every key up) [verified: Python os.kill -- CTRL_BREAK_EVENT reaches console
processes sharing a console; CreateProcess -- a new group keeps Ctrl+Break].
The GUI cannot send it (it has no console of ours), so it asks by files:
  STOP   no relaunch (as on Linux; alone it means "after this attempt");
  BREAK  stop the running attempt now: this watchdog removes it and sends
         Ctrl+Break to the farm;
  KEEP   with BREAK, the farm keeps the game (run_farm detaches, as on
         SIGUSR1 on Linux). run_farm removes it when it acts on it.
A Ctrl+Break or Ctrl+C in this watchdog's own console does the same as
STOP + BREAK. Linux keeps overnight.sh until this one has run a night there
beside it (the plan, phase 2b).

    python src/hivemind/watchdog.py [args passed straight to run_farm.py]
"""
from __future__ import annotations

import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

if __package__ in (None, ""):                       # run as a file, not -m
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hivemind import datapaths, files  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
GAP, LONG_GAP, FAST = 20, 180, 45
MEMORY_WAIT_S, MEMORY_NAP_S = 300, 15
POLL_S = 0.5
FINISHED, LOCKED, GAME_GUARD = 3, 4, 5              # run_farm's exit codes (overnight.sh)
WINDOWS = os.name == "nt"
CREATE_NEW_PROCESS_GROUP = 0x00000200
# THE RUN LOG IN UTF-8 ON WINDOWS TOO. MEASURED 2026-10-19 (the owner's 5th
# Windows run, run-005.log): Python wrote the redirected stdout in cp1252
# (an em dash as 0x97), so the log was not UTF-8, and a character cp1252
# lacks would raise UnicodeEncodeError mid-run. Linux is UTF-8 already.
UTF8_ENV = {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}


def night(*parts: str) -> Path:
    return datapaths.var("night", *parts)


STOP, BREAK, KEEP = "STOP", "BREAK", "KEEP"
PIDFILE, STARTFILE, FARM_PIDFILE, LEDGER = ("watchdog.pid", "watchdog.start",
                                            "run_farm.pid", "attempts.log")
KEPT_SESSION = "session.json"


def touch(name: str) -> None:
    try:
        night(name).touch()
    except OSError:
        pass


def take(name: str) -> bool:
    """Remove a request file; True when it was there."""
    try:
        night(name).unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return night(name).exists()


def last_attempt(folder: Path) -> int:
    best = 0
    for p in folder.glob("run-*.log"):
        m = re.fullmatch(r"run-(\d+)\.log", p.name)
        if m:
            best = max(best, int(m.group(1)))
    return best


def game_playing() -> str:
    """platform/current's game guard as the settings ask; '' on any error
    (overnight.sh: a failing check is no game)."""
    try:
        from hivemind.platform import current
        from hivemind.world.settings import Settings
        return current.gameguard.check(Settings()) or ""
    except Exception:
        return ""


def memory_ok() -> tuple[bool, str]:
    """Our model unloaded, then platform/current's memory check (a kept game
    is already in memory). Not ok on any error, as overnight.sh's gate."""
    try:
        from hivemind.brain.vlm import from_settings
        from hivemind.platform import current
        from_settings().unload()
        kept = current.kept.kept_session(night(KEPT_SESSION),
                                         current.make_session().config_path) is not None
        return current.memory.check("the game", kept=kept)
    except Exception as exc:
        return False, f"could not check the memory ({type(exc).__name__}: {exc})"


class Watchdog:
    def __init__(self, args: list[str], python: str = sys.executable, popen=subprocess.Popen,
                 clock=time.time, gate_game=game_playing, gate_memory=memory_ok,
                 report=None):
        self.args, self.python, self.popen, self.clock = list(args), python, popen, clock
        self.gate_game, self.gate_memory = gate_game, gate_memory
        self.report = report or self._night_report
        self.bounded = any(a == "--cycles" or a.startswith("--cycles=") for a in self.args)
        self.child: subprocess.Popen | None = None
        self.woken = threading.Event()               # a stop request: naps end at once
        self.broke = False                           # Ctrl+Break already sent to this child

    # ---- the ledger --------------------------------------------------------------
    def say(self, line: str) -> None:
        try:
            with open(night(LEDGER), "a", encoding="utf-8") as fh:
                fh.write(f"[watchdog] {line}\n")
        except OSError:
            pass

    # ---- stopping -----------------------------------------------------------------
    def on_signal(self, *_):
        self.say("signalled; asking the run to stop")
        touch(STOP)
        self.ask_break()

    def ask_break(self) -> None:
        """Ctrl+Break to the farm's group (SIGTERM off Windows), once."""
        self.woken.set()
        child = self.child
        if child is None or child.poll() is not None or self.broke:
            return
        self.broke = True
        try:
            if WINDOWS:
                os.kill(child.pid, signal.CTRL_BREAK_EVENT)
            else:
                child.send_signal(signal.SIGTERM)
        except OSError as exc:
            self.say(f"could not ask the run to stop ({exc})")

    def stopped(self) -> bool:
        if take(BREAK):
            touch(STOP)
            self.ask_break()
        return night(STOP).exists()

    def nap(self, seconds: float) -> None:
        """A sleep a stop cuts short (overnight.sh `nap`)."""
        end = time.monotonic() + seconds
        while time.monotonic() < end and not self.stopped():
            if self.woken.wait(min(POLL_S, max(0.0, end - time.monotonic()))):
                return

    def wait_child(self) -> int:
        """Until the farm exits, passing on a BREAK the moment it appears."""
        while True:
            try:
                return self.child.wait(timeout=POLL_S)
            except subprocess.TimeoutExpired:
                if take(BREAK):
                    touch(STOP)
                    self.ask_break()

    # ---- one night --------------------------------------------------------------------
    def claim(self) -> bool:
        """The pidfile, unless another live watchdog holds it."""
        other = files.pid_running(night(PIDFILE), "watchdog.py",
                                  start_path=night(STARTFILE))
        if other is not None and other != os.getpid():
            self.say(f"another watchdog (pid {other}) is running; not starting a second")
            return False
        me = files.process_identity(os.getpid())
        files.atomic_write(night(STARTFILE), (me[1] if me else "") + "\n")
        files.atomic_write(night(PIDFILE), f"{os.getpid()}\n")
        return True

    def run(self) -> int:
        night().mkdir(parents=True, exist_ok=True)
        if not self.claim():
            return 1
        take(BREAK)                                   # a leftover asks nothing of this run
        os.environ.setdefault("HIVEMIND_SESSION_STARTED", str(int(self.clock())))
        attempt, fast = last_attempt(night()), 0
        try:
            while not self.stopped():
                attempt += 1
                code, lasted = self.attempt(attempt)
                if code is None:
                    break
                if code == 0 and self.bounded:
                    self.say("finished the cycles it was asked for")
                    break
                if code == FINISHED:
                    self.say("the session limit (safety.max_session_h) is reached — not relaunching")
                    break
                if code == LOCKED:
                    self.say("another run_farm holds var/night/farm.lock — retrying after the gap")
                if code == GAME_GUARD:
                    self.say("the owner is playing a game — stopping (STOP set); press Play after your game")
                    touch(STOP)
                if code == 0:
                    self.say("exited 0 but no cycle limit was set — restarting")
                fast = fast + 1 if lasted < FAST else 0
                if self.stopped():
                    break
                if fast >= 3:
                    self.say(f"3 fast deaths in a row; waiting {LONG_GAP}s")
                    self.nap(LONG_GAP)
                    fast = 0
                else:
                    self.nap(GAP)
        finally:
            for name in (PIDFILE, STARTFILE, FARM_PIDFILE):
                take(name)
            self.say(f"finished {time.strftime('%F %T')} after {attempt} attempt(s)")
        return 0

    def attempt(self, n: int) -> tuple[int | None, float]:
        """One run_farm: (its exit code, seconds it lasted), or (None, 0)
        when a gate or a stop meant none was started."""
        log = night(f"run-{n:03d}.log")
        try:
            current = night("current.log")
            if current.is_symlink() or current.exists():
                current.unlink()
            current.symlink_to(log)
        except OSError:
            pass                                      # Windows without Developer Mode
        self.say(f"attempt {n} starting {time.strftime('%F %T')} -> {log}")
        game = self.gate_game()
        if game:
            self.say(f"game guard: you're playing {game} — stopping (STOP set); "
                     f"press Play after your game")
            touch(STOP)
            return None, 0
        waited = 0
        while waited < MEMORY_WAIT_S:
            ok, note = self.gate_memory()
            self.say(note)
            if ok:
                break
            self.say("waiting for memory")
            self.nap(MEMORY_NAP_S)
            waited += MEMORY_NAP_S
            if self.stopped():
                break
        if self.stopped():
            return None, 0
        start = self.clock()
        self.broke = False
        with open(log, "ab") as out:
            self.child = self.popen(
                [self.python, str(ROOT / "scripts" / "run_farm.py"), *self.args],
                cwd=str(ROOT), stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                env={**os.environ, "HIVEMIND_ATTEMPT": str(n),
                     **(UTF8_ENV if WINDOWS else {})},
                **({"creationflags": CREATE_NEW_PROCESS_GROUP} if WINDOWS else {}))
        files.atomic_write(night(FARM_PIDFILE), f"{self.child.pid}\n")
        code = self.wait_child()
        self.child = None
        take(FARM_PIDFILE)
        lasted = self.clock() - start
        self.say(f"attempt {n} exited {code} after {lasted:.0f}s")
        self.report()
        return code, lasted

    def _night_report(self) -> None:
        try:
            subprocess.run([self.python, str(ROOT / "scripts" / "night_report.py"), "--write"],
                           cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=120)
        except (OSError, subprocess.SubprocessError):
            pass


def main(argv: list[str] | None = None) -> int:
    dog = Watchdog(sys.argv[1:] if argv is None else argv)
    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), dog.on_signal)
    return dog.run()


if __name__ == "__main__":
    raise SystemExit(main())
