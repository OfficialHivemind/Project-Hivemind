"""The progression proof: every step the account takes, with how it is known
and the frame that shows it (docs/pending/progression-proof.md).

THE OWNER, 2026-10-26: it must progress an account from start to finish,
with evidence that it does. The bot already says what it did, in its own words,
in the run log
(the result lines below). This keeps the ones that are progression as one
row each of var/progression/milestones.jsonl, with the frame that proves it:

  {"at", "kind", "what", "how", "line", "frame", "frame_age_s", "proof"}

`proof` is "proven" when the bot's own result line has a frame on disk taken
within FRESH_S of it, "likely" otherwise (no frame, an old frame, or a result
that is only an inference: a quest giver's dialogue read is a hand-in by
every sign the bot has, but the game never says "handed in").

TWO SOURCES, ONE ROW SHAPE:
  * LINES, `match`: the bot's own result lines, said through run_farm's
    `narrate` (`Recorder.see`), or read back from old run logs
    (tools/progression_report.py --backfill, the same patterns);
  * FILES, `Recorder.check`: what the readers wrote -- the bee menu's count
    and gifted stars (var/bees.json), the HUD's honey (var/balance.json) --
    held against the last seen in var/progression/state.json, so a new bee,
    a new gifted type, a honey threshold or a field gate opened by the bee
    count is one row. The first look only writes a "baseline" row: the
    account as found, which is the zero a start-to-finish test is measured
    from.

Never raises into the caller: a row that cannot be written is said once and
dropped -- losing proof is bad, stopping the bot over it is worse.
"""
from __future__ import annotations

import json
import re
import shutil
import time
from datetime import date, datetime, timedelta
from pathlib import Path

DIR = "progression"
FILE = "milestones.jsonl"
STATE = "state.json"
FRAMES = "frames"
# A COPIED LIVE FRAME OLDER THAN THIS IS NOT THE MOMENT. The live view writes
# several frames a second while the bot runs (telemetry/liveview, 20 fps
# asked); a file older than this means the view had stopped.
# ponytail: 30 s is a judgement, not measured -- tighten once rows show ages.
FRESH_S = 30.0
CHECK_S = 60.0                      # the files are looked at this often, at most
SAY = "progress proof"              # the feed's and Telegram's line prefix

# THE BOT'S OWN RESULT LINES, (kind, pattern, how it knows). Each pattern is
# the line's text as narrate prints it (after the time), measured in the run
# logs (var/night/run-*.log, 2026-09-20 .. 2026-10-26):
PATTERNS = (
    # act/shoplook.buy: the window changed after Buy (purchases.json "ok");
    # "buying at the Mountain Top Shop: bought it — 'Hive Slot | 2.0B Honey |"
    ("bought", re.compile(r"^buying (?:at )?(?P<shop>[^:]+): bought it — "
                          r"'(?P<what>[^|']+?)\s*\|\s*(?P<price>[^|']*)"),
     "the shop window changed after Buy (act/shoplook.buy, var/purchases.json)"),
    # run_farm hatch_the_egg: "egg hatch: answered Yes to 'hatch basic egg';
    # the count read 2 -> 1" (16 lines, 03 Oct .. 21 Oct)
    ("hatched", re.compile(r"^egg hatch(?: \([^)]*\))?: answered Yes to "
                           r"'hatch (?P<what>[^']+)'"),
     "the game asked 'Hatch <egg>?' over the hive cell and Yes was pressed"),
    # stream/show.ROLLED: "royal jelly: 2 rolled on the cell at (1141, 292);
    # it now holds the Shocked Bee" (54 lines)
    ("jelly", re.compile(r"^royal jelly: [1-9]\d* rolled .*it now holds the "
                         r"(?P<what>.+? Bee)"),
     "the bee card read after the roll names the new bee"),
    # stream/show.HANDED_IN (109 lines): said only for a giver the quest menu
    # showed holding a finished quest -- the dialogue read is the hand-in
    ("quest", re.compile(r"^a dialogue was read at the (?P<what>.+?), so it "
                         r"leaves the hand-in queue"),
     "the quest menu showed it finished, then the giver's dialogue was read"),
    # act/badges: "badges: collected 2 complete badge(s); the page is kept
    # in .../var/badges/<stamp>" (5 lines)
    ("badge", re.compile(r"^badges: collected (?P<what>\d+) complete badge"),
     "the badge menu's claim was pressed and the page kept"),
    # stream/show.CRAFTED: "the Blender: collected the finished 7 Blue
    # Extract" (70 lines)
    ("crafted", re.compile(r"^the Blender: collected the finished (?P<what>\d+ .+?)\s*$"),
     "the Blender's finished craft was collected"),
    # brain/goals: "goals: the Hive Slot (bee 40) is ready to buy at the
    # Mountain Top Shop for 500,000,000 honey" (an example) -- kept once per goal (state)
    ("goal_ready", re.compile(r"^goals: the (?P<what>.+?) is ready to buy"),
     "the goals line: the HUD's honey (and the materials read) cover it"),
)
# kinds that are an inference however good the frame (see the docstring)
LIKELY_KINDS = {"quest"}
ONCE_KINDS = {"goal_ready"}         # one row per `what`, ever
# HONEY THRESHOLDS, the HUD's balance first seen at or past each.
HONEY_STEPS = tuple(10 ** k for k in range(3, 13))
_PATH = re.compile(r"(/[^\s'\"()]+?\.(?:png|jpg|jpeg))|kept in (/[^\s'\"()]+)")


def folder(var_root) -> Path:
    return Path(var_root) / DIR


def match(text: str):
    """(kind, what, how) for one of the bot's result lines, else None."""
    text = str(text or "").strip()
    for kind, pat, how in PATTERNS:
        m = pat.search(text)
        if m:
            what = m.group("what").strip()
            if kind == "bought" and (m.group("price") or "").strip():
                what = f"{what} for {m.group('price').strip()}"
            return kind, what, how
    return None


def frame_in(text: str) -> str:
    """A kept frame (or kept page folder) the line names, "" when none."""
    for m in _PATH.finditer(str(text or "")):
        path = (m.group(1) or m.group(2) or "").rstrip(".,;")
        if path and Path(path).exists():
            return path
    return ""


def rows(var_root, since: float | None = None) -> list:
    """Every row of milestones.jsonl, oldest first (a bad line is skipped)."""
    out = []
    try:
        text = (folder(var_root) / FILE).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for line in text.splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and (since is None or float(row.get("at") or 0) >= since):
            out.append(row)
    return out


def day_of(at: float) -> str:
    return datetime.fromtimestamp(float(at)).strftime("%Y-%m-%d")


def summary(var_root, day: str) -> str:
    """One line for `day` (YYYY-MM-DD): the milestones by kind, how many
    proven, and the honey the ledger's trips earned that day."""
    got = [r for r in rows(var_root) if day_of(r.get("at") or 0) == day
           and r.get("kind") != "baseline"]
    kinds: dict = {}
    for r in got:
        kinds[r.get("kind")] = kinds.get(r.get("kind"), 0) + 1
    proven = sum(1 for r in got if r.get("proof") == "proven")
    honey = ""
    try:
        from ..brain.ledger import Ledger
        start = datetime.strptime(day, "%Y-%m-%d").timestamp()
        trips = [t for t in Ledger(Path(var_root) / "trips.jsonl").trips(since=start)
                 if float(t.get("at") or 0) < start + 86400]
        if trips:
            tot = Ledger(Path(var_root) / "trips.jsonl").totals(rows=trips)
            rate = tot.honey_per_hour
            honey = (f"; {tot.honey:,} honey earned over {len(trips)} trips"
                     + (f" ({rate / 1e6:.1f}M/h)" if rate else ""))
    except Exception:
        honey = ""
    what = ", ".join(f"{n} {k}" for k, n in sorted(kinds.items())) or "no milestones"
    return (f"{SAY}: {day}: {what}; {proven} of {len(got)} proven by a frame{honey} "
            f"(var/progression)")


class Recorder:
    """run_farm's: `see(text)` on every narrated line, `check()` now and then
    (called by `see`, at most every CHECK_S). `emit(text)` says a line in the
    feed (run_farm's narrate, wrapped). `live_frame` is the live view's JPEG
    (telemetry/liveview's path), copied as the frame of a line naming none."""

    def __init__(self, var_root, live_frame=None, emit=None, clock=time.time):
        self.var_root = Path(var_root)
        self.live_frame = Path(live_frame) if live_frame else None
        self.emit = emit or (lambda text: None)
        self.clock = clock
        self._checked = -1e18
        self._said_error = False
        self._busy = False

    # ---- state ----------------------------------------------------------
    def _state(self) -> dict:
        try:
            body = json.loads((folder(self.var_root) / STATE).read_text(encoding="utf-8"))
            return body if isinstance(body, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_state(self, state: dict) -> None:
        path = folder(self.var_root) / STATE
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=1), encoding="utf-8")
        tmp.replace(path)

    # ---- one row ---------------------------------------------------------
    def _frame(self, kind: str, line: str, at: float) -> tuple:
        """(frame path, its age in s or None) for a row."""
        named = frame_in(line)
        if named:
            return named, 0.0
        src = self.live_frame
        if src is None or not src.exists():
            return "", None
        age = max(0.0, at - src.stat().st_mtime)
        dest = folder(self.var_root) / FRAMES / (
            datetime.fromtimestamp(at).strftime("%Y%m%d-%H%M%S") + f"-{kind}.jpg")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        return str(dest), round(age, 1)

    def record(self, kind: str, what: str, how: str, line: str = "",
               frame: str | None = None) -> dict | None:
        """Write one row (with its frame) and say it in the feed."""
        try:
            at = self.clock()
            if frame is None:
                frame, age = self._frame(kind, line, at)
            else:
                age = 0.0 if frame else None
            fresh = bool(frame) and age is not None and age <= FRESH_S
            row = {"at": round(at, 1), "kind": kind, "what": what, "how": how,
                   "line": line, "frame": frame or "", "frame_age_s": age,
                   "proof": "proven" if fresh and kind not in LIKELY_KINDS else "likely"}
            path = folder(self.var_root) / FILE
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row) + "\n")
            if kind != "baseline":
                self.emit(f"{SAY}: {kind}: {what} ({row['proof']}"
                          + (", frame kept" if frame else ", no frame") + ")")
            return row
        except Exception as exc:
            if not self._said_error:
                self._said_error = True
                self.emit(f"{SAY}: could not keep a row ({exc}) -- rows are lost until it can")
            return None

    # ---- the two sources ---------------------------------------------------
    def see(self, text: str) -> dict | None:
        """A narrated line: a row when it is a milestone; the files checked
        and yesterday's summary said when they are due. Never raises."""
        if self._busy or str(text).startswith(SAY):
            return None
        self._busy = True                  # `emit` narrates, which comes back here
        try:
            row = None
            got = match(text)
            if got:
                kind, what, how = got
                state = self._state()
                if kind in ONCE_KINDS:
                    seen = set(state.get(kind) or [])
                    if what in seen:
                        got = None
                    else:
                        state[kind] = sorted(seen | {what})
                        self._save_state(state)
                if got:
                    row = self.record(kind, what, how, line=str(text).strip())
            if self.clock() - self._checked >= CHECK_S:
                self._checked = self.clock()
                self.check()
            return row
        except Exception:
            return None
        finally:
            self._busy = False

    def check(self) -> list:
        """The readers' files against the last seen: new rows, oldest
        reasons first. The first look writes only the baseline row."""
        out = []
        state = self._state()
        var = self.var_root
        try:
            bees_body = json.loads((var / "bees.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            bees_body = {}
        try:
            honey = int(json.loads((var / "balance.json").read_text(encoding="utf-8"))
                        .get("honey") or 0)
        except (OSError, ValueError, TypeError):
            honey = 0
        bees = int(bees_body.get("total") or 0) if bees_body.get("verified", True) else 0
        gifted = sorted(set(bees_body.get("gifted") or []))
        tier = max([s for s in HONEY_STEPS if honey >= s], default=0)
        if "baseline" not in state:
            state.update(baseline=self.clock(), bees_max=bees, gifted=gifted, honey_tier=tier)
            self._save_state(state)
            self.record("baseline", f"{bees} bees, {len(gifted)} gifted types, "
                        f"{honey:,} honey",
                        "the bee menu read (var/bees.json) and the HUD (var/balance.json) "
                        "when the recorder first ran: the account as found")
            return out
        if bees > int(state.get("bees_max") or 0):
            before = int(state.get("bees_max") or 0)
            state["bees_max"] = bees
            out.append(self.record("bees", f"{before} -> {bees} bees",
                                   "the bee menu's own header, two agreeing reads "
                                   "(act/beemenu, var/bees.json)", frame=_beemenu(var)))
            for field, need in gates_crossed(before, bees):
                out.append(self.record("field_gate", f"{field} ({need} bees)",
                                       "the bee count passed the field's gate "
                                       "(data/knowledge/world.yaml bees_required)",
                                       frame=_beemenu(var)))
        new = [g for g in gifted if g not in set(state.get("gifted") or [])]
        if new:
            state["gifted"] = sorted(set(state.get("gifted") or []) | set(new))
            for name in new:
                out.append(self.record("gifted", f"gifted {name}",
                                       "the bee menu's star on that type (var/bees.json "
                                       "gifted)", frame=_beemenu(var)))
        if tier > int(state.get("honey_tier") or 0):
            state["honey_tier"] = tier
            out.append(self.record("honey", f"{tier:,} honey (HUD {honey:,})",
                                   "the HUD's honey, two agreeing reads (brain/owned, "
                                   "var/balance.json)"))
        self._save_state(state)
        today = day_of(self.clock())
        if state.get("summary_day") != today:
            last = state.get("summary_day")
            state["summary_day"] = today
            self._save_state(state)
            if last:
                self.emit(summary(var, last))
        return [r for r in out if r]


def _beemenu(var_root) -> str:
    """The newest kept bee-menu page folder (act/beemenu: var/beemenu/<stamp>)."""
    try:
        pages = sorted(p for p in (Path(var_root) / "beemenu").iterdir() if p.is_dir())
        return str(pages[-1]) if pages else ""
    except OSError:
        return ""


def gates_crossed(before: int, after: int) -> list:
    """[(field, bees_required)] the bee count newly reaches, from world.yaml."""
    try:
        import yaml
        from ..datapaths import data
        fields = (yaml.safe_load(data("knowledge", "world.yaml").read_text(encoding="utf-8"))
                  or {}).get("fields") or {}
    except Exception:
        return []
    return sorted(((name, int(b.get("bees_required") or 0)) for name, b in fields.items()
                   if before < int((b or {}).get("bees_required") or 0) <= after),
                  key=lambda x: (x[1], x[0]))


# ---- the old run logs (tools/progression_report.py --backfill) ------------------
LOG_LINE = re.compile(r"^\s*(\d\d):(\d\d):(\d\d)  (.*)$")


def dated_lines(log: Path):
    """(timestamp, text) for each timed line of a run log, oldest first. A
    line carries a time and no date: the last one is dated by the log's last
    write and each earlier one a day back when its time is later than the one
    after it (a run is hours; one that ran past midnight steps back once)."""
    try:
        end = datetime.fromtimestamp(log.stat().st_mtime)
        lines = log.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    out, day, after = [], end.date(), end.time().replace(microsecond=0)
    for line in reversed(lines):
        m = LOG_LINE.match(line)
        if not m:
            continue
        t = datetime.strptime(":".join(m.group(1, 2, 3)), "%H:%M:%S").time()
        # 60 s of slack: the last line can be a little after the file's mtime
        if (datetime.combine(date.min, t) - datetime.combine(date.min, after)
                > timedelta(seconds=60)):
            day -= timedelta(days=1)
        after = t
        out.append((datetime.combine(day, t).timestamp(), m.group(4)))
    out.reverse()
    return out
