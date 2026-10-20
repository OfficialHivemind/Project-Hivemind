"""Is there enough memory to start something heavy?

MEASURED THE HARD WAY. The Linux OOM killer terminated the agent twice mid-run
while a live game test was going, with these notifications:

    "Memory Shortage Avoided — Claude has been terminated by the Linux kernel
     because the system is low on memory."

This machine has 30 GB and the peak stack is large: Sober (Roblox) and a nested
Hyprland, the desktop app, a Qt GUI, and a 6 GB vision model. Swap was at 2.9 of
4 GB when it happened, so the system was already spilling.

Nothing here frees memory by itself -- it reports, so a caller can free what it
controls (the vision model's weights, a GUI left running) and refuse to start
rather than being killed halfway. Being killed halfway is the expensive
outcome: the game is left running, keys may be held, and whatever the run was
measuring is lost.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

MEMINFO = Path("/proc/meminfo")

# MEASURED: a Sober launch plus the nested compositor settles around 3-4 GB.
# Refusing below 6 GB leaves room for that plus the capture buffers, with
# enough margin that a spike does not reach the OOM killer.
SAFE_TO_START_GB = 6.0
# THE ALT GIVES WAY FIRST (tools/alt/README.md). Its bot runs on the same
# machine as the main's, and both read the same MemAvailable, so on equal lines
# the two would step aside together -- and a rejoin costs the MAIN the owner's
# Wealth Clock streak. Every line below derives from this one, so the alt
# starts only with ALT_YIELD_GB more free, and ends its run that much sooner.
ALT_YIELD_GB = 2.0
ALT = os.environ.get("HIVEMIND_ROLE") == "alt"
if ALT:
    SAFE_TO_START_GB += ALT_YIELD_GB
# AND THE ALT'S ROBLOX NEEDS VIDEO MEMORY, which no line above sees. MEASURED
# 2026-10-13 (the alt plan) on the test PC's 16 GB GPU: the main's Roblox,
# another game and llama-server together left under 1 GB of video memory free
# (the kernel's mem_info_vram_used / mem_info_vram_total). A second Sober there
# pushes the card over. So the alt starts only with ALT_VRAM_START_GB free on
# the card with the most VRAM (the discrete one; an integrated GPU reports far
# less). A start that attaches to a kept game is already on the card, so it is
# not asked.
ALT_VRAM_START_GB = 3.0
DRM = Path("/sys/class/drm")
# Swap this full means the system is ALREADY trading pages for time. Starting
# something big here is how the last two runs died.
SWAP_PRESSURE = 0.70

PRESSURE = Path("/proc/pressure/memory")

# BUT A FULL SWAP IS NOT THE SAME AS A MACHINE SHORT OF MEMORY, and the owner
# asked for exactly the case that tells them apart: playing another game at the
# same time as the bot. MEASURED 2026-09-26, another game open at
# 6.4 GB: 11.3 GB available, swap 4.0 of 4 GB (99%) -- and the kernel's own
# stall counter, /proc/pressure/memory, at `some avg60=0.00 full avg60=0.00`.
# The swap was full of idle pages (the chat apps, the desktop app: ~100-160 MB
# each) and nothing was waiting on memory. The old rule wanted 12 GB whenever
# swap passed 70%, so the watchdog sat in "waiting for memory" for as long as
# the game was open.
#
# PSI answers the question swap fullness only hints at: the share of the last
# minute in which some task was STALLED waiting for memory. So a full swap
# still counts, but as "no spill room", not as "under pressure":
GAME_GB = 4.0                     # the measured Sober + compositor footprint
# Tasks stalled this share of the last minute: memory is ALREADY short, whatever
# the free figure says. A chosen line, not a measured one -- this machine reads
# 0.00 in ordinary use, including with a game open and swap at 99%.
STALLED_PCT = 5.0

# ONCE RUNNING, the order in which the bot gives memory back (run_farm's
# heartbeat, every 20 s). Each line is derived from the one below it, so no
# step can push the machine straight into the next:
#
#   STEP_ASIDE_GB  the bot ends its run and frees its game (~4 GB). Below this
#                  the kernel is getting close to choosing a victim, and the
#                  owner's own game must not be it.
#   MODEL_DROP_GB  the vision model is dropped first, a gigabyte above that
#                  line: the drop is asked for on a 20 s heartbeat and takes
#                  about 4 s to free the memory (run_farm keep_memory_free),
#                  so the bot steps aside only if dropping it was not enough.
#   MODEL_LOAD_GB  the model is loaded again only with room for the load and
#                  some growth ABOVE the drop line; otherwise it would load,
#                  drop, load again.
#
# WHAT THE MODEL COSTS, MEASURED 2026-09-26 19:45 with the model server's own
# RSS (/proc/<llama-server>/status) beside MemAvailable: a fresh load is small
# -- 0.25 GB of server after a text prompt (free memory 4.9 -> 4.2 GB), 0.34
# GB after its first image (4.7 -> 4.2) -- and then EVERY IMAGE ADDS ABOUT 0.1
# GB: 0.34, 0.43, 0.52, 0.60, 0.75, 0.85, 1.01, 1.08, 1.26, 1.32 GB over ten
# feed-strip-sized questions, free memory falling with it (4.2 -> 3.2), all of
# it back on unload (4.8). So the 2.1-3.4 GB the drops freed in run-452 and
# run-457 were a session's growth, not the load, and a load line built on 3.4
# GB refused a load that costs half a gigabyte -- the bot played blind all
# evening with 4-6 GB free. The drop line resets the growth; the load needs
# the fresh load plus room for about ten images of growth before it is back
# at the drop line.
#
# THE DROP LINE WAS STEP_ASIDE + MODEL_RAM (4.5 GB), and run-457 showed what
# that costs with the owner's game open: loaded, the machine sat at 4.0-4.5
# GB with nothing stalled (PSI some avg60 0.3%), so the model was dropped
# every three to four minutes and loaded back by the next feed read, twenty
# seconds each time -- while the feed is how the bot knows which field it is
# in. A gigabyte of warning is what the drop needs, not the model's own size.
#
# AND HALF A GIGABYTE IS ENOUGH WARNING. The same evening the owner's system
# monitor showed most of the RAM used and swap full, and they judged the machine
# fine (no stutter). With about 6 GB free
# while the bot plays, a drop line at 3.0 kept the model unloaded (a reload
# needed 6.4) and the bot played half blind; at 2.5 a reload needs 5.9 and
# lands above the line. The step-aside needs two readings 20 s apart below
# 2 GB, and the drop is asked on the first, so the drop still comes first.
STEP_ASIDE_GB = SAFE_TO_START_GB - GAME_GB
MODEL_LOAD_COST_GB = 0.5          # a fresh load, free memory before -> after
MODEL_GROWTH_ROOM_GB = 1.0        # ~10 images at the measured ~0.1 GB each
MODEL_DROP_GB = STEP_ASIDE_GB + 0.5
MODEL_LOAD_GB = MODEL_DROP_GB + MODEL_LOAD_COST_GB + MODEL_GROWTH_ROOM_GB
# A READ THE RUN CANNOT GO ON WITHOUT -- claiming the hive at the start: no
# hive, no bees, nothing collected -- may load the model into a machine that it
# leaves ON the step-aside line, not above the drop line. MEASURED 2026-09-26
# 18:43, attempt 460: 8.0 GB free before the join, the model refused ("no room
# to load"), "walked 14 steps one way and 28 back without the claim panel
# appearing", and the run stopped: "could not claim a hive, so there are no
# bees". The drop rule takes the model out again straight after (run_farm
# `claim`), so the dip lasts one claim.
ESSENTIAL_LOAD_GB = STEP_ASIDE_GB + MODEL_LOAD_COST_GB
# THE MODEL SERVER'S "GROWTH" IS A CACHE, AND IT IS CAPPED AT 8 GB. MEASURED
# 2026-09-27 (attempt 482): llama-server's resident memory rose 2.32 -> 4.60 GB
# in three and a half minutes, at ~6 vision calls a minute (ollama's journal),
# and in attempt 481 it reached 8.5 GB, the machine sat at 3 GB free with swap
# full, and the capture stopped for a minute ("no frame from the capture").
# Its own `--help` names it: `--cache-ram N`, "the maximum cache size in MiB
# (default: 8192)" -- each prompt's state kept in host memory for reuse -- and
# ollama starts it without the flag (the fix at the source is
# LLAMA_ARG_CACHE_RAM in ollama's service, which is the owner's to set). A
# reload costs ~1.8 s ("llama-server started in 1.76 seconds"), so the bot
# recycles the model once its process holds MODEL_RSS_CAP_GB: two thirds of a
# fresh load's ~2 GB above it, a few minutes of vision calls.
MODEL_RSS_CAP_GB = 3.5
MODEL_PROCESS = "llama-server"
# WITH NOWHERE TO SPILL, the start must leave the machine, once the game has
# its share, a gigabyte above the step-aside line. It was SAFE_TO_START_GB +
# GAME_GB (10 GB) for an hour, and one evening showed what that cost: with a browser,
# another game and a recorder open, 8.3 GB was free, and the bot sat in
# "waiting for memory". Then 8 GB (a gigabyte
# above the model's drop line), and at 18:40 the machine sat at 8.0-8.1 GB:
# the watchdog's check passed and run_farm's own, a second later, did not
# (attempt 459, "exited 2 after 1s"). Whether the vision model fits as well is
# the model's own question (MODEL_LOAD_GB); without it the bot plays half
# blind -- MEASURED, attempt 458 (no model, 18:05-18:40) 4.27M honey/h against
# attempt 457's 7.38M with it -- which is still better than a stream of a bot
# waiting for memory.
#
# AND THE GAME IS SMALLER THAN GAME_GB SAYS. MEASURED 2026-09-26: at 17:21 the
# bot's processes were Sober 1.5 GB, the nested compositor 0.17 and run_farm
# 0.36 (2.0 GB), and attempt 464 went from 7.4 GB free to 5.5 in the game; at
# 19:50 the watchdog waited on 6.8-6.9 GB for a line built on 4 GB. So with a
# full swap the start needs room for the game as measured, with some growth,
# and for the vision model to load after it (MODEL_LOAD_GB), so the bot does
# not start blind.
GAME_MEASURED_GB = 2.5
SWAP_FULL_NEEDS_GB = GAME_MEASURED_GB + MODEL_LOAD_GB
# Stalled this share of the last TEN seconds while running: the machine is
# thrashing now, and the owner feels it as stutter in their game. Chosen, as
# STALLED_PCT is; it is four times that line because a ten-second window is
# noisier than a minute.
STALLING_NOW_PCT = 20.0


@dataclass(frozen=True)
class Memory:
    available_gb: float
    total_gb: float
    swap_used_gb: float
    swap_total_gb: float
    # /proc/pressure/memory `some`: percent of the last 60 s / 10 s in which a
    # task was stalled on memory. None where the kernel has no PSI.
    stall_pct: float | None = None
    stall_now_pct: float | None = None

    @property
    def swap_fraction(self) -> float:
        return self.swap_used_gb / self.swap_total_gb if self.swap_total_gb else 0.0

    @property
    def under_pressure(self) -> bool:
        """Too tight to start something big RIGHT NOW.

        Available memory is the decisive signal; swap fullness on its own is
        not. Swap records pressure that HAS happened, not pressure that is
        happening -- after the OOM kills, this machine sat at 72% swap with
        24.5 GB free, which is ample. Blocking on that alone would refuse
        every run for the rest of the session over a number that only drains
        on reboot.

        So swap only counts when memory is also getting tight: a full swap
        means the next spike has nowhere to go. And the kernel's stall counter
        decides whether "tight" is real (see PRESSURE above): with it, a full
        swap needs SWAP_FULL_NEEDS_GB; without it, the old doubled floor.
        """
        if self.available_gb < SAFE_TO_START_GB:
            return True
        if self.stall_pct is not None and self.stall_pct >= STALLED_PCT:
            return True
        if self.swap_fraction <= SWAP_PRESSURE:
            return False
        return self.available_gb < self.swap_full_needs_gb

    @property
    def swap_full_needs_gb(self) -> float:
        return (SAFE_TO_START_GB * 2 if self.stall_pct is None
                else SWAP_FULL_NEEDS_GB)

    def step_aside_reason(self) -> str | None:
        """Why a RUNNING bot should end its run and free its game, or None.

        The start rule above asks "is there room to begin?"; this asks "is
        there still room to go on?", which is a much lower bar -- a running
        game already has its memory.
        """
        if self.total_gb == 0.0:
            return None
        if self.available_gb < STEP_ASIDE_GB:
            return (f"only {self.available_gb:.1f} GB of memory left "
                    f"(the line is {STEP_ASIDE_GB:.0f} GB)")
        if (self.stall_now_pct is not None
                and self.stall_now_pct >= STALLING_NOW_PCT):
            return (f"the machine spent {self.stall_now_pct:.0f}% of the last "
                    f"ten seconds waiting on memory")
        return None

    @property
    def worth_mentioning(self) -> bool:
        """Not blocking, but the operator should know."""
        return self.swap_fraction > SWAP_PRESSURE or self.available_gb < 10.0

    def short_for(self, kept: bool = False) -> bool:
        """`under_pressure`, for a start that ATTACHES to a kept game when
        `kept`: the game's own footprint is already in the used figure, so it
        is not asked for twice. MEASURED 2026-10-03 11:32-11:52: after a
        keep-the-game deploy the start asked 6.5 GB (a full swap) for a game
        already running, read 6.3-6.7 GB, and refused three starts in 20
        minutes while the game sat idle. The stall test and the swap rule
        stand; only the game's share comes off."""
        if not kept:
            return self.under_pressure
        if self.available_gb < SAFE_TO_START_GB - GAME_GB:
            return True
        if self.stall_pct is not None and self.stall_pct >= STALLED_PCT:
            return True
        if self.swap_fraction <= SWAP_PRESSURE:
            return False
        game = GAME_MEASURED_GB if self.stall_pct is not None else GAME_GB
        return self.available_gb < self.swap_full_needs_gb - game

    def describe(self, kept: bool = False) -> str:
        text = (f"{self.available_gb:.1f} GB available of {self.total_gb:.0f}, "
                f"swap {self.swap_used_gb:.1f}/{self.swap_total_gb:.0f} GB "
                f"({self.swap_fraction:.0%})")
        if self.stall_pct is not None:
            text += f", stalled {self.stall_pct:.1f}% of the last minute"
        if kept:
            text += ", the kept game already in it"
        if self.short_for(kept):
            return text + "  — UNDER PRESSURE"
        if self.worth_mentioning:
            return text + "  — tight but workable"
        return text

    def advice(self) -> str:
        """What to free, in the order that frees the most for the least loss."""
        if not self.under_pressure:
            return ""
        steps = []
        if self.available_gb < SAFE_TO_START_GB:
            steps.append("turn off the vision model (it uses about 6 GB)")
            steps.append("close the Hivemind GUI if it is only showing a demo")
        if self.stall_pct is not None and self.stall_pct >= STALLED_PCT:
            steps.append("programs are already waiting on memory; close "
                         "something large")
        elif self.swap_fraction > SWAP_PRESSURE:
            steps.append(f"swap is full, so it waits for "
                         f"{self.swap_full_needs_gb:.0f} GB free; closing another "
                         f"program frees it, and so does a reboot")
        return "; ".join(steps)


def read() -> Memory:
    """Current memory, from /proc/meminfo. Zeros if it cannot be read."""
    values: dict[str, float] = {}
    try:
        for line in MEMINFO.read_text().splitlines():
            key, _, rest = line.partition(":")
            parts = rest.split()
            if parts:
                try:
                    values[key] = float(parts[0]) / 1024 / 1024   # kB -> GB
                except ValueError:
                    continue
    except OSError:
        return Memory(0.0, 0.0, 0.0, 0.0)
    swap_total = values.get("SwapTotal", 0.0)
    stall, stall_now = read_stall()
    return Memory(
        available_gb=values.get("MemAvailable", 0.0),
        total_gb=values.get("MemTotal", 0.0),
        swap_used_gb=max(0.0, swap_total - values.get("SwapFree", 0.0)),
        swap_total_gb=swap_total,
        stall_pct=stall,
        stall_now_pct=stall_now,
    )


def model_rss_gb(proc: Path = Path("/proc")) -> float | None:
    """Resident memory of the local model server (MODEL_PROCESS), in GB; the
    largest when several run, None when none does. Read from each process's
    `status`, which any user may read, so this asks nothing of ollama."""
    largest = None
    for status in proc.glob("[0-9]*/status"):
        try:
            text = status.read_text()
        except OSError:
            continue                   # gone between the listing and the read
        if not text.startswith(f"Name:\t{MODEL_PROCESS}\n"):
            continue
        for line in text.splitlines():
            if line.startswith("VmRSS:"):
                try:
                    gb = float(line.split()[1]) / 1024 / 1024   # kB -> GB
                except (IndexError, ValueError):
                    break
                largest = gb if largest is None else max(largest, gb)
                break
    return largest


def read_stall(path: Path = PRESSURE) -> tuple[float | None, float | None]:
    """(`some avg60`, `some avg10`) from the kernel's memory PSI file, or
    (None, None) where it is missing or unreadable. The line reads
    `some avg10=0.00 avg60=0.00 avg300=0.00 total=107921307`."""
    try:
        for line in path.read_text().splitlines():
            if line.startswith("some "):
                fields = dict(part.split("=", 1) for part in line.split()[1:])
                return float(fields["avg60"]), float(fields["avg10"])
    except (OSError, ValueError, KeyError):
        pass
    return None, None


def vram_free_gb(drm: Path | None = None) -> float | None:
    """Free video memory, in GB, of the card with the most VRAM (amdgpu's
    mem_info_vram_total/_used); None when no card reports it."""
    best = None
    for card in (DRM if drm is None else drm).glob("card*"):
        try:
            total = int((card / "device/mem_info_vram_total").read_text())
            used = int((card / "device/mem_info_vram_used").read_text())
        except (OSError, ValueError):
            continue                     # a connector (card1-DP-1), or no amdgpu
        if best is None or total > best[0]:
            best = (total, used)
    return None if best is None else (best[0] - best[1]) / 1024 ** 3


def check(what: str = "this", kept: bool = False) -> tuple[bool, str]:
    """(safe_to_start, message). The message is for a human, always. `kept`:
    the start attaches to a game already running (`Memory.short_for`)."""
    memory = read()
    if memory.total_gb == 0.0:
        return True, "could not read /proc/meminfo — proceeding"
    if memory.short_for(kept):
        needs = (f"it needs {SAFE_TO_START_GB:.0f} GB free, you have "
                 f"{memory.available_gb:.1f} GB; " if memory.available_gb < SAFE_TO_START_GB
                 else "")
        return False, (f"not enough memory to start {what}: {needs}"
                       f"{memory.describe(kept)}. Free some first: "
                       f"{memory.advice()}")
    if ALT and not kept:
        free = vram_free_gb()
        if free is None:
            return True, memory.describe(kept) + "; video memory not readable — proceeding"
        if free < ALT_VRAM_START_GB:
            return False, (f"not enough video memory to start {what} on the alt: "
                           f"{free:.1f} GB free on the GPU, it starts at "
                           f"{ALT_VRAM_START_GB:g} GB (the main's game and the owner's "
                           f"come first)")
        return True, memory.describe(kept) + f"; {free:.1f} GB video memory free"
    return True, memory.describe(kept)


# ---------------------------------------------------------------------------
# Watching OUR OWN process
# ---------------------------------------------------------------------------
# Everything above answers "is there room to start?". This answers "are WE the
# problem?", which is a different question and turned out to be the important
# one.
#
# MEASURED, 2026-09-20. The kernel OOM-killed three processes and named the
# same shape of victim each time -- one python holding most of the machine:
#
#     Killed process 210523 (python) anon-rss:25210976kB      (08:22)
#     Killed process 227158 (python) anon-rss:16140436kB      (09:48)
#     Killed process 230442 (python) anon-rss:23481892kB      (12:24)
#
# The machine has 30 GB and was using about 9 for everything else, so this was
# never a small machine struggling -- it was one of ours eating it. Reading the
# code did not find the cause: `scripts/diag_leak.py` drove FlowTracker,
# templates.find, blobs.find and frame allocation for 300 iterations each and
# every one was flat (+3 to +22 MB); the screencopy pool is reused and its
# buffers destroyed in a `finally`; the think panel trims at 400 rows; the
# telemetry sink prints rather than collects.
#
# So the cause is still UNKNOWN, and this exists because of that rather than in
# spite of it. An unexplained leak that kills the desktop is a different
# problem from an unexplained leak that stops its own run and writes down what
# it was doing at the time -- and the second one is a bug report.
PROCESS_STATUS = Path("/proc/self/status")

# Nothing we run legitimately needs this much. A capture loop holding one
# frame, a HUD reader and a route runner live in low hundreds of MB; the
# vision model is a separate process (ollama) and does not count against ours.
SELF_CEILING_GB = 8.0


def rss_gb() -> float:
    """This process's resident memory. 0.0 if /proc cannot be read."""
    try:
        for line in PROCESS_STATUS.read_text().splitlines():
            if line.startswith("VmRSS:"):
                return float(line.split()[1]) / 1024 / 1024   # kB -> GB
    except (OSError, ValueError, IndexError):
        pass
    return 0.0


class SelfWatch:
    """Stop our own run before the kernel stops the whole desktop.

    `check()` is called at a natural boundary -- the top of a farm cycle, the
    end of a probe -- and returns a reason string when the run should end, or
    None to carry on. It never raises and never kills anything: the caller
    owns the shutdown, because only the caller knows how to release the keys.

    The history is a `deque(maxlen=...)`, which is not a detail. A leak
    detector that accumulates a sample per cycle for ten hours is another
    leak, and writing this one unbounded would have been funny exactly once.
    """

    def __init__(self, ceiling_gb: float = SELF_CEILING_GB, keep: int = 240):
        from collections import deque
        self.ceiling_gb = float(ceiling_gb)
        self.samples: deque = deque(maxlen=keep)
        self.start_gb = rss_gb()

    def sample(self, note: str = "") -> float:
        now = rss_gb()
        self.samples.append((note, now))
        return now

    @property
    def grown_gb(self) -> float:
        return max(0.0, rss_gb() - self.start_gb)

    def check(self, note: str = "") -> str | None:
        """None to continue; a human-readable reason to stop."""
        now = self.sample(note)
        if now < self.ceiling_gb:
            return None
        return (f"this process has grown to {now:.1f} GB "
                f"(started at {self.start_gb:.1f} GB, ceiling "
                f"{self.ceiling_gb:.1f} GB) — stopping before the kernel "
                f"stops the desktop instead. Last checkpoints: "
                f"{self.describe_recent()}")

    def describe_recent(self, count: int = 5) -> str:
        recent = list(self.samples)[-count:]
        return ", ".join(f"{note or '?'} {gb:.1f}GB" for note, gb in recent)
