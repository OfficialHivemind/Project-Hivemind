"""The only input API the rest of Hivemind sees.

A stuck key is the worst failure this program can have: the character runs into
a wall forever, or worse the key leaks somewhere it shouldn't. There are four
independent guarantees against it, because any one of them can fail:

  1. `held()` context manager  -- releases on normal exit AND on exception
  2. `release_all()`           -- called between every task
  3. atexit hook               -- covers a clean interpreter shutdown
  4. SIGINT/SIGTERM handlers   -- covers Ctrl-C and `kill`

A fifth is often claimed -- that SIGKILL makes the compositor release everything
when it destroys our virtual keyboard. UNVERIFIED: zwp_virtual_keyboard_v1's spec
says nothing about held keys on destroy, so that is compositor-defined behaviour,
not a guarantee. wtype's README asserts it and wlroots probably does it, but we do
not treat it as a safety net. The four layers above are the ones we rely on.
"""
from __future__ import annotations

import atexit
import contextlib
import signal
import sys
import time

if sys.platform == "win32":
    # RL6 phase 3: win/input.WinInput reuses this class body (the stuck-key
    # guarantees, held(), drag, the never-chat rule) over SendInput backends,
    # so this module must import without pywayland there. Its pointer takes
    # the same evdev button code.
    BTN_LEFT = 0x110
else:
    from .wl.connection import WlConnection, nested_socket
    from .wl.vkeyboard import VirtualKeyboard
    from .wl.vpointer import BTN_LEFT, VirtualPointer


def _asked(check) -> bool:
    """A drag's check, where a raise is a no."""
    try:
        return bool(check())
    except Exception:
        return False


class VirtualInput:
    def __init__(self, socket: str | None = None,
                 width: int = 1920, height: int = 1080):
        self._conn = WlConnection(socket or nested_socket()).connect()
        self.kb = VirtualKeyboard(self._conn)
        self.mouse = VirtualPointer(self._conn, width, height)
        self._install_safety()

    # ---- safety -----------------------------------------------------------
    # ---- the one rule that is enforced rather than assumed ---------------
    # See type_text. `in_game` is set by whatever drives the session once the
    # game is up; until then the Roblox app's own search box is fair game.
    refuse_to_type: bool = True
    in_game: bool = False

    def no_chat_from(self, settings) -> None:
        """Refuse to type in game. `safety.never_chat` cannot say otherwise.

        LOCKED ON (DESIGN 8du). This used to obey the setting, and the GUI
        drew it as a live checkbox, so one click would have let the next run
        type into a focused game. The setting is kept for the GUI to show
        (world/settings.LOCKED); a false value is ignored here, not honoured.
        """
        self.refuse_to_type = True

    # Windows adds SIGBREAK (CTRL_BREAK_EVENT, the watchdog's clean stop there).
    SAFETY_SIGNALS = ("SIGINT", "SIGTERM")

    def _install_safety(self) -> None:
        atexit.register(self.release_all)
        for sig in (getattr(signal, name) for name in self.SAFETY_SIGNALS):
            prev = signal.getsignal(sig)
            def handler(signum, frame, _prev=prev):
                self.release_all()
                if callable(_prev):
                    _prev(signum, frame)
                else:
                    raise KeyboardInterrupt
            with contextlib.suppress(ValueError):   # not on the main thread
                signal.signal(sig, handler)

    def release_all(self) -> None:
        with contextlib.suppress(Exception):
            self.kb.release_all()
        with contextlib.suppress(Exception):
            self.mouse.release_all()

    # ---- keys -------------------------------------------------------------
    def press(self, *keys: str) -> None:
        """Press every key, or none of them.

        A multi-key press that fails partway used to leave the earlier keys
        down: `press('w', 'shfit')` put W down and then raised on the typo.
        Nothing released W until the next task boundary called release_all().
        So this unwinds what it has already pressed before re-raising.
        """
        done: list[str] = []
        try:
            for k in keys:
                self.kb.press(k)
                done.append(k)
        except Exception:
            for k in reversed(done):
                with contextlib.suppress(Exception):
                    self.kb.release(k)
            raise

    def release(self, *keys: str) -> None:
        """Release every key, even if one of them raises.

        The counterpart to press(): a failure on key 1 must not strand key 2.
        """
        failure: Exception | None = None
        for k in keys:
            try:
                self.kb.release(k)
            except Exception as exc:          # keep going; a stuck key is worse
                failure = failure or exc
        if failure is not None:
            raise failure

    @contextlib.contextmanager
    def held(self, *keys: str):
        """Hold keys for the duration of the block.

        THIS is the primitive the whole project needs and that shelling out to
        wtype cannot provide: the body can capture frames, run optical flow and
        decide when enough distance has been covered, while the key stays down.
        """
        # The press goes INSIDE the try. Outside it, an exception from press()
        # itself escaped before the finally was armed -- which is the one case
        # where a key is most likely to be down and unaccounted for.
        try:
            self.press(*keys)
            yield self
        finally:
            self.release(*keys)

    def tap(self, key: str, ms: int = 40) -> None:
        with self.held(key):
            time.sleep(ms / 1000)

    # ---- camera -----------------------------------------------------------
    # Roblox turns the follow camera with comma and period, and zooms with
    # PageUp/PageDown. Not a guess: BeeTuxMacro's utils.sh drives exactly these
    # keys (`wtype -P comma`), and 24 of the recorded routes contain camera
    # steps, so the transpiled graph cannot be executed without them.
    #
    # The camera matters more than it looks. Every movement key is relative to
    # where the camera points, so turning it redefines what "forward" means --
    # which is how the bot gets out of the corner it spawns in, facing the hive
    # wall with `w` blocked.
    def camera_left(self, taps: int = 1, gap: float = 0.1) -> None:
        self._camera("comma", taps, gap)

    def camera_right(self, taps: int = 1, gap: float = 0.1) -> None:
        self._camera("period", taps, gap)

    def camera_up(self, taps: int = 1, gap: float = 0.1) -> None:
        self._camera("pageup", taps, gap)

    def camera_down(self, taps: int = 1, gap: float = 0.1) -> None:
        self._camera("pagedown", taps, gap)

    def _camera(self, key: str, taps: int, gap: float) -> None:
        for _ in range(max(1, taps)):
            self.tap(key)
            time.sleep(gap)

    def type_text(self, text: str, delay: float = 0.04) -> None:
        """Type into a focused field -- the Roblox app's search box.

        NEVER IN-GAME CHAT, and that is now ENFORCED rather than merely true.

        `safety.never_chat` has always been described as "honoured by
        construction: the agent has no chat path at all", and it was listed in
        NOT_WIRED for exactly that reason -- nothing read the flag. A rule
        nothing enforces is a rule that survives only as long as nobody writes
        the code that breaks it, and this method is the one place in the
        project that can put characters into the game.

        So it refuses to type while the game has keyboard focus and the flag is
        set. The Roblox app's own search box, which is the legitimate use, is
        reached before the game is running and is unaffected.

        Talking to other players is the single behaviour with the clearest
        real-world cost -- it is what gets an account reported by a human
        rather than flagged by a heuristic -- so it gets a guard rather than a
        comment.
        """
        if self.refuse_to_type and self.in_game:
            raise PermissionError(
                "safety.never_chat is locked on and the game has focus: this "
                "bot does not type to other players. The app's search box is "
                "reachable before the game starts, which is where it is used.")
        self.kb.type_text(text, delay)

    def focus_game(self, x: int = 960, y: int = 540) -> None:
        """Give the game pointer focus so it will accept keyboard input.

        MEASURED, not folklore: keys sent before any pointer motion do nothing --
        frame difference 0.35 against a 0.34 baseline. After a single
        motion_absolute into the window, the same keys move the character
        (30.4, 28.0, 38.2, 33.1). Roblox needs a wl_pointer.enter before it will
        act on wl_keyboard events.

        Once is enough: five consecutive keypresses and a 6-second idle all kept
        working with no further mouse activity. A CLICK is not required, and in
        testing was worse than a plain move -- it lands on whatever is under the
        cursor.
        """
        self.mouse.move_to(x, y)
        time.sleep(0.3)

    # ---- mouse ------------------------------------------------------------
    def click(self, x: float | None = None, y: float | None = None) -> None:
        self.mouse.click(x, y, BTN_LEFT)

    def move_mouse(self, x: float, y: float) -> None:
        self.mouse.move_to(x, y)

    # evdev's BTN_LEFT, BTN_RIGHT, BTN_MIDDLE (Windows' pointer takes the same)
    BUTTONS = {"left": BTN_LEFT, "right": BTN_LEFT + 1, "middle": BTN_LEFT + 2}

    def mouse_button(self, name: str, down: bool) -> None:
        """One button down or up on its own: the owner's click from the live
        view (brain/controls, GameInput). The pointer tracks it, so
        `release_all` lets it go."""
        self.mouse.button(self.BUTTONS[name], 1 if down else 0)

    def drag(self, x0: float, y0: float, x1: float, y1: float, *,
             steps: int = 12, hold_s: float = 0.15, check=None) -> bool:
        """Press the left button at (x0, y0), move to (x1, y1) in `steps`,
        release there: how the game moves an item from the inventory onto a
        hive cell (Royal Jelly, an egg, a treat). The button is let go on every
        way out, and `release_all` lets it go too (the pointer tracks it).

        `check()`, asked with the item held over (x1, y1): False carries it
        back to (x0, y0) and lets go there instead -- over the list it came
        from, where a drop does nothing -- and the drag returns False."""
        self.mouse.move_to(x0, y0)
        time.sleep(0.05)
        self.mouse.button(BTN_LEFT, 1)
        dropped = True
        try:
            time.sleep(hold_s)
            n = max(1, int(steps))
            for i in range(1, n + 1):
                self.mouse.move_to(x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n)
                time.sleep(0.02)
            time.sleep(hold_s)
            if check is not None and not _asked(check):
                dropped = False
                for i in range(1, n + 1):
                    self.mouse.move_to(x1 + (x0 - x1) * i / n, y1 + (y0 - y1) * i / n)
                    time.sleep(0.02)
                time.sleep(hold_s)
        finally:
            self.mouse.button(BTN_LEFT, 0)
        return dropped

    def drag_seek(self, x0: float, y0: float, px: float, py: float, find, *,
                  check=None, steps: int = 12, hold_s: float = 0.15):
        """Press at (x0, y0) and carry the item to (px, py), where `find()` is
        asked with it held -- the frame there shows what it may go on. A
        point carries it on to that point and, if `check()` (asked there)
        passes too, lets go: the point is returned. None, a raise, or a
        failed check carries it back to (x0, y0) and lets go there, where a
        drop does nothing: None is returned."""
        self.mouse.move_to(x0, y0)
        time.sleep(0.05)
        self.mouse.button(BTN_LEFT, 1)
        n = max(1, int(steps))
        at, dropped = (float(x0), float(y0)), None

        def glide(to) -> None:
            nonlocal at
            for i in range(1, n + 1):
                self.mouse.move_to(at[0] + (to[0] - at[0]) * i / n,
                                   at[1] + (to[1] - at[1]) * i / n)
                time.sleep(0.02)
            at = (float(to[0]), float(to[1]))
        try:
            time.sleep(hold_s)
            glide((px, py))
            time.sleep(hold_s)
            try:
                target = find()
            except Exception:
                target = None
            if target is not None:
                glide(target)
                time.sleep(hold_s)
                if check is None or _asked(check):
                    dropped = at
            if dropped is None:
                glide((x0, y0))
                time.sleep(hold_s)
        finally:
            self.mouse.button(BTN_LEFT, 0)
        return dropped

    def scroll(self, steps: int = 1, horizontal: bool = False) -> None:
        """Wheel scroll; positive is down. Used to reach below-the-fold UI."""
        self.mouse.scroll(steps, horizontal)

    @property
    def held_keys(self) -> set[str]:
        return set(self.kb.held)

    def close(self) -> None:
        self.release_all()
        self._conn.close()

    def __enter__(self): return self
    def __exit__(self, *exc): self.close()
