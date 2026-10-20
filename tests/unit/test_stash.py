"""A player's call on each item (brain/stash): keep what goals need and a rescue
reserve, use what is at its cap or spare."""
import json

from hivemind.brain import stash as st

CATALOGUE = {"whirligig": {"label": "Whirligig", "role": "time_saver", "cap": 100},
             "micro_converter": {"label": "Micro-Converter", "role": "time_saver", "cap": 15},
             "oil": {"label": "Oil", "role": "material"}}


def stash(counts, caps=None, reserved=None):
    return st.Stash(catalogue=CATALOGUE, counts=dict(counts), caps=dict(caps or {}),
                    reserved=dict(reserved or {}))


def test_spare_whirligigs_are_used_and_two_are_kept_for_a_rescue():
    s = stash({"whirligig": 8}, {"whirligig": 100})
    v = s.routine_use("whirligig", 700_000, on_hotbar=True)
    assert v.use and "6 spare" in v.why and "700,000 honey" in v.why
    for _ in range(6):
        s.spent("whirligig")
    v = s.routine_use("whirligig", 700_000, on_hotbar=True)
    assert not v.use and "none spare" in v.why
    assert s.rescue_use("whirligig", on_hotbar=True).use          # the reserve is for this
    s.spent("whirligig", 2)
    assert not s.rescue_use("whirligig", on_hotbar=True).use


def test_at_its_cap_an_item_is_used_whatever_it_would_keep():
    s = stash({"micro_converter": 15}, {"micro_converter": 15})
    v = s.routine_use("micro_converter", None, on_hotbar=True)
    assert v.use and "at its cap" in v.why


def test_not_counted_or_not_on_the_hotbar_is_not_used_routinely():
    assert not stash({}).routine_use("whirligig", 1, on_hotbar=True).use
    assert "not counted" in stash({}).routine_use("whirligig", 1, on_hotbar=True).why
    assert not stash({"whirligig": 8}).routine_use("whirligig", 1, on_hotbar=False).use


def test_what_the_goals_need_is_kept():
    s = stash({"oil": 16}, reserved={"oil": 25})
    h = s.holding("oil")
    assert h.spare == 0 and "16 kept for the goals" not in h.describe()
    assert "25 kept for the goals" in h.describe()
    assert not s.routine_use("oil", 1, on_hotbar=True).use


def test_a_use_that_would_not_pay_is_not_made():
    v = stash({"whirligig": 8}).routine_use("whirligig", 0.0, on_hotbar=True)
    assert not v.use and "would not pay" in v.why


def test_counts_and_caps_come_from_the_inventory_file(tmp_path):
    cat = tmp_path / "c.yaml"
    cat.write_text("items:\n  whirligig: {label: Whirligig, role: time_saver}\n")
    inv = tmp_path / "inventory.json"
    inv.write_text(json.dumps({"read_at": 1.0, "items": {"whirligig": {"count": 8}},
                               "caps": {"whirligig": 100}}))
    s = st.Stash.from_files(cat, inv)
    h = s.holding("whirligig")
    assert h.have == 8 and h.cap == 100 and h.keep == 2 and h.spare == 6


def test_what_was_used_since_a_read_survives_a_new_process(tmp_path):
    """run-566 23:35: a new process counted the 22:29 read's 8 Whirligigs
    again after the last one had used four."""
    import json
    from hivemind.brain import stash as st
    cat = tmp_path / "consumables.yaml"
    cat.write_text("items:\n  whirligig: {label: Whirligig, role: time_saver, cap: 100}\n")
    inv = tmp_path / "inventory.json"
    inv.write_text(json.dumps({"read_at": 1000.0,
                               "items": {"whirligig": {"count": 8}}}))
    used = tmp_path / "stash_used.json"
    first = st.Stash.from_files(cat, inv, used_path=used)
    for _ in range(4):
        first.spent("whirligig")
    second = st.Stash.from_files(cat, inv, used_path=used)
    assert second.holding("whirligig").have == 4
    # a new read counts what is there; the old uses do not carry over
    inv.write_text(json.dumps({"read_at": 2000.0,
                               "items": {"whirligig": {"count": 4}}}))
    third = st.Stash.from_files(cat, inv, used_path=used)
    assert third.holding("whirligig").have == 4


def test_a_use_must_gain_more_as_the_stock_runs_down():
    from hivemind.brain import stash as st
    assert abs(st.gain_share(15, 15) - 0.10) < 1e-9          # a full stack
    assert abs(st.gain_share(8, 15) - (0.30 - 0.20 * 8 / 15)) < 1e-9
    assert abs(st.gain_share(1, 15) - (0.30 - 0.20 / 15)) < 1e-9
    assert st.gain_share(0, 15) == st.GAIN_SHARE_LAST
    assert st.gain_share(None, 15) == st.GAIN_SHARE_LAST
    # the 05:02 use (14,450 pollen/s, 3,441,326 bag): over the bar at 10%, not at 8/15
    bag, hive, field = 3_441_326, 1.33, 1.083
    gain = 14_450 * 75 * hive
    loss = bag * (hive - field)
    assert gain - loss - 0.10 * bag * hive > 0
    assert gain - loss - st.gain_share(8, 15) * bag * hive < 0
    # the 02:02 boost (43,164 pollen/s) clears it even near the last one
    gain = 43_164 * 75 * hive
    assert gain - loss - st.gain_share(2, 15) * bag * hive > 0


def test_the_measured_pay_is_the_last_measured_uses_not_the_last_uses():
    from hivemind.brain import stash as st
    # var/micro_converter.json at 05:08 on 2026-10-02: the one measured use
    # (1.0833, read from the reward feed) behind five whose pay did not read
    uses = ([{"ratio": None, "pollen": 3_605_339},
             {"ratio": 1.0833, "pollen": 3_639_156}]
            + [{"ratio": None, "honey_before": None}] * 5)
    assert st.measured_pay(uses) == 1.0833
    assert st.measured_pay([]) is None
    assert st.measured_pay([{"ratio": None}, {}, {"ratio": "x"}, "junk"]) is None
    # the window counts measured uses only, and is the median of them
    many = [{"ratio": r} for r in (2.0, 1.0, 1.1, 1.2, 1.3, 1.4)]
    assert st.measured_pay(many) == 1.2                      # 1.0..1.4, not 2.0
    assert st.measured_pay(many[-2:]) == 1.35


def test_field_consumables_glitter_alone_and_the_rest_in_a_boost():
    from hivemind.brain.stash import Stash
    s = Stash(catalogue={"glitter": {"label": "Glitter"}, "glue": {"label": "Glue"},
                         "blue_extract": {"label": "Blue Extract"}},
              counts={"glitter": 18, "glue": 9, "blue_extract": 54},
              reserved={"glitter": 15, "blue_extract": 50})
    assert s.field_use("glitter", home_boosted=False, last_used=None, now=0).use
    assert not s.field_use("glitter", home_boosted=True, last_used=None, now=0).use
    assert not s.field_use("glitter", home_boosted=False, last_used=0, now=600).use   # still on
    assert s.field_use("glitter", home_boosted=False, last_used=0, now=901).use
    assert not s.field_use("glue", home_boosted=False, last_used=None, now=0).use
    assert s.field_use("glue", home_boosted=True, last_used=None, now=0).use
    s.counts["blue_extract"] = 50                    # all kept for the Bubble Mask
    assert not s.field_use("blue_extract", home_boosted=True, last_used=None, now=0).use
    assert not s.field_use("whirligig", home_boosted=True, last_used=None, now=0).use


def test_a_magic_bean_is_planted_any_trip_one_sprout_at_a_time():
    # a sprout is run down by the field's own gathering and pays tokens over
    # it (wiki Sprout): no boost needed, and not again while one grows
    from hivemind.brain.stash import Stash
    s = Stash(catalogue={"magic_bean": {"label": "Magic Bean"}}, counts={"magic_bean": 7},
              reserved={})
    assert s.field_use("magic_bean", home_boosted=False, last_used=None, now=0).use
    assert s.field_use("magic_bean", home_boosted=True, last_used=None, now=0).use
    assert not s.field_use("magic_bean", home_boosted=False, last_used=0, now=600).use
    s.counts["magic_bean"] = 0
    assert not s.field_use("magic_bean", home_boosted=False, last_used=None, now=0).use


def test_two_readings_that_disagree_give_the_smaller_as_a_floor(tmp_path):
    import json
    from hivemind.brain.stash import Stash
    inv = tmp_path / "inventory.json"
    inv.write_text(json.dumps({"read_at": 1.0, "items": {"glue": {"count": 9}},
                               "unsure": {"glitter": ["18", "54", 18, 54], "enzymes": ["9", 19]}}))
    cat = tmp_path / "consumables.yaml"
    cat.write_text("items:\n  glitter: {label: Glitter}\n  glue: {label: Glue}\n  enzymes: {label: Enzymes}\n")
    s = Stash.from_files(cat, inv, reserved={"glitter": 15})
    assert s.holding("glitter").have == 18 and s.holding("glitter").spare == 3
    assert s.holding("enzymes").have == 9 and s.holding("glue").have == 9
    assert s.field_use("glitter", home_boosted=False, last_used=None, now=0).use


def test_a_complete_read_without_a_whirligig_row_counts_none(tmp_path):
    from hivemind.act import inventory as inv_mod
    cat = tmp_path / "c.yaml"
    cat.write_text("items:\n  whirligig: {label: Whirligig, role: time_saver}\n"
                   "  glue: {label: Glue, role: boost}\n")
    inv = tmp_path / "inventory.json"
    read = inv_mod.InventoryRead(ok=True, complete=True, counts={"glitter": 3},
                                 seen=["glitter"])
    inv_mod.write(inv, read, {}, zero_unseen=("whirligig",))
    s = st.Stash.from_files(cat, inv)
    assert s.holding("whirligig").have == 0
    assert s.holding("glue").have is None            # not a zero_unseen key
    v = s.rescue_use("whirligig", on_hotbar=True, greyed=True)
    assert not v.use and "none counted" in v.why
    # a read that stopped short of the end keeps it unknown
    read.complete = False
    inv_mod.write(inv, read, {}, zero_unseen=("whirligig",))
    assert st.Stash.from_files(cat, inv).holding("whirligig").have is None


def test_an_uncounted_greyed_tile_is_pressed_once_not_after_a_refusal():
    # run-1048 07:23-07:38: three presses on the same refused greyed Whirligig
    s = stash({})
    assert s.rescue_use("whirligig", on_hotbar=True, greyed=True).use
    s.refused_press("whirligig")
    assert not s.rescue_use("whirligig", on_hotbar=True, greyed=True).use
    assert s.rescue_use("micro_converter", on_hotbar=True, greyed=True).use


def test_a_new_inventory_read_clears_a_refusal(tmp_path):
    # the refusal lasts only as long as the read it was made against: run_farm's
    # the_stash() builds a new Stash from the files when inventory.json changes
    from hivemind.act import inventory as inv_mod
    cat = tmp_path / "c.yaml"
    cat.write_text("items:\n  whirligig: {label: Whirligig, role: time_saver}\n")
    inv = tmp_path / "inventory.json"
    read = inv_mod.InventoryRead(ok=True, complete=False, counts={"glitter": 3},
                                 seen=["glitter"])
    inv_mod.write(inv, read, {}, zero_unseen=("whirligig",))
    s = st.Stash.from_files(cat, inv)
    s.refused_press("whirligig")
    assert not s.rescue_use("whirligig", on_hotbar=True, greyed=True).use
    inv_mod.write(inv, read, {}, zero_unseen=("whirligig",))
    fresh = st.Stash.from_files(cat, inv)
    assert not fresh.refused
    assert fresh.rescue_use("whirligig", on_hotbar=True, greyed=True).use
