"""Asking the vision model what went wrong, at the moment it goes wrong.

THE OWNER'S IDEA, and it is the right one: "if u wire up the ai to see clearly
and analyze the gameplay then it can also help u fix and debug and stuff".

Every failure this project hit today was diagnosed by a human looking at a
screenshot after the fact:

    the bot farmed at the ticket shop    -- he watched it and said so
    it died to the Mantis repeatedly     -- he watched it and said so
    it opened a Polar Bear quest dialog  -- he watched it and said so
    it jumped behind a ledge going home  -- he watched it and said so

Every one of those is visible in a single frame, and the model can already
read a frame exactly -- MEASURED: handed a real notification panel it returned
"You've made 73,013,670 Honey", commas and all. What was missing was not
capability. It was that nothing ASKED.

WHAT THIS IS NOT. It does not decide anything. The bot's control flow is
unchanged and no key is pressed because of an answer here. The model is an
observer that writes down what it sees when something has already gone wrong,
and its answers go into the event stream as Thoughts -- so they appear in the
GUI's reasoning pane while the run is happening, and in the session log
afterwards for whoever is debugging.

That separation is deliberate. A 7B model is good enough to say "the character
is standing at a shop counter" and not good enough to be trusted with a
keypress, and conflating those is how a bot ends up doing something confident
and wrong.

WHY IT IS RATE-LIMITED. A question costs a couple of seconds and the answer is
only interesting when the situation changed. A stall that lasts a minute would
otherwise ask the same question twenty times and fill the pane with the same
sentence. `MIN_GAP_SECONDS` is a floor between questions, and identical
reasons inside that window are dropped.
"""
from __future__ import annotations

import time

from ..telemetry.events import Level, Log, Thought

MIN_GAP_SECONDS = 20.0

# Deliberately open questions. A leading question ("is the character stuck?")
# gets agreement from any model; an open one gets a description that can be
# read later and checked against the frame.
QUESTIONS = {
    "where": "Where is the player character in this Roblox Bee Swarm "
             "Simulator screenshot? Name the place if you recognise it "
             "(hive, flower field, shop, cannon). Answer in one sentence.",
    "why_no_pollen": "This is Roblox Bee Swarm Simulator. The player is "
                     "supposed to be collecting pollen in a flower field but "
                     "the pollen counter is not rising. Looking only at this "
                     "image, say what the player appears to be standing on or "
                     "near, and whether there are flowers around them. Two "
                     "sentences at most.",
    "dialog": "Is there a dialogue box, menu, shop window or NPC "
              "conversation open in this Roblox screenshot? If yes, say what "
              "it is and quote any text. If no, answer exactly: NO.",
    "danger": "In this Roblox Bee Swarm Simulator screenshot, is there a mob "
              "or monster near the player (for example a mantis, ladybug, "
              "rhino beetle, spider or scorpion)? If yes name it and say "
              "where it is. If no, answer exactly: NO.",
}


class Supervisor:
    """Looks at the screen when something goes wrong and says what it sees.

    `frames()` returns the current frame, `model` is a `brain.vlm.VisionModel`
    (duck-typed: anything with `.available()` and `.ask(png, question)`), and
    `emit` is the event sink.
    """

    def __init__(self, frames, model, emit=None, clock=time.monotonic,
                 min_gap: float = MIN_GAP_SECONDS):
        self.frames = frames
        self.model = model
        self.emit = emit or (lambda event: None)
        self.clock = clock
        self.min_gap = float(min_gap)
        self.asked = 0
        self.skipped = 0
        self._last_at = -1e9
        self._last_reason = ""

    def _encode(self, frame) -> bytes | None:
        try:
            import cv2
            ok, buf = cv2.imencode(".png", frame[:, :, :3])
            return buf.tobytes() if ok else None
        except Exception:
            return None

    def look(self, question_key: str, reason: str,
             force: bool = False) -> str | None:
        """Ask one question about the current frame. None if it did not ask.

        Never raises: a supervisor that can break the run it is supervising
        is worse than no supervisor.
        """
        now = self.clock()
        if not force and reason == self._last_reason and \
                now - self._last_at < self.min_gap:
            self.skipped += 1
            return None
        question = QUESTIONS.get(question_key, question_key)
        try:
            if not self.model.available():
                return None
            frame = self.frames()
            if frame is None:
                return None
            png = self._encode(frame)
            if png is None:
                return None
            answer = self.model.ask(png, question)
            text = getattr(answer, "text", answer)
            if not isinstance(text, str) or not text.strip():
                return None
        except Exception as exc:
            self.emit(Log(message=f"the supervisor could not look: {exc}",
                          level=Level.WARN, source="supervisor"))
            return None

        self.asked += 1
        self._last_at, self._last_reason = now, reason
        clean = " ".join(text.split())
        self.emit(Thought(topic="watching", text=clean, detail=reason))
        return clean

    def diagnose_stall(self, detail: str = "") -> str | None:
        """The pollen counter stopped moving. Why?"""
        return self.look("why_no_pollen", f"pollen flat: {detail}")

    def diagnose_lost(self, detail: str = "") -> str | None:
        """A route finished but nothing confirms where we are."""
        return self.look("where", f"position unconfirmed: {detail}")

    def check_dialog(self, detail: str = "") -> str | None:
        """Did we open something by accident? This is the Polar Bear check."""
        return self.look("dialog", f"checking for a dialogue: {detail}")

    def check_danger(self, detail: str = "") -> str | None:
        """Is there a mob about to kill us and empty the backpack?"""
        return self.look("danger", f"checking for mobs: {detail}")

    def describe(self) -> str:
        return (f"{self.asked} looks taken"
                + (f", {self.skipped} skipped as repeats" if self.skipped else ""))
