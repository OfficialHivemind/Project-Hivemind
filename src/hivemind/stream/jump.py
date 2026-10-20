"""Stream chat makes the bot jump. DESIGN 8ef.

The owner, live on YouTube: "make it so when people type "jump" the Ai
jumps". The first thing chat can make the character DO, so it is built the
way the field vote is (stream/gate): chat only ever ASKS, the bot decides.

  GUI side (`JumpAsks`): a chat line that is just "jump" -- "jump", "JUMP",
  "!jump", "jump!!", "jump jump" -- is an ask. The asks are folded into one
  `ChatJump` a second at most, so a chat typing it forty times sends the
  socket a few lines, not forty.

  Bot side (`ChatJumps`): an ask is held until the gather pattern reaches the
  end of a leg (act/routes.RouteRunner.between_legs), and only there does the
  character jump: in the field, walking the pattern -- never on a route
  between places, the cannon, a convert, a menu or the hive, and never while
  the owner has Pause or Take Over on (run_farm's `chat_jump` asks the
  guarded input first). At most one jump every JUMP_EVERY seconds, however
  many ask; an ask nobody could act on for JUMP_STALE seconds is dropped, so a
  "jump" typed during the walk home does not fire minutes later in the field.

Nothing here presses a key. `ChatJumps.take` says whether one may be pressed.
"""
from __future__ import annotations

import re
import threading
import time

from ..telemetry.events import ChatJump

# THE SPACING. Chosen, not measured: a Roblox jump is in the air for well under
# a second, and one every four seconds is a jump chat can see answer it while
# the pattern keeps most of its time on the ground. A gather pattern's leg is
# about half a second (24 legs in a ~13 s pass), so an ask waits one leg at
# most once the spacing allows it.
JUMP_EVERY = 4.0
# An ask older than this is about a moment that has gone. Twice the spacing:
# an ask that arrives just after a jump still gets the next one.
JUMP_STALE = 2 * JUMP_EVERY
# The GUI sends its folded asks this often at most.
SEND_EVERY = 1.0
# "jump jump jump" is still one person asking; a longer message is a sentence.
MAX_WORDS = 3

KEY_ON = "stream.chat_may_jump"

_WORD = re.compile(r"[a-z]+")


def is_jump(text) -> bool:
    """Is this chat line an ask to jump? Only the word itself, up to
    MAX_WORDS times, with any punctuation around it: "jump on the cannon"
    is a sentence about jumping, not an ask."""
    words = _WORD.findall(str(text or "").lower())
    return 0 < len(words) <= MAX_WORDS and all(w == "jump" for w in words)


class JumpAsks:
    """GUI side: chat's asks, folded into one ChatJump per SEND_EVERY."""

    def __init__(self, clock=time.time):
        self.clock = clock
        self._asks = 0
        self._askers: set[str] = set()
        self._platform = ""
        self._sent_at: float | None = None

    def hear(self, line) -> bool:
        """True when this ChatLine asked for a jump."""
        if not is_jump(getattr(line, "text", "")):
            return False
        self._asks += 1
        self._askers.add(str(getattr(line, "user", "") or "?"))
        self._platform = str(getattr(line, "platform", "") or "")[:20]
        return True

    def due(self) -> ChatJump | None:
        """The folded asks, once SEND_EVERY has passed since the last send."""
        now = self.clock()
        if not self._asks:
            return None
        if self._sent_at is not None and now - self._sent_at < SEND_EVERY:
            return None
        event = ChatJump(asks=self._asks, askers=len(self._askers),
                         platform=self._platform)
        event.at = now
        self._asks, self._askers, self._sent_at = 0, set(), now
        return event

    def clear(self) -> None:
        self._asks, self._askers = 0, set()


class ChatJumps:
    """Bot side. `offer` takes chat's ask off the socket (its reader thread);
    `take` is asked by the gather pattern between two legs (the farm's
    thread). `enabled()` reads the owner's switch at every use. Never raises:
    a stream feature must never be the reason a pattern stops."""

    def __init__(self, enabled=lambda: True, clock=time.time):
        self.enabled = enabled
        self.clock = clock
        self._lock = threading.Lock()
        self._asks = 0
        self._askers = 0
        self._asked_at: float | None = None
        self._jumped_at: float | None = None
        self.jumps = 0
        self.dropped = 0

    def _on(self) -> bool:
        try:
            return bool(self.enabled())
        except Exception:
            return False

    def offer(self, event) -> None:
        if not isinstance(event, ChatJump) or not self._on():
            return
        try:
            asks = max(1, min(1000, int(event.asks or 1)))
            askers = max(1, min(asks, int(event.askers or 1)))
        except (TypeError, ValueError):
            asks, askers = 1, 1
        now = self.clock()
        with self._lock:
            self._asks += asks
            self._askers = max(self._askers, askers)
            self._asked_at = now

    def take(self) -> tuple[int, int] | None:
        """(asks, askers) when the character may jump now, and the asks are
        spent; None otherwise. An ask kept waiting past JUMP_STALE is
        dropped; one inside the spacing waits for it."""
        if not self._on():
            with self._lock:
                self._asks, self._askers, self._asked_at = 0, 0, None
            return None
        now = self.clock()
        with self._lock:
            if not self._asks or self._asked_at is None:
                return None
            if now - self._asked_at > JUMP_STALE:
                self.dropped += self._asks
                self._asks, self._askers, self._asked_at = 0, 0, None
                return None
            if self._jumped_at is not None and now - self._jumped_at < JUMP_EVERY:
                return None
            asked = (self._asks, self._askers)
            self._asks, self._askers, self._asked_at = 0, 0, None
            self._jumped_at = now
            self.jumps += 1
            return asked
