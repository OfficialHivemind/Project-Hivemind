"""Driving the Roblox app's own UI -- the part outside the game world.

Sober launches the full Roblox desktop client, not just a game window, so before
the agent ever presses W it may be sitting on a home page, a game page or an
error dialog. This module is how it gets from there into a running game.

The home page advertises a keyboard scheme along the bottom:

    Slash  Search      Esc  Back
    PgUp / LeftBracket Scroll Up
    PgDn / RightBracket Scroll Down

MEASURED, and mostly disappointing. Pressing Slash did NOT open the search box:
the box kept its placeholder text and the typed query went nowhere. What the
letters actually did was move a focus ring around the left sidebar, and the
following Enter activated whatever it had landed on -- which turned out to be
"More". So the app is focus-and-activate navigable, not type-anywhere navigable,
and PageDown scrolled nothing at all (three presses, byte-identical frames).

Two consequences, both load-bearing:

  * the mouse is the reliable instrument here, so `click` and wheel `scroll` are
    the primitives the flows are built from
  * **never press Enter without knowing what holds focus.** The More page it
    landed on carries "Log Out" and "Exit" as ordinary activatable tiles, and a
    blind Enter is one keystroke from signing the account out

Nothing in this file assumes what a page looks like. Flows that depend on page
layout live in scripts/explore_appui*.py until they have been observed.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

import numpy as np

from ..vision import screenstate as ss
from ..vision.digits import TemplateSet


@dataclass
class AppUI:
    """Keyboard-first control of the Roblox app shell.

    `capture` is anything with a .capture() returning a BGR(A) frame.
    """
    inp: object
    capture: object
    templates: TemplateSet | None = None
    trace: list[tuple[float, str]] = field(default_factory=list)
    _t0: float = field(default_factory=time.monotonic)

    # ---- observation ------------------------------------------------------
    def frame(self) -> np.ndarray:
        return self.capture.capture()

    def screen(self, frame: np.ndarray | None = None) -> ss.Screen:
        return ss.classify(self.frame() if frame is None else frame, self.templates)

    def _note(self, msg: str) -> None:
        self.trace.append((time.monotonic() - self._t0, msg))

    def wait_for(self, *states: ss.Screen, timeout: float = 180.0,
                 poll: float = 2.0) -> ss.Screen:
        """Block until the screen is one of `states`, or return what it settled on.

        Every distinct state seen is recorded in `trace`, because when a join
        fails the *sequence* of screens is the diagnosis -- a straight jump to
        MODAL is a rejection, while LOADING that never leaves is a hang.
        """
        wanted = set(states)
        deadline = time.monotonic() + timeout
        last: ss.Screen | None = None
        while time.monotonic() < deadline:
            now = self.screen()
            if now != last:
                self._note(now.value)
                last = now
            if now in wanted:
                return now
            time.sleep(poll)
        return last if last is not None else ss.Screen.UNKNOWN

    # ---- keyboard navigation ----------------------------------------------
    def focus(self, x: int = 960, y: int = 540) -> None:
        """Roblox ignores keys until the pointer has entered the surface."""
        self.inp.focus_game(x, y)

    def search(self, text: str, settle: float = 1.5) -> None:
        """Open the search box with '/' and type a query."""
        self._note(f"search {text!r}")
        self.inp.tap("slash")
        time.sleep(settle)
        self.inp.type_text(text)
        time.sleep(settle)

    def submit(self) -> None:
        self.inp.tap("enter")

    def back(self) -> None:
        self._note("back")
        self.inp.tap("escape")

    def scroll_keys(self, pages: int = 1, settle: float = 0.6) -> None:
        """Positive scrolls down, negative up, via PageDown/PageUp.

        MEASURED: this moved nothing on the app's More page -- three presses
        gave byte-identical frames. Kept because the home page advertises the
        binding, but `scroll` is the one to reach for.
        """
        key = "pagedown" if pages > 0 else "pageup"
        self._note(f"scroll-key {key} x{abs(pages)}")
        for _ in range(abs(pages)):
            self.inp.tap(key)
            time.sleep(settle)

    def scroll(self, steps: int = 3, at: tuple[int, int] = (960, 700),
               settle: float = 0.8) -> None:
        """Wheel-scroll the view under `at`. Positive is down."""
        self._note(f"scroll wheel {steps} at {at}")
        self.inp.move_mouse(*at)
        time.sleep(0.1)
        self.inp.scroll(steps)
        time.sleep(settle)

    def click(self, x: int, y: int, settle: float = 1.2) -> None:
        self._note(f"click {x},{y}")
        self.inp.click(x, y)
        time.sleep(settle)

    # ---- dialogs ----------------------------------------------------------
    def dismiss_modal(self, index: int = 0) -> bool:
        """Click a dialog's button. Returns False if no dialog is on screen."""
        modal = ss.find_modal(self.frame())
        if modal is None or not modal.buttons:
            return False
        x, y = modal.button_centre(index)
        self._note(f"dismiss modal button@{x},{y}")
        self.inp.click(x, y)
        time.sleep(1.0)
        return True
