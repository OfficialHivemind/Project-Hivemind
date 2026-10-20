"""THE ONE PLAN: what Hivemind works on, as one choice (choose-design 2026-10-26).

A plan is a RECIPE: a fixed table of EXISTING setting values. Clicking a plan
writes those values into settings.yaml through the same writer a preset import
uses (world/settings.take_values), so the settings file always shows exactly
what the bot does -- there is no second path into the bot. The bot reads one
more thing: `plan.target` (and the alt plans' target lists) go in front of the
gear order in brain/goals.from_files (`prepend`).

NOTHING HERE ASKS. A click decides, `apply` says what changed and what it left
alone, and `undo` puts the file back.

YOURS STAYS YOURS: a key whose value is not what the last plan wrote (or, with
no plan written yet, neither the shipped default nor the installer's
safe-first-run seed) was set by the player, and a plan
never overwrites it; `apply` lists it in "kept" and `conflicts` names it, until
the player gives it back (`apply(..., take=...)`).

"custom" (every file until a plan is clicked, so the owner's own file is never
rewritten on upgrade) writes nothing.

THE ALT PLANS ('fuzzy_alt', 'tad_alt', 'hybrid') are hooks: their target lists
and any extra switches come from data/knowledge/progression/alt_goals.yaml when
it exists, shaped like
    fuzzy_alt:
      label: Fuzzy alt              # optional; the default label otherwise
      line: ...                     # optional
      targets: [Fuzzy Bee, ...]     # names goals.order understands, in order
      on: {key: value}              # optional switches over the progress recipe
Without the file they run the progress recipe. 'hybrid' with no entry of its
own takes the Fuzzy targets then the Tad ones.
"""
from __future__ import annotations

import difflib
import json
import re
import time
from pathlib import Path

import yaml

from ..datapaths import data as data_path
from ..files import atomic_write, read_text
from ..world.settings import (CONFIG, CORE_FEATURES, FEATURES, Settings,
                              defaults, take_values)

CUSTOM = "custom"
SNAPSHOT = "plan_applied.yaml"        # beside settings.yaml
HISTORY_MAX = 5                       # undo steps kept
ALT_FILE = ("knowledge", "progression", "alt_goals.yaml")
ALTS = ("fuzzy_alt", "tad_alt", "hybrid")

# What each choice is called on the Play page, and its one line. Plain words.
CHOICES = {
    "progress": ("Progress my account",
                 "Next gear, bees and quests, in the best order."),
    "item": ("Get one item", "Works toward the item you pick."),
    "honey": ("Make the most honey", "Best fields and boosts, no side trips."),
    "quests": ("Do quests", "Does the quests of the bear you pick first."),
    "tickets": ("Farm tickets", "Wealth Clock and ticket mobs. Spends none."),
    "macro": ("My own fields", "Farms your own field list, nothing else."),
    "fuzzy_alt": ("Fuzzy alt", "Builds an account toward Fuzzy Bees."),
    "tad_alt": ("Tad alt", "Builds an account toward Tadpole Bees."),
    "hybrid": ("Hybrid", "The fastest way to all of them."),
    CUSTOM: ("Your own setup", "Your own switches, untouched."),
}

GIVERS = ("polar", "honey", "bucko", "riley", "spirit", "black_bear",
          "brown_bear", "panda", "mother")      # not the Science Bear: NOT_WIRED
AI = {**{k: True for k in sorted(CORE_FEATURES)}, "mode.macro": False}

PROGRESS = {
    **AI, "quests.enabled": True, **{f"quests.{g}": True for g in GIVERS},
    "quests.scroll": True,
    "economy.dispensers": True, "economy.wealth_clock": True,
    "economy.memory_match": True, "economy.planters": True,
    "economy.use_items": True, "economy.buy": True, "economy.blender": True,
    "boost.keeper": True, "boost.boosters": True, "boost.glitter": True,
    "boost.dice": True, "boost.item_buffs": True, "gather.follow_boost": True,
    "gather.chase_tokens": True, "gather.micro_convert": True,
    "combat.bug_runs": True, "combat.bug_loot": True,
    "hive.read_bees": True, "goals.read_inventory": True, "hive.follow_plan": True,
    # combat.bosses stays as it is (choose-design: the player can pin it on)
}

RECIPES: dict[str, dict] = {
    "progress": PROGRESS,
    "item": {**PROGRESS, "quests.first": True},
    "honey": {
        **AI, "boost.keeper": True, "boost.boosters": True, "boost.glitter": True,
        "boost.dice": True, "boost.item_buffs": True, "economy.boosters": True,
        "gather.follow_boost": True, "economy.planters": True,
        "economy.use_items": True, "economy.dispensers": True,
        "economy.wealth_clock": True, "economy.buy": True,
        "gather.chase_tokens": True, "gather.micro_convert": True,
        "quests.enabled": False, "combat.bug_runs": False,
        "combat.bosses": False, "economy.sticker_tickets": False},
    # + the target bear's switch (resolve); other bears stay as they were
    "quests": {**AI, "quests.enabled": True, "quests.first": True,
               "quests.scroll": True, "combat.bug_runs": True,
               "combat.bug_loot": True},
    # The Wealth Clock is the one ticket source the bot "does" today
    # (data/knowledge/goals.yaml currencies); Black and Brown Bear quests pay
    # tickets too (ASSUMED from the same file's quest sources).
    "tickets": {**AI, "economy.wealth_clock": True, "combat.commando": True,
                "economy.planters": True, "economy.use_items": True,
                "quests.enabled": True, "quests.black_bear": True,
                "quests.brown_bear": True,
                "economy.sticker_tickets": False,
                # (economy.tickets.magic_beans only says what it would buy)
                "economy.tickets.diamond_eggs": False},
    "macro": {"mode.macro": True},
    "fuzzy_alt": PROGRESS, "tad_alt": PROGRESS, "hybrid": PROGRESS,
    CUSTOM: {},
}

# A recipe may only write a switch the Features page shows as working.
LIVE = frozenset(k for _g, k, _l, _t, badge in FEATURES if badge == "live")
EXTRA_KEYS = frozenset({"progression.hive"})     # resolve's hive guess
# progression goal kinds a player can own, so "I have it" fits (not bees,
# quests, slots or badges, which the bot reads or counts itself)
HAVE_KINDS = frozenset({"gear", "amulet", "beequip", "planter", "sticker"})


def _slug(text) -> str:
    return "_".join(re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).split())


def _yaml(path: Path):
    try:
        return yaml.safe_load(read_text(path, encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None


def _json(path: Path, empty):
    try:
        body = json.loads(read_text(path, encoding="utf-8"))
        return body if isinstance(body, type(empty)) else empty
    except (OSError, ValueError):
        return empty


# ---- the alt plans' hook ----------------------------------------------------
def alt_goals(path: Path | None = None) -> dict:
    """alt_goals.yaml as {choice: entry}, {} when absent or unreadable.
    The G12 file (brain/hybrid: a `targets` list of {id, label, line, steps})
    is read as {target id: {label, line, targets: [its step labels]}}; the
    older {choice: {targets: [names]}} shape is still taken as it is."""
    body = _yaml(path or data_path(*ALT_FILE))
    if not isinstance(body, dict):
        return {}
    if isinstance(body.get("targets"), list):
        from . import hybrid
        return {tid: {"label": t.get("label"), "line": t.get("line"), "on": t.get("on"),
                      # only things you can own: a quest step ("150 Bucko Bee
                      # quests") is no gear-order name, and the Gear page
                      # listed it as "not a goal this list knows" (FOUND
                      # 2026-10-26, plan-all --demo check, Hybrid + Tide Popper)
                      "targets": [str(g.get("label") or g["id"])
                                  for g in hybrid.steps(tid, body)
                                  if g.get("id") and g.get("kind") in HAVE_KINDS]}
                for tid, t in hybrid.targets(body).items()}
    return {k: v for k, v in body.items() if isinstance(v, dict)}


def picks(target) -> list[str]:
    """Hybrid's picked target ids from `plan.target` ("fuzzy_alt, tad_alt")."""
    return [p for p in re.split(r"[,\s]+", str(target or "")) if p]


def alt_targets(choice: str, alts: dict | None = None, picked=()) -> list[str]:
    """The names an alt plan puts first. Hybrid: the `picked` targets' names
    (Fuzzy and Tad alt when none), each name once, in pick order."""
    alts = alt_goals() if alts is None else alts
    own = [str(t) for t in (alts.get(choice) or {}).get("targets") or [] if str(t).strip()]
    if own or choice != "hybrid":
        return own
    ids = [p for p in picked if p in alts and p != "hybrid"] or ["fuzzy_alt", "tad_alt"]
    return list(dict.fromkeys(n for i in ids for n in alt_targets(i, alts)))


def label(choice: str, alts: dict | None = None) -> tuple[str, str]:
    """(name, one line) for the Play page."""
    name, line = CHOICES.get(choice, CHOICES[CUSTOM])
    if choice in ALTS:
        entry = (alt_goals() if alts is None else alts).get(choice) or {}
        name, line = str(entry.get("label") or name), str(entry.get("line") or line)
    return name, line


# ---- what a plan writes -----------------------------------------------------
def giver_key(name) -> str | None:
    """'Bucko Bee' / 'bucko' / 'bucko_bee' -> 'quests.bucko'."""
    from ..act.bearvisit import GIVER_SETTINGS
    slug = _slug(name)
    for giver, key in GIVER_SETTINGS.items():
        if slug and slug in (giver, key.split(".", 1)[1]):
            return key
    return None


def hive_colour(var_root) -> tuple[str | None, str]:
    """(red/blue/white or None, why) from var/bees.json's counts.
    ASSUMED rule: a hive is the colour most of its coloured bees are, and
    white when colourless bees outnumber the red and blue together; a tie or
    no read says nothing."""
    bees = _json(Path(var_root) / "bees.json", {})
    counts = bees.get("bees") or {}
    if not counts:
        return None, "the hive has not been read yet"
    try:
        kinds = (_yaml(data_path("knowledge", "bee_types.yaml")) or {}).get("types") or {}
    except AttributeError:
        kinds = {}
    by = {"red": 0, "blue": 0, "colourless": 0}
    for bee, n in counts.items():
        colour = (kinds.get(bee) or {}).get("colour")
        if colour in by:
            by[colour] += int(n) if isinstance(n, (int, float)) and n > 0 else 1
    said = f"{by['red']} red, {by['blue']} blue, {by['colourless']} white bees"
    if by["colourless"] > by["red"] + by["blue"]:
        return "white", said
    if by["red"] == by["blue"]:
        return None, said
    return ("red" if by["red"] > by["blue"] else "blue"), said


def resolve(choice: str, target: str = "", var_root=None) -> dict:
    """{key: value} the plan wants. Unknown choice -> {} (custom)."""
    out = dict(RECIPES.get(choice) or {})
    if choice == "quests":
        key = giver_key(target)
        if key:
            out[key] = True
    if choice in ALTS:
        extra = (alt_goals().get(choice) or {}).get("on") or {}
        out.update({k: v for k, v in extra.items() if k in LIVE})
    if out and choice != "macro" and var_root is not None:
        colour, _why = hive_colour(var_root)
        if colour:
            out["progression.hive"] = colour
    return out


def targets(settings) -> list[str]:
    """The names the plan puts in front of the gear order: `plan.target` for
    'item', the alt list for the alt plans, nothing for the rest."""
    goal = str(settings.get("plan.goal") or CUSTOM)
    if goal == "item":
        target = str(settings.get("plan.target") or "").strip()
        return [target] if target else []
    if goal in ALTS:
        return alt_targets(goal, picked=picks(settings.get("plan.target")))
    return []


def prepend(settings, typed: list, data: dict) -> list:
    """goals.from_files' order with the plan's targets first. An empty typed
    order stands for goals.yaml's default_order, which is kept behind them."""
    first = targets(settings)
    if not first:
        return typed
    return list(dict.fromkeys(first + (list(typed) or list(data.get("default_order") or []))))


def with_targets(settings, data: dict) -> dict:
    """`data` with each plan target that only the progression files know
    (Supreme Star Amulet: not in goals.yaml or gear_prices.yaml) as a goal,
    so goals.from_files keeps it in the order instead of dropping it as an
    unknown name (FOUND 2026-10-26, plan-all --demo check: Fuzzy alt lost
    its SSA). No `shop` (progression.plan_entry): the bot never buys it."""
    from . import progression
    from .goals import goal_key
    goals = dict(data.get("goals") or {})
    for name in targets(settings):
        if goal_key(name, dict(data, goals=goals)) is not None:
            continue
        goal, _body = _find_goal(name)
        if goal is None or goal.get("kind") not in HAVE_KINDS:
            continue
        nxt = progression.Next(goal, "")
        if nxt.honey:
            goals[nxt.id] = progression.plan_entry(nxt, progression.hive_from(settings))
    return dict(data, goals=goals)


# ---- apply, give back, undo -------------------------------------------------
def _snapshot_path(config) -> Path:
    return Path(config).parent / SNAPSHOT


def snapshot(config: Path | str = CONFIG) -> dict:
    body = _yaml(_snapshot_path(config))
    return body if isinstance(body, dict) else {}


def apply(choice: str, target: str = "", config: Path | str = CONFIG,
          var_root=None, take=(), clock=time.time) -> dict:
    """Write the plan into the settings file. Returns
    {"changed": {key: (old, new)}, "kept": {key: (yours, plan's)}, "skipped": [...]}.
    `take`: keys the player gave back to the plan (written even if "yours").
    'custom' writes nothing at all."""
    if choice not in RECIPES:
        raise ValueError(f"no plan called {choice!r}")
    result = {"changed": {}, "kept": {}, "skipped": []}
    if choice == CUSTOM:
        return result
    wanted = resolve(choice, target, var_root)
    current = Settings(config).values
    snap = snapshot(config)
    last = snap.get("applied") or {}
    shipped = defaults()
    # THE INSTALLER'S SEED IS NOT "YOURS" (choose-design 2026-10-26: every new
    # install's settings.yaml is safe-first-run.yaml, mode.macro on and every
    # errand off, so a first plan click kept them all -- a silent no-op,
    # FOUND in the plan-gui --demo render). A key no plan wrote yet counts as
    # the player's only when it is neither the default nor the seed's value.
    seeded = _yaml(data_path("presets", "safe-first-run.yaml"))
    seeded = seeded if isinstance(seeded, dict) else {}
    write, applied = {}, {}
    for key, value in wanted.items():
        now = current.get(key, shipped.get(key))
        untouched = (now == last[key] if key in last
                     else now == shipped.get(key) or (key in seeded and now == seeded[key]))
        if now != value and not untouched and key not in take:
            result["kept"][key] = (now, value)
            continue
        applied[key] = value
        if now != value:
            write[key] = value
    target = str(target or "") if choice in ("item", "quests", "hybrid") else ""
    for key, value in (("plan.goal", choice), ("plan.target", target)):
        if current.get(key) != value:
            write[key] = value
    written, result["skipped"] = take_values(write, config)
    result["changed"] = {k: (current.get(k, shipped.get(k)), v) for k, v in written.items()}
    history = ([{k: snap[k] for k in ("goal", "target", "applied", "previous", "at") if k in snap}]
               if snap.get("goal") else []) + list(snap.get("history") or [])
    atomic_write(_snapshot_path(config), yaml.safe_dump({
        "goal": choice, "target": target, "applied": applied,
        "previous": {k: old for k, (old, _new) in result["changed"].items()},
        "at": float(clock()), "history": history[:HISTORY_MAX]}, sort_keys=True))
    return result


def undo(config: Path | str = CONFIG) -> dict:
    """Put back what the last apply changed. {key: value written back}; {}
    when there is nothing to undo."""
    snap = snapshot(config)
    if not snap.get("goal"):
        return {}
    written, _skipped = take_values(dict(snap.get("previous") or {}), config)
    history = list(snap.get("history") or [])
    back = dict(history[0], history=history[1:]) if history else {}
    atomic_write(_snapshot_path(config), yaml.safe_dump(back, sort_keys=True))
    return written


def conflicts(config: Path | str = CONFIG, var_root=None) -> dict:
    """{key: (yours, plan's)}: what the current plan wants that the file says
    otherwise -- the SKIP line."""
    settings = Settings(config)
    goal = str(settings.get("plan.goal") or CUSTOM)
    wanted = resolve(goal, str(settings.get("plan.target") or ""), var_root)
    return {k: (settings.get(k), v) for k, v in wanted.items() if settings.get(k) != v}


def uses(choice: str, target: str = "") -> list[str]:
    """The Features page's short names of what the plan switches on."""
    names = {k: lbl for _g, k, lbl, _t, _b in FEATURES}
    return [names[k] for k, v in resolve(choice, target).items()
            if v is True and k in names and k not in CORE_FEATURES]


# ---- set from far away (Telegram's /plan) ------------------------------------
def names(choice: str) -> list[str]:
    """The names a target can be for `choice`: the bears for 'quests', the
    progression files' items for 'item', nothing for the rest."""
    if choice == "quests":
        from ..act.bearvisit import GIVER_SETTINGS
        return [g.replace("_", " ").title() for g in GIVER_SETTINGS]
    if choice != "item":
        return []
    from . import progression
    out = []
    for hive in progression.HIVES:
        for _i, goal in progression._goals(progression.load(hive)):
            name = str(goal.get("label") or goal.get("name") or goal.get("id") or "")
            if name and name not in out:
                out.append(name)
    return out


def _closest(word: str, pool: list[str]) -> list[str]:
    """Up to 5 names nearest `word`, never a pick: the caller shows them."""
    by = {_slug(p): p for p in pool}
    return [by[k] for k in difflib.get_close_matches(_slug(word), list(by), n=5, cutoff=0.4)]


def check(choice: str, target: str = "") -> str:
    """"" when this plan can be set, else why not in plain words, with the
    closest names. An unknown name is never guessed."""
    choice = _slug(choice)
    if choice not in RECIPES:
        near = _closest(choice, list(RECIPES)) or list(RECIPES)
        return f"There is no plan called '{choice}'. Plans: {', '.join(near)}."
    target = str(target or "").strip()
    if not target or choice not in ("item", "quests"):
        return ""
    if (giver_key(target) if choice == "quests" else _find_goal(target)[0]):
        return ""
    near = _closest(target, names(choice))
    what = "bear" if choice == "quests" else "item"
    return (f"'{target}' is not a {what} Hivemind knows."
            + (f" Closest: {', '.join(near)}." if near else ""))


def remote(choice: str, target: str = "", config: Path | str = CONFIG,
           var_root=None) -> str:
    """Set the plan (or 'undo' the last one) and say what happened, in plain
    words. The running bot calls this for Telegram's /plan (run_farm's
    on_command, Action.SET_PLAN); it never asks, and always offers the undo."""
    choice, target = _slug(choice), str(target or "").strip()
    feature = {k: lbl for _g, k, lbl, _t, _b in FEATURES}
    if choice == "undo":
        back = undo(config)
        if not back:
            return "Nothing to undo: no plan was set here."
        return (f"Undone: {len(back)} switch(es) put back. The plan is now "
                f"{label(str(Settings(config).get('plan.goal') or CUSTOM))[0]}.")
    bad = check(choice, target)
    if bad:
        return bad + " Nothing was changed."
    if choice == CUSTOM:
        take_values({"plan.goal": CUSTOM, "plan.target": ""}, config)
        return "Plan: Your own setup. Your switches stay exactly as they are."
    out = apply(choice, target, config, var_root)
    name = label(choice)[0] + (f" ({target})" if target and choice in ("item", "quests") else "")
    flips = [feature.get(k, k) for k in out["changed"] if not k.startswith("plan.")]
    said = [f"Plan set: {name}.",
            (f"Turned {len(flips)} switch(es): {', '.join(flips[:6])}"
             + (" ..." if len(flips) > 6 else "") + ".") if flips
            else "No switch needed changing."]
    if out["kept"]:
        said.append("Left your own: "
                    + ", ".join(feature.get(k, k) for k in list(out["kept"])[:6]) + ".")
    if out["skipped"]:
        said.append(f"Could not write {len(out['skipped'])} switch(es).")
    said.append("Send /plan undo to put it back.")
    return " ".join(said)


# ---- what it is doing and why ------------------------------------------------
def _ago(at, now: float) -> str:
    try:
        mins = max(0, int((now - float(at)) // 60))
    except (TypeError, ValueError):
        return ""
    return (f"{mins} min ago" if mins < 120 else f"{mins // 60} h ago" if mins < 2880
            else f"{mins // 1440} days ago")


def _tail_rows(path: Path, n: int, size: int = 65536) -> list[dict]:
    """The last `n` JSON rows of a .jsonl without reading all of it."""
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - size))
            lines = f.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return []
    rows = []
    for line in lines[-(n + 1):]:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows[-n:]


def _find_goal(name: str):
    """(goal, its file's data) from the progression files, else (None, {})."""
    from . import progression
    want = _slug(name)
    for hive in progression.HIVES:
        body = progression.load(hive)
        for _i, goal in progression._goals(body):
            if want in {_slug(goal.get("id")), _slug(goal.get("label")),
                        _slug(goal.get("name"))}:
                return goal, body
    return None, {}


def _goal_rows(name: str, acct) -> list[dict]:
    """{"what", "state": yes/no/?} rows for one target: owned, then each
    `requires`. A requirement nothing can read is a '?' row, never a guess."""
    from . import progression
    goal, body = _find_goal(name)
    if goal is None:
        return [{"what": f"{name}: not in the item lists", "state": "?"}]
    done = progression.done(acct, goal, body)
    rows = [{"what": f"{goal.get('label') or name}: {done or 'not owned yet'}",
             "state": "yes" if done else "no",
             "item": str(goal.get("label") or name) if goal.get("kind") in HAVE_KINDS else ""}]
    for need in goal.get("requires") or []:
        ok, why = progression.requirement(acct, need, body)
        rows.append({"what": str(why or need), "state": {True: "yes", False: "no"}.get(ok, "?")})
    return rows


def status(var_root, settings=None, clock=time.time) -> dict:
    """{now, why, next, goal, proof} for the Play card, the bar chip and
    Telegram, from what the bot already wrote. Never raises on missing files:
    a part with nothing to say is "" or []."""
    from . import progression
    var_root = Path(var_root)
    settings = Settings() if settings is None else settings
    now_t = float(clock())
    choice = str(settings.get("plan.goal") or CUSTOM)
    target = str(settings.get("plan.target") or "")
    name, line = label(choice)
    colour, colour_why = hive_colour(var_root)
    goal = {"id": choice, "label": name, "line": line, "target": target,
            "hive": colour or progression.hive_from(settings),
            "hive_why": (f"guessed from the hive: {colour_why}" if colour
                         else f"from Settings ({colour_why})")}
    # NOW and WHY: the last trip's decision (run_farm's last_plan["decision"])
    now = why = ""
    trips = _tail_rows(var_root / "trips.jsonl", 1)
    if trips:
        row = trips[-1]
        field = row.get("chosen") or row.get("aimed_at") or ""
        when = _ago(row.get("at"), now_t)
        if field:
            now = f"Gathering at {field}" + (f" ({when})" if when else "")
        elif row.get("action"):
            now = f"{str(row['action']).capitalize()}" + (f" ({when})" if when else "")
        pick = next((c for c in row.get("candidates") or []
                     if isinstance(c, dict) and c.get("field") == field), {})
        why = str(pick.get("why") or row.get("reason") or "")
    # NEXT: the plan's target(s), else the progression's next goals
    acct = progression.account_from_files(var_root, settings)
    names = targets(settings)
    if choice == "quests" and target:
        nxt = [{"what": f"{target}'s quests first", "state": "yes" if giver_key(target) else "?"}]
    elif names:
        nxt = next((rows for rows in (_goal_rows(n, acct) for n in names)
                    if rows[0]["state"] != "yes"), [])
    else:
        try:
            prog = progression.progress(var_root, settings, n=3)
            nxt = [{"what": n.label, "state": "no",
                    "item": n.label if n.goal.get("kind") in HAVE_KINDS else ""}
                   for n in prog.next] + [
                {"what": c, "state": "?"} for n in prog.next[:1] for c in n.checks]
        except Exception:              # a broken research file never ends a status
            nxt = []
    # PROOF: what the bot has measured or done, newest first, each dated
    proof = []
    for row in reversed(_json(var_root / "purchases.json", [])[-3:]):
        if isinstance(row, dict) and row.get("ok"):
            proof.append(f"bought {row.get('item')} ({_ago(row.get('at'), now_t)})")
    for row in reversed(_tail_rows(var_root / "progression" / "milestones.jsonl", 3)):
        text = row.get("text") or row.get("milestone") or row.get("what")
        if text:
            proof.append(f"{text} ({_ago(row.get('at'), now_t)})")
    bees = _json(var_root / "bees.json", {})
    if bees.get("total"):
        proof.append(f"{bees['total']} bees in the hive ({_ago(bees.get('read_at'), now_t)})")
    return {"now": now, "why": why, "next": nxt, "goal": goal, "proof": proof}
