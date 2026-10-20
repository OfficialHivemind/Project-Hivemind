"""ROADMAP M10: server hopping for the Vicious Bee -- the decision, the budgets,
the return to the private server, the one-shot start order, and the settings."""
from __future__ import annotations

import re
from pathlib import Path

import hivemind
from hivemind.act import hive
from hivemind.brain import hop
from hivemind.world.settings import NOT_WIRED, SECTIONS

ROOT = Path(hivemind.__file__).resolve().parents[2]
NOW = 1_792_400_000.0
B = hop.Budget(per_night=2, minutes=6, return_private=True)


def go(**kw):
    args = dict(hop_mode=hop.VICIOUS, wanted=2, goal_wants=False, hunt="absent", night=True,
                handin=False, memory_ok=True, memory_note="ok", hops=0, budget=B)
    args.update(kw)
    return hop.should_hop(**args)


def test_it_ships_look_only_and_off():
    assert hop.HOP_LIVE is False
    entries = {e[0]: e for _, es in SECTIONS for e in es}
    assert entries["server.hop"][3] == hop.OFF
    assert entries["server.hop"][5] == hop.CHOICES
    assert entries["server.hop_return"][3] is True


def test_hops_only_on_purpose():
    assert go()[0]
    assert go(goal_wants=True, wanted=0)[0]
    for kw, said in [({"hop_mode": hop.OFF}, "off"),
                     ({"wanted": 0}, "wants"),
                     ({"hunt": "killed"}, "killed"),
                     ({"hunt": ""}, "not at all"),
                     ({"night": False}, "not night"),
                     ({"handin": True}, "hand-in"),
                     ({"memory_ok": False, "memory_note": "3 GB free"}, "3 GB free"),
                     ({"hops": 2}, "2 of 2")]:
        ok, why = go(**kw)
        assert not ok and said in why, (kw, why)


def test_the_night_budget_counts_and_turns_at_noon():
    s = hop.order({}, NOW, "public", hours_in_server=3.2)
    assert hop.hops_tonight(s, NOW) == 1
    s = hop.order({**s, "out_since": NOW}, NOW + 60, "public")
    assert hop.hops_tonight(s, NOW + 60) == 2
    assert s["streak_resets"] == 1                 # only leaving PRIVATE costs the streak
    assert hop.hops_tonight(s, NOW + 86400) == 0   # the next night


def test_streak_cost_is_counted_honestly():
    assert hop.streak_cost(0.2)[0] == 0            # nothing built yet
    lost, said = hop.streak_cost(3.5)              # streak 3: 4,5,5,5,5 vs 1,2,3,4,5
    assert lost == 24 - 15 and "estimate" in said and "back to 1" in said
    assert hop.streak_cost(9)[0] == 25 - 15


def test_the_start_order_is_one_shot_and_fresh():
    s = hop.order({}, NOW, "public")
    public, after = hop.start_kind(s, NOW + 30, hop_mode=hop.VICIOUS, live=True)
    assert public and hop.in_public(after) and "next" not in after
    # taken once: the next start (a crash, a deploy) goes home
    again, home = hop.start_kind(after, NOW + 90, hop_mode=hop.VICIOUS, live=True)
    assert not again and not hop.in_public(home)
    # stale, switched off, or look-only: home
    assert not hop.start_kind(s, NOW + hop.NEXT_FRESH_S + 1, hop_mode=hop.VICIOUS, live=True)[0]
    assert not hop.start_kind(s, NOW, hop_mode=hop.OFF, live=True)[0]
    assert not hop.start_kind(s, NOW, hop_mode=hop.VICIOUS)[0]
    # a kept game (a deploy) stays where it was
    kept = hop.start_kind(after, NOW + 90, hop_mode=hop.VICIOUS, live=True, kept=True)[1]
    assert hop.in_public(kept) and not hop.in_public(hop.went_home(kept))


def test_in_a_public_server_it_returns_hops_or_stays():
    s = {"out_since": NOW, "server_since": NOW, "night": hop.night_key(NOW), "hops": 1}
    step = lambda t, **kw: hop.in_public_step(s, NOW + t, **{  # noqa: E731
        "budget": B, "hunt": "", "wanted": 1, "goal_wants": False, **kw})[0]
    assert step(60) == "stay"
    assert step(60, hunt="absent") == "hop"
    assert step(7 * 60) == "hop"                           # no night here in 6 min
    assert step(60, hunt="killed") == "return"
    assert step(60, hunt="died") == "return"               # a loss is not hopped on
    assert step(60, wanted=0) == "return"
    assert step(hop.RETURN_BEFORE_S) == "return"           # before the Wealth Clock's hour
    used = {**s, "hops": 2}
    assert hop.in_public_step(used, NOW + 60, budget=B, hunt="absent", wanted=1,
                              goal_wants=False)[0] == "return"
    stay = hop.Budget(2, 6, return_private=False)
    assert hop.in_public_step(used, NOW + 60, budget=stay, hunt="absent", wanted=1,
                              goal_wants=False)[0] == "stay"


def test_a_new_public_server_hunts_at_once_and_repeats_are_seen():
    s = {"out_since": NOW, "server_since": NOW + 100}
    assert hop.fresh_server(s, NOW) and not hop.fresh_server(s, NOW + 200)
    assert not hop.fresh_server({}, NOW)
    s, again = hop.arrived({}, "abc123")
    assert not again
    assert hop.arrived(s, "abc123")[1]
    assert hop.last_hunt([{"at": NOW - 5, "result": "absent"}], NOW) == ""
    assert hop.last_hunt([{"at": NOW + 5, "result": "absent"}], NOW) == "absent"


def test_never_claims_another_players_hive():
    """A public server has other players' hives: the claim key is pressed only
    on the game's own 'Claim Hive' prompt, which it shows on an unclaimed hive
    alone; anything unread is never acted on."""
    assert hive._state_of("Claim Hive") is hive.SlotState.EMPTY
    assert hive._state_of("") is hive.SlotState.UNKNOWN
    assert hive._state_of("ExampleHost123's hive") is hive.SlotState.UNKNOWN
    assert hive._state_of("Make Honey") is hive.SlotState.MINE


class _S:
    def __init__(self, **v):
        self.v = v

    def int(self, k):
        return self.v[k]

    def bool(self, k):
        return self.v[k]

    def get(self, k, d=None):
        return self.v.get(k, d)


def test_budget_and_mode_from_settings():
    b = hop.Budget.from_settings(_S(**{"server.hop_per_night": 5, "server.hop_minutes": 0,
                                       "server.hop_return": False}))
    assert (b.per_night, b.minutes, b.return_private) == (5, 1, False)
    assert hop.Budget.from_settings(_S()) == hop.Budget()
    assert hop.mode(_S(**{"server.hop": "vicious hunt at night"})) == hop.VICIOUS
    assert hop.mode(_S(**{"server.hop": "nonsense"})) == hop.OFF


def test_wired_into_the_run_and_the_window():
    farm = (ROOT / "scripts" / "run_farm.py").read_text()
    assert "hop_after_hunt(hunt_began)" in farm
    assert re.search(r"bootstrap\.start\(private=not public_hop", farm)
    shell = (ROOT / "src" / "hivemind" / "gui" / "shell.py").read_text()
    for key in ("server.hop", "server.hop_per_night", "server.hop_minutes", "server.hop_return"):
        assert f'("{key}"' in shell and key not in NOT_WIRED
