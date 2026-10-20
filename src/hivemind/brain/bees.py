"""Whether the bees are actually working, and what makes them stop.

THIS MODULE EXISTS BECAUSE THE BOT SPENT A NIGHT FARMING NOTHING.

The measurement, from `docs/BUGS.md`: five minutes standing still in a field
with no reset at any point gave `pollen 0/660,000` and zero bees visible, in
every single minute. Before that, 120 s of gathering at the fields and 120 s at
the hive both collected zero. Every "the route did not reach a field" symptom
chased for hours was downstream of this, and the navigation was never wrong --
the character was standing in good fields with nothing to gather with.

RESEARCHED 2026-09-20 (four questions, each claim then handed to a separate
agent instructed to refute it). Three facts, and together they explain all of
it:

  1. YOU DO NOT OWN A HIVE UNTIL YOU CLAIM ONE, every join. The game marks free
     pads with a red beam and you claim one by pressing E (PC) or tapping the
     large blue button at the top of the screen (tablet/iOS/Android -- which is
     what Sober runs). **Bees only exist once a hive is claimed.** No hive, no
     bees, no pollen, however good the field.

  2. DEATH SENDS THE BEES HOME. Wiki, verbatim: "Once a player dies, all of
     their bees return to the hive to rest, but do not recover energy. This is
     to prevent abusing resetting to get all bees to max energy." They return
     on their own and the player does not have to be at the hive.

  3. DEATH ALSO EMPTIES THE BACKPACK. The owner, watching a live run: a
     death loses all the pollen and sends the player home. This is the
     expensive half and it was learned late. A reset is not a free teleport
     home -- it is a teleport that destroys everything gathered on the way.
     A cycle that resets instead of walking home banks nothing, which is
     exactly what happened: pollen kept rising, honey never moved, and a
     session holding 637,130 pollen started the next run at 0.

  4. WHILE THEY ARE AWAY, NOTHING COLLECTS. Tool-clicking and movement
     collection still work, but this bot does not click, so its collection
     during that window is literally zero.

So the bot's own habits were the second half of the problem. It used `reset` as
a navigation primitive -- it is a free teleport to a known position, which is
genuinely useful -- and ran it roughly twenty times in a night. Each one sent
the swarm home. It then read the resulting zero as "this field is barren",
searched for a better one, got stuck, and reset AGAIN. A loop that punishes
itself for the thing it just did.

RECOVERY_SECONDS IS SOURCED, NOT MEASURED, AND THE SOURCE DISAGREES WITH
ITSELF: the wiki's Energy page says 30 s for all bees (Shocked Bee 15 s) while
the Bees page gives a different figure. 30 s is taken as the working number
because the failure it causes is cheap and self-correcting -- waiting slightly
too long costs seconds, while waiting too little marks a good field barren and
sends the bot on another search. It is a parameter, not a constant, and
`measured_from` records when a real measurement replaces it.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

# See the module docstring: sourced from the wiki, which contradicts itself,
# and rounded up in the direction whose failure is cheap.
RECOVERY_SECONDS = 30.0

# How long after a claim we are willing to believe bees exist without seeing
# evidence. Nothing in the repo measures how long a freshly claimed hive takes
# to load its bees, so this is a budget and is labelled as one.
CLAIM_SETTLE_SECONDS = 5.0


@dataclass
class Swarm:
    """What we believe about the bees, and why.

    Every field records HOW the belief was formed, because the two failure
    modes here are opposite and both expensive: believing the bees are out
    when they are not wastes a night, and believing they are down when they
    are working adds pointless waiting to every cycle.
    """

    hive_claimed: bool = False
    claimed_at: float | None = None
    last_death_at: float | None = None
    # set the moment pollen is seen to RISE -- the only direct proof that
    # bees are working, as opposed to an inference from a clock
    last_proof_at: float | None = None
    deaths: int = 0
    recovery_seconds: float = RECOVERY_SECONDS
    measured_from: str = "wiki Energy page (30 s), unverified on this account"
    notes: list[str] = field(default_factory=list)

    # ---- events -----------------------------------------------------------
    def claimed(self, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        self.hive_claimed = True
        self.claimed_at = now

    def died(self, why: str = "reset", now: float | None = None) -> None:
        """Record a death. A reset IS a death; that is the whole point."""
        now = time.monotonic() if now is None else now
        self.last_death_at = now
        self.deaths += 1
        self.notes.append(f"{why} at {now:.1f}")

    def saw_pollen_rise(self, now: float | None = None) -> None:
        """Direct proof the bees are out. Outranks every clock in here."""
        now = time.monotonic() if now is None else now
        self.last_proof_at = now

    # ---- questions --------------------------------------------------------
    def resting_for(self, now: float | None = None) -> float:
        """Seconds still to wait before the swarm should be back. 0 when out."""
        if self.last_death_at is None:
            return 0.0
        now = time.monotonic() if now is None else now
        if self.last_proof_at is not None and self.last_proof_at > self.last_death_at:
            return 0.0                      # seen working since the death
        left = self.recovery_seconds - (now - self.last_death_at)
        return max(0.0, left)

    def can_gather(self, now: float | None = None) -> tuple[bool, str]:
        """(ready, why). `why` is for a human and is always populated."""
        if not self.hive_claimed:
            return False, ("no hive has been claimed in this server, and bees "
                           "only exist once a hive is claimed — there is "
                           "nothing to gather with")
        left = self.resting_for(now)
        if left > 0:
            return False, (f"the bees went home {self.deaths} death(s) ago and "
                           f"need about {left:.0f}s more to come back "
                           f"({self.measured_from})")
        return True, "hive claimed and the swarm should be out"

    def explains_zero(self, now: float | None = None) -> str | None:
        """If pollen is not rising, is there a known reason that is NOT the field?

        This is what stops the search loop blaming geography for something it
        did to itself. Returns None when the bees really should be working and
        a barren reading therefore means something.
        """
        ready, why = self.can_gather(now)
        return None if ready else why

    def describe(self) -> str:
        if not self.hive_claimed:
            return "no hive claimed — no bees"
        left = self.resting_for()
        if left > 0:
            return f"bees resting, ~{left:.0f}s left (after {self.deaths} deaths)"
        proof = "" if self.last_proof_at is None else ", pollen seen rising"
        return f"hive claimed, swarm out{proof}"
