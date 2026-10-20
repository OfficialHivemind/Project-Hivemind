"""The settings schema, shared by the GUI and the bot.

The point of the shared declaration is that a control cannot exist without
something reading it, and a key cannot be read that no control can reach. The
first two tests enforce exactly that.
"""
import pytest
import yaml

from hivemind.world.settings import (NOT_WIRED, SECTIONS, Settings,
                                     defaults, describe, wired)


def test_every_key_is_unique():
    keys = [entry[0] for _, entries in SECTIONS for entry in entries]
    assert len(keys) == len(set(keys))


def test_every_entry_is_well_formed():
    for section, entries in SECTIONS:
        for entry in entries:
            key, label, kind, default, help_text, *rest = entry
            assert kind in ("bool", "int", "float", "choice", "text", "list"), key
            if kind == "list":
                assert isinstance(default, list), key
            assert label, key
            if kind == "choice":
                assert rest and default in rest[0], f"{key}: default not a choice"
            if kind == "bool":
                assert isinstance(default, bool), key
            if kind == "int":
                assert isinstance(default, int) and not isinstance(default, bool), key


def test_the_gui_builds_from_the_same_schema():
    """If these ever diverge, a control exists that nothing reads."""
    pytest.importorskip("PySide6")
    from hivemind.gui.panels import settings as panel
    assert panel.SECTIONS is SECTIONS


def test_missing_file_gives_defaults_without_raising(tmp_path):
    s = Settings(tmp_path / "nope.yaml")
    assert s.values == defaults()
    assert s.problems == []


def test_malformed_yaml_falls_back_to_defaults(tmp_path):
    path = tmp_path / "s.yaml"
    path.write_text("{ not: valid: yaml: at all")
    s = Settings(path)
    assert s.values == defaults()
    assert s.problems


def test_a_non_mapping_file_is_rejected(tmp_path):
    path = tmp_path / "s.yaml"
    path.write_text("- a\n- b\n")
    s = Settings(path)
    assert s.values == defaults()
    assert "not a mapping" in s.problems[0]


def test_stored_values_override_defaults(tmp_path):
    path = tmp_path / "s.yaml"
    path.write_text(yaml.safe_dump({"gather.convert_at": 75}))
    assert Settings(path).int("gather.convert_at") == 75


def test_a_wrong_type_is_rejected_and_reported(tmp_path):
    path = tmp_path / "s.yaml"
    path.write_text(yaml.safe_dump({"gather.convert_at": "ninety"}))
    s = Settings(path)
    assert s.int("gather.convert_at") == defaults()["gather.convert_at"]
    assert any("gather.convert_at" in p for p in s.problems)


def test_an_unknown_key_is_kept_not_discarded(tmp_path):
    """Downgrading then upgrading must not silently erase choices."""
    path = tmp_path / "s.yaml"
    path.write_text(yaml.safe_dump({"future.setting": 1}))
    assert Settings(path).get("future.setting") == 1


def test_fraction_converts_percentages(tmp_path):
    s = Settings(tmp_path / "none.yaml")
    # the default is 95 since the pro tester, round 1 (19 Oct 2026)
    assert s.fraction("gather.convert_at") == pytest.approx(0.95)


def test_early_harvest_defaults_off():
    """It must stay off until field degradation has been measured."""
    assert defaults()["economy.early_harvest"] is False


def test_every_risky_setting_explains_itself():
    risky = ["economy.early_harvest", "economy.wind_shrine", "combat.vicious",
             "safety.jitter", "autonomy.min_confidence"]
    for key in risky:
        assert len(describe(key)) > 30, f"{key} needs an explanation"


# --- bool must not sneak through the int/float check ------------------------
# `isinstance(True, int)` is True, so a YAML boolean used to be accepted for
# every int setting and, via the int-for-float escape hatch, every float one.
# float(False) == 0.0, which switched the irreversibility firewall off with
# nothing reported in `problems`. YAML makes this easy to hit by accident:
# no / off / n / y are all booleans.

@pytest.mark.parametrize("text, key, default", [
    ("autonomy.min_confidence: no\n", "autonomy.min_confidence", 0.9),
    ("autonomy.min_confidence: yes\n", "autonomy.min_confidence", 0.9),
    ("gather.convert_at: yes\n", "gather.convert_at", 95),   # pro tester round 1
    ("gather.convert_at: off\n", "gather.convert_at", 95),
])
def test_a_boolean_is_rejected_for_a_number(tmp_path, text, key, default):
    path = tmp_path / "settings.yaml"
    path.write_text(text)
    s = Settings(path)
    assert s.values[key] == default, "the default must survive"
    assert not isinstance(s.values[key], bool)
    assert any(key in p for p in s.problems), "the user must be told"


def test_the_firewall_is_not_silently_disabled(tmp_path):
    """The concrete consequence, end to end."""
    path = tmp_path / "settings.yaml"
    path.write_text("autonomy.min_confidence: no\n")
    s = Settings(path)
    assert s.float("autonomy.min_confidence") == 0.9
    assert s.problems


def test_real_numbers_and_real_booleans_still_load(tmp_path):
    """The check must not become so strict that valid files are rejected."""
    path = tmp_path / "settings.yaml"
    path.write_text("autonomy.min_confidence: 0.7\n"
                    "gather.convert_at: 85\n"
                    "safety.never_chat: true\n")
    s = Settings(path)
    assert s.problems == []
    assert s.float("autonomy.min_confidence") == 0.7
    assert s.int("gather.convert_at") == 85
    assert s.bool("safety.never_chat") is True


def test_an_int_is_still_accepted_for_a_float(tmp_path):
    """The int-for-float escape hatch is deliberate and must survive."""
    path = tmp_path / "settings.yaml"
    path.write_text("autonomy.min_confidence: 1\n")
    s = Settings(path)
    assert s.problems == []
    assert s.float("autonomy.min_confidence") == 1.0


# --- a control that looks live and does nothing is a lie -------------------
# The schema is deliberately ahead of the engines, which is fine. Presenting an
# unwired toggle as working is not. This keeps NOT_WIRED honest in BOTH
# directions, by scanning the source rather than trusting the list.

def _keys_read_by_engines() -> set[str]:
    import pathlib
    import re
    import hivemind
    root = pathlib.Path(hivemind.__file__).resolve().parents[2]   # the code under test, not this file's tree (ROADMAP P3 gotcha)
    src = root / "src" / "hivemind"
    # scripts/run_farm.py IS the farm engine: most toggles are read there.
    paths = list(src.rglob("*.py")) + list((root / "scripts").glob("*.py"))
    # as_posix: on Windows str(path) has backslashes and none of these
    # exclusions matched (MEASURED 2026-10-21), so brain/autonomy's reads
    # counted as wiring.
    body = "\n".join(
        path.read_text(encoding="utf-8") for path in paths
        if "/gen/" not in path.as_posix()
        and path.name != "settings.py"                 # the schema itself
        and "gui/panels/settings.py" not in path.as_posix()  # the control builder
        # brain/autonomy's Arbiter reads the autonomy.* keys and the locks,
        # but nothing runs the Arbiter (world/settings, DESIGN 8du), so a
        # key it reads is still unwired.
        and "brain/autonomy.py" not in path.as_posix()
    )
    return {key for _, entries in SECTIONS for entry in entries
            if (key := entry[0]) and re.search(re.escape(key), body)}


def test_nothing_claims_to_be_wired_when_it_is_not():
    """The direction that matters: a live-looking control that does nothing."""
    read = _keys_read_by_engines()
    every = {e[0] for _, entries in SECTIONS for e in entries}
    pretending = (every - NOT_WIRED) - read
    assert not pretending, (
        "these settings are presented as working but nothing reads them — "
        f"add them to NOT_WIRED or wire them up: {sorted(pretending)}")


def test_nothing_is_marked_unwired_once_it_is_actually_used():
    """The other direction, so the warning disappears when the work is done."""
    stale = NOT_WIRED & _keys_read_by_engines()
    assert not stale, (
        f"these are wired now and should come out of NOT_WIRED: {sorted(stale)}")


def test_every_unwired_key_is_a_real_setting():
    every = {e[0] for _, entries in SECTIONS for e in entries}
    assert NOT_WIRED <= every, f"NOT_WIRED names nothing: {NOT_WIRED - every}"


def test_the_vision_model_toggle_actually_switches_the_model_off():
    """It shipped as a control wired to nothing, which is the exact thing the
    owner asked not to happen. Now it reaches the client, so assert the
    behaviour rather than merely that a key is referenced somewhere."""
    from hivemind.brain.vlm import from_settings

    class Off:
        def bool(self, key):
            return False

        def get(self, key, fallback=None):
            return "qwen2.5vl:7b"

    model = from_settings(Off())
    assert not model.enabled
    assert not model.available()
    assert "settings" in model.reason
    assert wired("perf.vlm")


# ---- every dead switch must say what is stopping it ------------------------
# "not built yet" is honest and useless: it cannot tell the owner whether a
# switch needs a week of work or one walk around the map, and most of these
# need the walk.
def test_every_unwired_setting_explains_itself():
    from hivemind.world.settings import BLOCKED_BY
    missing = NOT_WIRED - set(BLOCKED_BY)
    assert not missing, (
        "these switches are dead and do not say why, so the owner cannot tell "
        f"what would fix them: {sorted(missing)}")


def test_no_reason_is_given_for_a_setting_that_actually_works():
    from hivemind.world.settings import BLOCKED_BY
    stale = set(BLOCKED_BY) - NOT_WIRED
    assert not stale, (
        "these work now, so the excuse beside them is a lie: "
        f"{sorted(stale)}")


def test_blocked_by_is_empty_for_working_settings():
    from hivemind.world.settings import blocked_by
    assert blocked_by("gather.auto_field") == ""


def test_blocked_by_explains_a_dead_one():
    """The example moved on 2026-09-21: `gather.chase_tokens` used to be the
    dead switch here and is now built, which is the outcome this test wants.
    It moved again on 2026-10-14: `economy.planters` became real, so the
    example is now the nectar vials."""
    from hivemind.world.settings import blocked_by
    assert blocked_by("economy.planters") == ""
    assert "Vial" in blocked_by("economy.nectar_vials")


def test_a_retired_switch_reads_the_default_quietly(tmp_path):
    """ROADMAP S11: `gather.rotate_camera: true` from when it was a switch."""
    from hivemind.world.settings import Settings
    config = tmp_path / "settings.yaml"
    config.write_text("gather.rotate_camera: true\n")
    s = Settings(config)
    assert s.get("gather.rotate_camera") == "never"
    assert not [p for p in s.problems if "rotate_camera" in p]


# ---- macro mode (ROADMAP U16) -------------------------------------------------
def test_macro_mode_is_off_by_default():
    """Nothing changes for the owner until they switch it on."""
    assert defaults()["mode.macro"] is False and defaults()["macro.fields"] == []


def test_a_macro_entry_takes_the_defaults_it_leaves_out(tmp_path):
    path = tmp_path / "settings.yaml"
    path.write_text(yaml.safe_dump({"macro.fields": [
        {"field": "Pine Tree"},
        {"field": "Rose", "minutes": 0, "pattern": "farm_snake", "convert_at": 75,
         "return": "respawn", "sprinklers": 0}]}))
    s = Settings(path)
    assert s.problems == []
    assert s.get("macro.fields") == [
        # convert_at 95: MACRO_ENTRY's, since the pro tester's round 1 (19 Oct 2026)
        {"field": "Pine Tree", "minutes": 15, "pattern": "field", "convert_at": 95,
         "return": "walk", "sprinklers": 1},
        {"field": "Rose", "minutes": 0, "pattern": "farm_snake", "convert_at": 75,
         "return": "respawn", "sprinklers": 0}]


@pytest.mark.parametrize("bad, said", [
    ({"field": "Moon Field"}, "unknown field"),
    ({"field": "auto"}, "unknown field"),
    ({"field": "Pine Tree", "pattern": "IntelliPine"}, "unknown pattern"),
    ({"field": "Pine Tree", "pattern": "farm_mobs"}, "unknown pattern"),   # a route, not a pattern
    ({"field": "Pine Tree", "return": "rejoin"}, "unknown return"),
    ({"field": "Pine Tree", "speed": 3}, "unknown keys"),
    ({"field": "Pine Tree", "minutes": -1}, "minutes"),
    ({"field": "Pine Tree", "minutes": True}, "minutes"),
    ({"field": "Pine Tree", "convert_at": 5}, "convert_at"),
    ({"field": "Pine Tree", "sprinklers": 9}, "sprinklers"),
    ({"field": "Pine Tree", "sprinklers": "2"}, "sprinklers"),
    ("Pine Tree", "not a mapping"),
])
def test_a_bad_macro_entry_is_left_out_and_said(tmp_path, bad, said):
    path = tmp_path / "settings.yaml"
    path.write_text(yaml.safe_dump({"macro.fields": [bad, {"field": "Clover"}]}))
    s = Settings(path)
    assert [e["field"] for e in s.get("macro.fields")] == ["Clover"]
    assert any("entry 1" in p and said in p for p in s.problems), s.problems


def test_macro_fields_must_be_a_list(tmp_path):
    path = tmp_path / "settings.yaml"
    path.write_text("macro.fields: Pine Tree\n")
    s = Settings(path)
    assert s.get("macro.fields") == [] and any("macro.fields" in p for p in s.problems)


def test_every_macro_pattern_is_a_routine_the_bot_has():
    """The dropdown offers only patterns that exist: 'field' is each field's
    own natro_pattern_<field>, the rest are routines in data/world/paths.yaml."""
    import pathlib
    from hivemind.world.settings import MACRO_PATTERNS
    import hivemind
    root = pathlib.Path(hivemind.__file__).resolve().parents[2]   # the code under test, not this file's tree (ROADMAP P3 gotcha)
    routines = {r["name"] for r in yaml.safe_load((root / "data/world/paths.yaml").read_text())["routines"]}
    assert set(MACRO_PATTERNS) - {"field"} <= routines


def test_no_other_macro_product_is_named_in_the_settings_text():
    """AGENTS.md hard rule 7: the labels, help, feature blurbs and 'not built
    yet' reasons are app text (the (?) tooltips, Settings > Features)."""
    import hashlib
    import re
    from hivemind.world import settings as s
    # macro names as sha256 prefixes, so this file doesn't name them
    other = {"cfef850d0830a8bc", "13c7d14e12cdab63", "70b6144fae4d4c16", "d605c8dc445875ec"}
    texts = [str(x) for _, entries in SECTIONS for e in entries for x in (e[1], e[4])]
    texts += [x for f in s.FEATURES for x in f[2:4]] + list(s.BLOCKED_BY.values())
    named = [t[:80] for t in texts
             if any(hashlib.sha256(w.lower().encode()).hexdigest()[:16] in other
                    for w in re.findall(r"[A-Za-z]+", t))]
    assert not named, named
