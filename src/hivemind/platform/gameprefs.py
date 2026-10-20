"""The game's OWN settings (ROADMAP gameprefs): the Roblox menu settings that
break the bot, read from the file Roblox saves them in, each named with its
fix in plain words. `hivemind doctor` and every start (run_farm) say them.

WHERE THE FILE IS:
  Linux (Sober): ~/.var/app/org.vinegarhq.Sober/data/sober/appData/
      GlobalBasicSettings_13.xml -- MEASURED 2026-10-26 on the owner's PC
      (written by the game at 18:23 that day, 98 lines, one UserGameSettings
      item). The number is the file format's; the newest-numbered file wins.
  Windows: %LOCALAPPDATA%\\Roblox\\GlobalBasicSettings_13.xml -- ASSUMED
      (the Roblox player's usual place; not yet seen on the Windows test PC).

WHAT IS RIGHT is what the bot was built and measured on, not a guess: the
owner's file, MEASURED 2026-10-26, holds ControlMode 1, ComputerCameraMovement
Mode 0, ComputerMovementMode 0, CameraYInverted false, PreferredTextSize 1,
SavedQualityLevel 10, FramerateCap 240, PerformanceStatsVisible false,
OnScreenProfilerEnabled false -- and every route, timing and screen box in
this repo was measured with it like that. Enum numbers are Roblox's own
(create.roblox.com engine enums, read 2026-10-26).

Not checked: Fullscreen. Our own session makes the window fullscreen on both
platforms (platform/wlr_session RC_XML, platform/win/session
fullscreen_focused), whatever the game's own switch says.

THE FIX (`guard.fix_game_settings`, default OFF) writes only the settings
with one safe right value, only while the game is closed (Roblox writes the
file itself and would put the old values back), after a dated backup beside
it. The frame-rate cap and graphics level are never written: which value is
best is not measured yet (a timing test at 60 vs 240 comes first).
"""
from __future__ import annotations

import os
import re
import shutil
import time
from pathlib import Path

SOBER_DIR = Path.home() / ".var/app/org.vinegarhq.Sober/data/sober/appData"
WINDOWS = os.name == "nt"
VALUE = re.compile(r'(<(bool|int|token|float|string) name="([^"]+)">)([^<]*)(</\2>)')

CAMERA = {"2": "Follow", "3": "Orbital", "4": "Camera Toggle"}
TEXT = {"2": "Large", "3": "Larger", "4": "Largest"}

# setting -> (is it right?, the value the fix writes or None, what is wrong,
# the fix in plain words, does it break the bot outright?)
RULES = {
    # MEASURED: act/routes._shift_lock and nav/journey tap Shift and
    # world/bearings flips its shift-lock state on each tap (22 shift_lock
    # steps in data/world/paths.yaml; "shift lock off" 1,800+ times in the
    # last 40 run logs). With the switch off (ControlMode 0, Classic) the tap
    # does nothing, the bot believes the opposite and A/D walk the wrong way.
    "ControlMode": (lambda v: v == "1", "1", lambda v: "Shift Lock Switch is off",
                    "in Roblox's Settings turn Shift Lock Switch On. The bot presses "
                    "Shift to lock the camera on its walks; with the switch off that "
                    "does nothing and it walks the wrong way", True),
    # Follow/Orbital/Toggle turn the camera by themselves (ASSUMED from the
    # mode names); the counted camera taps that set a heading (act/routes
    # CAMERA_KEYS, comma/period) assume it stays where they left it.
    "ComputerCameraMovementMode": (
        lambda v: v in ("0", "1"), "0",
        lambda v: f"Camera Mode is {CAMERA.get(v, v)}",
        "in Roblox's Settings set Camera Mode to Default (Classic). Other modes "
        "turn the camera by themselves and the bot's walks lose their heading", True),
    # ClickToMove: a click in the world walks the character there (Roblox's
    # documented behaviour) -- and the bot clicks the world to collect.
    "ComputerMovementMode": (
        lambda v: v != "2", "0", lambda v: "Movement Mode is Click to Move",
        "in Roblox's Settings set Movement Mode to Default. With Click to Move "
        "every click the bot makes walks your character somewhere", True),
    # ASSUMED: inverting also flips the PageUp/PageDown tilt the routes use
    # (act/routes CAMERA_KEYS "up"/"down"); not tried.
    "CameraYInverted": (
        lambda v: v == "false", "false", lambda v: "Invert Camera is on",
        "in Roblox's Settings turn Camera Inverted Off. The bot tilts the camera "
        "the way it was measured, which inverted is the other way", False),
    # Overlays over the picture the bot reads (ASSUMED: drawn over the game).
    "PerformanceStatsVisible": (
        lambda v: v == "false", "false", lambda v: "Performance Stats are showing",
        "in Roblox's Settings turn Performance Stats Off (Shift+F5 in the game "
        "also hides them). They cover part of the screen the bot reads", False),
    "OnScreenProfilerEnabled": (
        lambda v: v == "false", "false", lambda v: "the Micro Profiler is showing",
        "press Ctrl+F6 in the game to hide the Micro Profiler. It covers the top "
        "of the screen the bot reads", False),
    # ASSUMED: bigger text moves the Roblox menus the join and the bot's
    # menu reads click on, which were all measured at Medium.
    "PreferredTextSize": (
        lambda v: v == "1", "1", lambda v: f"Text Size is {TEXT.get(v, v)}",
        "in Roblox's Settings set Text Size to Medium. The menus the bot reads "
        "were measured at Medium, and bigger text moves them", False),
    # Never written: lower is easier on a weak PC, and nothing has measured
    # whether the screen reads hold at other levels (ASSUMED they may not).
    "SavedQualityLevel": (
        lambda v: v == "10", None,
        lambda v: f"Graphics Quality is {'Automatic' if v == '0' else v}",
        "every screen read was measured at Graphics Quality 10 and other levels "
        "are untested. If the bot misreads things, try 10 in Roblox's Settings", False),
    # Never written: walk timing at 60 vs 240 is not measured yet. Under 60
    # the frames the bot compares (flow, haste) are far apart. 0/-1 = no cap
    # (ASSUMED).
    "FramerateCap": (
        lambda v: not v.lstrip("-").isdigit() or int(v) <= 0 or int(v) >= 60, None,
        lambda v: f"Maximum Frame Rate is {v}",
        "in Roblox's Settings set Maximum Frame Rate to 60 or more. The bot was "
        "measured at 240 and its movement checks compare frames", False),
}


def settings_file(home: Path | None = None) -> Path | None:
    """The newest-numbered GlobalBasicSettings_<n>.xml, or None."""
    if home is None:
        home = (Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Roblox"
                if WINDOWS else SOBER_DIR)
    # THE GAME'S FILE, NOT STUDIO'S. MEASURED 2026-10-27 on a Windows PC with
    # Roblox Studio: %LOCALAPPDATA%\Roblox holds GlobalBasicSettings_13.xml
    # AND GlobalBasicSettings_13_Studio.xml; the old *.xml glob tied them on
    # 13 and the name order put Studio's last, so its settings were judged.
    files = sorted((p for p in home.glob("GlobalBasicSettings_*.xml")
                    if re.fullmatch(r"GlobalBasicSettings_\d+", p.stem)),
                   key=lambda p: int(p.stem.rsplit("_", 1)[1]))
    return files[-1] if files else None


def read(path: Path) -> dict[str, str]:
    """Every saved setting -> its text value."""
    return {m.group(3): m.group(4) for m in VALUE.finditer(path.read_text(encoding="utf-8"))}


def problems(values: dict[str, str]) -> list[tuple[str, str, str, bool]]:
    """(setting, what is wrong, the fix, breaks the bot) for each wrong one.
    A setting missing from the file is not flagged (ASSUMED: the game's own
    default then, right for the breaking rules; every rule is in the owner's
    MEASURED file, so a missing one has not been seen)."""
    out = []
    for name, (right, _, wrong, fix, breaks) in RULES.items():
        if name in values and not right(values[name]):
            out.append((name, wrong(values[name]), fix, breaks))
    return out


def game_running() -> bool:
    """Is the game open? Unsure counts as open: the fix never writes then."""
    if WINDOWS:
        return True     # ponytail: no Windows write yet; add after the Windows test PC shows the file
    from .startfails import flatpak_instances
    out = flatpak_instances()
    return not (out == "(nothing, exit 0)" or
                (not out.startswith("(") and "org.vinegarhq.Sober" not in out))


def fix(path: Path, running=game_running) -> str:
    """Write the safe right value of each wrong setting, with a backup.
    Returns what it did, in a few words."""
    values = read(path)
    todo = {n: RULES[n][1] for n, *_ in problems(values) if RULES[n][1] is not None}
    if not todo:
        return "nothing it can fix"
    if running():
        return "the game is open, so nothing was written: close it and start again"
    backup = path.with_name(f"{path.name}.hivemind-{time.strftime('%Y%m%d-%H%M%S')}")
    shutil.copy2(path, backup)
    text = VALUE.sub(lambda m: m.group(1) + todo.get(m.group(3), m.group(4)) + m.group(5),
                     path.read_text(encoding="utf-8"))
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return f"set {', '.join(f'{n} {v}' for n, v in todo.items())} (backup {backup.name})"


def start_lines(fix_on: bool, path: Path | None = None, running=game_running) -> list[str]:
    """What a start says about the game's settings, one line each."""
    path = path or settings_file()
    if path is None:
        return ["no saved Roblox settings found yet (the game writes them on its "
                "first launch), so they are not checked"]
    try:
        found = problems(read(path))
        if found and fix_on:
            done = fix(path, running)
            found = problems(read(path))
            lines = [f"fixing them: {done}"]
        else:
            lines = []
    except OSError as exc:
        return [f"could not read {path.name} ({exc})"]
    if not found:
        return lines + ["all as the bot was measured with"]
    return lines + [f"{'BREAKS THE BOT: ' if breaks else ''}{wrong} -- {how}"
                    for _, wrong, how, breaks in found]
