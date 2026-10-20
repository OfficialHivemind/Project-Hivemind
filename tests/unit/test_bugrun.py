

def test_a_drop_line_is_read_as_tesseract_writes_it():
    """MEASURED 2026-10-03: "+580 Honey (from Rhino Beetle)" reads "1580 Honëx
    (from Rhino Beetle)" -- the plus as a 1 -- and "from" can read "rom"."""
    from hivemind.act.bugrun import DROPPED
    def got(t):
        return [m.groups() for m in DROPPED.finditer(t)]
    assert got("+580 Honey (from Rhino Beetle)") == [("580", "Honey", "Rhino Beetle")]
    assert got("| 1580 Honëx (from Rhino Beetle)") == [("580", "Honëx", "Rhino Beetle")]
    assert got("11 Oil (from Werewolf)") == [("1", "Oil", "Werewolf")]
    assert got("+3 Pineapples (rom Spider)") == [("3", "Pineapples", "Spider")]
    assert got("Defeated Werewolf! (+25 Battle Points)") == []


def test_a_sprouts_drops_are_counted_like_a_mobs():
    # "+1 Royal Jelly (from Sprout)" -- a Magic Bean's sprout, 2026-10-03 06:57
    from hivemind.act import bugrun

    class Book:
        def slug_for(self, name):
            return "mantis" if name == "mantis" else None
    drops = bugrun.FeedDrops(Book(), clock=lambda: 0.0, extras={"sprout": "sprout"})
    got = drops.seen("+1 Royal Jelly (from Sprout)\n+4 Treats (from Sprout)\n+850 Bond (from Mantis)")
    assert ("sprout", "royal jelly", 1) in got and ("sprout", "treats", 4) in got
    assert ("mantis", "bond", 850) in got
    assert bugrun.FeedDrops(Book(), clock=lambda: 0.0).seen("+1 Royal Jelly (from Sprout)") == []


def test_what_kills_paid_is_measured_from_the_two_logs(tmp_path):
    # the owner's list, item 11: drop rates from its own kill log
    import json
    from hivemind.act import bugrun
    kills, drops = tmp_path / "k.jsonl", tmp_path / "d.jsonl"
    kills.write_text("".join(json.dumps(r) + "\n" for r in [
        {"at": 100.0, "mob": "mantis"}, {"at": 200.0, "mob": "mantis"},
        {"at": 300.0, "mob": "ladybug"}]))
    drops.write_text("".join(json.dumps(r) + "\n" for r in [
        {"at": 103.0, "mob": "mantis", "item": "honey", "amount": 400},
        {"at": 98.0, "mob": "mantis", "item": "honex", "amount": 100},   # read a look early, misread
        {"at": 203.0, "mob": "mantis", "item": "bond", "amount": 850},   # not honey
        {"at": 260.0, "mob": "mantis", "item": "honey", "amount": 999},  # past both kills' windows
        {"at": 301.0, "mob": "ladybug", "item": "honey", "amount": 50},
        {"at": 204.0, "mob": "mantis", "item": "tickets", "amount": 410},  # one ticket KILL
        {"at": 205.0, "mob": "mantis", "item": "ticket", "amount": 1}]))
    got = bugrun.measured_loot(kills, drops)
    assert got["mantis"] == (250.0, 2, 1) and got["ladybug"] == (50.0, 1, 0)
    assert bugrun.measured_loot(tmp_path / "none", drops) == {}


def test_a_mob_killed_often_enough_is_priced_by_what_its_kills_paid(tmp_path):
    from pathlib import Path

    from hivemind.act import bugrun

    class On:
        def bool(self, key):
            return True

        def int(self, key):
            return 0
    root = Path(__file__).resolve().parents[2]
    book = bugrun.load(root / "data/knowledge/mobs.yaml")
    log = bugrun.KillLog(tmp_path / "bugrun.json")
    where = next(f for f in book.profiles if "mantis" in book.mobs_in(f))
    wiki, _ = bugrun.choose(book, log, On(), now=1e10, usable=lambda f: (f == where, "test"))
    from hivemind.brain import mobtable
    n = 10 * mobtable.PRIOR_KILLS
    paid, _ = bugrun.choose(book, log, On(), now=1e10, usable=lambda f: (f == where, "test"),
                            measured={"mantis": (12_345.0, n, 0)})
    assert wiki.field == paid.field == where
    assert f"(measured, {n} kills)" in paid.why and "(wiki)" in wiki.why
    assert paid.loot < wiki.loot          # no tickets in 500 kills: the wiki's 20% is gone
    # a few kills only nudge the wiki's figure: the prior holds
    few, _ = bugrun.choose(book, log, On(), now=1e10, usable=lambda f: (f == where, "test"),
                           measured={"mantis": (12_345.0, 1, 0)})
    assert few.loot != wiki.loot and abs(few.loot - wiki.loot) < 0.3 * wiki.loot


def test_a_field_whose_runs_found_nothing_is_priced_and_ranked_by_what_they_found(tmp_path):
    # ROADMAP M1, MEASURED 2026-10-26: the Pumpkin Patch's Werewolf, 1 kill in
    # 6 runs (var/bugrun.json); every other field near the wiki's count
    from pathlib import Path

    from hivemind.act import bugrun

    class On:
        def bool(self, key):
            return True

        def int(self, key):
            return 0
    root = Path(__file__).resolve().parents[2]
    book = bugrun.load(root / "data/knowledge/mobs.yaml")
    log = bugrun.KillLog(tmp_path / "bugrun.json")
    only = lambda f: (f == "pumpkin", "test")                       # noqa: E731
    fresh, _ = bugrun.choose(book, log, On(), now=1e10, usable=only)
    assert fresh.field == "pumpkin" and "runs here" not in fresh.why
    for found in (["werewolf"], [], [], [], [], []):
        log.note_run({"field": "pumpkin", "mobs": ["werewolf"], "feed_kills": found})
    log.note_run({"field": "pumpkin", "mobs": ["werewolf"], "left": "walk_out_failed"})
    assert bugrun.run_yield(log, "pumpkin", ["werewolf"], 1) == (4 / 9, 6, 1)
    seen, _ = bugrun.choose(book, log, On(), now=1e10, usable=only)
    assert abs(seen.loot - fresh.loot * 4 / 9) < 1e-6
    assert "runs here found 1 kill(s) in 6, so 44% of the wiki's count" in seen.why
    # never over the wiki's count, and no record is the wiki's count
    log.note_run({"field": "rose", "mobs": ["scorpion"], "feed_kills": ["scorpion"] * 9})
    assert bugrun.run_yield(log, "rose", ["scorpion"], 2)[0] == 1.0
    assert bugrun.run_yield(log, "spider", ["spider"], 1) == (1.0, 0, 0)
    # A QUEST'S FIELDS RANK BY THE QUEST'S KILLS A SECOND: two fields' quest
    # mobs, the same planned run; the one whose runs find them goes first
    two = lambda f: (f in ("pumpkin", "rose"), "test")              # noqa: E731
    pick, _ = bugrun.choose(book, log, On(), now=1e10, usable=two, plan=lambda f: 60.0,
                            quest={"werewolf": 2, "scorpion": 2})
    assert pick.field == "rose"
