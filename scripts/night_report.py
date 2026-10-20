#!/usr/bin/env python3
"""What happened overnight, in one page, for someone who was asleep.

The owner is not a programmer and went to bed asking to wake up to honey. A
directory of `run-0NN.log` files is not an answer to that. This reads every
log the night produced and says what actually happened: how much honey was
earned, how many cycles ran, what killed the character, what crashed and what
the bot learned about each field.

Every number here is parsed out of a log line the bot itself wrote, or read
live from the HUD. Nothing is estimated, and a figure that could not be found
is printed as "not measured" rather than as zero.

    ./.venv/bin/python scripts/night_report.py [--write]
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
NIGHT = ROOT / "var" / "night"
REPORT = NIGHT / "MORNING.md"

# ONE TRIP, IN HOURS. A trip gathers for about twenty minutes and banks the
# whole backpack at the end, so this is the shortest window over which an
# hourly rate means anything at all. See the headline rate line.
TRIP_HOURS = 20 / 60

HONEY = re.compile(r"starting honey:\s+([\d,]+)")
POLLEN = re.compile(r"starting pollen:\s+([\d,]+)/([\d,]+)")
CYCLE = re.compile(r"cycle (\d+): ([\d,]+|pollen not measured)[^,]*,\s*"
                   r"(\+?[\d,-]+ honey|honey not measured)")
DIED = re.compile(r"died: pollen fell ([\d,]+) -> ([\d,]+)")
TRACEBACK = re.compile(r"^Traceback", re.M)
# A DELIBERATE STOP IS NOT A CRASH. Asking the run to stop during bootstrap
# lands in `platform/input`'s signal handler, which raises KeyboardInterrupt
# so that every held key is released on the way out -- the safety mechanism
# working exactly as designed. It leaves a traceback in the log, and counting
# those as crashes made a clean night look like a broken one.
DELIBERATE = re.compile(r"KeyboardInterrupt|stop requested", re.M)


def number(text: str) -> int | None:
    try:
        return int(text.replace(",", ""))
    except (ValueError, AttributeError):
        return None


# A GAP THIS LONG BETWEEN ATTEMPTS MEANS A DIFFERENT NIGHT. The ledger is
# append-only and spans every night the watchdog has ever run, so "the first
# attempt in it" is not the first attempt of THIS night.
#
# It read 15 hours' worth on 2026-09-22 and reported "earned 2,051,028 honey
# overnight (1,187,358 -> 3,238,386)" when the night had begun on 3,113,848 and
# earned 124,538 -- sixteen times too high, in the headline. Attempts within a
# night are minutes apart and the longest healthy one measured is about twenty
# minutes, so three hours cannot split a night and cannot join two.
NIGHT_GAP = 3 * 3600.0


def owner_needed() -> str:
    """The newest run log's start blocked on something only the owner can do
    -- Roblox's agreements box (act/bootstrap.NEEDS_THE_OWNER) -- said as it
    said it, with when it began; "" when the newest start was not."""
    logs = sorted(NIGHT.glob("run-*.log"), key=lambda p: p.stat().st_mtime)
    if not logs:
        return ""
    try:
        text = logs[-1].read_text(errors="replace")
    except OSError:
        return ""
    if '"Updated Agreements"' not in text or "FAILED" not in text:
        return ""
    since = None
    for log in reversed(logs):
        try:
            body = log.read_text(errors="replace")
        except OSError:
            break
        if '"Updated Agreements"' in body:
            since = log
        else:
            break
    when = (time.strftime("%H:%M", time.localtime(since.stat().st_mtime))
            if since is not None else "")
    return ("Roblox is showing its \"Updated Agreements\" box (Terms of Use, "
            "Privacy Policy) and will not let anyone in until you press I Agree"
            + (f" (every start since {when})" if when else "") + ".")


def _attempt_times() -> list[float]:
    """Every attempt start in the ledger, oldest first, as unix times."""
    out: list[float] = []
    try:
        rows = (NIGHT / "attempts.log").read_text(errors="replace").splitlines()
    except OSError:
        return out
    for row in rows:
        if "starting" not in row:
            continue
        found = re.search(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", row)
        if not found:
            continue
        try:
            out.append(time.mktime(time.strptime(found.group(1),
                                                 "%Y-%m-%d %H:%M:%S")))
        except ValueError:
            continue
    return out


def night_started() -> float | None:
    """When the first attempt of THIS night began, as a unix time.

    From the watchdog's ledger, which is append-only, and NOT from a log
    file's timestamp -- finished run logs get archived, which rewrites their
    mtime and made the honey-per-hour figure read three times too high.

    Walks back from the newest attempt while the attempts are close together;
    the first gap longer than NIGHT_GAP is where the night began.
    """
    times = _attempt_times()
    if not times:
        return None
    start = times[-1]
    for earlier, later in zip(reversed(times[:-1]), reversed(times[1:])):
        if later - earlier > NIGHT_GAP:
            break
        start = earlier
    return start


STAMP = re.compile(r"(\d{2}):(\d{2}):(\d{2})")


def _stamp_before(text: str, index: int) -> int | None:
    """Seconds-of-day of the last HH:MM:SS before `index`, for deduplication."""
    found = None
    for match in STAMP.finditer(text, 0, index):
        found = match
    if found is None:
        return None
    hours, minutes, seconds = (int(part) for part in found.groups())
    return hours * 3600 + minutes * 60 + seconds


def _running(pattern: str) -> bool:
    """Is a process matching `pattern` alive? Used to say, at the top of the
    report, whether the bot is still going -- which is the first thing anyone
    reading this at breakfast wants to know."""
    import subprocess
    try:
        found = subprocess.run(["pgrep", "-f", pattern],
                               capture_output=True, timeout=5)
        return found.returncode == 0
    except Exception:
        return False


def _logs_named_since(started: float | None) -> list[pathlib.Path] | None:
    """The run logs the ledger names for THIS night, oldest first.

    The ledger writes the log path on every attempt, so this is exact --
    unlike globbing, which cannot tell one night's `run-041.log` from
    another's. Returns None when the ledger cannot be read, so the caller
    falls back to globbing rather than reporting an empty night.
    """
    if started is None:
        return None
    wanted: list[pathlib.Path] = []
    try:
        rows = (NIGHT / "attempts.log").read_text(errors="replace").splitlines()
    except OSError:
        return None
    for row in rows:
        if "starting" not in row:
            continue
        stamp = re.search(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", row)
        path = re.search(r"-> (\S+\.log)", row)
        if not stamp or not path:
            continue
        try:
            when = time.mktime(time.strptime(stamp.group(1),
                                             "%Y-%m-%d %H:%M:%S"))
        except ValueError:
            continue
        if when + 1 < started:
            continue
        found = pathlib.Path(path.group(1))
        if found not in wanted:
            wanted.append(found)
    return [f for f in wanted if f.exists()] or None


def runs() -> list[pathlib.Path]:
    """Every run log of THIS night, oldest first.

    A restarted watchdog reuses `run-00N.log` names and appends, so anything
    tailing the live log re-reads hours-old lines as though they were
    happening now -- which misread an old "FAILED: Sober never opened a
    window" as current, twice. Finished logs are archived into `earlier/` so
    reused names start empty.

    AND THE NIGHT HAS TO END SOMEWHERE. Globbing every log in the folder mixed
    nights together: on 2026-09-22 the report opened with "earned 2,051,028
    honey overnight (1,187,358 -> 3,238,386)" when the night had begun on
    3,113,848 and earned 124,538. Sixteen times too high, in the headline, and
    the cycle and death counts were wrong by the same kind of margin. The
    ledger names each attempt's log, so the night's own logs can be listed
    exactly; globbing is the fallback for a missing ledger.
    """
    named = _logs_named_since(night_started())
    if named is not None:
        return named
    old = sorted((NIGHT / "earlier").glob("*.log"))
    return old + sorted(NIGHT.glob("run-*.log"))


def _attempts_with_logs() -> list[tuple[float, pathlib.Path]]:
    """(start time, log path) per attempt in the ledger, oldest first.

    Kept as PAIRS rather than two lists. `_logs_named_since` deduplicates by
    path -- the watchdog reuses `run-0NN.log` names -- so it had 85 entries
    against 143 attempts, and indexing the two together paired an attempt with
    someone else's log.
    """
    out: list[tuple[float, pathlib.Path]] = []
    try:
        rows = (NIGHT / "attempts.log").read_text(errors="replace").splitlines()
    except OSError:
        return out
    for row in rows:
        if "starting" not in row:
            continue
        stamp = re.search(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", row)
        path = re.search(r"-> (\S+\.log)", row)
        if not stamp or not path:
            continue
        try:
            when = time.mktime(time.strptime(stamp.group(1),
                                             "%Y-%m-%d %H:%M:%S"))
        except ValueError:
            continue
        out.append((when, pathlib.Path(path.group(1))))
    return out


def recent_rate():
    """(honey gained, hours, per hour) for the run in progress, or None.

    Measured from the CURRENT attempt's own starting-honey line against what
    is on screen now, so it describes the code that is running rather than an
    average over everything that has run tonight.
    """
    now = live_honey()
    attempts = _attempts_with_logs()
    if now is None or not attempts:
        return None
    # The newest attempt may not have read its honey yet -- a run spends its
    # first forty seconds joining -- so walk back to the most recent one that
    # did, carrying its own start time with it.
    for when, log in reversed(attempts):
        if not log.exists():
            continue
        try:
            text = log.read_text(errors="replace")
        except OSError:
            continue
        found = re.search(r"starting honey:\s+([\d,]+)", text)
        if found is None:
            continue
        began = number(found.group(1))
        if began is None:
            continue
        hours = (time.time() - when) / 3600.0
        if hours < 2 / 60:
            # Too young to be a rate -- a run spends its first forty seconds
            # joining. Fall back to the attempt before it rather than give up:
            # returning None here meant the line vanished for the first two
            # minutes of every restart, which is most of the time on a night
            # that restarts every cycle.
            continue
        return now - began, hours, (now - began) / hours
    return None


def live_honey() -> int | None:
    """The honey figure on screen right now, or None if it cannot be read."""
    age = _frame_age()
    if age is None or age > LIVE_FRAME_MAX_AGE_S:
        return None            # a stale frame is history, not "now"
    try:
        import cv2
        sys.path.insert(0, str(ROOT / "src"))
        from hivemind.brain.farm import HudReader
        from hivemind.vision import screenstate as ss
        frame = cv2.imread(str(_live_view()))
        if frame is None:
            return None
        hud = HudReader(lambda: frame,
                        ss.load_templates(ROOT / "data/templates/digits"))
        reading = hud.honey()
        return int(reading.value) if reading.ok else None
    except Exception:
        return None


# A live frame older than this is not live. The bot's LiveView rewrites the
# file at 20 fps while it runs; two minutes of silence means it is not running.
LIVE_FRAME_MAX_AGE_S = 120.0


def _live_view() -> pathlib.Path:
    """The LiveView's JPEG (datapaths.runtime_dir, /run/user/1000 here)."""
    sys.path.insert(0, str(ROOT / "src"))
    from hivemind.datapaths import runtime_dir
    return runtime_dir() / "hivemind-live.jpg"


def _frame_age() -> float | None:
    try:
        return time.time() - _live_view().stat().st_mtime
    except OSError:
        return None


def live_hud() -> str:
    """Ask the game directly, so the last line is current rather than historic.

    A STALE FRAME IS SAID TO BE STALE. On 2026-09-22 the bot had been stopped
    for half an hour and this line still read "Right now: honey 5,488,335",
    off a frame written at 18:55. A number with no time on it is a claim about
    now, so an old frame gets its age instead of a verdict.
    """
    age = _frame_age()
    if age is not None and age > LIVE_FRAME_MAX_AGE_S:
        return (f"no live frame — the last one was written "
                f"{age / 60:.0f} minutes ago, so the bot is not running")
    try:
        import cv2
        sys.path.insert(0, str(ROOT / "src"))
        from hivemind.brain.farm import HudReader
        from hivemind.vision import screenstate as ss
        frame = cv2.imread(str(_live_view()))
        if frame is None:
            return "the game is not on screen right now"
        hud = HudReader(lambda: frame,
                        ss.load_templates(ROOT / "data/templates/digits"))
        honey, pollen = hud.honey(), hud.pollen()
        line = (f"honey {honey.describe()}, "
                f"backpack {pollen.describe()}")
        # SAY HOW SURE IT IS. `describe()` prints a figure and nothing else,
        # and a misread pollen counter is the single most expensive bug of
        # 2026-09-22 (DESIGN 8m) -- it read "212?1,072,500 at confidence
        # 0.19" and cost 200x on a trip. This is the most prominent live
        # number in the report; presenting a 0.6-confidence digit read as
        # plain fact is how a reader stops questioning it.
        worst = min(float(getattr(honey, "score", 1.0) or 0.0),
                    float(getattr(pollen, "score", 1.0) or 0.0))
        if worst < 0.75:
            line += (f" — read at only {worst:.0%} confidence, so treat the "
                     f"digits as approximate")
        return line
    except Exception as exc:
        return f"could not read the HUD ({exc})"


def gear_plan(live):
    """(the gear-goal plan, "") or (None, why), from `brain.goals` -- the
    module the bot plans with and the GUI draws -- with the live frame's
    honey when there is one and the ledger's last confirmed convert when not.
    """
    try:
        sys.path.insert(0, str(ROOT / "src"))
        from hivemind.brain import goals as goals_plan
        return goals_plan.from_files(
            var_root=ROOT / "var", honey=live,
            honey_from="the live frame" if live is not None else "",
            honey_at=time.time() if live is not None else None), ""
    except Exception as exc:                               # noqa: BLE001
        return None, str(exc)


def gear_section(plan) -> list[str]:
    """The owner's gear goals as a report section. See brain/goals."""
    from hivemind.brain import goals as goals_plan
    out = ["## Your gear goals",
           "_What you asked for, in your order (Settings › Goals › Gear to "
           "work towards). The bot buys the next Hive Slot itself, with honey "
           "and never Robux; when another is affordable it puts a card in "
           "Hivemind's Decision Inbox, and you buy it._", "",
           f"- {plan.honey_line()}; "
           + (f"rate: {plan.rate.describe()}" if plan.rate
              else "no honey rate measured yet, so no times are given"), "",
           "| goal | where | honey | short, counting the ones above | about | now |",
           "| --- | --- | --- | --- | --- | --- |"]
    for row in plan.rows:
        short = ("—" if row.owned else "not read" if row.queue_short is None
                 else f"{row.queue_short:,}")
        out.append(f"| {row.label} | {row.shop_label} | {row.cost:,} | {short} | "
                   f"{goals_plan.hours_text(row.eta_hours) or '—'} | "
                   f"{getattr(row, 'state_text', row.state)} |")
    out.append("")
    for row in plan.rows:
        if row.next_step and (not row.owned
                              or getattr(row, "owned_how", "") == "inferred"):
            out.append(f"- **{row.label}:** {row.next_step}")
    if plan.unknown_names:
        out.append(f"- *Not goals the list knows: {', '.join(plan.unknown_names)}*")
    if plan.unread_counts:
        out.append(f"- *Material counts it could not read (Settings › Goals "
                   f"› Materials you hold): {', '.join(plan.unread_counts)}*")
    out.append("")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true",
                    help=f"also write {REPORT}")
    args = ap.parse_args()

    first_honey = last_honey = None
    # EARNED IS NOT (LAST - FIRST). The owner spends honey -- that is what it
    # is for -- and on 2026-09-22 he spent about 13.7M between attempts 213
    # (18,847,505) and 216 (5,175,093) while the bot had earned 15.7M. Read
    # off the balance alone, the night looked like +2.4M. So every rise
    # between successive readings is counted as earned and every fall as
    # spent, and both are said. A fall is spending, not a loss: the bot has no
    # way to lose honey, only pollen.
    earned_total = spent_total = 0
    previous_honey = None
    cycles = deaths = crashes = 0
    pollen_lost = 0
    gathered: list[int] = []
    per_run = []

    for path in runs():
        text = path.read_text(errors="replace")
        honeys = [number(m) for m in HONEY.findall(text)]
        honeys = [h for h in honeys if h is not None]
        if honeys:
            if first_honey is None:
                first_honey = honeys[0]
            last_honey = honeys[-1]
            for h in honeys:
                if previous_honey is not None:
                    if h >= previous_honey:
                        earned_total += h - previous_honey
                    else:
                        spent_total += previous_honey - h
                previous_honey = h
        run_cycles = CYCLE.findall(text)
        cycles += len(run_cycles)
        for got, _ in [(m[1], m[2]) for m in run_cycles]:
            value = number(got)
            if value is not None:
                gathered.append(value)
        # ONE DEATH, NOT TWO. Two independent detectors notice the same death
        # -- `brain/alive.DeathWatch` reading the pill once a second, and the
        # farm loop's own check between pattern passes -- so a single mantis
        # writes two "died: pollen fell" lines a few seconds apart with
        # slightly different peaks. Counting both reported 6 deaths for a
        # night that had 4. Lines close together are the same event.
        run_deaths = []
        previous_at = None
        for match in DIED.finditer(text):
            at = _stamp_before(text, match.start())
            if previous_at is not None and at is not None \
                    and at - previous_at < 30:
                previous_at = at
                continue
            previous_at = at
            run_deaths.append(match.groups())
        deaths += len(run_deaths)
        for before, after in run_deaths:
            a, b = number(before), number(after)
            if a is not None and b is not None:
                pollen_lost += max(0, a - b)
        crashed = bool(TRACEBACK.search(text)) and not DELIBERATE.search(text)
        crashes += int(crashed)
        per_run.append((path.name, len(run_cycles), len(run_deaths), crashed))

    lines: list[str] = []
    add = lines.append
    add("# Hivemind — overnight report")
    add("")
    add(f"_generated {time.strftime('%Y-%m-%d %H:%M')}_")
    add("")
    # Read the live figures FIRST: the summary below quotes them, and the
    # detail sections further down reuse the same values rather than asking
    # the game twice.
    now = live_honey()
    latest = now if now is not None else last_honey
    # THE LIVE FIGURE IS THE LAST READING TOO, and it is folded in HERE, before
    # the headline is worked out (DESIGN 8du). It used to be added only in the
    # Honey section further down, so on any night with spending the short
    # version's "It earned X ... about Y an hour" left out the current
    # attempt's gains and disagreed with "Earned: +..." a few lines below.
    if now is not None and previous_honey is not None:
        if now >= previous_honey:
            earned_total += now - previous_honey
        else:
            spent_total += previous_honey - now
    # The farm is DOWN only if the watchdog is gone too. Between attempts --
    # during a rejoin, which happens every cycle -- run_farm is legitimately
    # absent for about a minute, and reporting that as "NOT running" at the
    # top of the page is alarming and wrong.
    farming = bool(_running("run_farm.py"))
    supervised = bool(_running("overnight.sh"))
    alive = farming or supervised

    # THE FIVE LINES THAT MATTER, before 200 lines of detail. The owner is
    # not a programmer and will read this at breakfast; burying "it worked and
    # here is how much" under an engineering changelog is a way of not saying
    # it.
    earned = (latest - first_honey) if (first_honey is not None
                                        and latest is not None) else None
    # Honey per hour, measured from the first run's clock rather than claimed.
    # It is the single number that says whether the night's work paid off, and
    # it roughly tripled between the first hour and the fourth as the trip
    # length tuned itself.
    # EARNED IS THE SUM OF THE RISES, NOT THE CHANGE IN THE BALANCE. The owner
    # spends honey -- that is what it is for. On 2026-09-22 he spent 13.7M
    # between attempts 213 and 216 while the bot had earned 16.0M, and this
    # line read the night as +2.4M. `earned_total`/`spent_total` are summed
    # over successive readings above; the balance change is still shown.
    if earned is not None and spent_total:
        earned = earned_total
    per_hour = None
    started = night_started()
    if started and earned:
        hours = max(0.05, (time.time() - started) / 3600.0)
        per_hour = earned / hours

    add("## The short version")
    # WAITING FOR HIM, said first: a start that found Roblox's "Updated
    # Agreements" box (act/bootstrap.NEEDS_THE_OWNER) cannot go on until he
    # presses I Agree, and the bot never does. MEASURED 2026-10-02 00:55 on.
    waiting = owner_needed()
    if waiting:
        add(f"- **The bot is waiting for you: {waiting}** It has tried every "
            f"15 minutes since; once you have, the next start joins by itself.")
    if earned is not None:
        add(f"- It earned **{earned:,} honey** overnight "
            f"({first_honey:,} → {latest:,}"
            + (f" on the balance, after **{spent_total:,} spent** — the bot "
               f"cannot lose honey, so that was you buying things" if spent_total else "")
            + ")."
            + (f" That is about **{per_hour:,.0f} an hour**."
               if per_hour else ""))
    # THE RATE RIGHT NOW, not only the night's average. A night that started
    # broken and was fixed at 2 a.m. averages out to something that describes
    # neither half: on 2026-09-22 the average read 81,220 an hour while the
    # run in progress was earning 411,000. "Is it working now" is a different
    # question from "how did the night go", and the average answers only the
    # second.
    recent = recent_rate()
    if recent:
        gained, hours, rate = recent
        # DO NOT EXTRAPOLATE ACROSS LESS THAN ONE TRIP. Honey arrives in
        # lumps -- a trip gathers for twenty minutes and banks the lot in one
        # go -- so a window shorter than a trip either contains a whole bank
        # or none of it, and dividing by the window is meaningless either way.
        # MEASURED 2026-09-22 04:56: a bank of +1,019,114 landed eight minutes
        # into an attempt and this line read "earning about 8,207,001 an
        # hour", which is not a rate, it is one bank and a small denominator.
        if hours >= TRIP_HOURS:
            add(f"- **Right now it is earning about {rate:,.0f} an hour** "
                f"({gained:+,} in the last {hours * 60:.0f} minutes). That is "
                f"the figure to judge it by if the night started badly.")
        else:
            add(f"- In the last {hours * 60:.0f} minutes it has banked "
                f"**{gained:+,}**. That is less than one trip, and honey "
                f"arrives in lumps of a whole backpack, so it is deliberately "
                f"not turned into an hourly figure — the average above is the "
                f"honest one until this attempt has run "
                f"{TRIP_HOURS * 60:.0f} minutes.")
    add(f"- It ran **{cycles}** farming trips and is "
        + ("**still running**." if alive else "**NOT running** — see below.")
        + ("" if farming or not alive else
           " (between trips right now — it rejoins the server to bank, which "
           "takes about a minute.)"))
    add(f"- It died **{deaths}** time{'' if deaths == 1 else 's'}"
        + (f", costing {pollen_lost:,} pollen." if pollen_lost else "."))
    # THE GEAR HE ASKED FOR (DESIGN 8dp). This line used to say "Nothing at
    # your level is worth buying", which stopped being true the day he asked
    # for the Porcelain Dipper, the Port-O-Hive and the Ace room. The bot still
    # buys nothing -- that part is by design -- and the plan is below.
    gear, gear_error = gear_plan(now)
    if gear is not None and gear.rows:
        line = gear.headline()
        line = line[len("goals: "):] if line.startswith("goals: ") else line
        add(f"- **The bot bought nothing — it never does.** Gear: {line}. "
            f"All of it is under *Your gear goals* below.")
    else:
        add("- **The bot bought nothing — it never does.**"
            + (f" *(could not plan the gear goals: {gear_error})*"
               if gear_error else ""))
    # THE ONE ASK, AT THE TOP. It used to say "at the very bottom", which is
    # four hundred lines away in a document read on a phone at breakfast. The
    # night of 2026-09-22 spent itself proving this is the bottleneck: the
    # trips gather well and then land a field over, because every recorded
    # route out assumes a pad the bot cannot name.
    try:
        sys.path.insert(0, str(ROOT / "src"))
        from hivemind.world.settings import Settings
        slot = int(Settings().get("move.hive_slot") or 0)
    except Exception as exc:                           # noqa: BLE001
        # SAY SO RATHER THAN ASSUME UNSET. The first version imported
        # `hivemind.brain.settings`, which does not exist, and swallowed the
        # ImportError into `slot = 0` -- so the line below would have nagged
        # for a hive slot for ever, including after it had been set. A check
        # that silently fails closed is indistinguishable from a check that
        # is not running, which is the mistake this file keeps re-learning.
        slot = 0
        add(f"- *(could not read your settings to check the hive slot: "
            f"{exc})*")
    if slot:
        add(f"- Your hive slot is set to **{slot}**, so the walks out start "
            f"from the right pad.")
    else:
        # THE BOT MEASURED IT ITSELF, so the ask is only still an ask when the
        # measurement is missing too. It felt for the ramp wall and read the
        # slot off the distance walked (act/routes._hive_offset, DESIGN 8w);
        # var/heading.json records which slot and whether it was measured or
        # merely the one that last arrived.
        measured, source = None, ""
        try:
            import json as _json
            body = _json.loads((ROOT / "var" / "heading.json").read_text())
            measured = int(body.get("slot") or 0) or None
            source = str(body.get("slot_source") or "")
        except Exception:
            measured = None
        if measured and source == "measured":
            add(f"- **Your hive slot is {measured}, and the bot worked that out "
                f"itself** — it walked at the ramp until the wall stopped it and "
                f"read the slot off the distance. Nothing needed from you. (It is "
                f"in the Movement panel as `move.hive_slot` if you ever want to "
                f"change it.)")
        elif measured:
            add(f"- The bot is running as hive slot **{measured}**, which is the "
                f"slot that last arrived rather than one it measured. If that is "
                f"wrong, `move.hive_slot` in the Movement panel is ten seconds.")
        else:
            add("- **TEN SECONDS FROM YOU: which hive slot do you own, 1 to 6?** "
                "Put it in the Movement panel (`move.hive_slot`). Every recorded "
                "route out of the hive assumes the character starts on one "
                "particular pad, and without this the sideways walk to your pad "
                "is skipped — which is why trips aim at one field and get "
                "credited another.")
    add("- The rest of what would help is at the very bottom — all of it is "
        "\"show it something once\", not work.")
    add("")
    add("## Honey")
    # `latest` prefers what is on screen NOW over the last figure a log
    # happened to record: a run writes its starting honey and then never
    # mentions the total again, so the log lags by however long the current
    # run has been going -- on a good cycle, most of a million honey.
    if first_honey is not None and latest is not None:
        add(f"- Started the night on **{first_honey:,}** honey")
        add(f"- Now: **{latest:,}**"
            + ("" if now is not None else " (last figure in the logs)"))
        if spent_total:
            add(f"- **Earned: +{earned_total:,}** — and **{spent_total:,} was "
                f"spent** (the balance fell between readings; the bot cannot "
                f"lose honey, so that was you buying things), leaving the "
                f"balance {latest - first_honey:+,} on the night")
        else:
            add(f"- **Earned: {latest - first_honey:+,}**")
    else:
        add("- not measured — no run logged a starting honey figure")
    add(f"- Right now: {live_hud()}")
    add("")
    if gear is not None and gear.rows:
        lines.extend(gear_section(gear))
    add("## Farming")
    add(f"- Cycles completed: **{cycles}**")
    if gathered:
        add(f"- Pollen gathered per cycle: best **{max(gathered):,}**, "
            f"typical **{sorted(gathered)[len(gathered)//2]:,}**")
    add(f"- Deaths: **{deaths}**"
        + (f", costing **{pollen_lost:,}** pollen" if pollen_lost else ""))
    # Count from the watchdog's own ledger, not from log FILES. A restarted
    # watchdog reuses run-00N.log names, so counting files understated 40
    # attempts as 11 -- and "how many times did it have to restart" is one of
    # the few numbers that says whether the night was actually healthy.
    #
    # ONLY THIS NIGHT'S, though: the ledger is append-only and spans every
    # night, so counting all of it reported 143 restarts for a night that had
    # 18. `_attempt_times` and `night_started` agree on where the night began.
    begun = night_started()
    started = len([t for t in _attempt_times()
                   if begun is None or t + 1 >= begun]) or len(per_run)
    add(f"- Runs started: **{started}**, of which **{crashes}** crashed with "
        f"a traceback")
    add("  - restarts are normal: the game's launch fails transiently and the "
        "watchdog retries")
    add("")

    # EVERY TRIP, EXACTLY, from the ledger rather than from regexes over log
    # prose. The sections above parse what the run PRINTED, which is all there
    # was before `brain.ledger`; this one reads what it RECORDED. Printed as
    # well as, not instead of, because the ledger only knows trips made since
    # it was wired in and the logs still hold the nights before that.
    # Imported here, like every other hivemind import in this script: the
    # report must still print when the package cannot be imported at all.
    tonight: list = []
    book = None
    try:
        sys.path.insert(0, str(ROOT / "src"))
        from hivemind.brain.ledger import Ledger, latest_session
        book = Ledger(ROOT / "var" / "trips.jsonl")
        tonight = latest_session(book.trips())
    except Exception as exc:                      # noqa: BLE001
        add(f"*could not read the trip ledger ({exc})*")
        add("")
    if tonight and book is not None:
        totals = book.totals(rows=tonight)
        add("## Every trip, exactly")
        add(f"- {totals.describe()}")
        if totals.walked_home or totals.not_home:
            gathered = totals.walked_home + totals.not_home
            add(f"- **Walked home and converted on {totals.walked_home} of "
                f"{gathered} trips that gathered**; the other {totals.not_home} "
                f"never reached the pad and the rejoin banked the backpack "
                f"instead (about a minute each, and it keeps the pollen).")
        best = book.best_fields(rows=tonight)
        if best:
            add("- Honey by the field the game actually paid it in: "
                + ", ".join(f"**{name}** {value:,}" for name, value in best))
        if totals.unattributed:
            add(f"- **{totals.unattributed:,}** was earned on trips where the "
                f"game never named a field, so it is not put against one. "
                f"That is not a rounding note: a trip that reaches nowhere "
                f"still picks up a little honey from tokens, and crediting it "
                f"to wherever the trip was aimed would make a field it never "
                f"reached look like it pays.")
        add("")
        where = book.pollen_by_field(rows=tonight)
        if where:
            add("- **Pollen by the field the game named, and what it paid per "
                "second there** (honey is banked a cycle later, so pollen is the "
                "honest answer to where the work happened): "
                + ", ".join(f"**{name}** {v['pollen']:,} at {v['per_second']:,.0f}/s"
                            f" over {v['trips']} trip(s)"
                            for name, v in sorted(where.items(),
                                                  key=lambda kv: -kv[1]["pollen"])[:6]))
        patterns = book.by_pattern(rows=tonight)
        if len(patterns) > 1 or any(v["trips"] >= 2 for v in patterns.values()):
            add("- **Pollen per gathering second, by pattern** (the only honest way "
                "to compare Natro's per-field patterns with our old `farm_snake`): "
                + ", ".join(f"`{name}` {v['per_second']:,}/s over {v['trips']} trip(s)"
                            for name, v in sorted(patterns.items(),
                                                  key=lambda kv: -(kv[1]["per_second"] or 0))))
        add("")
        add("| when | aimed at | paid in | out for | passes | honey |")
        add("| --- | --- | --- | --- | --- | --- |")
        for row in list(reversed(tonight))[:25]:
            honey = row.get("honey")
            when = time.strftime("%H:%M", time.localtime(row.get("at") or 0))
            aimed = row.get("aimed_at") or "—"
            paid = row.get("credited") or "—"
            marks = []
            # A CYCLE THAT GATHERED NOTHING AND BANKED A FORTUNE is the
            # previous trip's backpack, kept through the rejoin. Real honey,
            # wrong clock -- say so in the row as well as in the summary.
            if (row.get("honey") and int(row.get("passes") or 0) == 0
                    and float(row.get("gather_seconds") or 0.0) == 0.0):
                marks.append("an earlier trip's backpack, banked on arrival")
            if int(row.get("deaths") or 0):
                marks.append(f"{row['deaths']} death(s)")
            if int(row.get("unreadable_pollen") or 0):
                marks.append(f"counter unreadable {row['unreadable_pollen']}x")
            if row.get("recoveries"):
                marks.append("recovered " + ", ".join(row["recoveries"]))
            note = (" <br>" + "; ".join(marks)) if marks else ""
            add(f"| {when} | {aimed} | {paid} | "
                f"{float(row.get('seconds') or 0):.0f}s | "
                f"{int(row.get('passes') or 0)} | "
                + (f"{honey:+,}" if honey is not None else "*not measured*")
                + f"{note} |")
        add("")
        add("*Same file the Ledger tab in Hivemind reads — var/trips.jsonl, "
            "one line per trip, written as each trip ends.*")
        add("")

    # WHICH ROUTES LAND, from the skill book the farm folds each trip into
    # (brain/skills, DESIGN 8dy). A quarantined route is not taken while
    # another goes the same way, and it is here so the owner knows which ones
    # to walk and record again; scripts/replay_skills.py prints the full table.
    stats = ROOT / "var" / "skill_stats.json"
    if stats.exists():
        add("## Which routes land")
        try:
            sys.path.insert(0, str(ROOT / "src"))
            from hivemind.brain.skills import SKILL_WINDOW, SkillBook
            skill_book = SkillBook(stats)
            if not skill_book.load():
                raise ValueError("written under other rules — the next run rebuilds it")
            quarantined = skill_book.quarantine_list()
            if quarantined:
                add(f"**Needs the owner — quarantined routes.** Each landed where it is "
                    f"named so rarely over its last {SKILL_WINDOW} verdicts that the "
                    f"bot is 95% sure it lands there less than half the time. A "
                    f"field's walk or flight that is quarantined is not taken while "
                    f"the other is allowed; a walk home or an errand has no other "
                    f"route, so it is still walked. Recording it again (or fixing "
                    f"its steps) starts its record afresh:")
                for s in quarantined:
                    add(f"- `{s.route}` ({s.kind} to {s.target.replace('_', ' ')}): "
                        f"{s.record()}; all time {s.landed} landed, {s.elsewhere} "
                        f"elsewhere, {s.unknown} unknown"
                        + (f", {s.missed} cannon miss(es)" if s.missed else ""))
            else:
                add("- no route is quarantined")
            add("")
            add(f"| route | last {SKILL_WINDOW} | all time: landed / elsewhere / "
                f"unknown | a landed run takes (median s) |")
            add("| --- | --- | --- | --- |")
            for r in skill_book.table():
                good, bad = r["window"]
                add(f"| `{r['route']}` | {good} of {good + bad}"
                    + (" **quarantined**" if r["quarantined"] else "")
                    + f" | {r['landed']} / {r['elsewhere']} / {r['unknown']}"
                    + (f" (+{r['missed']} cannon miss)" if r["missed"] else "")
                    + (f" | {r['median_s']:.0f} |" if r["median_s"] else " | — |"))
            add("")
            add(f"*var/skill_stats.json, {skill_book.built or 'folded trip by trip'}; "
                f"scripts/replay_skills.py rebuilds it from var/trips.jsonl and "
                f"prints every route.*")
        except Exception as exc:                  # noqa: BLE001
            add(f"- could not read var/skill_stats.json ({exc})")
        add("")

    notes = ROOT / "var" / "field_notes.json"
    if notes.exists():
        add("## What it learned about the fields")
        try:
            data = json.loads(notes.read_text())
            rows = []
            for name, body in (data.get("fields") or {}).items():
                seconds = float(body.get("seconds", 0) or 0)
                pollen = int(body.get("pollen", 0) or 0)
                if seconds > 0 and pollen > 0:
                    rows.append((pollen / seconds, name, pollen, seconds))
            for rate, name, pollen, seconds in sorted(rows, reverse=True):
                add(f"- **{name.replace('_', ' ')}**: {rate:,.0f} pollen/sec "
                    f"(measured over {seconds:,.0f}s)")
            if not rows:
                add("- nothing measured yet")
        except (OSError, ValueError) as exc:
            add(f"- could not read the field notes ({exc})")
        add("")

    quests = ROOT / "var" / "quests.json"
    if quests.exists():
        add("## Your quests, read off your own screen")
        try:
            data = json.loads(quests.read_text())
            for quest in data.get("quests") or []:
                name = quest.get("name") or "(unnamed)"
                giver = quest.get("giver")
                add(f"- **{name}**" + (f" — from {giver}" if giver else ""))
                for need in quest.get("requirements") or []:
                    add(f"  - {need}")
            if not data.get("quests"):
                add("- the menu was read but no quest lines came out of it")
            # And what the bot can actually DO about them, said plainly --
            # including the parts it cannot, because a requirement quietly
            # ignored looks exactly like one that is finished.
            try:
                import sys as _sys
                _sys.path.insert(0, str(ROOT / "src"))
                from hivemind.brain.questneeds import load as load_needs
                needs = load_needs(quests)
                add("")
                add(f"**What it can act on:** {needs.describe()}")
                if needs.unread:
                    add("")
                    add("Lines it did not understand (so it did nothing "
                        "about them):")
                    for line in needs.unread:
                        add(f"  - `{line}`")
            except Exception as exc:
                add(f"- could not work out what to do about them ({exc})")
        except (OSError, ValueError) as exc:
            add(f"- could not read them back ({exc})")
        add("")

    # WHAT THE SUBSYSTEMS BUILT ON 2026-09-22 DID, from their own log lines.
    # Each of these was built while the owner played and first runs live
    # after this report was written; the lines below are what they say.
    recent = [p for p in sorted(NIGHT.glob("run-*.log"))
              if time.time() - p.stat().st_mtime < 24 * 3600]
    if recent:
        text = "\n".join(p.read_text(errors="replace") for p in recent[-60:])
        # NOT `lines`: that is the report itself (`add` appends to it), and
        # the first version of this block shadowed it with the run logs and
        # wrote a 2.3 MB log where the morning report should have been.
        log_lines = text.splitlines()
        flights = [ln for ln in log_lines if "via_red_cannon" in ln and ("to " in ln or "natro_out" in ln)]
        cannon_ok = sum(1 for ln in log_lines if "at the red cannon after" in ln)
        cannon_lost = sum(1 for ln in log_lines if "never stood at the red cannon" in ln)
        # THE HOLD'S LENGTH IS THE MEASUREMENT (DESIGN 8dl): seconds of right
        # from the hop's landing to the cannon's prompt, one per approach.
        cannon_holds = sorted(float(m.group(1)) for ln in log_lines for m in re.finditer(
            r"at the red cannon after 1 hop and ([\d.]+)s holding right", ln))
        landed = sum(1 for ln in log_lines if "on our own pad after" in ln)
        blocked = sum(1 for ln in log_lines if "blocked walking at the hive" in ln)
        row = sum(1 for ln in log_lines if "this is the row" in ln or "end of the hive row" in ln)
        haste = [ln.split("buff bar: ", 1)[1] for ln in log_lines if "buff bar: " in ln]
        school = [ln.split("school: ", 1)[1] for ln in log_lines if "school: " in ln and " — " in ln]
        taught = {"collected": 0, "nothing": 0, "unknown": 0}
        for ln in school:
            for key in taught:
                if f"— {key}:" in ln:
                    taught[key] += 1
        add("## New tonight, as it happened")
        add(f"- **Cannon:** {cannon_ok} approach(es) reached the red cannon's prompt, "
            f"{cannon_lost} gave up; {len(flights)} flight route(s) started"
            + (f"; held right {cannon_holds[0]:.2f}-{cannon_holds[-1]:.2f}s from the hop "
               f"to the prompt, median {cannon_holds[len(cannon_holds) // 2]:.2f}s "
               f"over {len(cannon_holds)}" if cannon_holds else "") + ".")
        add(f"- **Walk home by sight:** landed on our own pad {landed} time(s); found the row "
            f"{row} time(s); gave up as blocked {blocked} time(s).")
        add(f"- **Haste read off the buff bar:** {len(haste)} change(s) narrated"
            + (f", last: {haste[-1]}" if haste else "") + ".")
        add(f"- **The school:** {taught['collected']} chase(s) judged a token by the counters, "
            f"{taught['nothing']} judged not a token, {taught['unknown']} unknown.")
        # THE BUG RUNS (DESIGN 8do), from their own record: act/bugrun keeps
        # the last runs in var/bugrun.json with how each one ended.
        try:
            body = json.loads((ROOT / "var" / "bugrun.json").read_text())
            done = [r for r in body.get("runs") or []
                    if time.time() - float(r.get("at", 0) or 0) < 24 * 3600]
        except (OSError, ValueError, TypeError, AttributeError):
            done = []
        if done:
            ends: dict = {}
            for r in done:
                key = f"{r.get('field', '?')} {r.get('left', '?')}"
                ends[key] = ends.get(key, 0) + 1
            fed = sum(len(r.get("feed_kills") or ()) for r in done)
            # A "gone" the feed did not confirm: the bars left the detector,
            # which on 233202's frames happened with both scorpions alive.
            unconfirmed = sum(1 for r in done if r.get("gone_unconfirmed"))
            secs = sorted(float(r.get("seconds", 0) or 0) for r in done)
            cost = sum(float(r.get("honey_cost") or 0) for r in done)
            add(f"- **Bug runs:** {len(done)} in the last day, median "
                f"{secs[len(secs) // 2]:.0f}s; " + ", ".join(
                    f"{k} x{n}" for k, n in sorted(ends.items()))
                + f"; {fed} kill(s) named by the reward feed during them"
                + (f"; {unconfirmed} gone with no feed line by the end of the "
                   f"loot walk" if unconfirmed else "")
                + (f"; about {cost:,.0f} honey of gathering spent" if cost else "")
                + ". (killed = the feed named every mob there; gone = the bars "
                  "left the detector, a kill only where the feed named it; "
                  "cap = the bar never went; not_found = no bar and no hit; "
                  "health = left at the retreat line; late = the run's time "
                  "was up before it stood.)")
        add("")

    ledger = NIGHT / "attempts.log"
    if ledger.exists():
        tail = ledger.read_text(errors="replace").splitlines()[-6:]
        add("## The watchdog's last few decisions")
        add("```")
        lines.extend(tail)
        add("```")
        add("")

    changes = NIGHT / "changes.md"
    if changes.exists():
        add("## What I changed while you slept")
        add(changes.read_text().strip())
        add("")

    out = "\n".join(lines)
    print(out)
    if args.write:
        REPORT.write_text(out)
        print(f"\n(written to {REPORT})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
