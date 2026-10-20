"""Stopping a walk when the place we are walking TO comes into view.

WHY THIS EXISTS AT ALL. A recorded route is a list of timed key holds, so a
walk covers the right distance only while the walkspeed is the one it was
recorded at. MEASURED 2026-09-21: `from_hive_to_red_cannon` overshot the
cannon into the honeycomb wall behind it by its last 0.75 s, three runs out of
three, having worked 41 times in 47 the night before from the same start. A
hold that ends when the prompt appears does not care what the walkspeed is.

WHY IT NEEDED FIXING. The first version asked one question -- "is the
top-centre panel box on screen?" -- and that question is True BEFORE THE ROUTE
HAS MOVED, because the character is standing on its own hive pad and the pad's
own "Make Honey" prompt is showing. So arrival fired on the first watch tick of
the first walk, every remaining approach walk was skipped as "already
arrived", and the route pressed E at the hive and then ran its post-cannon legs
from the hive instead of from the cannon. The owner watched the result: "it
tried going to the cannon to go to pumpkin but failed walked past and went to
black bear". The log line that proves it, from var/gui-run.log at 21:07:36:

    from_hive_to_pumpkin_with_red_cannon: w: stopped early — the target is
    in view

`w` is the FIRST step of that route.

THE RULE THAT FIXES IT is the obvious one once seen: you cannot be standing at
the place you are walking to while you are still standing at the place you set
off from. So a panel that is showing when the walk is armed does not count.
Arrival can only fire after a frame has come back with NO panel on it -- the
character has stepped off whatever it started at -- and a panel has then
appeared again.

WHAT THIS DELIBERATELY DOES NOT DO is read the panel. Reading costs a vision
model call of about a second, and it would be asked at the watch rate with a
movement key held down, so every ask would walk another thirty studs past the
thing it was checking for. The authoritative read happens once, at the press,
where `nav.journey.guard` already does it and already refuses a press at a
panel that does not name the place the route is for. So the cost of this
watcher being wrong is bounded: the approach stops early, the guard reads the
panel, and a wrong panel is refused and reported rather than pressed.
"""
from __future__ import annotations

from typing import Callable


class Arrival:
    """"Has the prompt for the place we are heading to just appeared?"

    Asked at the watch rate during the approach walks of a route. Costs one
    frame grab and one colour-threshold pass, about a millisecond.

    `frames()` returns a frame or None. `panel_present(frame)` is
    `vision.banner.present` -- True when the top-centre panel box is on
    screen, which says nothing about what it says.
    """

    def __init__(self, frames: Callable, panel_present: Callable, *,
                 emit: Callable | None = None):
        self.frames = frames
        self.panel_present = panel_present
        self.emit = emit
        # A panel was showing when this approach was armed, so the first
        # panel we see is not news.
        self._armed = False
        self._cleared = True
        self.destination = ""
        # Counted so a run can be read afterwards: how often the start prompt
        # held it back, and how often it actually stopped a walk.
        self.arms = 0
        self.looks = 0
        self.held_back = 0
        self.fired = 0

    # ---- arming -------------------------------------------------------------
    def arm(self, destination: str = "") -> None:
        """Called once before the approach walks begin.

        Looks at the screen right now. If a panel is already showing, arrival
        is held back until it goes away; if the screen is blank, or we could
        not look, arrival is live immediately.
        """
        self.destination = str(destination or "")
        self.arms += 1
        self._armed = True
        showing = self._panel()
        # None -- could not look -- is treated as "no panel showing", which is
        # the permissive choice, and it is the right one here: the pessimistic
        # choice would disarm arrival for the whole route every time a single
        # frame grab failed, and then every walk runs on its timer again,
        # which is the failure this watcher exists to stop. A stray early fire
        # costs one refused press with a reason; a disarmed watcher costs the
        # trip.
        self._cleared = not showing
        if showing:
            self._say(f"a prompt is already showing here, so the walk to "
                      f"{self._where()} will not stop for it — waiting to "
                      f"step off it first")

    def disarm(self) -> None:
        self._armed = False
        self._cleared = True
        self.destination = ""

    # ---- the question -------------------------------------------------------
    def __call__(self) -> bool:
        if not self._armed:
            return False
        showing = self._panel()
        if showing is None:
            return False                       # could not look; keep walking
        self.looks += 1
        if not showing:
            if not self._cleared:
                self._cleared = True
                self._say("stepped off the prompt we started on — now "
                          f"watching for {self._where()}")
            return False
        if not self._cleared:
            # This is still the prompt the route set off from. THE BUG.
            self.held_back += 1
            return False
        self.fired += 1
        self._say("a prompt has come into view — stopping the walk here "
                  "rather than running the rest of the timer")
        return True

    # ---- helpers ------------------------------------------------------------
    def _panel(self) -> bool | None:
        """True panel, False no panel, None could not look."""
        try:
            frame = self.frames()
        except Exception:
            return None
        if frame is None:
            return None
        try:
            return bool(self.panel_present(frame))
        except Exception:
            return None

    def _where(self) -> str:
        return (self.destination.replace("_", " ") if self.destination
                else "the place we are walking to")

    def _say(self, text: str) -> None:
        if self.emit is None:
            return
        try:
            from ..telemetry.events import Thought
            self.emit(Thought(topic="arrival", text=text))
        except Exception:
            pass
