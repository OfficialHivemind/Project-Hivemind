"""The bot's end of the buttons. Without this the GUI talks to nobody.

WHAT WAS ACTUALLY WRONG. `ipc/bus.EventServer` has taken an `on_message`
handler since it was written, and no script has ever passed one. So Start,
Pause, Stop and Take Over all reached the socket and stopped there. The GUI
even reported success, because `bridge.send()` returning True means the bytes
were written -- not that anything acted on them. Four controls that looked live
and were not, which is the exact thing the owner ruled out: "dont add fake
things for looks it needs to work and actaully be useefull to me".

THE HANDOVER IS THE ONE THAT HAD TO BE SAFE. His request:

    "it should be so i can have a button in hivemind to takover and from that
     point it watches me play and learns intill i press pass back button"

Taking over is not pausing. A pause can leave a key held -- the walk is
suspended mid-stride and resumes later. A handover means a PERSON now has the
keyboard, and a key the bot is still holding would fight them for it. So
`TAKE_OVER` releases everything first and refuses to hand back control of the
keyboard until `PASS_BACK`, and `hold()` raises rather than quietly pressing.

WHY A LOOP HAS TO ASK. Nothing here can interrupt a running function; Python
does not work that way and threads that kill other threads are how you end up
with a key held forever. Instead every long loop calls `check()` between steps,
which is where a pause blocks and a stop raises. The panic key stays the answer
for a loop that has stopped calling it -- that one reads /dev/input below the
whole process and does not depend on this file being reached at all.

WHAT THE GUI MAY CLAIM, AND WHEN (DESIGN 8du). The window used to flip to
"Pass back -- you have the controls" the moment the command was sent, while
the step in progress kept pressing keys for up to eleven minutes. The contract
now, in the order it happens:

  1. TAKE_OVER / PAUSE lands: for a handover every key comes up (`_release`)
     and `may_press()` / `guard()` refuse at once; `report()` says
     `handing_over` (or "pausing -- finishing the current step"), never yet
     `handed_over`.
  2. The loop next blocks on `_resume` -- in `check()`, or in an input-layer
     guard that waits the same way. That is the acknowledgement
     (`_ResumeGate`): `_parked` goes True and `report()` now says
     `handed_over`, or `parked` for a pause.
  3. PASS_BACK / RESUME: `_resume` is set, `_parked` goes False, the loop
     wakes and carries on from that step.

How soon step 2 comes is decided by how often the farm asks -- the input-layer
guard is audit-core's half (brain F2: a wait before every press). This file
only makes sure the GUI never claims more than the loop has done.
"""
from __future__ import annotations

import contextlib
import threading
import time

from ..platform.api import GameNotFocused
from ..telemetry.events import Action, Command, GameInput, StatusUpdate


class Stopped(Exception):
    """Raised out of `check()` when the owner pressed Stop."""


class HandedOver(Exception):
    """Raised when the bot tries to press a key while the owner is driving."""


class _ResumeGate(threading.Event):
    """`Controls._resume`, which knows when a loop is waiting on it.

    THE ACKNOWLEDGEMENT LIVES IN THE WAIT, not in any one caller (DESIGN
    8du): `check()` blocks here, and so does anything else that waits for a
    pause or a handover to end the same way -- an input-layer guard polling
    `_resume.wait(poll)` included -- so every one of them tells the GUI the
    moment it has actually stopped, with nothing to wire up per caller.
    """

    def __init__(self, on_park, on_resume):
        super().__init__()
        self._on_park, self._on_resume = on_park, on_resume

    def wait(self, timeout: float | None = None) -> bool:
        if not self.is_set():
            self._on_park()
        return super().wait(timeout)

    def set(self) -> None:
        # SET FIRST, THEN UNPARK. The other order let a park that was already
        # past wait()'s is_set() land after the unpark, leaving `_parked` True
        # on a loop that had carried on -- and the next TAKE_OVER then said
        # "you have the controls" mid-trip. `Controls._on_park` re-checks.
        super().set()
        self._on_resume()


# The pointer rests this long between its move and a button going down
# (owner_input): a press in the same instant as the move is lost.
OWNER_HOVER_S = 0.05


class Controls:
    """Run state the GUI can change and a loop can ask about.

    `vin` is the virtual input, and is required for a safe handover: keys must
    come up the instant the owner takes the controls, not at the end of
    whatever walk happens to be in progress.
    """

    def __init__(self, vin=None, emit=None, clock=time.monotonic,
                 running: bool = False):
        self.vin = vin
        self.emit = emit or (lambda event: None)
        self.clock = clock
        self._lock = threading.RLock()
        self._resume = _ResumeGate(self._on_park, self._on_resume)
        self._resume.set()
        self._paused = False
        self._stopped = False
        self._handed_over = False
        # A FARM PROCESS IS RUNNING FROM ITS FIRST LINE. Nothing ever sends it
        # START -- the GUI launches the process instead -- so this stayed False
        # and every report() said "idle" to a bot that was farming.
        self._running = bool(running)
        # True once a loop has blocked on `_resume` since it was last set:
        # the moment a pause or a handover has actually taken hold. See "WHAT
        # THE GUI MAY CLAIM" and `_ResumeGate`.
        self._parked = False
        self.started_at = clock()
        self.commands = 0
        # Every Take Over ever pressed, so an input that slept through a whole
        # handover (a 15 s coast) still knows one happened. See GuardedInput.
        self.handovers = 0
        # The owner's live-view inputs that were not applied (owner_input).
        self.owner_dropped = 0
        self._owner_moved_at = 0.0

    # ---- what the loop asks ----------------------------------------------
    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def stopped(self) -> bool:
        return self._stopped

    @property
    def handed_over(self) -> bool:
        return self._handed_over

    def check(self, timeout: float | None = None) -> None:
        """Call between steps. Blocks while paused, raises when stopped.

        A handover counts as paused: the loop waits, it does not die, so
        pressing Pass Back picks up where it left off rather than starting the
        session again.
        """
        if self._stopped:
            raise Stopped("stop was pressed")
        if not self._resume.is_set():
            self._resume.wait(timeout)
        if self._stopped:
            raise Stopped("stop was pressed")

    def may_press(self) -> bool:
        """False while the owner has the keyboard."""
        return not (self._handed_over or self._stopped)

    def wait_while_held(self, poll: float = 0.25) -> None:
        """Block while paused or handed over; return at once on Stop."""
        while (self._paused or self._handed_over) and not self._stopped:
            self._resume.wait(poll)

    def guard(self) -> None:
        """Raise unless the bot is allowed to press keys right now."""
        if self._stopped:
            raise Stopped("stop was pressed")
        if self._handed_over:
            raise HandedOver("the owner has the controls")

    # ---- what the GUI changes --------------------------------------------
    def handle(self, event) -> None:
        """Feed this to `EventServer(on_message=...)`. Ignores anything else."""
        if isinstance(event, GameInput):
            self.owner_input(event)
            return
        if not isinstance(event, Command):
            return
        with self._lock:
            self.commands += 1
            action = event.action
            if action == Action.START:
                self._running, self._stopped, self._paused = True, False, False
                self._resume.set()
            elif action == Action.PAUSE:
                self._paused = True
                self._resume.clear()
            elif action == Action.RESUME:
                self._paused = False
                if not self._handed_over:
                    self._resume.set()
            elif action == Action.STOP:
                self._stopped, self._running = True, False
                self._release("stop")
                self._resume.set()          # let a waiting loop up to raise
            elif action == Action.TAKE_OVER:
                self._handed_over = True
                self.handovers += 1
                self._release("handover")
                self._resume.clear()
            elif action == Action.PASS_BACK:
                # WHAT THE OWNER HELD COMES UP before the bot moves again: a
                # key he held in the live view must not walk the bot's route.
                self._release("pass back")
                self._handed_over = False
                if not self._paused:
                    self._resume.set()
            else:
                return
        self.report()

    def owner_drives(self) -> None:
        """The owner has the controls from the start: nothing of the bot's
        runs (the first-run Roblox login, teach_map), so nothing else would
        ever park. The GUI is told `handed_over` and its live view takes the
        controls (gui/panels/liveview, RL1b step 3)."""
        self.handle(Command(action=Action.TAKE_OVER,
                            reason="the owner drives; the bot runs nothing"))
        self._resume.wait(0)                # the park, and its report

    def owner_input(self, event: GameInput) -> bool:
        """THE OWNER'S MOUSE AND KEYS FROM THE LIVE VIEW (RL1b step 3), into
        the game through this run's own input -- the one path in, never a
        second. Only while he has the controls AND the loop has parked:
        before that the step in progress still owns the input. Never raises
        (this runs on the socket's reader thread); False when dropped.

        The owner's own hands, so the bot's gates do not apply: no
        GuardedInput, and type_text's never-chat lock is not on this path --
        it is what a person at the keyboard can do anyway."""
        vin = self.vin
        if vin is None or self._stopped or not (self._handed_over and self._parked):
            self.owner_dropped += 1
            return False
        op = event.op
        try:
            if op == "move":
                vin.move_mouse(event.x, event.y)
                self._owner_moved_at = time.monotonic()
            elif op in ("down", "up"):
                if op == "down":
                    # A PRESS RIGHT BEHIND THE POINTER'S ARRIVAL IS LOST: the
                    # click that gives the live view focus sends its move and
                    # its press together. MEASURED in headless labwc with the
                    # stand-in window (test_take_control's live check): no
                    # click at all, and with OWNER_HOVER_S between them it lands.
                    gap = self._owner_moved_at + OWNER_HOVER_S - time.monotonic()
                    if gap > 0:
                        time.sleep(gap)
                vin.mouse_button(event.button, op == "down")
            elif op == "key_down":
                vin.press(event.key)
            elif op == "key_up":
                vin.release(event.key)
            elif op == "scroll":
                vin.scroll(int(event.steps))
            elif op == "release_all":
                vin.release_all()
            else:
                raise ValueError(op)
        except Exception:                   # an unknown key or button name
            self.owner_dropped += 1
            return False
        return True

    def _on_park(self) -> None:
        """A loop has just blocked on `_resume`: THE ACKNOWLEDGEMENT. It is
        at a step boundary and pressing nothing, so now -- and only now --
        the GUI may say the pause or the handover has taken hold.

        UNDER THE LOCK, AND CHECKED AGAIN (DESIGN 8du). wait() tests
        is_set() and then calls this, and a RESUME or PASS_BACK can land in
        between: the wait then returns at once, so a park recorded here
        would be a claim about a loop that is already walking again. The
        lock orders this against `handle`; the re-check catches the resume
        that won.
        """
        with self._lock:
            if self._parked:
                return
            self._parked = True
            if self._resume.is_set():
                self._parked = False
                return
            self.report()

    def _on_resume(self) -> None:
        self._parked = False

    def _release(self, why: str) -> None:
        """Every key up, now. The single most important line in this file."""
        if self.vin is None:
            return
        try:
            self.vin.release_all()
        except Exception:
            # A handover that fails is worse than one that throws: say so, and
            # do not let an input error stop the state change from landing.
            # Never `handed_over` here: keys that would not come up are the
            # one case where the owner must not be told he has the keyboard.
            self.emit(StatusUpdate(running=self._running, paused=self._paused,
                                   handing_over=self._handed_over,
                                   note=f"could not release keys on {why}"))

    # ---- what the GUI is told --------------------------------------------
    def report(self, note: str = "") -> StatusUpdate:
        """Tell the GUI the real state. `note` describes normal work only.

        THE HEARTBEAT CALLS THIS NOW (DESIGN 8du). It used to send its own
        StatusUpdate(running=True, paused=False, handed_over=False) every
        20 s, which overwrote a pause within seconds and flipped the button
        back to "Pause" -- so the obvious click on a paused bot paused it
        again. A periodic push must never hardcode who is driving.
        """
        # ONE THREAD AT A TIME, BUILD AND SEND TOGETHER: the heartbeat, the
        # loop's park and the socket's commands all report. Unlocked, a
        # heartbeat built before a park and sent after it undid the park's
        # "handed over" for 20 s. `emit` is a queue put that never blocks
        # (ipc/bus EventServer.send), so holding the lock across it is safe.
        with self._lock:
            held = self._paused or self._handed_over or self._stopped
            update = StatusUpdate(
                running=self._running and not self._stopped,
                paused=self._paused or self._handed_over,
                handed_over=self._handed_over and self._parked,
                # A stopped bot is not handing over: Stop is live while a
                # handover is pending (gui/panels/status), and STOP un-parks.
                handing_over=(self._handed_over and not self._parked
                              and not self._stopped),
                parked=self._parked,
                uptime_s=self.clock() - self.started_at,
                note=self.describe() if held or not note else note)
            self.emit(update)
        return update

    def describe(self) -> str:
        # NOTHING WATCHES OR LEARNS DURING A HANDOVER, so this no longer says
        # it does: no code reads `handed_over` to record anything (grep, 8du).
        # scripts/watch_me_play.py is the recorder, and it runs on its own.
        if self._stopped:
            return "stopped"
        if self._handed_over:
            return ("you have the controls — the bot is not pressing anything"
                    if self._parked else
                    "handing over — keys released, the bot is finishing its "
                    "current step")
        if self._paused:
            return ("paused" if self._parked
                    else "pausing — finishing the current step")
        return "running" if self._running else "idle"


# Keys whose press is decided on a frame looked at just before it: after any
# wait at the gate that frame is stale. Return is the respawn's -- sent only
# once `reset_dialog_present` has seen the confirmation (act/routes._reset).
# E is every interact -- the cannon, a giver, a dispenser, the hive's convert
# and claim -- each pressed on a panel read a moment before, and a Pause lets
# the owner walk the character anywhere: a waited E sent on Resume lands on
# whatever he left it at, "Open Shop" included (review of 2026-09-26).
# "<click>" is a click AT A POSITION (dialogue, quests, the app UI), aimed at
# a box found on that frame; a waited one goes to a remembered place, and on
# a menu he has closed it opens it again. A click with no position is the
# tool's (act/clicker) and is not in here.
STALE_AFTER_A_WAIT = frozenset({"enter", "return", "kp_enter", "e", "<click>"})


class GuardedInput:
    """The input every loop is handed, with the owner's buttons in front of it.

    THE PROMISE ABOVE THAT NOTHING KEPT. `may_press` and `guard` had no
    callers (audit 2026-09-25, brain F2): the only reader of these controls
    was the farm loop's gate at the top of each cycle, so after Take Over the
    running gather -- up to 1,200 s of WASD, token chases, the walk home, the
    convert's E, an errand, a respawn -- carried on pressing keys under the
    owner's hands, and the clicker kept clicking at whatever he opened. Pause
    did nothing until the trip ended. So every press, tap, hold and click
    passes through here first:

      * PAUSED: the keys this knows are down come up, it waits, and on Resume
        they go back down, so a paused route carries on where it stood ("the
        walk is suspended mid-stride and resumes later"). A Return, an E or
        a click at a position that had to wait is dropped: the frame it was
        decided on is not the screen it would land on (STALE_AFTER_A_WAIT),
        and the caller looks again or backs out.
      * HANDED OVER: it waits too (Controls has already released every key),
        and from then until the loop reaches the top of its next cycle and
        calls `fresh()`, NOTHING is sent: whatever was being done was decided
        about a character the owner has since moved, and an `e` meant for a
        hive pad lands wherever he left it. Dropping is safe; sending is not.
        `stale` says so, for the loop to stop early rather than run its
        course with no keys.
      * HOLDING: a key already down is not a press, so the loops that hold
        keys while they sleep ask `hold_point` every slice, and the keys come
        up within a tenth of a second of the button either way.
      * STOPPED: passes. The stop flag winds the loops down.

    `may_press` is asked by `may_send`, the clicker's gate. `guard` stays
    uncalled on purpose: it raises, and an exception thrown from inside a
    hold is how a key ends up held with nobody left to lift it. Releases
    always pass straight through, never guarded.
    """

    def __init__(self, vin, controls: Controls, poll: float = 0.25,
                 on_unfocused=None):
        self._vin = vin
        self._controls = controls
        self._poll = float(poll)
        self._down: list[str] = []
        self._seen = controls.handovers
        self._on_unfocused = on_unfocused
        self.dropped = 0
        self.unfocused = 0

    # ---- what the loop asks ---------------------------------------------
    @property
    def stale(self) -> bool:
        """A handover has happened since the loop last started fresh."""
        return self._controls.handovers != self._seen

    def fresh(self) -> None:
        """The loop is at the top of a cycle: what it does next is new."""
        self._seen = self._controls.handovers

    def may_send(self) -> bool:
        """Would an input go out right now without waiting? (The clicker's
        gate: a click must never wait, only not happen.) `may_press` is the
        owner's half of the answer; a Pause and a stale cycle are the rest."""
        c = self._controls
        return c.may_press() and not c.paused and not self.stale

    def hold_point(self) -> float | None:
        """For a loop that is HOLDING keys while it sleeps, asked every slice
        (act/routes.RouteRunner at WATCH_HZ, act/hiverow). The seconds a
        Pause or a Take Over held it here, 0.0 when neither did, or None when
        the owner has taken the controls since the cycle began -- the hold
        is over, and the caller ends it.

        A press is gated once, and then held: `coast` sleeps 15.4 s with W
        down. So the keys this knows are down come up HERE, the moment the
        loop next looks (a tenth of a second at WATCH_HZ), it waits, and on
        Resume they go back down -- the walk suspended mid-stride -- for the
        caller to add the seconds to its deadline.
        """
        c = self._controls
        if c.stopped:
            return 0.0                     # the stop flag winds the loop down
        if self.stale:
            return None
        if not (c.paused or c.handed_over):
            return 0.0
        began = time.monotonic()
        if not self._wait_out():
            return None
        return time.monotonic() - began

    # ---- the gate ---------------------------------------------------------
    def _wait_out(self) -> bool:
        """Keys up, wait out a Pause or a handover, keys back down after a
        Pause. False when nothing may be sent any more (a handover happened,
        or Stop was pressed during the wait)."""
        c = self._controls
        down = list(self._down)
        for k in down:
            try:
                self._vin.release(k)
            except Exception:
                pass
        c.wait_while_held(self._poll)
        if self.stale:
            self._down.clear()
            return False
        if c.stopped:
            return False
        for k in down:                     # a Pause: back down as they were
            self._vin.press(k)
        return True

    def _gate(self, key: str | None = None) -> bool:
        """True when this input may go out; waits while paused/handed over."""
        c = self._controls
        if c.stopped:
            return True
        waited = False
        if c.paused or c.handed_over:
            waited = True
            if not self._wait_out():
                if self.stale:
                    self.dropped += 1
                return False
        if self.stale:
            self._down.clear()
            self.dropped += 1
            return False
        if waited and key is not None and str(key).lower() in STALE_AFTER_A_WAIT:
            self.dropped += 1
            return False
        return True

    def _call(self, key, fn) -> tuple[bool, object]:
        """(sent, what `fn` returned) once the gate lets it out.

        ROBLOX NOT IN FRONT IS A PAUSE, NOT A CRASH (RL6, Windows only:
        platform/api GameNotFocused). SendInput reaches whatever window is
        in front, so the Windows input refuses -- letting every key go --
        when the owner Alt-Tabs away. Here that is `on_unfocused(why)`, which
        pauses the controls (FocusGuard.lost) the way the minimized-window
        guard does, and the send waits at the gate like any paused input;
        FocusGuard resumes when Roblox is in front again, and the keys this
        knows were down go back down (`_wait_out`). With no `on_unfocused`
        it raises as before. Linux never raises it."""
        c = self._controls
        while True:
            try:
                if not self._gate(key):
                    return False, None
                return True, fn()
            except GameNotFocused as exc:
                self.unfocused += 1
                if self._on_unfocused is None:
                    raise
                self._on_unfocused(str(exc))
                if c.stopped:
                    return False, None
                if not (c.paused or c.handed_over):
                    time.sleep(self._poll)        # not paused (yet): look again shortly

    # ---- the guarded calls ------------------------------------------------
    # Each returns False when the input was NOT sent, so the one caller that
    # must know -- the respawn's Return (act/routes._reset) -- can back out
    # of the dialog instead of believing it confirmed it. The raw input
    # returns None, so `is False` is never true without this guard.
    def press(self, *keys: str) -> bool:
        if not self._call(keys[0] if len(keys) == 1 else None,
                          lambda: self._vin.press(*keys))[0]:
            return False
        for k in keys:
            if k not in self._down:
                self._down.append(k)
        return True

    def release(self, *keys: str) -> None:
        for k in keys:
            if k in self._down:
                self._down.remove(k)
        self._vin.release(*keys)

    def release_all(self) -> None:
        self._down.clear()
        self._vin.release_all()

    @contextlib.contextmanager
    def held(self, *keys: str):
        stack = contextlib.ExitStack()            # the raw input's held(), once entered
        if not self._call(None, lambda: stack.enter_context(self._vin.held(*keys)))[0]:
            yield self
            return
        for k in keys:
            if k not in self._down:
                self._down.append(k)
        try:
            with stack:
                yield self
        finally:
            for k in keys:
                if k in self._down:
                    self._down.remove(k)

    def tap(self, key: str, *args, **kwargs) -> bool:
        return self._call(key, lambda: self._vin.tap(key, *args, **kwargs))[0]

    def click(self, *args, **kwargs) -> bool:
        return self._call("<click>" if (args or kwargs) else None,
                          lambda: self._vin.click(*args, **kwargs))[0]

    def drag(self, *args, **kwargs) -> bool:
        """A drag is a click that moves: aimed at what was on screen when it
        was decided, so it is dropped after a wait like one (STALE_AFTER_A_WAIT
        "<click>")."""
        sent, done = self._call("<click>", lambda: self._vin.drag(*args, **kwargs))
        return sent and done is not False

    def drag_seek(self, *args, **kwargs):
        """A drag that looks before it lets go (platform/input): gated as a
        drag; None when held back, as when it carried the item home."""
        return self._call("<click>", lambda: self._vin.drag_seek(*args, **kwargs))[1]

    # Everything else that sends something is an input too, and is gated the
    # same way; anything that does not (held_keys, no_chat_from, close) is
    # the raw input's.
    GATED = frozenset({"camera_left", "camera_right", "camera_up",
                       "camera_down", "move_mouse", "scroll", "type_text",
                       "focus_game"})

    def __getattr__(self, name):
        attr = getattr(self._vin, name)
        if name in GuardedInput.GATED and callable(attr):
            def gated(*args, **kwargs):
                return self._call(None, lambda: attr(*args, **kwargs))[1]
            return gated
        return attr

    def __setattr__(self, name, value):
        if name.startswith("_") or name in ("dropped", "unfocused"):
            object.__setattr__(self, name, value)
        else:
            setattr(self._vin, name, value)    # e.g. `in_game`, on the real one


class FocusGuard:
    """WINDOWS: ROBLOX MUST BE IN FRONT (RL6; the plan, 4b). SendInput goes
    to the foreground window, so while the owner has another window in front
    the bot pauses itself -- the Pause button's pause, pressing nothing --
    and resumes when Roblox is in front again. Like run_farm's window guard
    it resumes only a pause of its own: a button pressed in between leaves
    the controls to the owner.

    `lost(why)` is called by GuardedInput the moment an input is refused and
    by `tick` (run_farm's thread, every few seconds) when it sees another
    window in front; `focused()` is the session's game_focused."""

    def __init__(self, controls: Controls, focused, say=lambda message, warn=False: None):
        self.controls, self.focused, self.say = controls, focused, say
        self.ours: int | None = None       # controls.commands just after our pause
        self.pauses = 0

    def lost(self, why: str = "Roblox is not the window in front") -> None:
        c = self.controls
        with c._lock:
            if self.ours is not None or c.paused or c.handed_over or c.stopped:
                return
            c.handle(Command(action=Action.PAUSE, reason=why))
            self.ours = c.commands
            self.pauses += 1
        self.say(f"paused: {why} -- every key is up; it carries on by itself when "
                 f"Roblox is in front again (click its window)", True)

    def tick(self) -> None:
        try:
            front = bool(self.focused())
        except Exception:
            return                          # a watcher must never end a run
        c = self.controls
        if not front:
            self.lost()
            return
        if self.ours is None:
            return
        if c.paused and c.commands == self.ours:
            c.handle(Command(action=Action.RESUME, reason="Roblox is in front again"))
            self.say("Roblox is in front again -- resuming")
        else:
            self.say("Roblox is in front again, but the controls were used during "
                     "the pause -- leaving them as the owner set them")
        self.ours = None
