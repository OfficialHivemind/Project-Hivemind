"""What the bot actually did, kept across restarts.

WHY THIS IS A FILE AND NOT AN EVENT. The GUI learns everything else from a
live socket, which is right for "what is happening now" and useless for "what
did you do while I was asleep": the stream starts empty every time the run
restarts, and the night of 2026-09-21 restarted 134 times. The owner asked for
stats in the app showing what the bot did, and that is a question about
the whole night, so the answer has to outlive the process that measured it.

WHY APPEND-ONLY JSONL. One line per completed trip, written and flushed as the
trip ends. There is a single writer, so an append needs no lock; a reader can
read a file that is being written to without coordinating; and a run killed
mid-write costs the last line rather than the file. That last point is not
hypothetical -- the OOM killer has ended runs here twice.

WHAT IT REFUSES TO DO. It never turns "not measured" into a zero. A trip whose
pollen counter was never legible records `null`, is counted in
`Totals.unmeasured`, and is left out of the sums. A ledger that quietly read
None as 0 would show a tidy total that understated the night, and the owner's
standing rule is that nothing here is added for looks: it must work and be
useful.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

# Bumped only when a reader would MISREAD an old line, never for a new field --
# see `trips`, which defaults missing keys and keeps unknown ones.
FORMAT = 1


@dataclass
class Totals:
    """Sums over a set of trips. Only over what was measured."""
    trips: int = 0
    honey: int = 0
    pollen: int = 0
    seconds: float = 0.0
    gather_seconds: float = 0.0
    passes: int = 0
    deaths: int = 0
    # trips whose honey delta was never legible, so they are absent from
    # `honey` rather than counted as zero
    unmeasured: int = 0
    # HOW THE TRIPS GOT HOME. A trip that gathered and then converted walked
    # home and stood on its own pad; one that gathered and did not convert
    # never got there, and what follows it is the rejoin (which keeps the
    # backpack; the next cycle banks it as a carry-in). The owner asked to
    # see what the bot did, and the walk home is the part that failed 52
    # times in a row before it first landed (DESIGN 8ab), so it is counted.
    walked_home: int = 0
    not_home: int = 0
    # HONEY BANKED BY A CYCLE THAT GATHERED NOTHING. It is real honey and it
    # belongs in `honey`, but the pollen behind it was gathered on an EARLIER
    # trip -- typically one whose walk home failed, after which the rejoin
    # preserved the backpack and the next cycle converted it on arrival. It is
    # kept out of the rate because it was not earned in this cycle's seconds.
    # MEASURED 2026-09-22 04:51: a 59-second cycle with 0 passes banked
    # 1,019,114 honey, and the rate read 12,606,955/hr.
    #
    # KNOWN LIMIT, AND IT IS NOT A ROUNDING ONE. The test is "this cycle
    # gathered nothing", which misses a cycle that banks a previous trip's
    # backpack AND does a little gathering of its own. MEASURED 2026-09-22
    # 06:17: 50,365 pollen over 6 passes, +1,034,438 honey -- that honey came
    # almost entirely from the 418,434 pollen of the trip before it, but the
    # 6 passes make it look like income earned in 83 seconds, and the panel's
    # rate read 889K/hr because of it.
    #
    # The exact fix is to record what the convert actually consumed rather
    # than infer it: `FarmLoop._convert` already reads the backpack before
    # pressing the key, so a `pollen_converted` field on the Cycle would
    # settle it outright. Not done on the morning of 2026-09-22 -- it needs a
    # farm change and a restart for what is a reporting nuance, and guessing
    # a honey-per-pollen constant to detect it instead would be exactly the
    # kind of invented number this file refuses.
    carried_in: int = 0
    # seconds belonging to cycles that actually gathered -- the rate's divisor
    earning_seconds: float = 0.0
    # field name -> honey the GAME credited there, best first once sorted.
    # Only ever a field the reward feed named. See `totals`.
    by_field: dict[str, int] = field(default_factory=dict)
    # honey from trips the feed never named a field for. It was earned
    # somewhere; nothing says where, so it is not put against a field.
    unattributed: int = 0

    @property
    def earned_here(self) -> int:
        """Honey whose pollen was gathered by the trips being counted."""
        return self.honey - self.carried_in

    @property
    def honey_per_hour(self) -> float | None:
        """Honey earned by these trips over the time those trips took.

        None rather than 0 when nothing has been measured: an unknown rate and
        a rate of zero look identical on a dashboard and mean opposite things.

        Carry-in banks are excluded from BOTH sides. A cycle that gathered
        nothing and banked a previous trip's backpack is real honey in the
        wrong seconds, and leaving it in read 12,606,955/hr off two trips.
        """
        if self.earning_seconds <= 0 or self.trips == self.unmeasured:
            return None
        return self.earned_here * 3600.0 / self.earning_seconds

    def describe(self) -> str:
        if not self.trips:
            return "no trips recorded yet"
        parts = [f"{self.trips} trips", f"{self.honey:,} honey"]
        if self.carried_in:
            parts.append(f"of which {self.carried_in:,} was an earlier trip's "
                         f"backpack, banked on arrival")
        if self.pollen:
            parts.append(f"{self.pollen:,} pollen")
        rate = self.honey_per_hour
        if rate is not None:
            parts.append(f"{rate:,.0f} honey/hr")
        if self.deaths:
            parts.append(f"{self.deaths} deaths")
        if self.unmeasured:
            parts.append(f"{self.unmeasured} not measured")
        return ", ".join(parts)


# How many of a field's latest trips `pollen_by_field` also totals alone.
RECENT_TRIPS = 10
# ...AND HOW MANY GATHERING SECONDS THEY MUST COVER, reaching further back by
# whole trips until they do (decide.RECENT_SECONDS_ENOUGH is this number).
#
# A COUNT ALONE PUNISHED THE FASTEST FIELD. A field that fills the bag quickly
# has short trips, so its last ten fell under decide's 1,800 s bar and the
# planner went back to the lifetime field-notes pair. MEASURED 2026-10-20 on
# var/trips.jsonl: Mountain Top's last 10 trips paid 29,317 pollen/s over
# 1,645 s (about 165 s a trip, the bag full), so it was ranked on the paid
# pair's 3,158/s -- days of a weaker hive -- scored 1,764 against Pine Tree's
# 20,946, and was not chosen once from 10-14 09:47 to 10-20 (142 h). Never
# chosen, never re-measured. Eleven trips cover the bar: 32,220/s over 1,982 s.
RECENT_SECONDS = 1800.0


class Ledger:
    """Append-only record of completed trips."""

    def __init__(self, path: str | Path, clock=time.time):
        self.path = Path(path)
        self.clock = clock

    # ---- writing ---------------------------------------------------------
    def record(self, cycle, *, aimed_at: str | None = None,
               credited: str | None = None,
               attempt: int | None = None,
               extra: dict | None = None) -> dict:
        """Append one trip, taking every number from the Cycle as measured.

        `aimed_at` and `credited` are kept SEPARATELY and on purpose. On
        2026-09-22 a trip aimed at Sunflower was credited Dandelion by the
        game's own reward feed and earned 378,000 honey an hour doing it; a
        ledger that recorded only the intention would have said Sunflower, and
        the one that recorded only the credit would have lost the fact that the
        routes are still landing a field over. Both are true and they are
        different facts.

        `extra` ADDS KEYS AND NEVER REPLACES ONE (FORMAT stays 1, see
        `trips`): the decision behind the trip, the routes it ran and what each
        did (DESIGN 8dy). A key the row already has keeps the Cycle's value.
        """
        row = {
            "format": FORMAT,
            "at": float(self.clock()),
            "attempt": attempt,
            "cycle": int(getattr(cycle, "number", 0) or 0),
            "aimed_at": aimed_at,
            "credited": credited,
            "seconds": float(getattr(cycle, "seconds", 0.0) or 0.0),
            "gather_seconds": float(getattr(cycle, "gather_seconds", 0.0) or 0.0),
            "passes": int(getattr(cycle, "pattern_passes", 0) or 0),
            "pollen": getattr(cycle, "pollen_gathered", None),
            # the part of `pollen` refilled after a fall in the field
            # (brain/farm POLLEN_BOOKING): `pollen - refilled` is the old booking
            "refilled": int(getattr(cycle, "pollen_refilled", 0) or 0),
            "honey": getattr(cycle, "honey_earned", None),
            "deaths": int(getattr(cycle, "deaths", 0) or 0),
            "tokens": int(getattr(cycle, "tokens_chased", 0) or 0),
            "unreadable_pollen": int(getattr(cycle, "unreadable_pollen", 0) or 0),
            "converted": bool(getattr(cycle, "converted", False)),
            "gather_ended": str(getattr(cycle, "gather_ended", "") or ""),
            "recoveries": list(getattr(cycle, "recoveries", ()) or ()),
            "ok": bool(getattr(cycle, "ok", True)),
            "reason": str(getattr(cycle, "reason", "") or ""),
            "convert_note": str(getattr(cycle, "convert_note", "") or ""),
            "pattern": str(getattr(cycle, "pattern", "") or ""),
        }
        for key, value in (extra or {}).items():
            row.setdefault(key, value)
        self.append(row)
        return row

    def append(self, row: dict) -> None:
        """One line, flushed. Never raises into the farm loop.

        A trip that earned honey and failed to write it down is still a trip
        that earned honey, so a broken disk must not end the night.
        """
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, separators=(",", ":")) + "\n")
                fh.flush()
        except OSError:
            pass

    # ---- reading ---------------------------------------------------------
    def trips(self, since: float | None = None) -> list[dict]:
        """Every recorded trip, oldest first.

        A line that will not parse is SKIPPED rather than fatal. The last line
        of a file whose writer was killed mid-append is routinely half a line,
        and losing one trip is not a reason to show the owner nothing.
        """
        if not self.path.exists():
            return []
        out: list[dict] = []
        try:
            text = self.path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if not isinstance(row, dict):
                continue
            if since is not None and float(row.get("at") or 0.0) < since:
                continue
            out.append(row)
        return out

    def totals(self, rows: Iterable[dict] | None = None,
               since: float | None = None) -> Totals:
        rows = list(self.trips(since=since) if rows is None else rows)
        t = Totals(trips=len(rows))
        for row in rows:
            honey = row.get("honey")
            pollen = row.get("pollen")
            gathered_here = (int(row.get("passes") or 0) > 0
                             or float(row.get("gather_seconds") or 0.0) > 0)
            if honey is None:
                t.unmeasured += 1
            else:
                t.honey += int(honey)
                if not gathered_here:
                    t.carried_in += int(honey)
                # ONLY THE FIELD THE GAME NAMED, and never the aim. This
                # read `credited or aimed_at`, and on 2026-09-22 the report
                # therefore announced "honey by the field the game actually
                # paid it in: sunflower 1,498" for five trips whose `paid in`
                # column was an em dash -- trips that had reached nowhere at
                # all. Falling back to the aim turns "we do not know" into a
                # claim that a field pays, which is the one thing the reward
                # feed exists to avoid guessing (DESIGN 8b).
                #
                # A carry-in bank is excluded as well: its pollen came from an
                # earlier trip, so whatever field this cycle was pointed at is
                # not where the honey was gathered.
                where = row.get("credited")
                if where and gathered_here:
                    t.by_field[where] = t.by_field.get(where, 0) + int(honey)
                elif gathered_here:
                    t.unattributed += int(honey)
            if pollen is not None:
                t.pollen += int(pollen)
            t.seconds += float(row.get("seconds") or 0.0)
            # ONLY A TRIP WHOSE HONEY WAS MEASURED adds its seconds to the
            # rate's: since a convert may leave at the empty bag
            # (gather.leave_at_empty_bag) three trips in four bank honey
            # nobody read, and their seconds over the measured trips' honey
            # read a quarter of the truth.
            if gathered_here and honey is not None:
                t.earning_seconds += float(row.get("seconds") or 0.0)
            t.gather_seconds += float(row.get("gather_seconds") or 0.0)
            t.passes += int(row.get("passes") or 0)
            t.deaths += int(row.get("deaths") or 0)
            if gathered_here:
                if bool(row.get("converted")):
                    t.walked_home += 1
                else:
                    t.not_home += 1
        return t

    def pollen_by_field(self, rows: Iterable[dict] | None = None,
                        since: float | None = None) -> dict:
        """Pollen gathered per field the game NAMED, with the seconds it took.

        WHY THIS AND NOT `by_field`. Honey is banked on the cycle AFTER the one
        that gathered it -- the walk home fails, the rejoin lands at the hive
        and the next cycle's claim converts the bag -- so honey-by-field
        attributes the money to whatever the banking cycle happened to aim at,
        or to nothing. Pollen has no such lag: the reward feed names the field
        while the pollen is being picked up. This is the honest answer to
        "where did the work happen".
        """
        out: dict = {}
        latest: dict = {}
        for row in (self.trips(since=since) if rows is None else rows):
            field, pollen = row.get("credited"), row.get("pollen")
            seconds = float(row.get("gather_seconds") or 0.0)
            if not field or pollen is None or seconds <= 0:
                continue
            got = out.setdefault(field, {"pollen": 0, "seconds": 0.0, "trips": 0})
            got["pollen"] += int(pollen)
            got["seconds"] += seconds
            got["trips"] += 1
            latest.setdefault(field, []).append((int(pollen), seconds))
        for field, got in out.items():
            got["per_second"] = round(got["pollen"] / got["seconds"], 1) if got["seconds"] else None
            # THE SAME, OVER THE LATEST TRIPS ALONE (brain/decide's "recent"
            # source): the hive grows, and a rate averaged over days of a
            # weaker one understates what a trip pays now. At least
            # RECENT_TRIPS of them, and more until RECENT_SECONDS are covered.
            trips = latest[field]
            last = trips[-RECENT_TRIPS:]
            back = len(trips) - len(last)
            while back > 0 and sum(t for _, t in last) < RECENT_SECONDS:
                back -= 1
                last.insert(0, trips[back])
            got["recent_trips"] = len(last)
            got["recent_pollen"] = sum(p for p, _ in last)
            got["recent_seconds"] = sum(t for _, t in last)
        return out

    def by_pattern(self, rows: Iterable[dict] | None = None,
                   since: float | None = None) -> dict:
        """Pollen per gathering second, per gather pattern: the comparison that
        decides whether Natro's per-field patterns beat `farm_snake`.

        Only trips that gathered and whose pollen was legible count, and the
        rate is over GATHERING seconds, not the whole trip -- the walk out and
        the walk home are the same for both patterns.
        """
        out: dict = {}
        for row in (self.trips(since=since) if rows is None else rows):
            name = str(row.get("pattern") or "")
            pollen, seconds = row.get("pollen"), float(row.get("gather_seconds") or 0.0)
            if not name or pollen is None or seconds <= 0:
                continue
            got = out.setdefault(name, {"trips": 0, "pollen": 0, "seconds": 0.0})
            got["trips"] += 1
            got["pollen"] += int(pollen)
            got["seconds"] += seconds
        for got in out.values():
            got["per_second"] = round(got["pollen"] / got["seconds"], 1) if got["seconds"] else None
        return out

    def best_fields(self, rows: Iterable[dict] | None = None,
                    since: float | None = None) -> list[tuple[str, int]]:
        table = self.totals(rows=rows, since=since).by_field
        return sorted(table.items(), key=lambda kv: -kv[1])


# A GAP LONGER THAN THIS ENDS A SESSION. Same rule and same number as
# scripts/night_report.py's NIGHT_GAP, and for the same reason: on 2026-09-21
# the morning report added last night's honey to tonight's and claimed
# 2,051,028 when the night had actually earned 124,538. The bot restarts
# constantly, so "one process" is not a session; a long quiet gap is.
SESSION_GAP = 3 * 3600


def sessions(rows: Iterable[dict], gap: float = SESSION_GAP) -> list[list[dict]]:
    """Split trips into sittings, oldest first, on a long quiet gap."""
    out: list[list[dict]] = []
    last: float | None = None
    for row in rows:
        at = float(row.get("at") or 0.0)
        if last is None or at - last > gap:
            out.append([])
        out[-1].append(row)
        last = at
    return out


def latest_session(rows: Iterable[dict], gap: float = SESSION_GAP) -> list[dict]:
    """Just this sitting's trips. Empty when there are none."""
    split = sessions(rows, gap=gap)
    return split[-1] if split else []
