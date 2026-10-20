"""Keeping the seconds BEFORE something went wrong.

THE PROBLEM WITH DEBUGGING THIS BOT. Every failure so far was diagnosed by a
human watching live and reporting it afterwards -- the ticket shop, the ledge,
the Polar Bear dialogue, the Mantis. By the time the bot notices something is
wrong, the evidence is gone: it notices a stall 100 seconds after the pollen
stopped rising, and it notices a death only as a backpack that is suddenly
empty. A screenshot taken THEN shows a character standing somewhere harmless.

What matters is the frames just before. The Mantis is in those. So is whatever
the character walked into, and whatever dialogue opened.

This keeps a short rolling window of recent frames in memory and writes it out
when something goes wrong. It is the black box, not the camera.

IT IS BOUNDED, AND THAT IS NOT A DETAIL. The kernel OOM-killed three processes
on this machine today, each a single Python holding 16-25 GB, and the cause was
never found. A debugging aid that accumulates frames for an eight-hour
overnight run would be a fourth. So the window is a `deque(maxlen=...)` of
JPEG-ENCODED bytes, not arrays: at the default 40 frames of 1920x1080 JPEG that
is roughly 8 MB, and it cannot grow whatever happens.

Encoding on the way IN rather than on the way out is deliberate too. A raw
1920x1080 BGRA frame is 8 MB on its own, so forty of them would be 330 MB of
live arrays; encoded, the same history costs about as much as one raw frame.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from pathlib import Path

# MEASURED, and the original number was stale by 2.5x: this is fed from
# LiveView, which now runs at 20 fps (telemetry/liveview.py), so 40 frames was
# 2.0 seconds and not the 5 the old comment claimed. A mantis wind-up, lunge
# and death does not reliably fit in two seconds, which means the single most
# valuable dataset this project can collect was being truncated at the moment
# it mattered.
#
# 150 frames is 7.5 s at 20 fps and roughly 30 MB of JPEG -- still a hard
# bound, which is the property that matters. The view never made its 20: over
# the newest 400 saves the 150 frames spanned a median 10.8 s (13.8 a
# second), and its frame hook now feeds this at that 13.8 whatever the
# picture's rate (telemetry/liveview.TAP_FPS, DESIGN 8eb).
DEFAULT_WINDOW = 150
DEFAULT_QUALITY = 75
MAX_SAVED_INCIDENTS = 200    # a full disk is its own outage

# FOLDERS ARE NAMED BY DATE AND TIME. They were `%H%M%S` only, with
# `mkdir(exist_ok=True)`, so a save at the same second on a later day would
# write its frames and reason.txt over the older folder. The bot runs every
# night, so every second of the day comes round again. MEASURED 2026-09-24
# 01:30: var/incidents holds 2,028 folders (1,876 mob-sighting, 28.6 MB each
# on average) in 56 GB, against 1,878 MOB lines in run-011..345. The death
# saves 222322 and 222324 on 09-20 show that two saves of one reason can land
# seconds apart. A name that is still taken gets "-2", "-3", ... Old folders
# keep their names; nothing in src/ or scripts/ parses them (only globs such
# as "*-token").
STAMP_FORMAT = "%Y%m%d-%H%M%S"

# THE MOMENT IN FULL, THE LEAD-UP THINNED, for the kinds saved often. MEASURED
# 2026-10-14 22:10: var/incidents was 146 GB in 5,167 folders, 4,479 of them
# mob-sighting at ~30 MB (150 full-HD frames, ~265 KB each at quality 75) --
# about 5 GB a day. The studies read the end of a window (threat: frame 149;
# chase: 105-117 and 130-149; nameplate: the last and the middle) at full
# resolution, since their numbers are pixels, so neither the size nor the
# quality changes. A save with `lead_every=n` keeps every frame of the last
# MOMENT_SECONDS and every n-th before it; files keep their window index
# (149 is still the moment), so a gap in the numbers is a thinned frame.
MOMENT_SECONDS = 3.5


class IncidentRecorder:
    """A rolling window of recent frames, written out on demand.

    `push(frame)` is called from whatever is already capturing -- there is no
    second capture loop and no extra load on the compositor.
    """

    def __init__(self, directory: str | Path, window: int = DEFAULT_WINDOW,
                 quality: int = DEFAULT_QUALITY, clock=time.monotonic):
        self.directory = Path(directory)
        self.window: deque = deque(maxlen=max(1, int(window)))
        self.quality = int(quality)
        self.clock = clock
        self.saved = 0
        self.dropped = 0
        # Saves refused by `every` (see `save`), and when each reason was
        # last written.
        self.held_back = 0
        self._last_saved: dict[str, float] = {}
        self._lock = threading.Lock()

    def push(self, frame) -> bool:
        """Encode and remember one frame. Never raises."""
        try:
            import cv2
            if frame is None or getattr(frame, "size", 0) == 0:
                # Counted, not just refused. A capture that keeps handing back
                # nothing is exactly the kind of quiet failure worth seeing in
                # the summary -- silently returning False makes a broken
                # camera look the same as an idle one.
                self.dropped += 1
                return False
            # THE FRAME AS CAPTURED, alpha and all: the JPEG encoder drops it
            # itself. MEASURED on 45 saved 1920x1080 frames (DESIGN 8eb): the
            # same bytes as encoding frame[:, :, :3], in 2.7 ms instead of
            # 10.6 -- the slice is not contiguous and cost 8 ms to copy.
            ok, buf = cv2.imencode(".jpg", frame,
                                   [cv2.IMWRITE_JPEG_QUALITY, self.quality])
            if not ok:
                self.dropped += 1
                return False
            with self._lock:
                self.window.append((self.clock(), buf.tobytes()))
            return True
        except Exception:
            self.dropped += 1
            return False

    def save(self, reason: str, note: str = "",
             every: float | None = None, lead_every: int = 1) -> Path | None:
        """Write the window out. Returns the directory, or None.

        The frames are numbered so that the LAST one is the moment the
        incident was noticed and frame 000 is the oldest -- reading them in
        order shows what led up to it.

        `every`: when given, a save of the same `reason` less than that many
        seconds after the last one written is refused and counted in
        `held_back`.

        `lead_every`: see MOMENT_SECONDS. Nothing is written while the disk
        is short of room (telemetry/storage.frames_allowed).
        """
        if self.saved >= MAX_SAVED_INCIDENTS:
            return None
        from . import storage
        if not storage.frames_allowed(self.directory):
            return None
        if every is not None:
            last = self._last_saved.get(reason)
            if last is not None and self.clock() - last < float(every):
                self.held_back += 1
                return None
        with self._lock:
            frames = list(self.window)
        if not frames:
            return None
        slug = "".join(c if c.isalnum() or c in "-_" else "-"
                       for c in reason.lower())[:48].strip("-")
        base = f"{time.strftime(STAMP_FORMAT)}-{slug or 'incident'}"
        try:
            out = self.directory / base
            taken = 1
            while out.exists():
                taken += 1
                out = self.directory / f"{base}-{taken}"
            out.mkdir(parents=True, exist_ok=True)
            first, last = frames[0][0], frames[-1][0]
            kept = 0
            for i, (when, data) in enumerate(frames):
                if (lead_every > 1 and i % lead_every
                        and last - when > MOMENT_SECONDS):
                    continue
                (out / f"{i:03d}_t{when - first:+05.1f}s.jpg").write_bytes(data)
                kept += 1
            thinned = (f" Thinned: every frame of the last {MOMENT_SECONDS:g}s, "
                       f"every {lead_every}th before; {kept} of {len(frames)} "
                       f"kept, numbered by their place in the window."
                       if kept < len(frames) else "")
            (out / "reason.txt").write_text(
                f"{reason}\n\n{note}\n\n"
                f"{len(frames)} frames spanning "
                f"{last - first:.1f}s, oldest first. The LAST frame "
                f"is the moment this was noticed.{thinned}\n")
            self.saved += 1
            self._last_saved[reason] = self.clock()
            return out
        except OSError:
            return None

    def keep_newest(self, folder: str, label: str, note: str = "") -> Path | None:
        """Write the NEWEST frame in the window as `<folder>/<label>.jpg`
        (and `note`, once, as reason.txt). Never raises; None when nothing
        was written.

        For a state that lasts a minute -- the HUD gone (ROADMAP A25,
        run-1023 22:57: a minute without the HUD after a Glitter use, and no
        frame kept) -- where `save`'s ten-second window would show only the
        moment it began. The caller picks `folder` once and calls this at each
        mark, so one folder holds the whole minute.
        """
        from . import storage
        try:
            if not storage.frames_allowed(self.directory):
                return None
            with self._lock:
                newest = self.window[-1][1] if self.window else None
            if newest is None:
                return None
            out = self.directory / folder
            out.mkdir(parents=True, exist_ok=True)
            if note and not (out / "reason.txt").exists():
                (out / "reason.txt").write_text(note + "\n")
            path = out / f"{label}.jpg"
            path.write_bytes(newest)
            return path
        except OSError:
            return None

    def describe(self) -> str:
        return (f"{self.saved} incidents saved, {len(self.window)} frames in "
                f"the window"
                + (f", {self.held_back} held back by a once-per-interval "
                   f"limit" if self.held_back else "")
                + (f", {self.dropped} frames dropped" if self.dropped else ""))
