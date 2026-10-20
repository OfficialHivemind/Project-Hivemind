"""Letting the model steer, instead of replaying a recorded walk.

THE OWNER'S ARGUMENT, and today's evidence is on his side:

    "ai should be the one moving the character its prolly smarter it can look
     at the screen and be like hmm im over here and look around and be like oh
     my hives over here i gotta go there and deposit honey and stuff like that"

I argued against this on latency: the model answers in 1.6-9 s and movement
needs decisions far faster than that. That argument was about the wrong layer.
Dodging a mantis needs reflexes. Deciding WHICH WAY THE HIVE IS does not -- a
human glances, picks a direction, walks for several seconds, and glances
again. At that cadence the model is fast enough, and it re-decides from what
is actually on screen every time.

Meanwhile the recorded routes keep failing in exactly the way a fixed script
fails when reality moves: "it took cannon to pine, it immidietly went up ramp
and tried to glide from ramp which as youwould expected did nothing but hit
the ground then it walked to the right towards pine into a wall", "then made
its way inside the trophy store with sprinklers". A route cannot notice a
wall. This can.

HOW THE TWO LAYERS SPLIT

  fast, every 100 ms   mob nameplates, the prompt panel, the HUD -- reflexes
                       and facts, from cheap detectors that never guess
  slow, every few sec  which way to go, and whether we have arrived

ARRIVAL IS NOT THE MODEL'S JOB. The model proposes a direction; a measured
detector confirms the destination. `vision.banner` reading "Make Honey" is
what says we are at the hive, because that has been verified on real frames
and the model's opinion has not. If the model says ARRIVED and the detector
disagrees, the detector wins and the walk continues.

WHAT IT IS ALLOWED TO PRESS. Movement keys only -- w, a, s, d -- plus the
camera taps. It cannot press `e`, `escape`, `enter` or `r`, so no answer it
gives can open a menu, leave the server, claim something, or start a
conversation with Polar Bear. The worst a wrong answer can do is walk the
wrong way for a couple of seconds, which the next look corrects.
"""
from __future__ import annotations

import time

from ..telemetry.events import Thought

# Movement only. This set is the safety boundary and is checked, not trusted.
MOVES = {
    "FORWARD": "w",
    "BACK": "s",
    "LEFT": "a",
    "RIGHT": "d",
}
TURN = {"TURN_LEFT": "comma", "TURN_RIGHT": "period"}

# How long one decision's movement lasts. Long enough that the model's
# thinking time is not most of the cycle, short enough that a wrong call is
# cheap to undo.
STEP_SECONDS = 1.8

# Asked for a single word plus a short reason: generation length is what
# actually costs time here, far more than image size.
QUESTION = (
    "You are controlling the player in Roblox Bee Swarm Simulator and you can "
    "see the current screen.\n"
    "GOAL: {goal}\n"
    "{knowledge}"
    "{history}"
    "Reply with exactly one of these words on the first line:\n"
    "  FORWARD, BACK, LEFT, RIGHT, TURN_LEFT, TURN_RIGHT, ARRIVED, UNKNOWN\n"
    "Then one short sentence saying why.\n"
    "Pick TURN_LEFT or TURN_RIGHT if what you need is not visible and you "
    "should look around. Pick UNKNOWN if you genuinely cannot tell."
)

# THE MODEL HAS NO MEMORY, AND WITHOUT ONE IT SPINS.
#
# MEASURED on the first live run of this class: asked the same question 25
# times it answered TURN_LEFT 25 times, turning three complete circles. Every
# individual answer was reasonable -- "the player is facing a wall and needs
# to turn left" -- and each was made with no knowledge that the previous
# twenty-four said the same thing. That is not the model being stupid; it is
# being asked a question that has no memory in it.
#
# Two fixes, and both are needed. The history below goes INTO the prompt so
# the answer can take it into account, and the hard rule further down stops a
# repeat regardless of what comes back, because a prompt is a request and a
# loop needs a guarantee.
HISTORY_SHOWN = 5

# A full turn is eight camera taps. Turning more than that without
# moving means everything has already been looked at, so the answer cannot be
# "turn again" -- the character has to go somewhere.
MAX_TURNS_BEFORE_MOVING = 8


class Navigator:
    """Walks toward a goal by looking, deciding, moving, and looking again.

    `arrived()` is a cheap measured check that overrides the model. `frames()`
    returns the current frame, `model` answers questions about it, and `vin`
    is the keyboard.
    """

    def __init__(self, vin, frames, model, arrived=None, emit=None,
                 step_seconds: float = STEP_SECONDS, sleep=time.sleep,
                 encode=None):
        self.vin = vin
        self.frames = frames
        self.model = model
        self.arrived = arrived or (lambda: False)
        self.emit = emit or (lambda event: None)
        self.step_seconds = float(step_seconds)
        self.sleep = sleep
        self.encode = encode or _encode_png
        self.steps = 0
        self.unknowns = 0
        self.history: list[str] = []
        self.forced_moves = 0
        self.goal_hint = ""

    def _ask(self, goal: str) -> tuple[str, str]:
        """(decision, reason). ("UNKNOWN", why) when it cannot answer."""
        frame = self.frames()
        if frame is None:
            return "UNKNOWN", "no frame"
        try:
            png = self.encode(frame)
            answer = self.model.ask(png, QUESTION.format(
                goal=goal, history=self._history_line(),
                knowledge=self._knowledge_line()))
        except Exception as exc:
            return "UNKNOWN", f"the model could not answer: {exc}"
        text = getattr(answer, "text", answer)
        if not isinstance(text, str) or not text.strip():
            return "UNKNOWN", "empty answer"
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        head = lines[0].upper().strip(" .:*#-")
        reason = " ".join(lines[1:])[:160] if len(lines) > 1 else ""
        for word in list(MOVES) + list(TURN) + ["ARRIVED", "UNKNOWN"]:
            if head.startswith(word):
                return word, reason
        # The first word was not a decision. Look for one anywhere rather than
        # inventing a direction.
        upper = text.upper()
        for word in list(MOVES) + list(TURN) + ["ARRIVED"]:
            if word in upper:
                return word, reason or text[:160]
        return "UNKNOWN", text[:160]

    def _knowledge_line(self) -> str:
        """What the places look like, from the knowledge base.

        Without it the model is picking a direction from one frame with no
        idea what it is looking for, and it shows: it walked into the shop
        repeatedly because nothing ever told it the shop is not a
        destination. The briefing is about 200 tokens and names the hive by
        its yellow honeycomb walls and its "Make Honey" prompt.
        """
        try:
            from .knowledge import for_navigation
            briefing = for_navigation(self.goal_hint)
        except Exception:
            return ""
        return f"{briefing}\n" if briefing else ""

    def _history_line(self) -> str:
        """What has already been tried, so the answer can account for it."""
        if not self.history:
            return ""
        recent = self.history[-HISTORY_SHOWN:]
        line = ("YOUR LAST ACTIONS (most recent last): "
                + ", ".join(recent) + ".\n")
        if len(recent) >= 2 and len(set(recent)) == 1:
            line += (f"That action has not worked {len(recent)} times in a "
                     f"row. Choose something different.\n")
        return line

    def _turn_streak(self) -> int:
        """How many turns in a row, ignoring nothing else."""
        streak = 0
        for past in reversed(self.history):
            if past in TURN:
                streak += 1
            else:
                break
        return streak

    def _move(self, decision: str) -> None:
        if decision in MOVES:
            with self.vin.held(MOVES[decision]):
                self.sleep(self.step_seconds)
        elif decision in TURN:
            self.vin.tap(TURN[decision])
            self.sleep(0.4)

    def go(self, goal: str, max_steps: int = 20) -> bool:
        """Head for `goal`. True once `arrived()` agrees.

        The measured check is consulted BEFORE the model every step: if it
        already says we are there, nothing needs deciding.
        """
        for step in range(max_steps):
            if self.arrived():
                self.emit(Thought(topic="navigate",
                                  text=f"arrived: {goal}",
                                  detail=f"confirmed after {step} steps"))
                return True
            decision, reason = self._ask(goal)
            self.steps += 1
            self.emit(Thought(topic="navigate",
                              text=f"{decision} — {reason}" if reason
                                   else decision,
                              detail=f"goal: {goal} (step {step + 1})"))
            if decision == "ARRIVED":
                # The model's opinion, not a fact. Check it.
                if self.arrived():
                    return True
                self.emit(Thought(
                    topic="navigate",
                    text="the model said ARRIVED but nothing confirms it — "
                         "carrying on",
                    detail=f"goal: {goal}"))
                continue
            if decision == "UNKNOWN":
                self.unknowns += 1
                decision = "TURN_RIGHT"

            # THE GUARANTEE, not the request. Eight taps is a full circle, so
            # a ninth turn in a row is looking at something already seen. Walk
            # instead: being somewhere else is what changes the view.
            if decision in TURN and self._turn_streak() >= MAX_TURNS_BEFORE_MOVING:
                self.forced_moves += 1
                self.emit(Thought(
                    topic="navigate",
                    text=f"turned {self._turn_streak()} times without moving "
                         f"— walking forward instead of turning again",
                    detail=f"goal: {goal}"))
                decision = "FORWARD"

            self.history.append(decision)
            self._move(decision)
        return self.arrived()


def _encode_png(frame) -> bytes:
    import cv2
    ok, buf = cv2.imencode(".png", frame[:, :, :3])
    if not ok:
        raise ValueError("could not encode the frame")
    return buf.tobytes()
