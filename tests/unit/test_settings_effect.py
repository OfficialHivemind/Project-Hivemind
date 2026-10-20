"""Does each setting really change what the bot does? (owner, 2026-10-19:
"make sure the options actually change how ai acts too otherwise there is no
point having them"). The audit is docs/pending/settings-audit.md.

test_settings.py asks whether a key's NAME appears anywhere in the engines,
which a log line or a comment satisfies. This asks for more, statically: a
real READ of the key -- `x.get/bool/int/float/fraction(key)` (or the stream
window's `_get/_on`, or a subscript) whose value is used, not only printed --
in the code that runs: src/ (the GUI only for stream.* and gui.* keys) and
the three scripts that run unattended. A key reached through a constant
(bugrun.MASTER_SWITCH) or a mapping (errands.PLACE_SETTINGS) is followed.

What it cannot see: whether the read is ever reached at run time. Those are
held below by hand, each with the fact that makes it dead, so the fact
changing fails the test too.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

from hivemind.world.settings import LOCKED, NOT_WIRED, SECTIONS

ROOT = Path(__file__).resolve().parents[2]
KEYS = {e[0] for _, entries in SECTIONS for e in entries}

# ---- today's audit (docs/pending/settings-audit.md) -------------------------
# NEVER READ by anything that runs. A new setting nothing reads lands here and
# fails `test_the_unread_settings_are_exactly_the_known_ones`.
DEAD = {
    "economy.min_field_health", "economy.nectar_vials", "combat.mobs",
    "quests.science", "autonomy.question_timeout_m", "move.open_loop",
    "move.reset_to_start", "safety.click_mode", "perf.render_unfocused",
    "perf.record",
    # read only by brain/autonomy.Arbiter, which nothing constructs
    "autonomy.mode", "autonomy.max_spend", "autonomy.min_confidence",
}
# READ BY CODE THAT CAN NEVER REACH IT: errands.wanted_place reads it, but
# only for a place in run_farm's PLACE_ROUTES, and there is no
# natro_out_wind_shrine route (nor is it in errands.FREE_TO_USE).
UNREACHABLE = {"economy.wind_shrine"}
# THE VALUE IS IGNORED BY DESIGN (world/settings LOCKED).
READ_ONLY = {"safety.never_chat"}
GUI_ONLY = {"gui.mode", "gui.layout"}
NOT_EFFECT = DEAD | UNREACHABLE | READ_ONLY | GUI_ONLY

READS = {"get", "bool", "int", "float", "fraction", "_get", "_on"}
LOGGERS = {"print", "Log", "narrate", "say", "note", "on_note"}
RUNTIME_SCRIPTS = ("run_farm.py", "telegram_alerts.py", "daily_card.py")
SKIP = ("world/settings.py",            # the schema
        "brain/autonomy.py",            # the Arbiter nothing runs
        "gui/panels/settings.py",       # the control builder
        "gui/shell.py")                 # the cards


def _files():
    for path in sorted((ROOT / "src" / "hivemind").rglob("*.py")):
        rel = path.relative_to(ROOT / "src" / "hivemind").as_posix()
        if "/gen/" not in f"/{rel}" and not rel.endswith(SKIP):
            yield path, rel.startswith("gui/")
    for name in RUNTIME_SCRIPTS:
        yield ROOT / "scripts" / name, False


def _keys_in(node) -> set[str]:
    return {n.value for n in ast.walk(node)
            if isinstance(n, ast.Constant) and n.value in KEYS}


def _parse():
    trees = []
    for path, gui in _files():
        tree = ast.parse(path.read_text())
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                child.parent = parent
        trees.append((path, gui, tree))
    return trees


def _constants(trees) -> tuple[dict, dict]:
    """NAME = "key" anywhere at module/class level, and module-level
    containers (dicts, tuples, lists) holding keys, per module."""
    names: dict[str, set] = {}
    containers: dict[Path, dict[str, set]] = {}
    for path, _gui, tree in trees:
        top = list(tree.body) + [s for c in tree.body if isinstance(c, ast.ClassDef)
                                 for s in c.body]
        for node in top:
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                # a defaults table is not a read of what it lists
                if not isinstance(target, ast.Name) or target.id == "DEFAULTS":
                    continue
                if isinstance(node.value, ast.Constant) and node.value.value in KEYS:
                    names.setdefault(target.id, set()).add(node.value.value)
                elif isinstance(node.value, (ast.Dict, ast.Tuple, ast.List, ast.Set,
                                             ast.BinOp)):
                    found = _keys_in(node.value)
                    if found:
                        containers.setdefault(path, {})[target.id] = found
    return names, containers


def _logged_only(node) -> bool:
    """Inside an f-string, or an argument of print/Log/narrate."""
    up = getattr(node, "parent", None)
    while up is not None and not isinstance(up, ast.stmt):
        if isinstance(up, ast.JoinedStr):
            return True
        if isinstance(up, ast.Call):
            f = up.func
            if (f.id if isinstance(f, ast.Name) else
                    f.attr if isinstance(f, ast.Attribute) else "") in LOGGERS:
                return True
        up = getattr(up, "parent", None)
    return False


def _enclosing(node, kinds):
    up = getattr(node, "parent", None)
    while up is not None and not isinstance(up, kinds):
        up = getattr(up, "parent", None)
    return up


def _resolve(arg, path, names, containers) -> set[str]:
    if isinstance(arg, ast.Constant):
        return {arg.value} & KEYS
    ident = arg.id if isinstance(arg, ast.Name) else (
        arg.attr if isinstance(arg, ast.Attribute) else None)
    if ident is None:
        return set()
    if ident in names:
        return set(names[ident])
    out: set[str] = set()
    # `for key in ("a", "b"): settings.bool(key)`
    loop = _enclosing(arg, ast.For)
    while loop is not None:
        if isinstance(loop.target, ast.Name) and loop.target.id == ident:
            out |= _keys_in(loop.iter)
        loop = _enclosing(loop, ast.For)
    # `key = MAPPING.get(name); settings.bool(key)`
    func = _enclosing(arg, (ast.FunctionDef, ast.AsyncFunctionDef))
    mine = containers.get(path, {})
    if func is not None:
        for n in ast.walk(func):
            if isinstance(n, ast.Name) and n.id in mine:
                out |= mine[n.id]
    return out


def read_sites() -> dict[str, list[str]]:
    """key -> ["file:line", ...] of reads whose value is used."""
    trees = _parse()
    names, containers = _constants(trees)
    sites: dict[str, list[str]] = {}

    def add(keys, path, gui, node):
        for key in keys:
            if gui and not key.startswith(("stream.", "gui.")):
                continue
            sites.setdefault(key, []).append(
                f"{path.relative_to(ROOT)}:{node.lineno}")

    for path, gui, tree in trees:
        for node in ast.walk(tree):
            if _logged_only(node):
                continue
            if isinstance(node, ast.Call) and node.args:
                f = node.func
                name = (f.attr if isinstance(f, ast.Attribute) else
                        f.id if isinstance(f, ast.Name) else "")
                if name in READS:
                    add(_resolve(node.args[0], path, names, containers), path, gui, node)
            elif isinstance(node, ast.Subscript) and isinstance(node.ctx, ast.Load) \
                    and isinstance(node.slice, ast.Constant) and node.slice.value in KEYS:
                add({node.slice.value}, path, gui, node)
        # telegram_alerts: ALERTS rows are (key, pattern, ...), each sent only
        # `if ... not wanted(kind ...)`. Counted only while that test exists.
        if path.name == "telegram_alerts.py" and any(
                isinstance(n, ast.If) and any(
                    isinstance(c, ast.Call) and getattr(c.func, "id", "") == "wanted"
                    for c in ast.walk(n.test))
                for n in ast.walk(tree)):
            add(containers.get(path, {}).get("ALERTS", set()), path, gui, tree.body[0])
    return sites


def test_every_effect_setting_is_read_where_it_decides_something():
    sites = read_sites()
    missing = sorted((KEYS - NOT_EFFECT) - set(sites))
    assert not missing, (
        "these settings are presented as working but nothing reads them into a "
        f"decision (only names, comments or log lines): {missing}")


def test_the_unread_settings_are_exactly_the_known_ones():
    """A NEW setting nothing reads fails here; so does a dead one that gets
    wired (take it out of DEAD, and out of world/settings NOT_WIRED)."""
    unread = KEYS - set(read_sites())
    assert unread == DEAD | READ_ONLY, (
        f"newly unread: {sorted(unread - DEAD - READ_ONLY)}; "
        f"read now, still listed dead: {sorted((DEAD | READ_ONLY) - unread)}")


def test_the_known_lists_are_real_settings():
    assert NOT_EFFECT <= KEYS, NOT_EFFECT - KEYS


def test_the_dead_ones_are_labelled_dead_in_the_window():
    """The panel greys NOT_WIRED; a dead key it shows as live is the lie."""
    assert DEAD <= NOT_WIRED, sorted(DEAD - NOT_WIRED)
    assert READ_ONLY <= set(LOCKED), sorted(READ_ONLY - set(LOCKED))


def test_nothing_runs_the_arbiter():
    """autonomy.mode/max_spend/min_confidence are dead only while no code
    imports brain.autonomy."""
    pattern = re.compile(r"brain\.autonomy|from \.+brain import autonomy|"
                         r"from \.+ import autonomy|import autonomy|Arbiter\(")
    users = [str(p.relative_to(ROOT)) for p, _gui in _files()
             if pattern.search(p.read_text())]
    assert not users, f"the Arbiter is used now; re-audit the autonomy.* settings: {users}"


def test_the_wind_shrine_is_still_unreachable():
    """economy.wind_shrine changes nothing while there is no route to the
    shrine and it is not a place E may be pressed at. When either changes,
    re-audit it (it may be EFFECT then)."""
    routes = (ROOT / "data" / "world" / "natro_paths.yaml").read_text()
    assert "natro_out_wind_shrine" not in routes
    from hivemind.act.errands import FREE_TO_USE
    assert "wind_shrine" not in FREE_TO_USE


def test_the_static_check_sees_through_constants_and_mappings():
    """The resolver's own check: keys read only through bugrun's constants,
    errands' and bearvisit's mappings, a `for key in (...)` loop and
    telegram's ALERTS table must all be found."""
    sites = read_sites()
    for key in ("combat.bug_runs", "combat.bug_spider", "economy.dispensers",
                "quests.polar", "economy.use_items", "telegram.planter",
                "gather.natro_field_start", "stream.chat_may_jump"):
        assert key in sites, key
    # and a key named only in a log line is not a read
    assert "combat.mobs" not in sites


# ---- U12: the Features page (world/settings.FEATURES) -------------------------
from hivemind.world.settings import (CORE_FEATURES, FEATURE_EXCLUDED,  # noqa: E402
                                     FEATURE_GROUPS, FEATURES)

# errand/behaviour toggles, found by key prefix and type: a bool, or a choice
# with an 'off'/'never' value
FEATURE_PREFIXES = ("gather.", "move.", "economy.", "combat.", "challenges.", "quests.",
                    "badges.", "hive.", "eggs.", "goals.", "boost.", "planner.",
                    "telegram.", "learn.", "mode.", "server.", "account.")
# a look-only feature's switch is its module's *_LIVE constant
LIVE_FLAGS = {"combat.mondo_loot": ("src/hivemind/act/mondo.py", "MONDO_LOOT_LIVE"),
              "challenges.stick_bug": ("src/hivemind/act/stickbug.py", "STICK_BUG_LIVE"),
              "hive.grind_basic": ("scripts/run_farm.py", "GRIND_REPLACE_LIVE")}
SCHEMA = {e[0]: e for _, entries in SECTIONS for e in entries}


def _toggles() -> set[str]:
    return {k for k, e in SCHEMA.items() if k.startswith(FEATURE_PREFIXES) and (
        e[2] == "bool" or (e[2] == "choice" and {"off", "never"} & set(e[5])))}


def test_every_feature_is_a_setting_that_is_really_read():
    keys = [key for _, key, *_ in FEATURES]
    assert len(keys) == len(set(keys)), "a feature listed twice"
    sites = read_sites()
    assert not [k for k in keys if k not in sites or k in NOT_EFFECT], (
        [k for k in keys if k not in sites or k in NOT_EFFECT])
    assert {g for g, *_ in FEATURES} == set(FEATURE_GROUPS)
    assert {b for *_, b in FEATURES} <= {"live", "look-only", "needs measuring"}
    assert CORE_FEATURES <= set(keys)


def test_every_errand_and_behaviour_toggle_is_on_the_features_page():
    keys = {key for _, key, *_ in FEATURES}
    missing = _toggles() - keys - set(FEATURE_EXCLUDED)
    assert not missing, f"add these to FEATURES or say why not in FEATURE_EXCLUDED: {missing}"
    assert not keys & set(FEATURE_EXCLUDED)
    assert set(FEATURE_EXCLUDED) <= _toggles(), set(FEATURE_EXCLUDED) - _toggles()


def test_a_look_only_badge_follows_its_live_constant():
    badge = {key: b for _, key, _, _, b in FEATURES}
    for key, (rel, name) in LIVE_FLAGS.items():
        live = re.search(rf"^{name} = (True|False)", (ROOT / rel).read_text(), re.M)
        assert live, (rel, name)
        assert (badge[key] == "live") == (live.group(1) == "True"), (key, badge[key])


# ---- U15b: shipped defaults off --------------------------------------------------
def test_every_feature_ships_off_but_the_core_farm_loop():
    from hivemind.world.settings import U15B_WAS, defaults, feature_off
    d = defaults()
    on = sorted(k for _, k, *_ in FEATURES if k not in CORE_FEATURES and d[k] != feature_off(k))
    assert not on, f"optional features that ship ON: {on}"
    assert all(d[k] is True for k in CORE_FEATURES), sorted(CORE_FEATURES)
    # every flip is recorded with its old default, for tools/pin_owner_settings.py
    assert all(d[k] == feature_off(k) != was for k, was in U15B_WAS.items())
