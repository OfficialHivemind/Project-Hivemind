"""Settings from the owner's phone: Telegram /settings, /set and /preset
(ROADMAP tgset; remote control is a paid feature elsewhere, free here).

WHO WRITES. The running bot, never scripts/telegram_alerts.py: /set and
/preset travel as a socket Command (Action.SET_SETTING / SET_PRESET) and
run_farm's on_command calls `set_one` / `apply_preset` here -- the same path
/plan takes (brain/plan.remote), behind the same telegram.commands switch.
/settings only reads, and runs as `python -m hivemind.world.remote_settings`
on the venv: the alerts service runs on /usr/bin/python3, which has no PyYAML
(MEASURED 2026-10-27: importing world.settings there raises
ModuleNotFoundError), so it cannot read the schema itself.

NEVER FROM THE PHONE (`denied`): a secret, a LOCKED key, a NOT_IN_PRESETS key
(world/settings), and the DENY lists below -- the account and this PC, the
safety rails, the spending limits, anything that could show private data,
and Telegram's own switches (so a phone cannot widen its own reach). Their
values are not shown either. Nothing in the schema spends Robux (AGENTS.md
rule 1); a key that ever names Robux is refused by name all the same.
"""
from __future__ import annotations

import difflib
import math
import sys
from pathlib import Path

import yaml

from ..files import read_text
from .settings import (CONFIG, FEATURE_GROUPS, FEATURES, LISTS, LOCKED,
                       NOT_IN_PRESETS, SECRET, SECTIONS, Settings, feature_off,
                       settle, take_values, takes_effect)

DENY_PREFIX = {
    "account.": "your Roblox account and its join link",
    "server.": "which server it joins (private links live there)",
    "platform.": "this PC's setup",
    "gui.": "this PC's window",
    "perf.": "this PC's speed and memory",
    "storage.": "this PC's disk",
    "stream.": "the stream's privacy and chat",
    "telegram.": "what Telegram may see and do",
    "safety.": "a safety rail (panic key, never chat, session cap)",
    "guard.": "the game guard (never beside another game)",
    "autonomy.": "the spending and confidence limits",
    "eggs.": "a safeguard on rare eggs",
    "plan.": "the plan: use /plan",
}
DENY_KEYS = {
    "move.hive_slot": "your hive slot, a fact about your account",
    # the bee menu's gifted Hasty read sets the speed (memory: never by hand)
    "move.walkspeed": "your measured walking speed",
}
SHOWN_MAX = 25                    # /settings <word>: rows in one message


def _entries() -> dict[str, tuple]:
    return {e[0]: e for _, es in SECTIONS for e in es}


def denied(key: str) -> str:
    """Why `key` may not be read or changed from Telegram, or ""."""
    if "robux" in key.lower():
        return "it would spend Robux"
    if key in SECRET:
        return "it is a secret"
    if key in LOCKED:
        return "it is locked"
    if key in NOT_IN_PRESETS:
        return "it belongs to this PC"
    if key in DENY_KEYS:
        return DENY_KEYS[key]
    for prefix, why in DENY_PREFIX.items():
        if key.startswith(prefix):
            return why
    return ""


def parse(key: str, text: str):
    """(the value, "") or (None, why not) for /set's words; never guessed."""
    entry = _entries()[key]
    kind, text = entry[2], str(text).strip()
    if kind == "bool":
        word = text.lower()
        if word in ("on", "true", "yes", "1"):
            return True, ""
        if word in ("off", "false", "no", "0"):
            return False, ""
        return None, f"{key} is on or off, not '{text}'."
    if kind in ("int", "float"):
        try:
            number = float(text.replace(",", "").replace("_", "").rstrip("%"))
        except ValueError:
            number = math.nan
        if not math.isfinite(number):     # 'nan'/'inf' parse as floats
            return None, f"{key} is a number, not '{text}'."
        if kind == "int" and number != int(number):
            return None, f"{key} is a whole number, not '{text}'."
        return (int(number) if kind == "int" else number), ""
    if kind == "choice":
        for choice in entry[5]:
            if choice.lower() == text.lower():
                return choice, ""
        return None, f"{key} is one of: {', '.join(entry[5])}."
    return text, ""


def _show(value) -> str:
    return "on" if value is True else "off" if value is False else str(value)


def set_one(key: str, text: str, config: Path | str = CONFIG) -> str:
    """/set <key> <value>: write one setting and say what changed, in plain
    words; the old value is in the answer, so /set puts it back."""
    key = str(key or "").strip().lower()
    entries = _entries()
    if key not in entries:
        near = difflib.get_close_matches(key, [k for k in entries if not denied(k)], 3)
        return (f"There is no setting called '{key}'."
                + (f" Closest: {', '.join(near)}." if near else "")
                + " /settings <word> finds the names. Nothing was changed.")
    why = denied(key)
    if why:
        return f"{key} cannot be changed from Telegram: {why}. Nothing was changed."
    if key in LISTS:
        return f"{key} is a list: change it in Hivemind. Nothing was changed."
    value, bad = parse(key, text)
    if bad:
        return bad + " Nothing was changed."
    used, note = settle(key, value)
    before = Settings(config).get(key)
    if before == used:
        return f"{entries[key][1]} ({key}) is already {_show(used)}. Nothing was changed."
    take_values({key: used}, config, allowed={key})
    return (f"Set: {entries[key][1]} ({key}) {_show(before)} -> {_show(used)}, "
            f"{takes_effect(key)}." + (f" ({note})" if note else "")
            + f" To put it back: /set {key} {_show(before)}")


def preset_dir(config: Path | str = CONFIG) -> Path:
    """The window's presets folder (gui/shell._preset_dir), beside settings.yaml."""
    return Path(config).parent / "presets"


def preset_names(config: Path | str = CONFIG) -> list[str]:
    try:
        return sorted(p.stem for p in preset_dir(config).glob("*.yaml"))
    except OSError:
        return []


def apply_preset(name: str, config: Path | str = CONFIG) -> str:
    """/preset <name>: a saved preset into the file, as the window's preset
    switcher loads it (world/settings.take_values), without the keys
    `denied` keeps from the phone."""
    names = preset_names(config)
    want = " ".join(str(name or "").split()).lower()
    match = [n for n in names if n.lower() == want]
    if not match:
        return ((f"There is no preset called '{name}'. Presets: {', '.join(names)}."
                 if names else "There are no saved presets: save one in Hivemind "
                 "(Preset > Save current as preset).") + " Nothing was changed.")
    try:
        loaded = yaml.safe_load(read_text(preset_dir(config) / f"{match[0]}.yaml"))
    except (OSError, yaml.YAMLError) as exc:
        return f"The preset {match[0]} could not be read ({type(exc).__name__}). Nothing was changed."
    if not isinstance(loaded, dict):
        return f"{match[0]} is not a Hivemind preset. Nothing was changed."
    now = Settings(config)
    kept = sorted(k for k in loaded if denied(k))
    take = {k: v for k, v in loaded.items() if not denied(k)}
    written, skipped = take_values(take, config)
    changed = [k for k, v in written.items() if now.get(k) != v]
    return (f"Preset {match[0]} loaded: {len(changed)} setting(s) changed"
            + (f" ({', '.join(changed[:6])}{' ...' if len(changed) > 6 else ''})" if changed else "")
            + f", {len(written)} written."
            + (f" Left as they are: {len(kept) + len(skipped)} setting(s) Telegram may not "
               "change (account, PC, safety) or this version does not know."
               if kept or skipped else ""))


def overview(config: Path | str = CONFIG) -> str:
    """/settings: the plan, the field, and the Features page's switches by
    group -- which are on by name, how many are off."""
    s = Settings(config)
    lines = [f"Plan: {s.get('plan.goal') or 'custom'}"
             + (" · Macro mode" if s.get("mode.macro") else " · AI mode")
             + f" · field {s.get('gather.field')} · convert at {s.get('gather.convert_at')}%"]
    for group in FEATURE_GROUPS:
        rows = [(key, label) for g, key, label, _l, _b in FEATURES if g == group]
        on = [label for key, label in rows if s.get(key) != feature_off(key)]
        lines.append(f"{group}: " + (", ".join(on) if on else "all off")
                     + (f" ({len(rows) - len(on)} off)" if on and len(rows) > len(on) else ""))
    if presets := preset_names(config):
        lines.append("Presets: " + ", ".join(presets) + " (/preset <name>)")
    lines.append("/settings <word> shows each with its name, /set <name> <value> changes one.")
    return "\n".join(lines)


def find(word: str, config: Path | str = CONFIG) -> str:
    """/settings <word>: matching settings as `name = value  label`; a key
    `denied` here shows no value."""
    s, word = Settings(config), str(word).strip().lower()
    hits = [e for e in _entries().values()
            if word in e[0].lower() or word in e[1].lower() or word in e[4].lower()]
    if not hits:
        return f"No setting matches '{word}'. /settings shows the main switches."
    rows = [f"{e[0]} = " + ("(not from Telegram)" if denied(e[0]) else
                            "(a list)" if e[0] in LISTS else _show(s.get(e[0])))
            + f"  {e[1]}" for e in hits[:SHOWN_MAX]]
    if len(hits) > SHOWN_MAX:
        rows.append(f"... and {len(hits) - SHOWN_MAX} more: try a longer word.")
    return "\n".join(rows)


if __name__ == "__main__":       # telegram_alerts' /settings [word] --config PATH
    args = sys.argv[1:]
    path = CONFIG
    if "--config" in args:
        at = args.index("--config")
        path, args = Path(args[at + 1]), args[:at] + args[at + 2:]
    print(find(" ".join(args), path) if args else overview(path))
