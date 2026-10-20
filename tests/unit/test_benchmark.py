"""scripts/benchmark.py on synthetic trips: a known effect is found, no
effect raises no alarm (nor honey that comes in hour-long lumps), a spend is
not counted as a loss, the card finds a deploy from its log + backup, and the
time accounting books every second of a run to one slice."""
import importlib.util
import json
import random
import time
from pathlib import Path

import hivemind

# the tree under test, found through the package (the deploy gate runs a copy
# of this file from the live tree, whose scripts/ may be older)
ROOT = Path(hivemind.__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("benchmark", ROOT / "scripts" / "benchmark.py")
bm = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bm)

T0 = 1_791_000_000.0


def trips(n, gain, land, start=T0, rng=None, bal=1_000_000_000, spend_at=None, hourly=0.0,
          sd=0.3):
    """n trips 600 s apart; honey rises ~`gain` a trip; a walk home lands with
    P `land`. `hourly`: each clock hour's trips share one lognormal level of
    that sigma (the hour's buffs, boosts and payouts)."""
    rng = rng or random.Random(0)
    out, level = [], {}
    for i in range(n):
        at = start + 600 * i
        if i == spend_at:
            bal -= 300_000_000                       # a purchase between trips
        read = bal
        m = level.setdefault(int(at // 3600), rng.lognormvariate(0, hourly)) if hourly else 1.0
        g = max(0, int(rng.gauss(gain, gain * sd) * m))
        bal += g
        out.append({"at": at, "attempt": 1, "decision_id": f"1-{int((at - 500) * 1000)}",
                    "action": "gather", "aimed_at": "pine_tree", "credited": "pine_tree",
                    "converted": True, "deaths": 0, "seconds": 500, "gather_seconds": 300,
                    "pollen": g // 2, "context": {"honey": read},
                    "convert_note": f"converted — honey settled at {bal:,} (+{g:,})",
                    "routes": [{"kind": "home", "outcome":
                                "landed" if rng.random() < land else "elsewhere"}]})
    return out, bal


def test_known_effect_is_detected():
    rng = random.Random(1)
    a, bal = trips(60, 10_000_000, 0.95, rng=rng)
    b, _ = trips(60, 14_000_000, 0.55, start=T0 + 36_000, rng=rng, bal=bal)
    us = bm.units(a + b)
    cmp = bm.compare(us[:60], us[60:])
    assert cmp["honey_per_hour"]["verdict"] == "better"
    assert 55e6 < cmp["honey_per_hour"]["before"] < 66e6       # 10M a 600 s trip = 60M/h
    assert cmp["landing_pct"]["verdict"] == "worse"
    assert bm.regression(cmp) == ["landing_pct"]


def test_no_effect_no_false_alarm():
    alarms = 0
    for seed in range(20):
        rng = random.Random(seed)
        a, bal = trips(60, 10_000_000, 0.85, rng=rng)
        b, _ = trips(60, 10_000_000, 0.85, start=T0 + 40_000, rng=rng, bal=bal)
        us = bm.units(a + b)
        alarms += bool(bm.regression(bm.compare(us[:60], us[60:], seed=seed)))
    assert alarms <= 1, alarms


def test_lumpy_but_flat_honey_raises_no_alarm():
    """The same rate on both sides, but it moves in hour-long lumps. Single
    trips resampled as independent called this worse on 4 seeds of 40 (2 of
    these 20); whole hours resampled, on none."""
    alarms = 0
    for seed in range(20):
        rng = random.Random(seed)
        a, bal = trips(72, 10_000_000, 0.85, rng=rng, hourly=1.2)
        b, _ = trips(72, 10_000_000, 0.85, start=T0 + 72 * 600 + 3600, rng=rng, bal=bal,
                     hourly=1.2)
        us = bm.units(a + b)
        alarms += bool(bm.regression(bm.compare(us[:72], us[72:], seed=seed, boot=500)))
    assert alarms <= 1, alarms


def test_too_few_hours_is_no_verdict():
    a, bal = trips(30, 10_000_000, 0.9, start=T0)               # 30 trips in 5 hours
    b, _ = trips(30, 10_000_000, 0.9, start=T0 + 30_000, bal=bal)
    us = bm.units(a + b)
    cmp = bm.compare(us[:30], us[30:])
    assert cmp["verdict"] == "too few trips" and cmp["hours_before"] < bm.MIN_BLOCKS


def test_spend_is_left_out_and_few_trips_say_so():
    plain, _ = trips(30, 10_000_000, 1.0)
    spent, _ = trips(30, 10_000_000, 1.0, spend_at=12)
    h0 = bm.summary(bm.units(plain), T0, T0 + 30 * 600)["honey_per_hour"]
    h1 = bm.summary(bm.units(spent), T0, T0 + 30 * 600)["honey_per_hour"]
    assert abs(h1 - h0) / h0 < 0.05
    assert bm.compare(bm.units(plain)[:5], bm.units(plain)[5:])["verdict"] == "too few trips"


def test_card_finds_the_deploy_and_flags_it(tmp_path):
    var, work = tmp_path / "var", tmp_path / "work"
    (var / "night").mkdir(parents=True)
    (work / "backups").mkdir(parents=True)
    rng = random.Random(3)
    a, bal = trips(60, 10_000_000, 0.95, rng=rng)
    b, _ = trips(60, 10_000_000, 0.40, start=T0 + 36_000 + 60, rng=rng, bal=bal)
    (var / "trips.jsonl").write_text("".join(json.dumps(r) + "\n" for r in a + b))
    t = T0 + 36_000
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(t))
    (work / "backups" / f"live-{stamp}.tgz").write_bytes(b"")
    (var / "night" / "deploy-1200.log").write_text(
        f"installing integ (abc1234) over 0000000\nbackup: {work}/backups/live-{stamp}.tgz\n")
    card = bm.build(var, T0 + 36_000 + 60 * 600, hours=72, work=work, boot=500)
    assert [d["sha"] for d in card["deploys"]] == ["abc1234"]
    assert card["regressions"] and card["regressions"][0]["worse_on"] == ["landing_pct"]
    assert "REGRESSION: abc1234" in bm.telegram_text(card)
    assert "## Deploys" in bm.markdown(card)
    split = bm.build(var, T0 + 36_000 + 60 * 600, work=work, boot=500, before="abc1234")
    assert split["comparison"]["result"]["landing_pct"]["verdict"] == "worse"


def _one_deploy(tmp_path, rows, t):
    var, work = tmp_path / "var", tmp_path / "work"
    (var / "night").mkdir(parents=True)
    (work / "backups").mkdir(parents=True)
    (var / "trips.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(t))
    (work / "backups" / f"live-{stamp}.tgz").write_bytes(b"")
    (var / "night" / "deploy-1200.log").write_text(
        f"installing integ (abc1234) over 0000000\nbackup: {work}/backups/live-{stamp}.tgz\n")
    return var, work


def test_drift_is_the_windows_own_swing_not_the_deploy(tmp_path):
    """ROADMAP P18: honey/h slides 1.5% an hour for 4 days (the 19-22 Oct
    shape: quest sets and boosts come and go over hours) with a deploy that
    changes nothing in the middle. The plain split calls it worse at p < 0.01;
    the same split at every no-deploy hour around it says as much, so no alarm."""
    rng, rows, bal = random.Random(7), [], 1_000_000_000
    for i in range(576):                                         # 96 h of 600 s trips
        r, bal = trips(1, 30_000_000 * 0.985 ** (i / 6), 0.9, start=T0 + 600 * i, rng=rng,
                       bal=bal, sd=0.1)
        rows += r
    t = T0 + 48 * 3600 - 300
    var, work = _one_deploy(tmp_path, rows, t)
    card = bm.build(var, T0 + 96 * 3600, hours=72, work=work, boot=300)
    (d,) = card["deploys"]
    assert bm.regression(d["local"]) == ["honey_per_hour"]       # the uncalibrated alarm
    assert d["alarm"]["calibrated"]["honey_per_hour"]["verdict"] == bm.SWINGS
    assert d["alarm"]["calibrated"]["honey_per_hour"]["splits"] >= bm.PLACEBO_MIN
    assert card["regressions"] == [] and "REGRESSION" not in bm.telegram_text(card)
    assert "abc1234: honey/h within the window's own swings" in bm.telegram_text(card)


def test_a_step_at_the_deploy_still_alarms(tmp_path):
    """Flat for 2 days, then 40% less honey from the deploy on: no
    no-deploy split around it moves as far, so the alarm stands."""
    rng = random.Random(8)
    a, bal = trips(288, 10_000_000, 0.9, rng=rng)
    b, _ = trips(288, 6_000_000, 0.9, start=T0 + 288 * 600, rng=rng, bal=bal)
    var, work = _one_deploy(tmp_path, a + b, T0 + 288 * 600 - 300)
    card = bm.build(var, T0 + 96 * 3600, hours=72, work=work, boot=300)
    cal = card["deploys"][0]["alarm"]["calibrated"]["honey_per_hour"]
    assert cal["verdict"] == "worse" and cal["as_extreme"] == 0, cal
    assert card["regressions"][0]["worse_on"] == ["honey_per_hour"]


def test_a_colour_quests_field_is_quest_forced():
    """decide's colour-quest reason ends "so it goes first (quests.first)",
    not "quests first": 20 Oct's Pumpkin trips over Pine Tree were missed."""
    why = ("the quests still want 28,140,605 white pollen and this is the most white "
           "pollen/s measured (6,710/s: 13,305 x 50% white), so it goes first (quests.first)")
    row = {"chosen": "pumpkin", "candidates": [{"field": "pumpkin", "score": 7968.1, "why": why},
                                                {"field": "pine_tree", "score": 21590.5,
                                                 "why": "measured"}]}
    assert bm._quest_forced(row)
    row["candidates"][1]["score"] = 10.0                         # it was the best anyway
    assert not bm._quest_forced(row)


def test_time_accounting_books_every_second(tmp_path):
    """One 20-minute run and a 1-minute one after a restart: the ledger's
    walks and gather inside the trips, the log's markers around them."""
    var = tmp_path / "var"
    (var / "night").mkdir(parents=True)
    t = time.mktime(time.strptime("2026-10-14 10:00:00", "%Y-%m-%d %H:%M:%S"))
    (var / "night" / "attempts.log").write_text(
        "[overnight] attempt 7 starting 2026-10-14 10:00:00 -> /x/run-7.log\n"
        "[overnight] attempt 7 exited 0 after 1200s\n"
        "[overnight] attempt 8 starting 2026-10-14 10:21:00 -> /x/run-8.log\n"
        "[overnight] attempt 8 exited 0 after 60s\n")
    (var / "night" / "run-7.log").write_text("\n".join([
        "  === bootstrap ===",
        "    10:00:05  in game after 5s",
        "    10:01:00  reading the quest menu — the run is starting",       # quests 40 s
        "    10:01:40  opening the badge menu: clicking (195, 128), the rosette",
        "    10:02:00  badges: the badge menu shows no claim on its first page",  # menus 20 s
        "    10:05:00  goals: nothing to buy",                               # a note: no switch
        "    10:12:00  waiting out Haste (about 9s) before the walk home",   # 10 s, in the trip
        "    10:13:00  convert: pressed E on the pad with 5,000,000/5,000,000 (100%)",
        "    10:13:20  the backpack is empty and we are on our own pad — going to the "
        "wealth clock to use it (every 1h)",                                 # dispensers 70 s
        "  threat eye: not counting mob health bar 76x11 on natro_out_wealth_clock",
        "    10:14:30  respawned onto our own pad after the errand — the pad's own prompt",
        "    10:19:30  could not reach the hive 1 times — asking for a rejoin",
    ]) + "\n")
    route = lambda kind, s: {"kind": kind, "outcome": "landed", "seconds": s}  # noqa: E731
    rows = [{"at": t + 900, "attempt": 7, "seconds": 700, "gather_seconds": 400,
             "routes": [route("out", 50), route("home", 60)]},
            {"at": t + 1150, "attempt": 7, "seconds": 150, "gather_seconds": 100,
             "routes": [route("flight", 20), route("home", 20)]}]
    acc = bm.time_account(var, bm.runs(var, t + 3600), rows, t - 3600, t + 3600)
    got = {k: v["s"] for k, v in acc["slices"].items() if v["s"]}
    assert got == {"gather": 500, "walk out": 70, "walk home": 80, "convert": 20,
                   "quests": 40, "menus & items": 20, "dispensers": 70, "buff waits": 10,
                   "trip overhead": 70, "unknown": 150,
                   "rejoin/startup": 140 + 30 + 60 + 60}, got
    assert acc["running_h"] == round(1320 / 3600, 2) and acc["off_h"] == round(5880 / 3600, 2)
    assert acc["biggest_non_gather"] == "rejoin/startup"
    assert abs(acc["slices"]["gather"]["pct"] - 100 * 500 / 1320) < 0.1
    assert bm.time_line(acc).startswith("time: gather 38%, rejoin/startup 22%")
    assert "| dispensers | errands |" in "\n".join(bm.time_md(acc))


def test_nightly_rewrites_the_card_idempotently(tmp_path, capsys):
    """ROADMAP P20: --nightly rewrites var/benchmark.json/.md in place (no temp
    file left), the same bytes for the same --now, one line printed; it is the
    plain card, so --before/--after are refused."""
    import pytest
    var, work = tmp_path / "var", tmp_path / "work"
    var.mkdir()
    rows, _ = trips(60, 10_000_000, 0.9, rng=random.Random(5))
    (var / "trips.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    (var / "benchmark.json").write_text('{"generated_at": 1, "baseline": {}}')  # a stale card
    now = str(T0 + 60 * 600)
    args = ["--nightly", "--var", str(var), "--work", str(work), "--now", now]
    assert bm.main(args) == 0
    first = {p.name: p.read_bytes() for p in var.iterdir()}
    assert sorted(first) == ["benchmark.json", "benchmark.md", "trips.jsonl"]
    card = json.loads(first["benchmark.json"])
    assert card["generated_at"] == float(now) and card["baseline"]["trips"] == 60
    assert bm.main(args) == 0
    assert {p.name: p.read_bytes() for p in var.iterdir()} == first
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 2 and out[0].startswith("benchmark --nightly: rewrote")
    assert "Benchmark 72h: honey" in out[0]
    with pytest.raises(SystemExit):
        bm.main(args + ["--before", "abc1234"])


def test_benchmark_never_touches_the_game():
    """It reads files; nothing that moves, clicks or captures is imported."""
    src = (ROOT / "scripts" / "benchmark.py").read_text(encoding="utf-8")
    for part in ("hivemind.platform", "hivemind.act", "hivemind.vision", "pyautogui"):
        assert part not in src, part
