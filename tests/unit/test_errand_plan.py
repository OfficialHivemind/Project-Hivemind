"""B5: brain/value.plan -- the profit-aware errand order (ROADMAP B5 METHOD)."""
from hivemind.brain.value import Scored, plan

RATE = 1000.0      # honey a second of gathering


def row(name, v, seconds=60.0, p=1.0, ready_in=0.0):
    return Scored(name, None, seconds, p, v, ready_in)


def test_best_order_and_only_the_first():
    # B is far better a second; both pay, so the plan holds both, B first
    first, seq, skipped = plan([row("a", 200_000, 100), row("b", 300_000, 30)], RATE)
    assert first.name == "b" and [r.name for r in seq][0] == "b" and not skipped


def test_negative_profit_skipped_but_keep_is_not():
    rows = [row("coconut", 20_000, 60), row("clock", 30_000, 60), row("ok", 500_000, 60)]
    first, seq, skipped = plan(rows, RATE, keep=("clock",))
    assert [r.name for r in skipped] == ["coconut"]
    assert first.name == "ok" and "coconut" not in [r.name for r in seq]
    # nothing priced is worth it: the unpriced keep today's order
    first, _seq, skipped = plan([row("coconut", 20_000), row("ant_pass", None)], RATE)
    assert first.name == "ant_pass" and skipped[0].name == "coconut"


def test_nearly_ready_can_win():
    # a big errand due in 60 s, waited for, beats a long small ready one; one
    # due in 10 min is not considered
    rows = [row("small", 160_000, 150), row("big", 2_000_000, 60, ready_in=60),
            row("later", 9_000_000, 60, ready_in=600)]
    first, seq, _ = plan(rows, RATE)
    assert first.name == "big" and "later" not in [r.name for r in seq]
    # but a short ready errand that fills the wait goes first
    first, seq, _ = plan([row("quick", 80_000, 60), rows[1]], RATE)
    assert [r.name for r in seq] == ["quick", "big"]


def test_time_window_respected():
    # an appointment 90-200 s from now: the 120 s errand would run into it
    rows = [row("long", 900_000, 120), row("short", 300_000, 40)]
    first, seq, _ = plan(rows, RATE, windows=[(90.0, 200.0)])
    assert first.name == "short" and [r.name for r in seq] == ["short"]
    assert plan([row("long", 900_000, 120)], RATE, windows=[(0.0, 60.0)])[0] is None


def test_walk_home_anyway_makes_near_errands_cheaper():
    near = row("near", 50_000, 45)          # 50k against 45k of gathering: +5k
    assert plan([near], RATE)[0].name == "near"
    near = row("near", 40_000, 45)
    assert plan([near], RATE)[0] is None
    assert plan([near], RATE, home_saved_s=20.0)[0].name == "near"


def test_due_in_is_the_true_wait():
    # MEASURED 2026-10-22 16:52:25: the clock read "due in 37s" was 337 s away
    # (the 300 s early window had been taken off); due_in is the real wait
    from hivemind.brain.value import due_in
    now = 1000.0
    assert due_in(now + 337, now - 5, now - 3000, 1.0, now) == 337
    assert due_in(now - 10, now - 5, now - 3000, 1.0, now) == 0
    # no timer read since the last use: the wiki's period
    assert due_in(0.0, 0.0, now - 600, 1.0, now) == 3000
    assert due_in(0.0, 0.0, now - 600, 0.0, now) == float("inf")
    assert due_in(0.0, 0.0, 0.0, 0.0, now) == 0
    # a timer read BEFORE the last use is stale: the wiki's period decides
    last = now - 600
    assert due_in(now + 337, last - 1, last, 1.0, now) == 3600 - (now - last)


def test_a_clock_337s_away_is_not_planned_now():
    # the live change of value.due_in: the planner's ready_in is the true
    # 337 s (not 37 s), past NEARLY_READY_S, so the plan does not pick it
    assert plan([row("wealth_clock", 2_000_000, 60, ready_in=337)], RATE)[0] is None


def test_new_errand_rules_ship_look_only():
    # AGENTS.md rule 4: the priced wait, the both-arms skip and the balance rho
    # are logged ("errands would: ...") until their logs are checked
    from pathlib import Path
    import hivemind
    farm = (Path(hivemind.__file__).resolve().parents[2] / "scripts" / "run_farm.py"
            ).read_text(encoding="utf-8")
    for flag in ("ERRAND_WAIT_PRICED_LIVE", "ERRAND_SKIP_NEGATIVE_LIVE", "RHO_BALANCE_LIVE"):
        assert f"\n{flag} = False\n" in farm
    assert "errands would: skip the" in farm and "errands would: walk away" in farm
    assert "within + _early(name)" in farm       # the early window is _next_usable's
    assert 'ERRAND_CHOICES_FILE = ROOT / "var" / "errand_choices.jsonl"' in farm
    # the choice log carries what picked it and each candidate's Beta counts
    assert '"picker": picker' in farm and '"landed": _beta(r.name)[0]' in farm
    # the priced wait counts the walk back, and its maths cannot stop an errand
    assert "_delay / _rho + _again" in farm and "_wait_cap = _delay = None" in farm
