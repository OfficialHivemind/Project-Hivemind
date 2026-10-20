"""An errand may only press a key when the game's own panel agrees.

`e` converts pollen, opens shops and starts NPC conversations. This project has
already opened a Polar Bear quest dialogue by pressing it where it believed the
hive was, so every test here is about the gap between "the route ran" and "the
right thing is in front of us".
"""
from __future__ import annotations

from hivemind.act.errands import Errand, run_errand

CLOCK = Errand(name="wealth_clock", expect=("wealth clock", "use clock"),
               gives="honey")


class Presser:
    def __init__(self):
        self.pressed = []

    def tap(self, key):
        self.pressed.append(key)


def frames():
    return object()


def says(*texts):
    seen = list(texts)

    def read(frame):
        return seen.pop(0) if len(seen) > 1 else seen[0]
    return read


def test_it_presses_nothing_when_the_route_failed():
    vin = Presser()
    out = run_errand(CLOCK, walk=lambda: False, frames=frames,
                     read_text=says("Use Wealth Clock"), vin=vin, press=True,
                     sleep=lambda s: None)
    assert out.used is False
    assert vin.pressed == []


def test_it_presses_nothing_when_the_panel_says_something_else():
    vin = Presser()
    out = run_errand(CLOCK, walk=lambda: True, frames=frames,
                     read_text=says("Talk to Polar Bear"), vin=vin, press=True,
                     sleep=lambda s: None)
    assert out.used is False
    assert vin.pressed == []
    assert "does not say this is" in out.reason


def test_it_presses_nothing_when_there_is_no_panel_at_all():
    vin = Presser()
    out = run_errand(CLOCK, walk=lambda: True, frames=frames,
                     read_text=says(""), vin=vin, press=True,
                     sleep=lambda s: None)
    assert out.used is False
    assert vin.pressed == []


def test_it_uses_it_when_the_panel_agrees():
    vin = Presser()
    out = run_errand(CLOCK, walk=lambda: True, frames=frames,
                     read_text=says("Use Wealth Clock", "Collected!"),
                     vin=vin, press=True, sleep=lambda s: None)
    assert out.used is True
    assert vin.pressed == ["e"]


def test_looking_is_the_default_so_an_unknown_place_is_never_pressed():
    vin = Presser()
    out = run_errand(CLOCK, walk=lambda: True, frames=frames,
                     read_text=says("Use Wealth Clock"), vin=vin,
                     sleep=lambda s: None)
    assert out.used is False
    assert vin.pressed == []
    assert "looking only" in out.reason


def test_an_errand_with_nothing_to_match_on_can_never_confirm():
    """A half-filled table must not become a licence to press keys."""
    blank = Errand(name="mystery")
    vin = Presser()
    out = run_errand(blank, walk=lambda: True, frames=frames,
                     read_text=says("anything at all"), vin=vin, press=True,
                     sleep=lambda s: None)
    assert out.used is False
    assert vin.pressed == []


def test_it_records_what_it_saw_so_expect_can_be_filled_in_honestly():
    out = run_errand(Errand(name="mystery"), walk=lambda: True, frames=frames,
                     read_text=says("Use Blueberry Dispenser"),
                     sleep=lambda s: None)
    assert "Blueberry Dispenser" in out.saw


def test_a_route_that_raises_is_not_an_arrival():
    def boom():
        raise RuntimeError("capture failed")

    out = run_errand(CLOCK, walk=boom, frames=frames,
                     read_text=says("Use Wealth Clock"), sleep=lambda s: None)
    assert out.walked is False
    assert out.used is False


def test_it_says_whether_the_panel_changed_after_pressing():
    out = run_errand(CLOCK, walk=lambda: True, frames=frames,
                     read_text=says("Use Wealth Clock", "Use Wealth Clock"),
                     vin=Presser(), press=True, sleep=lambda s: None)
    assert "read the same after pressing" in out.reason


# ---- turning a read panel into something safe to press at -------------------
# `act/errands` is finished, tested, and has never run, because the one thing
# it needs is the words each panel shows -- that is what stops a key being
# pressed at scenery. The recon now reads them into var/place_panels.json.
# A PANEL READ AT A ROUTE'S END IS AN OBSERVATION, NOT A CONFIRMATION that the
# route reached the place it is named after. MEASURED 2026-09-23 04:10: the
# recon walked `natro_out_honey_dispenser`, four steps off the pad, and the
# panel there said `Open Shop`.

def test_a_panel_that_names_the_place_becomes_its_expect():
    from hivemind.act.errands import expect_from_panel
    assert expect_from_panel("wealth_clock", "Use Wealth Clock") == ("use wealth clock",)
    # MEASURED 2026-09-23 21:06:51: on cooldown the panel carries the timer,
    # and the timer is not part of what to expect next time
    assert expect_from_panel("wealth_clock", "Use the Wealth Clock (57:22)") == ("use the wealth clock",)
    assert expect_from_panel("blender", "Use Blender") == ("use blender",)


def test_a_synonym_counts_as_naming_it():
    from hivemind.act.errands import expect_from_panel
    got = expect_from_panel("blueberry_dispenser", "Collect Blueberries")
    assert got == ("collect blueberries",)


def test_a_panel_that_names_something_else_is_refused():
    from hivemind.act.errands import expect_from_panel
    assert expect_from_panel("blender", "Something Else Entirely") == ()
    assert expect_from_panel("wealth_clock", "") == ()


def test_a_till_is_never_turned_into_an_expect():
    """One keypress from spending the owner's honey, which is the only action
    in this game that cannot be undone."""
    from hivemind.act.errands import expect_from_panel, NEVER_PRESS
    assert expect_from_panel("honey_dispenser", "Open Shop") == ()
    for bad in NEVER_PRESS:
        assert expect_from_panel("wealth_clock", f"Wealth Clock {bad}") == (), bad


def test_a_refused_panel_leaves_an_errand_unconfirmable():
    """() must mean the engine presses nothing, not that it presses at
    anything."""
    from hivemind.act.errands import Errand, expect_from_panel
    errand = Errand(name="honey_dispenser",
                    expect=expect_from_panel("honey_dispenser", "Open Shop"))
    assert not errand.matches("Open Shop")
    assert not errand.matches("anything at all")


def test_a_confirmed_panel_matches_itself_and_little_else():
    from hivemind.act.errands import Errand, expect_from_panel
    errand = Errand(name="wealth_clock",
                    expect=expect_from_panel("wealth_clock", "Use Wealth Clock"))
    assert errand.matches("Use Wealth Clock")
    assert errand.matches("[E] Use Wealth Clock")
    assert not errand.matches("Open Shop")
    assert not errand.matches("Make Honey")


# ---- the owner's economy switches, wired at last ---------------------------
# They sat in NOT_WIRED under "SHOW IT ONCE: the recorded route lands near the
# clock but not close enough for a prompt" -- a verdict on BeeTuxMacro's
# routes, not on the places. With Natro's routes, the panel recon and
# `expect_from_panel`, they are real controls.

class _Switches:
    def __init__(self, off=()):
        self.off = set(off)

    def bool(self, key):
        return key not in self.off


def test_a_place_the_owner_switched_off_is_skipped():
    from hivemind.act.errands import wanted_place
    off = _Switches(off={"economy.wealth_clock"})
    assert not wanted_place(off, "wealth_clock")
    assert wanted_place(off, "blender")


def test_one_switch_covers_every_dispenser():
    from hivemind.act.errands import wanted_place
    off = _Switches(off={"economy.dispensers"})
    for name in ("blueberry_dispenser", "strawberry_dispenser",
                 "treat_dispenser", "honey_dispenser", "glue_dispenser"):
        assert not wanted_place(off, name), name


def test_a_place_with_no_switch_runs():
    """The switches exist to let the owner say no, not to enumerate
    everything."""
    from hivemind.act.errands import wanted_place
    assert wanted_place(_Switches(), "ant_pass")


def test_unreadable_settings_keep_a_place_on():
    from hivemind.act.errands import wanted_place

    class Broken:
        def bool(self, key):
            raise RuntimeError("no settings file")

    assert wanted_place(Broken(), "wealth_clock")


def test_every_mapped_switch_is_a_real_setting():
    from hivemind.act.errands import PLACE_SETTINGS
    from hivemind.world.settings import SECTIONS
    every = {e[0] for _, entries in SECTIONS for e in entries}
    missing = set(PLACE_SETTINGS.values()) - every
    assert not missing, f"these map to settings that do not exist: {missing}"


def test_the_wired_switches_are_out_of_the_unwired_list():
    from hivemind.act.errands import PLACE_SETTINGS
    from hivemind.world.settings import NOT_WIRED
    still = set(PLACE_SETTINGS.values()) & NOT_WIRED
    assert not still, f"wired but still marked unwired: {sorted(still)}"


def test_the_beesmas_machines_are_used_and_walked_over_as_natro_does():
    # natro_macro.ahk nm_Wreath / nm_Samovar: a wait for the payout to land,
    # then three back-and-forth rows over it, in units of 4 studs
    from hivemind.act import errands
    assert errands.free_to_use("honey_wreath") and errands.free_to_use("samovar")
    assert not errands.free_to_use("stockings")          # its pass jumps on a timing
    for name, steps in errands.LOOT_WALKS.items():
        assert steps[0]["op"] == "pause" and steps[0]["seconds"] >= 4.0, name
        walks = [s for s in steps if s["op"] == "walk"]
        assert all(set(s["keys"]) <= set("wasd") and s["studs"] > 0 for s in walks), name
        assert sum(1 for s in walks if s["studs"] == 24.0) == 7, name     # 3 rows of 2 + the last


# ---- B16: the machine's own timer, not the wiki's period -------------------
# Real prompt strings from var/night/run-*.log and var/errand_ready.json.

def test_b16_real_prompts_parse_to_their_timers():
    from hivemind.act.errands import countdown_seconds
    assert countdown_seconds("Use the Wealth Clock (57:22)") == 57 * 60 + 22
    assert countdown_seconds("Use the Blue Field Booster (44:59)") == 44 * 60 + 59
    assert countdown_seconds("Use the Free Ant Pass Dispenser (1:59:59)") == 7199
    assert countdown_seconds("Use the Blueberry Dispenser (3:59:59)") == 14399
    assert countdown_seconds("Use the Wealth Clock (26s)") == 26
    assert countdown_seconds("Use the Treat Dispenser") is None
    assert countdown_seconds("Use the Wealth Clock (57:7x)") is None


def test_b16_a_timer_past_its_period_x1_5_is_cut_to_that():
    from hivemind.act.errands import capped
    assert capped(57 * 60 + 22, 1.0) == 57 * 60 + 22
    assert capped(5 * 3600 + 3599, 1.0) == 5400.0       # "(5:59:59)" for "(59:59)"
    assert capped(9000.0, 0.0) == 9000.0                # no period known: as read
    assert capped(None, 1.0) is None


def test_b16_a_misread_timer_on_arrival_books_at_most_the_cap():
    honey = Errand(name="honey_dispenser", expect=("use the honey dispenser",),
                   every_hours=1.0)
    out = run_errand(honey, walk=lambda: True, frames=frames,
                     read_text=says("Use the Honey Dispenser (5:59:59)"),
                     vin=Presser(), press=True, sleep=lambda s: None)
    assert out.used is False and out.cooling == 5400.0


def test_b16_the_read_back_after_a_press_is_capped_too():
    booster = Errand(name="blue_field_booster",
                     expect=("use the blue field booster",), every_hours=0.75)
    out = run_errand(booster, walk=lambda: True, frames=frames,
                     read_text=says("Use the Blue Field Booster",
                                    "Use the Blue Field Booster (44:59)"),
                     vin=Presser(), press=True, sleep=lambda s: None)
    assert out.used is True and out.next_in == 44 * 60 + 59


def test_b16_the_log_line_names_the_prompt_timer_and_the_wiki_period():
    import time
    from hivemind.act.errands import booked_line
    due = time.mktime((2026, 10, 19, 21, 29, 0, 0, 0, -1))
    assert booked_line("wealth_clock", 57 * 60 + 22, due, 1.0) == (
        "wealth clock: the prompt says ready in 57:22 — booked for 21:29, "
        "not the wiki's 1h")
    assert "ready in 1:59:59" in booked_line("ant_pass", 7199, due, 2.0)
    assert "the wiki's 45 min" in booked_line("red_field_booster", 2699, due, 0.75)


def test_b16_run_farm_books_and_logs_off_the_prompt():
    from pathlib import Path
    import hivemind
    src = (Path(hivemind.__file__).resolve().parents[2]
           / "scripts" / "run_farm.py").read_text()
    assert src.count("resources_booked_line(") == 2
    assert "the prompt shows no timer — " in src


def test_the_balloon_reads_the_left_honey_before_its_own_start():
    """ROADMAP P19 (brain/farm read_left_honey): a convert that left at the
    empty bag lands its honey first, so neither the balloon's start nor the
    trip's honey holds the other's."""
    from pathlib import Path
    import hivemind
    src = (Path(hivemind.__file__).resolve().parents[2]
           / "scripts" / "run_farm.py").read_text(encoding="utf-8")
    body = src[src.index("def convert_the_balloon"):]
    assert body.index("loop.read_left_honey()") < body.index("start = getattr(hud.honey()")


def test_a_priced_wait_walks_away_and_its_shadow_only_says_so():
    # the clock's timer reads 4m 46s on arrival (MEASURED 2026-10-22 16:52:25)
    notes = []
    out = run_errand(CLOCK, walk=lambda: True, frames=frames,
                     read_text=says("Use the Wealth Clock (4:46)"),
                     vin=Presser(), press=True, sleep=lambda s: None, max_wait=4.0,
                     on_note=notes.append)
    assert out.used is False and out.cooling == 286
    assert not any("waiting here" in n for n in notes)
    # shadow: the line is logged, the wait itself is unchanged (the timer
    # is gone on the next read, so the wait ends at once)
    notes = []
    run_errand(CLOCK, walk=lambda: True, frames=frames,
               read_text=says("Use the Wealth Clock (4:46)", "Use the Wealth Clock"),
               vin=Presser(), sleep=lambda s: None, on_note=notes.append,
               wait_verdict=lambda left: f"errands would: walk away ({left:.0f}s)")
    assert "errands would: walk away (286s)" in notes
    assert any("waiting here" in n for n in notes)
