"""Is the world still on screen? Asked often, because today it was not.

WHAT HAPPENED, 2026-09-20. Sober exited three seconds after a successful hive
claim -- no crash in the journal, no OOM, and its own log stops mid-heartbeat
with no shutdown line. The compositor stayed up with nothing in it, and the bot
went on farming a black rectangle for over two minutes. The owner noticed before
the bot did, which is the part that has to change: "why is the screen black".

THE GUARD ALREADY EXISTED AND WAS TOO SLOW. `farm.BLIND_READS_ALLOWED` is 3 and
the check is correct, but the HUD is only read once per pattern pass, and
`farm_snake` is 231.6 studs -- about 44 s. Three passes is over two minutes, and
the counter had reached exactly 3 when the run was stopped by hand. It was one
read and 44 seconds from catching this itself.

SO THE ANSWER IS TO ASK CHEAPLY AND OFTEN RATHER THAN THOROUGHLY AND RARELY.
MEASURED on this machine: `screenstate.hud_present` costs **0.20 ms** on a real
frame and **0.01 ms** on a black one, against 22.8 ms for a full HUD digit read.
At the walk watcher's 10 Hz that is 0.2% of one core, so it can run on every
tick and still be free.

WHY IT WAITS RATHER THAN FIRING AT THE FIRST BLANK FRAME. A death, a respawn, a
loading screen and a menu all hide the HUD for a moment and none of them means
the game is gone. BeeTuxMacro waits 7.5 s for a respawn to finish, which is the
only measured figure we have for how long the world can legitimately be absent,
so the threshold sits above it.
"""
from __future__ import annotations

import os
import time

from ..platform import soberhealth
from ..telemetry.events import Level, Log

# Longer than the 7.5 s respawn settle measured in BeeTuxMacro's utils.sh, so a
# death cannot be mistaken for a dead game. Short enough that today's failure
# would have been caught in twelve seconds instead of over two minutes.
GONE_AFTER = 12.0

# The check is 0.20 ms, so this is not about cost -- it is about not asking the
# same question of the same frame twenty times a second for no new information.
CHECK_EVERY = 0.5

# ABSENCE HAS TO BE WATCHED, NOT ASSUMED (DESIGN 8dw). MEASURED 2026-09-26
# 07:30:20, attempt 433: the guard called the game gone and stopped the run --
# a rejoin, and the Wealth Clock's hour with it -- while the Roblox client log
# (var/sober.log) kept its 20 s session heartbeat through 07:29:48, 07:30:08,
# 07:30:28 and 07:30:48 with no leave or disconnect, and every route frame
# saved from 07:30:19 on passes `hud_present`. The one failing frame on disk
# is 07:29:38 (the pad's Make Honey panel over a red, full Pollen pill), and
# the convert that followed held the loop for ~40 s in which the guard is not
# called at all. So a gap between checks longer than this restarts the count
# instead of counting as absence...
UNWATCHED_GAP = 3.0
# ...the verdict needs this many absent looks, not one look at each end of a
# gap (12 s at CHECK_EVERY would be 24; 4 is two seconds of watching)...
MIN_ABSENT_LOOKS = 4
# ...and before stopping anything it takes this many fresh looks this far
# apart: one of them showing the world means it never left. A real exit (the
# 2026-09-20 black screen) fails all three in about a second, so it still
# stops within GONE_AFTER plus that.
CONFIRM_LOOKS = 3
CONFIRM_GAP = 0.4
# THE CLIENT'S OWN WORD, AS A SECOND OPINION (DESIGN 8dz). The Roblox client
# log (platform/clientlog) beats a session heartbeat every 20.0 s while the
# client runs and writes a leave or disconnect line when the server
# connection ends. MEASURED twice on 2026-09-26: the 07:30:20 stop above, and
# 10:34:14 (attempt 444, with this confirmed-absence guard installed). That
# session's client log beat at 10:33:43 and 10:34:03 and wrote no leave or
# disconnect before the teardown the stop began at 10:34:14, and all 300
# frames of the two threat dumps saved either side of it (103404, 103422)
# pass `hud_present`, the character gathering in Blue Flower; what the guard
# saw in the seconds between is not on disk. Both stops came about 18 minutes
# into the session, 12-19 s after one of the client's two-minutely flag
# fetches ("Settings Date header", DynamicFastVariableReloader) at 1,084 s of
# its uptime -- 14 s at 10:34 (the 07:30 session's log has since rotated
# out of Sober's folder). So while the log says the client is alive and
# connected, a missing HUD is a screen state and not a lost game: the guard
# HOLDS -- `check` answers True, so the held key comes up and nothing walks
# blind, but nothing is stopped -- and waits for the HUD, for at most this
# long from the first missing look: the 60 s the farm loop already gives a
# HUD to come back (brain/farm HUD_WAIT_SECONDS: a measured join reached the
# world in 39.5 s). A live client whose HUD stays away longer than that is a
# screen that waiting has not brought back, and it stops as before. A missed
# heartbeat or a disconnect ends the hold at once.
CLIENT_WAIT_AT_MOST = 60.0
# FROZEN FRAMES ARE NOT THE WORLD (ROADMAP A11, platform/soberhealth). A frame
# with the HUD drawn passed this guard however long it stayed the same, so a
# hung game or compositor would be farmed blind. MEASURED 2026-10-26 over
# 414,031 consecutive frame pairs of the Oct var/incidents clips: the longest
# run of byte-identical frames that came back was 6.6 s (20261012-075325-stall,
# the world with the HUD up), the next 3.0 s; Sober's splash (run 1116) was
# all 10.8 s. So FROZEN_AFTER is three times the longest that came back, and a
# frozen screen then counts as absent, with the client log's hold as before.
# LOOK-ONLY until a night's "frozen frames would:" lines are checked: a stop
# for it is a rejoin, and no frozen-with-HUD incident is on disk yet.
FROZEN_AFTER = 20.0
FROZEN_LIVE = False


class WorldGuard:
    """Watches for the world disappearing, and says so once.

    `present(frame) -> bool` is the cheap structural test, not a digit read.
    `on_gone()` is called ONCE, the moment the world has been absent longer
    than `gone_after` -- it is where a caller sets its stop flag.
    `client() -> bool | None` is the client log's word (see
    CLIENT_WAIT_AT_MOST); while it says True the guard `holding`s instead.
    """

    def __init__(self, frames, present, on_gone=None, emit=None,
                 gone_after: float = GONE_AFTER,
                 check_every: float = CHECK_EVERY, clock=time.monotonic,
                 client=None, on_hold=None, unblock=None, compositor=None):
        self.frames = frames
        self.present = present
        self.on_gone = on_gone or (lambda: None)
        self.emit = emit or (lambda event: None)
        self.gone_after = float(gone_after)
        self.check_every = float(check_every)
        self.clock = clock
        self.gone = False
        self.checks = 0
        self.missing_since: float | None = None
        self.absent_looks = 0
        self.sleep = time.sleep
        # `client() -> bool | None`: platform/clientlog.ClientLog.alive. None
        # (no log, not joined) leaves the guard exactly as it was.
        self.client = client
        # HOLDING: the verdict was due, but the client log says the game is
        # there, so the keys are up and the run waits for the HUD (see
        # CLIENT_WAIT_AT_MOST). `holds` counts them, `waited` is the longest.
        self.holding = False
        # `on_hold(frame)`: told once as each hold begins, with the frame the
        # guard found no HUD in -- what the 10:34 stop could not show, since
        # nothing kept the guard's own frames. It must not block: the keys
        # are still down until `check` returns.
        self.on_hold = on_hold
        # `unblock(frame) -> str`: asked on every look while HOLDING, for a
        # screen state the run can clear itself; a non-empty answer says what
        # it did. MEASURED 2026-10-16 11:54 (var/incidents/20261016-115456-
        # hud-hold, ROADMAP A25): a game "Use Micro-Converter? Yes/No" box sat
        # over the world for the whole 60 s, the HUD dimmed under it, and the
        # run rejoined -- a box that waiting never closes. The 22:58 rejoin
        # of 15 Oct (also mid-Glitter) is the same shape.
        self.unblock = unblock
        self.unblocked = 0
        # `compositor() -> bool | None`: soberhealth.compositor_alive. False
        # makes a failed capture the game gone at once (ROADMAP A11): nothing
        # can be on a compositor that has exited.
        self.compositor = compositor
        self.frozen = soberhealth.Frozen(UNWATCHED_GAP)
        self.said_frozen = False
        # What the screen was when the verdict came (soberhealth.screen_kind),
        # or the compositor's exit: said in `describe`.
        self.cause = ""
        self.holds = 0
        self.waited = 0.0
        self.outwaited = False
        self.gone_for = 0.0
        # None, not 0.0. With 0.0 the first call computes `now - 0.0`, which
        # is only large because `time.monotonic()` happens to be large -- under
        # an injected clock starting at zero the guard never looked at all, and
        # a test caught it.
        self._last_check: float | None = None

    def check(self) -> bool:
        """True once the world has been gone too long. Safe to call at 10 Hz.

        Returning True is also what stops a held key, because this is wired
        into the same watcher the mob detector uses -- so the character stops
        walking into a wall it cannot see. It is True while `holding` too:
        the keys come up although nothing is stopped.
        """
        now = self.clock()
        if self._last_check is not None and now - self._last_check < self.check_every:
            return self.gone or self.holding
        unwatched = (self._last_check is not None
                     and now - self._last_check > UNWATCHED_GAP)
        self._last_check = now
        if unwatched and self.missing_since is not None and not self.gone:
            # Nobody looked in between: that time is not evidence either way.
            self.missing_since = None
            self.absent_looks = 0
            self.holding = False

        try:
            frame = self.frames()
            here = frame is not None and bool(self.present(frame))
        except Exception:
            # A capture failure is not evidence the game is gone; it is
            # evidence we could not look. Say nothing and try again --
            # unless the compositor itself has exited (ROADMAP A11).
            if not self.gone and self._compositor_lost():
                self.gone = True
                self.cause = ("the nested compositor the game ran in has exited, "
                              "so every capture fails")
                self.emit(Log(message=self.describe(), level=Level.ERROR,
                              source="alive"))
                self.on_gone()
            return self.gone or self.holding
        if here and self._frozen(frame, now):
            here = False

        self.checks += 1
        if here:
            if self.missing_since is not None and not self.gone:
                if self.holding:
                    self.waited = max(self.waited, now - self.missing_since)
                    self.emit(Log(message=(
                        f"the world is back on screen after "
                        f"{now - self.missing_since:.0f}s without the HUD, as "
                        f"the Roblox client's log said it would be — the keys "
                        f"were up while it was away, and the run goes on "
                        f"(DESIGN 8dz)"), level=Level.WARN, source="alive"))
                else:
                    self.emit(Log(message="the world is back on screen",
                                  level=Level.INFO, source="alive"))
            self.missing_since = None
            self.absent_looks = 0
            self.holding = False
            self.gone = False
            self.cause = ""
            return False

        self.absent_looks += 1
        if self.missing_since is None:
            self.missing_since = now
            return False
        if (not self.gone and now - self.missing_since >= self.gone_after
                and self.absent_looks >= MIN_ABSENT_LOOKS):
            # The client's word first: it is a read of state the log reader
            # already holds, where the fresh looks below sleep 0.8 s, and
            # this is asked every CHECK_EVERY while it holds.
            alive = self._client_alive()
            if alive and now - self.missing_since < CLIENT_WAIT_AT_MOST:
                if not self.holding:
                    self.holding = True
                    self.holds += 1
                    if self.on_hold is not None:
                        try:
                            self.on_hold(frame)
                        except Exception:
                            pass           # a snapshot must never keep keys down
                    missing = now - self.missing_since
                    self.emit(Log(message=(
                        f"the HUD has been missing for {missing:.0f}s "
                        f"over {self.absent_looks} looks, but the Roblox client's own "
                        f"log still beats its heartbeat and records no leave or "
                        f"disconnect — keys up, waiting up to "
                        f"{CLIENT_WAIT_AT_MOST - missing:.0f}s more for the HUD "
                        f"({CLIENT_WAIT_AT_MOST:.0f}s from the first missing look) "
                        f"rather than calling the game gone (DESIGN 8dz)"),
                        level=Level.WARN, source="alive"))
                if self.unblock is not None:
                    try:
                        did = self.unblock(frame)
                    except Exception:
                        did = ""           # an unblock that fails is just no help
                    if did:
                        self.unblocked += 1
                        self.emit(Log(message=did, level=Level.WARN, source="alive"))
                return True
            self.outwaited = bool(alive)
            self.holding = False
            if self._seen_again():
                self.emit(Log(message=(
                    f"the HUD was missing for {now - self.missing_since:.0f}s "
                    f"over {self.absent_looks} looks, but a fresh look shows "
                    f"the world — not stopping (DESIGN 8dw)"),
                    level=Level.WARN, source="alive"))
                self.missing_since = None
                self.absent_looks = 0
                return False
            self.gone = True
            self.gone_for = now - self.missing_since
            self.cause = (soberhealth.screen_kind(frame) if frame is not None else "") or self.cause
            self.emit(Log(message=self.describe(), level=Level.ERROR,
                          source="alive"))
            self.on_gone()
        return self.gone

    def _client_alive(self) -> bool:
        """The client log's verdict; only True counts, and a reader that
        fails is no evidence."""
        if self.client is None:
            return False
        try:
            return self.client() is True
        except Exception:
            return False

    def _compositor_lost(self) -> bool:
        """Only a definite False counts; a reader that fails is no evidence."""
        if self.compositor is None:
            return False
        try:
            return self.compositor() is False
        except Exception:
            return False

    def _frozen(self, frame, now: float) -> bool:
        """The screen has not changed for FROZEN_AFTER: True only when
        FROZEN_LIVE; look-only it says so once a freeze."""
        still = self.frozen.see(frame, now)
        if still < FROZEN_AFTER:
            self.said_frozen = False
            return False
        if FROZEN_LIVE:
            if not self.cause:
                self.cause = f"the screen has not changed for {still:.0f}s"
            return True
        if not self.said_frozen:
            self.said_frozen = True
            self.emit(Log(message=(
                f"frozen frames would: count the world as gone — the screen has "
                f"not changed by one sampled byte for {still:.0f}s with the HUD up "
                f"(FROZEN_LIVE is off, ROADMAP A11)"), level=Level.WARN, source="alive"))
        return False

    def _seen_again(self) -> bool:
        """CONFIRM_LOOKS fresh looks, CONFIRM_GAP apart: is the world there in
        any of them? A capture that fails is not a sighting."""
        for i in range(CONFIRM_LOOKS):
            if i:
                self.sleep(CONFIRM_GAP)
            try:
                frame = self.frames()
                if (frame is not None and bool(self.present(frame))
                        and not self._frozen(frame, self.clock())):
                    return True
            except Exception:
                continue
        return False

    def describe(self) -> str:
        if not self.gone:
            if self.missing_since is None:
                return "the world is on screen"
            if self.holding:
                return ("the HUD is missing but the Roblox client's log says the "
                        "game is there — keys up, waiting for the HUD")
            return "the HUD is missing, waiting to see whether it comes back"
        gone_for = max(self.gone_after, self.gone_for)
        if self.cause.startswith("the nested compositor"):
            return (f"{self.cause} — the game is gone, so the run stops and the "
                    f"relaunch starts a fresh session")
        seen = f" ({self.cause})" if self.cause else ""
        if self.outwaited:
            return (f"the world has been off screen for {gone_for:.0f}s{seen} "
                    f"although the Roblox client's log still beats — a screen "
                    f"that waiting has not brought back, so the run stops and "
                    f"the relaunch rejoins")
        return (f"the world has been off screen for {gone_for:.0f}s{seen} — "
                "the game is gone, so there is nothing to press keys at")


# How far pollen must fall, as a fraction of the best seen, to be a death
# rather than a misread. Pollen only rises while gathering, so the margin is
# wide -- the same figures the farm loop already uses.
#
# NOT LOWERED, although a CONVERSION LINK -- pollen turned into honey where
# the character stands -- falls below it too, and at 0.5 the watch called one
# a death, filed it against the field and cut the walk short. MEASURED (audit
# 2026-09-26) two ways. Every "died: pollen fell" line in var/night/run-*.log,
# as what was left over the best at the confirming look:
#
#     real deaths   0, 0, 0, 0.0004, 0.0006, 0.0013, 0.0013, 0.023, 0.070, 0.089
#     links         0.394 (run-338 23:11:29), 0.434 (23:11:25), 0.444 (run-356)
#
# -- the links being incidents 231129, 231125 and 20260924-055153, whose
# frames show the character still gathering and the feed saying "Honey (from
# Conversion Link)". But every saved death clip, var/incidents/*-death, read
# frame by frame, overlaps the two: the two legible Links fell to 0.193 of the
# best at the first low look (231125, 231129; "+9,772 Honey (from Conversion
# Link)" in the feed, the character alive in Strawberry), the third to 0.470
# (055153), and a real death fell no lower than 0.433 at its first legible
# low look and was confirmed at 0.497 (223009: the screen goes red, the
# character respawns on the pad with 3,207 of 6,457 --
# night/earlier/005243-run-003.log 22:30:09). A threshold between the two
# logged groups, 0.2, would miss that death, so no drop separates them; the
# honey does, below. And 055153 is a CHAIN of links, each taking a quarter of
# what was left, so a fall that is not a death also moves the baseline down
# (`check`).
DEATH_DROP = 0.5
DEATH_MIN_POLLEN = 1_000
# What a death leaves in the bag, at most, and what a Conversion Link leaves,
# at least. MEASURED (run-654/655, 2026-10-05): real deaths -- the compass at
# the hive a second later -- read 11,717-15,570 at the first read after the
# fall (the respawn's own bag then 0-2,205), at most 4% of what the bag held;
# the Links -- still in the field -- left 652,047-1,244,653, 24-38% of it. So a
# fall that leaves more than both of these is a Link (DeathWatch, brain/farm).
DEATH_LEAVES_MAX = 20_000
# AND THE FEED'S OWN WORDS. MEASURED 2026-10-06 22:47:15 (var/incidents/
# 20261006-224715-death): the bag fell 1,521,984 -> 1,076 with the character
# standing in the Mushroom Field, the feed reading "+273,957 Honey (from Coin
# Scatter)", "+456,595 Honey (from Coin Scatter)" and "Honey (from Conversion
# Link)" -- the bag turned to honey where it stood, the honey counter not read
# in time -- and no "You died!". Taken for a death, the walk home went the hive
# area's way from a field and the run ended asking for a rejoin. A death's own
# line is "You died! Your bees must recover at the hive."
IN_FIELD_CONVERSION_WORDS = ("coin scatter", "conversion link")
DIED_WORDS = "you died"
LINK_KEEPS_SHARE = 0.12


# A DEATH NEEDS PROOF, not only a fall nothing vetoed (AREA deaths, 2026-10-21).
# MEASURED over the 14 death incidents of 20-21 Oct, each last frame checked by
# eye: 8 were not deaths -- the character alive in the field, no "You died!",
# no health bar drawn, the feed reading "Honey (from Pine Tree Forest)" /
# "(from Pepper Patch)" (20261020-023021, 20261021-095515, 111040, 111538,
# 143237, 180055, 210935, 213947). Three of them ended a trip and two of those
# a "did not get there". The 5 real ones each show at least one of: the feed's
# "You died!" (235620), the own health bar read 0 (vision/hurt.own_health:
# 020156, 071805, 235620, 060404; held at 0 for 1.9-3.5 s, ending 0-4.9 s
# before the fall was confirmed, so a once-a-second ring catches it) or the hive
# row in view after the respawn (055507 155,235 px, 060404 618,071, 071805
# 94,141; act/homing.NEAR_YELLOW). The 8 false ones show none: health at least
# 0.69 or no bar, the hive row 0-11,366 px. tests/unit/test_alive.py replays
# them. THE ROW COUNTS ONLY AFTER A TELEPORT, not a walk: two readings in a
# row of the 1 Hz ring (at most DEATH_PROOF_ROW_GAP apart) must jump from
# under NEAR_YELLOW to DEATH_PROOF_ROW_JUMP or more. 023032 (at the hive,
# 101,136 px) was a false death: run-1101 02:30:32 "15,163 -> 0", then at
# 02:30:42 a convert with 320,377 in the bag -- a walk home beside the hive.
# MEASURED 2026-10-21 on its frames: the row rose 19,825 -> 48,348 -> 87,724
# -> 168,848 over 3 s (never under 50,000 then over 100,000 a second later),
# so "a reading under NEAR_YELLOW more than 2 s before" would still have
# passed it. The real ones jumped: 055507 0 -> 193,868 (a 0.3 s white flash
# 6 s before the fall), 060404 0 -> 176,343, 071805 20,126 -> 156,864.
# ponytail: 055507's flash is 0.3 s; a 1 Hz ring can miss it, and that
# death would then be vetoed once live -- check its "would: veto" lines.
# AND IT FAILS TOWARD FILING: no frame at the fall, or a row read that
# raised, files the death as before.
# LOOK-ONLY until a night's "death proof would: veto" lines are checked: a veto
# changes when trips end.
DEATH_PROOF_LIVE = False
DEATH_PROOF_HEALTH = 0.05
DEATH_PROOF_SECONDS = 10.0
DEATH_PROOF_ROW_GAP = 1.5
DEATH_PROOF_ROW_JUMP = 100_000

# AND A BAR THAT FALLS WITH A BIG BAG IS A REASON TO LEAVE (AREA deaths, step 3,
# LOOK-ONLY). MEASURED on the real Pine Tree deaths (vision/hurt.own_health):
# 060404 0.6 -> 0.4 (t+0.8) -> 0.2 -> 0 (t+2.8), 1,045,384 pollen lost, the
# mob logged at 06:03:51, 13 s before; 020156 0.5 -> 0.4 -> 0.2 -> 0 over 6 s;
# 071805 0.2 -> 0. None of the 8 false deaths drew the bar. The gather pattern
# walks on beside the mob (brain/threat cuts one walk only). So a bar that
# says leave (`retreat_due`) with at least decide.WORTH_PROTECTING in the bag is
# said as "retreat would:", once per RETREAT_SAY_SECONDS. RETREAT_LIVE's live
# half (end the gather, walk home) is built after a night of those lines.
#
# WHEN THE BAR SAYS LEAVE: two reads in a row (one tick apart, at most
# RETREAT_READ_GAP) both drawn, both under RETREAT_FALLING, the newer under
# RETREAT_HEALTH, and neither an exact 0.0. MEASURED 2026-10-27 (docs/pending/
# retreat.md): replayed at 1 Hz over all 232 saved death windows and 5,451
# mob-sighting windows with no death within 90 s (var/incidents, 20 Sep-27 Oct).
# Of the 80 real deaths (the bar reaches 0), 45 drew a bar between 0.05 and 0.6
# at least 0.5 s before it emptied; the rest died from full in one read, which
# no bar rule can see. The old rule (one read under 0.6) caught 43 of those 45
# but fired in 88 of the 5,451 quiet windows; this one catches 37 of 45 (82%,
# median 2.9 s before the bar empties) and fires in 6. In the logs (runs
# 1173-1257) only 6 of 31 old warnings came before a death.
#   * an exact 0.0 is the reader's flash path (hurt.own_health returns 0.0 when
#     the fill's left end is dim, as bugrun.Hits notes): 112 of the 267 quiet
#     windows that drew a bar read 0.00 somewhere, two in a row in 7 of them
#     (20261006-050424 ...). A real empty bar is the death itself, too late.
#   * the older read under RETREAT_FALLING, not under RETREAT_HEALTH: falls are
#     about 0.2 a second (060404 above), so asking both reads to be under 0.3
#     lost 37 -> 27 deaths for no fewer quiet fires (6 -> 6).
#   * a low bar that is refilling still counts: 041615 sat at 0.30-0.38 rising
#     for 8 s and died; refusing a rising pair changed no count (ASSUMED that a
#     mob is still near while the bar is low).
RETREAT_LIVE = False
RETREAT_HEALTH = 0.3
RETREAT_FALLING = 0.6
RETREAT_READ_GAP = 1.5
RETREAT_SAY_SECONDS = 10.0


def retreat_due(reads) -> bool:
    """Whether the last two own-health reads of `reads` ([(at, health)],
    drawn reads only, oldest first) say leave (RETREAT_HEALTH above)."""
    if len(reads) < 2:
        return False
    (ta, a), (tb, b) = reads[-2:]
    return (tb - ta <= RETREAT_READ_GAP and b < RETREAT_HEALTH
            and a < RETREAT_FALLING and a != 0.0 and b != 0.0)


def row_jump(rows) -> tuple[int, int] | None:
    """The first (before, after) of two readings in a row of `rows` ([(at,
    hive row px)], oldest first) at most DEATH_PROOF_ROW_GAP apart that jumped
    from under NEAR_YELLOW to DEATH_PROOF_ROW_JUMP or more: a teleport."""
    from ..act.homing import NEAR_YELLOW
    for (ta, a), (tb, b) in zip(rows, rows[1:]):
        if tb - ta <= DEATH_PROOF_ROW_GAP and a < NEAR_YELLOW and b >= DEATH_PROOF_ROW_JUMP:
            return (int(a), int(b))
    return None


def death_proof(said: str, low_health: float | None, frame,
                jump: tuple[int, int] | None = None) -> str:
    """Why a fall is a death -- the feed's DIED_WORDS, the own health bar read
    at most DEATH_PROOF_HEALTH within DEATH_PROOF_SECONDS (`low_health`, the
    lowest drawn reading, None for none), or the hive row in view on `frame`
    (act/homing.NEAR_YELLOW) after a teleport (`jump`, from `row_jump`) -- or
    "" when none of the three holds. A row read that raises files it."""
    if DIED_WORDS in (said or ""):
        return "the feed reads You died"
    if low_health is not None and low_health <= DEATH_PROOF_HEALTH:
        return f"the health bar read {low_health:.2f}"
    if frame is not None:
        try:
            from ..act.hive import hive_bearing
            from ..act.homing import NEAR_YELLOW
            yellow = hive_bearing(frame)[1]
        except Exception:
            return "hive row unreadable (filed)"
        if yellow >= NEAR_YELLOW and jump is not None:
            return (f"the hive row is in view ({yellow:,} px) after a jump "
                    f"{jump[0]:,} -> {jump[1]:,} px")
    return ""

# A DEATH THE FEED HAS SINCE CONTRADICTED (ROADMAP A28). MEASURED run-1025
# 06:04:38: "died: pollen fell 167,370 -> 7,247" -- every incident frame
# shows the character alive in Pine Tree under a cloud of honey numbers (a
# conversion) -- and the trip gathered on there for five more minutes,
# the feed naming Pine Tree from 06:04:50. The walk home still believed the
# death ("the character is at the spawn point"), looked for the hive wall
# from Pine Tree, saw 0 px in every direction, and rejoined. A field the
# feed credits this long after the death is where the character stands;
# the margin skips feed lines from before it still fading on screen.
FEED_AFTER_DEATH_SECONDS = 10.0


def field_after_death(notes, died_at: float) -> str | None:
    """The field the feed credited from FEED_AFTER_DEATH_SECONDS after the
    death on (`notes` a FieldNotes, `died_at` on its clock), or None -- in
    which case the death still stands and the character is at the hive."""
    try:
        return notes.field_since(float(died_at) + FEED_AFTER_DEATH_SECONDS)
    except Exception:
        return None


# A DEATH ON THE WALK HOME IS THAT WALK'S MISS (ROADMAP A9, rule D1; audit in
# docs/pending/deaths-2026-10-19.md). MEASURED 5-13 Oct: 18 deaths on walks
# home took 59.8M pollen, the biggest cause of the fortnight. 12 were falls
# off the map (the frames go black, then red: incidents 20261011-210716,
# 20261012-065602, -075723): Rose's walk home 9 times (1.4-5.3M each, 11 Oct
# 01:21 to 12 Oct 07:57), Cactus's twice, Pumpkin's once. 3 were mobs: on
# Mountain Top twice while it stood out the Haste wait before the walk (9 Oct
# 13:56 6.8M, 10 Oct 04:49 3.0M), on Blue Flower's walk once (13 Oct 02:56,
# 5.0M). Each was logged "counts neither for nor against that walk home", so
# the planner went on pricing those walks home at P 0.92. None since 13 Oct
# 13:49 (R4's leaned walks home, more Whirligigs); this keeps a relapse from
# hiding. Only a death that took a trip's worth of pollen (run_farm
# DEATH_PROVES_FIELD: 16 of the 18 lost 1.4-6.8M, the other two 3,793 and
# 7,043) and that no feed line since has contradicted (A28).
WALK_HOME_DEATH_MIN_LOST = 55_000


def walk_home_death_counts(died_at, entered: float, lost, field_since) -> bool:
    """Should the death that cut a walk home short count as that walk's miss?
    `died_at` the death's stamp (on_death, only on an empty bag) or None,
    `entered` when the walk home began (same clock), `lost` the pollen it
    took, `field_since` field_after_death's answer."""
    return (died_at is not None and float(died_at) >= float(entered)
            and int(lost or 0) >= WALK_HOME_DEATH_MIN_LOST and not field_since)


# A FALL THAT ENDS A TRIP WHILE IT LEAVES A SMALL BAG WELL FILLED (A9, rule D3,
# LOOK-ONLY). MEASURED since 14 Oct: a Link chain on a just-emptied bag falls
# under DEATH_LEAVES_MAX and gets called a death; 6 trips ended for it: the
# pad then was not there ("pad: held forward for 8s without the hive prompt",
# run-1048 06:31 6,852 of 24,625 and 06:48 8,799 of 23,561, run-1049 08:00
# 13,320 of 33,364, run-1067 23:22 3,678 of 19,206), the feed still named the
# field (run-1049 07:55, 6,779 of 16,821) or the bag was kept (run-1018 08:04,
# 15,961 of 101,232). But a real death at the hive left 3,567 of 16,352
# (run-705 02:20, the pad found in 0.2 s), so the share alone cannot tell
# them apart: the farm loop says what it would do and still ends the trip.
LOOK_LINK_SHARE = 0.15
LOOK_LINK_BAG_MAX = 200_000


def small_bag_fall_unproven(best, left) -> bool:
    """Would rule D3 hold the trip: a bag under LOOK_LINK_BAG_MAX that kept at
    least LOOK_LINK_SHARE of itself through the fall?"""
    try:
        best, left = int(best), int(left)
    except (TypeError, ValueError):
        return False
    return 0 < best < LOOK_LINK_BAG_MAX and left >= LOOK_LINK_SHARE * best
# A FALL THE HONEY ROSE WITH IS A CONVERSION, NOT A DEATH. MEASURED on the
# same clips as the honey risen since the best reading over the pollen lost,
# at every low look where both pills read: real deaths 0.000-0.020, and
# 0.145-0.184 for the 223009 death; the Links 1.020-2.773. A pickup puts back
# 1.02-1.06 honey per pollen it takes (231125 frames 124-125: 7,941 -> 1,533
# and honey +6,536; 055153 frames 013-016: 46,358 -> 35,508 and honey
# +11,463), and a base read before an earlier link of a chain carries that
# link's honey too. Across a real death honey moves by the hive's trickle
# alone (20260924-041615: 965,906 -> 0 with honey +44 across the fall and
# +1,174 over the whole 11.4 s window). Half sits between them. It must hold
# on BOTH looks, and the honey counter rolls unreadably for seconds after a
# conversion (055153: unreadable in 74 of the 90 frames whose reading
# changed, and on all 40 of its low looks), so this is a veto used when both
# looks can read it, never a requirement; DEATH_DROP is the rule that holds
# without it.
#
# The trickle is taken off first: the rise between the last two honey
# readings before the fall, times the seconds since (about 100 a second in
# 041615), so a slow gatherer's own honey cannot pass for a conversion.
# Refreshed at most every HONEY_BASE_SECONDS while pollen is not falling, one
# HUD read (22.8 ms MEASURED, see DEATH_CHECK_EVERY) each; the trickle
# correction makes its age harmless.
CONVERSION_HONEY_SHARE = 0.5
HONEY_BASE_SECONDS = 5.0
# AND NO MORE THAN A LINK CAN PAY. A veto on a rise alone would hide a real
# death behind one misread honey reading: brain/farm has seen the counter read
# about nothing (about "-16,000,000 honey"), and a base misread that low makes any
# fall look like a huge rise on both looks. The Links above read at most
# 2.773 of the pollen lost, and this is twice that. A base misread to about
# nothing reads as the whole honey counter, tens of millions on this account
# against a bag of at most about 1.3 million, so about 17 or more even for a
# full bag. A base that fell from the reading before it is itself the misread
# (honey never falls, brain/farm), and then there is no veto either
# (`rise_past_trickle`): DEATH_DROP decides.
LINK_HONEY_MAX = 5.5


def rise_past_trickle(base: list, value: int | None, now: float) -> int | None:
    """Honey `value` read at `now` over the newest of `base` -- the last two
    (honey, read at) from before a fall -- less the trickle those two
    measured. None when there is nothing to compare, or when the newer of the
    two is below the older: honey never falls, so that base is the misread and
    nothing can be judged against it (LINK_HONEY_MAX). See
    CONVERSION_HONEY_SHARE; the farm loop's own death test uses it too."""
    if not base or value is None:
        return None
    last, at = base[-1]
    trickle = 0.0
    if len(base) >= 2:
        old, old_at = base[-2]
        if last < old:
            return None
        if at > old_at:
            trickle = max(0.0, (last - old) / (at - old_at))
    return int(value - last - trickle * max(0.0, now - at))


def honey_says_converted(rise: int | None, lost: int) -> bool:
    """Did the honey rise with a fall of `lost` pollen the way a Conversion
    Link pays it -- past its trickle (`rise_past_trickle`) by at least
    CONVERSION_HONEY_SHARE of the fall and by no more than LINK_HONEY_MAX of
    it? False when the rise could not be read. Shared by DeathWatch and the
    farm loop's own death test, so the two cannot disagree about a Link."""
    return (rise is not None and lost > 0
            and CONVERSION_HONEY_SHARE * lost <= rise <= LINK_HONEY_MAX * lost)


# How often to look. A HUD read costs 22.8 ms, so once a second is about 2% of
# one core -- and it is the difference between catching a death as it happens
# and noticing it up to a whole pattern pass later.
DEATH_CHECK_EVERY = 1.0


class DeathWatch:
    """Notices a death WHEN IT HAPPENS, not a pattern pass later.

    THE BUG THIS FIXES, and it cost a real diagnosis. On 2026-09-20 a mantis
    killed the character carrying 362,208 pollen. The farm loop noticed,
    correctly, and saved an incident -- but it only reads pollen once per
    pattern pass, and `farm_snake` is 231.6 studs. By the time the drop was
    seen the character had already respawned, so ALL 150 SAVED FRAMES SHOWED
    THE HIVE. The evidence window contained the aftermath and none of the
    cause, and the owner had to tell us what killed them.

    Reading the pill once a second instead costs about 2% of one core and puts
    the mantis inside the window.

    It reports and does not act: `on_death(lost, reading)` is where the caller
    saves its incident. Nothing here presses a key, because the right response
    to a death is a decision the farm loop owns.
    """

    def __init__(self, pollen, on_death=None, emit=None,
                 drop: float = DEATH_DROP, floor: int = DEATH_MIN_POLLEN,
                 check_every: float = DEATH_CHECK_EVERY, clock=time.monotonic,
                 honey=None, feed=None, frame=None):
        self.pollen = pollen
        # `frame() -> image`: a recent game frame (run_farm's shared capture),
        # read once a tick for the own health bar and at a death for the hive
        # row (death_proof). None: no proof is asked for.
        self.frame = frame
        self._health: list[tuple[float, float]] = []   # (at, drawn health)
        self._rows: list[tuple[float, int]] = []       # (at, hive row px)
        self.unproven = 0              # falls death_proof found no proof for
        self._said_retreat = -1e9
        # `feed() -> str`: the reward feed's words now, asked only when a fall
        # would be called a death (IN_FIELD_CONVERSION_WORDS). None: not asked.
        self.feed = feed
        # `honey() -> Reading`: see CONVERSION_HONEY_SHARE. None: pollen only.
        # `_honey_base` is the last two legible readings from before any fall,
        # (value, read at), newest last; `_pending_honey` the one taken at
        # the first low look.
        self.honey = honey
        self._honey_base: list[tuple[int, float]] = []
        self._pending_honey: tuple[int, float] | None = None
        self.conversions = 0           # falls the honey showed were a Link
        self.on_death = on_death or (lambda lost, value: None)
        self.emit = emit or (lambda event: None)
        self.drop = float(drop)
        self.floor = int(floor)
        self.check_every = float(check_every)
        self.clock = clock
        self.best = None
        self.deaths = 0
        self.checks = 0
        self._last_check: float | None = None
        self._suspended = 0
        self._pending: int | None = None   # a low read awaiting confirmation
        self.suppressed = 0            # converts this would have called deaths
        # The last HUD reading this took, legible or not, and when. The threat
        # watch asks through `latest` whether the bag is empty before it drops
        # a far bar on a walk out (DESIGN 8di). The HUD is not read again for
        # that.
        self.last_reading = None
        self.last_read_at: float | None = None

    def latest(self, max_age: float):
        """The last reading if it is at most `max_age` seconds old, else None.

        None also while suspended, because a convert or a respawn is emptying
        the bag and nothing read before it describes the bag now.
        """
        if self._suspended or self.last_read_at is None:
            return None
        if self.clock() - self.last_read_at > float(max_age):
            return None
        return self.last_reading

    def check(self) -> bool:
        """True on the tick a death is seen. Safe to call at 10 Hz."""
        if self._suspended:
            return False
        now = self.clock()
        if self._last_check is not None and now - self._last_check < self.check_every:
            return False
        self._last_check = now

        try:
            reading = self.pollen()
        except Exception:
            return False                  # could not look; not evidence
        self.last_reading, self.last_read_at = reading, now
        value = getattr(reading, "value", None)
        if value is None:
            # The bar is still read, at the last bag seen: `retreat_due` needs
            # two reads a tick apart, and MEASURED (docs/pending/retreat.md)
            # the pill was unreadable in 182 of 3,162 low-bar death frames,
            # which cost 37 -> 34 of the 45 catchable deaths.
            self._look_health(now, self.best or 0)
            return False                  # unreadable is NOT zero
        self.checks += 1
        value = int(value)
        self._look_health(now, value)

        if self.best is None or value > self.best:
            self.best = value
            self._honey_before(now)
            return False
        if self.best < self.floor:
            return False                  # too little at stake to tell
        if value > self.best * self.drop:
            self._pending = None
            # A FALL THAT IS NOT A DEATH MOVES THE BASELINE DOWN WITH IT.
            # Conversion Links come in chains, each taking about a quarter of
            # what is left: MEASURED in incident 20260924-055153, 46,358 ->
            # 35,508, then 37,264 -> 27,295, then 26,515 -> 20,168 inside ten
            # seconds, 0.435 of the peak and falling, with the honey unreadable
            # on every low look. Measured against the peak, the third link
            # passes for a death; measured against the last level, none does.
            # A death still falls to about nothing from wherever it starts,
            # and a misread level is replaced by the next higher reading.
            if value < self.best:
                self.best = value
            self._honey_before(now)
            return False

        # ONE LOW READING IS NOT A DEATH, because one low reading is also what
        # a misread looks like. MEASURED on 2026-09-20: the pollen pill was
        # read as 60,053, then 1,259, then 66,153, then 1,259 again inside two
        # seconds, and a fourth read came back
        # '1,259?948,750' at confidence 0.19. The counter cannot actually
        # recover 65,000 pollen in a second, so at least two of those were
        # wrong. A death, by contrast, persists: the backpack stays empty.
        #
        # So the drop has to survive a second consecutive look. This costs one
        # second of notice -- the incident window is seven and a half seconds
        # and still contains the cause -- and it is the difference between an
        # incident file per death and one per misread.
        if self._pending is None:
            self._pending = value
            self._pending_honey = self._honey_now(now)
            return False
        self._pending = None

        # A CONVERSION LINK, SEEN IN THE HONEY: both looks read honey risen
        # past its trickle by what a Link pays for what the bag lost
        # (honey_says_converted: CONVERSION_HONEY_SHARE to LINK_HONEY_MAX).
        lost = self.best - value
        first = self._honey_rise(self._pending_honey)
        second = self._honey_rise(self._honey_now(now))
        if honey_says_converted(first, lost) and honey_says_converted(second, lost):
            self.conversions += 1
            self.emit(Log(message=(
                f"pollen fell {self.best:,} -> {value:,} but honey rose "
                f"{second:,} past its trickle on both looks — a conversion in "
                f"the field (a Conversion Link), not a death; nothing is filed"),
                source="alive"))
            self.best = value
            self._honey_base = []
            return False
        # OR IN WHAT IS LEFT, which the honey cannot see while a Link's
        # numbers float over its counter: a death leaves next to nothing.
        # MEASURED: 24 Links since 2026-09-27 were filed as deaths, 16 of them
        # in Pine Tree (brain/fieldnotes FALSE_DEATHS), and the planner cut
        # trips there short for them.
        if value > max(DEATH_LEAVES_MAX, LINK_KEEPS_SHARE * self.best):
            self.conversions += 1
            self.emit(Log(message=(
                f"pollen fell {self.best:,} -> {value:,} but {value:,} is left, "
                f"and a death leaves the bag empty — a conversion in the field "
                f"(a Conversion Link), not a death; nothing is filed"),
                source="alive"))
            self.best = value
            self._honey_base = []
            return False
        said = self._feed_words()
        if said and DIED_WORDS not in said and any(w in said for w in IN_FIELD_CONVERSION_WORDS):
            self.conversions += 1
            self.emit(Log(message=(
                f"pollen fell {self.best:,} -> {value:,} and the feed reads a "
                f"conversion where the character stands ({said[:80]!r}) and no "
                f"death — not a death; nothing is filed"), source="alive"))
            self.best = value
            self._honey_base = []
            return False
        frame = self._frame() if self.frame is not None else None
        if frame is not None:           # no frame at the fall: filed as before
            proof = death_proof(said, self._lowest_health(now), frame,
                                row_jump(self._rows))
            if not proof:
                note = (f"pollen fell {self.best:,} -> {value:,} with no proof "
                        f"of a death: no You died, no health fall, no hive row")
                if DEATH_PROOF_LIVE:
                    self.unproven += 1
                    self.emit(Log(message=f"not a death: {note}; nothing is filed",
                                  level=Level.WARN, source="alive"))
                    self.best = value
                    self._honey_base = []
                    return False
                self.emit(Log(message=(f"death proof would: veto — {note} "
                                       f"(DEATH_PROOF_LIVE off, filed as before)"),
                              level=Level.WARN, source="alive"))
        self.deaths += 1
        self.emit(Log(message=(f"died: pollen fell {self.best:,} -> {value:,} "
                               f"({lost:,} lost)"),
                      level=Level.WARN, source="alive"))
        self.on_death(lost, value)
        self.best = value                 # start again from where we are now
        return True

    def _frame(self):
        try:
            return self.frame()
        except Exception:
            return None

    def _look_health(self, now: float, bag: int) -> None:
        """Keep the own health bar's drawn readings and the hive row's of the
        last DEATH_PROOF_SECONDS (0.04 ms and 13 ms a read MEASURED on the
        incident frames), and say what `retreat_due` would do with `bag`
        pollen at stake."""
        if self.frame is None:
            return
        frame = self._frame()
        try:
            from ..vision.hurt import own_health
            health = own_health(frame) if frame is not None else None
        except Exception:
            health = None
        self._health = [(at, h) for at, h in self._health
                        if now - at <= DEATH_PROOF_SECONDS]
        self._rows = [(at, y) for at, y in self._rows if now - at <= DEATH_PROOF_SECONDS]
        if frame is not None:
            # ponytail: a full-frame hive_bearing once a tick (~13 ms at 1 Hz);
            # read a downscaled frame if tick time ever shows it.
            try:
                from ..act.hive import hive_bearing
                self._rows.append((now, int(hive_bearing(frame)[1])))
            except Exception:
                pass
        if health is not None:
            self._health.append((now, float(health)))
            self._retreat_would(now, bag)

    def _retreat_would(self, now: float, bag: int) -> None:
        # Silent once RETREAT_LIVE is on: the live half has to say what it does.
        from .decide import WORTH_PROTECTING
        if (RETREAT_LIVE or bag < WORTH_PROTECTING or not retreat_due(self._health)
                or now - self._said_retreat < RETREAT_SAY_SECONDS):
            return
        self._said_retreat = now
        (_, before), (_, health) = self._health[-2:]
        self.emit(Log(message=(
            f"retreat would: end the gather and walk home — the health bar "
            f"reads {before:.2f} then {health:.2f} with {bag:,} pollen in the "
            f"bag (RETREAT_LIVE off, nothing done)"), level=Level.WARN, source="alive"))

    def _lowest_health(self, now: float) -> float | None:
        seen = [h for at, h in self._health if now - at <= DEATH_PROOF_SECONDS]
        return min(seen) if seen else None

    def _feed_words(self) -> str:
        """The feed's words, lower-cased and spaced once, or "" (no reader,
        nothing read, or a reader that raised)."""
        if self.feed is None:
            return ""
        try:
            return " ".join(str(self.feed() or "").lower().split())
        except Exception:
            return ""

    # ---- the honey half: a Conversion Link is not a death ----------------
    def _honey_now(self, now: float) -> tuple[int, float] | None:
        """One honey reading as (value, at), or None when there is no reader
        or the counter did not read (it rolls after a conversion)."""
        if self.honey is None:
            return None
        try:
            value = getattr(self.honey(), "value", None)
        except Exception:
            return None
        return None if value is None else (int(value), now)

    def _honey_before(self, now: float) -> None:
        """Keep the last two honey readings from before any fall, at most one
        every HONEY_BASE_SECONDS."""
        if self.honey is None:
            return
        if self._honey_base and now - self._honey_base[-1][1] < HONEY_BASE_SECONDS:
            return
        seen = self._honey_now(now)
        if seen is not None:
            self._honey_base = (self._honey_base + [seen])[-2:]

    def _honey_rise(self, seen) -> int | None:
        """A look's honey, (value, at), over the baseline past its trickle
        (rise_past_trickle); None when either cannot be read."""
        if seen is None:
            return None
        return rise_past_trickle(self._honey_base, seen[0], seen[1])

    def converted(self) -> None:
        """Tell it the backpack was emptied on purpose, so that is not a death."""
        self._honey_base = []              # a convert is not the trickle
        self.best = None
        self.last_reading = self.last_read_at = None

    # ---- converting is not dying ------------------------------------------
    # A CONVERT AND A DEATH LOOK IDENTICAL FROM THE POLLEN PILL, and this
    # method existed from the start for that reason -- and was never called by
    # anything. MEASURED on 2026-09-20: the bot converted 532,850 pollen into
    # 498,423 honey, exactly as intended, and the log recorded
    #
    #     died: pollen fell 60,053 -> 1,259 (58,794 lost) with no convert in
    #     between
    #
    # twice inside two seconds. Nothing was lost; the backpack had been emptied
    # on purpose. Crying wolf here is not harmless: `watching()` returns True
    # on a death, so every false one cuts a walk short, and every one saves an
    # incident window, so the real evidence gets buried under converts.
    #
    # `converted()` alone is not enough, and that is why these exist. The dwell
    # lasts around a hundred seconds and the counter falls the whole way, so
    # clearing the peak once at the start just re-baselines on the first read
    # and reports a death on the second. The loop knows precisely when it is
    # converting, so it says so, and nothing is inferred.
    def suspend(self) -> None:
        self._suspended += 1

    def resume(self) -> None:
        """Stop suspending, and treat wherever the backpack is now as the new
        normal -- otherwise the pre-convert peak would make the first read
        after a successful convert look like a catastrophe."""
        if self._suspended:
            self._suspended -= 1
        if not self._suspended:
            self.suppressed += 1
            self.best = None
            self._pending = None
            self._honey_base = []
            self.last_reading = self.last_read_at = None

    @property
    def suspended(self) -> bool:
        return bool(self._suspended)


class SessionCap:
    """Stops the run after `safety.max_session_h`, if the owner set one.

    WHY IT IS A SETTING AND NOT A CONSTANT. The owner ran this overnight on
    purpose -- to wake up to upgraded gear and a pile of honey -- so the
    default of 0.0, meaning "until you stop it", is the right
    default for them. Somebody who wants a two-hour session should get a
    two-hour session, and before this nothing read the number at all.

    It asks the loop to stop at a step boundary; it never kills anything.
    A run cut off mid-walk could leave a key held down, which is the one
    failure this project refuses to ship.

    A SESSION IS THE WATCHDOG'S, NOT ONE ATTEMPT'S (DESIGN 8du). Measured
    from this process's own start, the cap could never fire under
    scripts/overnight.sh -- which is what the GUI's Start launches -- because
    every attempt is a new process: MEASURED over the 421 attempts in
    var/night/attempts.log, median 274 s, p75 718 s, longest-cited 1493 s
    (attempt 404). And when it did fire, run_farm exited 0 and
    the watchdog relaunched it 20 s later ("exited 0 but no cycle limit was
    set — restarting"). So the watchdog exports its start time as `ENV`,
    `from_env` counts from it on the wall clock, and an expired session ends
    run_farm with `EXIT_FINISHED`, which overnight.sh treats as "done".
    """

    # The variable scripts/overnight.sh exports once, before its first attempt.
    ENV = "HIVEMIND_SESSION_STARTED"
    # run_farm's exit status once the session limit is reached. 0, 1 and 2
    # are taken (finished or gave up, bootstrap failed, no memory) and
    # overnight.sh restarts on all of them.
    EXIT_FINISHED = 3

    def __init__(self, settings=None, hours: float | None = None,
                 clock=time.monotonic, emit=None,
                 started_at: float | None = None):
        self.clock = clock
        self.emit = emit or (lambda event: None)
        self.started_at = clock() if started_at is None else float(started_at)
        self.origin = "this run"
        self.stopped = False
        if hours is None:
            hours = 0.0
            try:
                hours = float(settings.get("safety.max_session_h", 0.0) or 0.0)
            except Exception:
                hours = 0.0
        self.hours = max(0.0, float(hours))

    @classmethod
    def from_env(cls, settings=None, emit=None, environ=None) -> "SessionCap":
        """A cap counted from the watchdog's start when there is a watchdog.

        Without the variable (a run started by hand) it counts from this
        process, as it always did. A value that is not a past epoch time is
        ignored rather than trusted.
        """
        environ = os.environ if environ is None else environ
        try:
            began = float(environ.get(cls.ENV, ""))
        except (TypeError, ValueError):
            began = None
        if began is None or not 0 < began <= time.time():
            return cls(settings, emit=emit)
        cap = cls(settings, emit=emit, clock=time.time, started_at=began)
        cap.origin = "the watchdog's start"
        return cap

    @property
    def limited(self) -> bool:
        return self.hours > 0

    def elapsed(self) -> float:
        return self.clock() - self.started_at

    def expired(self) -> bool:
        """True once, when the cap is reached. False forever if unlimited."""
        if not self.limited or self.stopped:
            return False
        if self.elapsed() < self.hours * 3600.0:
            return False
        self.stopped = True
        self.emit(Log(
            message=(f"stopping: safety.max_session_h is {self.hours:g} and "
                     f"this session has run {self.elapsed() / 3600.0:.1f} "
                     f"hours"),
            level=Level.INFO, source="session"))
        return True

    def describe(self) -> str:
        if not self.limited:
            return "no session limit set (safety.max_session_h = 0)"
        return (f"{self.elapsed() / 3600.0:.1f}h of {self.hours:g}h "
                f"session limit used, counted from {self.origin}")
