"""One zip that holds what the team needs to debug a run (RL6 task 3).

    python scripts/debug_bundle.py [--runs 3]
    (installed app: python\\python.exe scripts\\debug_bundle.py)

Writes var/debug-bundle-<date>-<time>.zip with:
  about.txt       OS, Python, Hivemind version, the light selftest checks
                  (packages, cv2.ml, data, tesseract), screen and Roblox window
                  size on Windows
  settings.yaml   the user's settings, every secret and the username blanked
  var/night/attempts.log, the newest --runs run-NNN.log, var/gui-run.log
  var/incidents/<newest>/   the newest incident folder (its frames)

NO SECRET GETS IN. Every value in telegram.env, discord.env and secrets.env,
server.yaml's private link (and its codes), and account.username is looked for
in every file: a text file has it replaced, any other file (a frame) is left
out. The value list is tools/team_sync.sh's (12 characters or more for the
.env values). tests/unit/test_debug_bundle.py fails if one gets through.

The frames show the user's game: send the zip privately (Telegram, a DM),
never in a public channel.
"""
from __future__ import annotations

import argparse
import os
import platform
import re
import sys
import time
import urllib.parse
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

import yaml  # noqa: E402

from hivemind import datapaths, selftest  # noqa: E402

ENV_FILES = ("telegram.env", "discord.env", "secrets.env")
# world/settings SECRET (kept here as names, so this tool need not import the
# settings schema) plus the username, which AGENTS.md rule 6 counts as private,
# and account.share_link: the Windows/alt join's private-server share link,
# which lets whoever holds it into the server and is a plain settings.yaml
# value, not a SECRET (found 2026-10-21 reviewing this tool).
PRIVATE_KEYS = ("stream.youtube_api_key", "server.link", "account.username",
                "account.share_link")
TEXT = {".log", ".txt", ".json", ".jsonl", ".yaml", ".yml", ".md", ".csv"}
BLANK, HIDDEN = "[blanked]", b"[secret]"


def secret_values(config: Path) -> list[str]:
    """Every value that must not leave the PC, longest first."""
    vals: list[str] = []
    for name in ENV_FILES:
        try:
            lines = (config / name).read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            _, _, v = line.partition("=")
            v = v.strip().strip('"')
            if len(v) >= 12:
                vals.append(v)
    server = _yaml(config / "server.yaml")
    link = str(server.get("private_link") or "")
    if link:
        vals.append(link)
        vals += [v for vs in urllib.parse.parse_qs(urllib.parse.urlparse(link).query).values()
                 for v in vs if len(v) >= 12]
    settings = _yaml(config / "settings.yaml")
    private = [str(settings[k]) for k in PRIVATE_KEYS
               if settings.get(k) and len(str(settings[k])) >= 3]
    vals += private
    # A link's own codes too: the bot logs a share link's code inside the
    # roblox:// URI it opens (platform/lastserver.ShareLink.uri), not the link.
    vals += [v for link in private
             for vs in urllib.parse.parse_qs(urllib.parse.urlparse(link).query).values()
             for v in vs if len(v) >= 12]
    return sorted(set(vals), key=len, reverse=True)


def _yaml(path: Path) -> dict:
    try:
        got = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return got if isinstance(got, dict) else {}


def clean(name: str, data: bytes, pattern: re.Pattern | None) -> bytes | None:
    """`data` with every secret hidden, or None when it cannot be (not text)."""
    if pattern is None or not pattern.search(data):
        return data
    if Path(name).suffix.lower() not in TEXT:
        return None
    return pattern.sub(HIDDEN, data)


def blanked_settings(config: Path) -> bytes:
    settings = _yaml(config / "settings.yaml")
    for key in PRIVATE_KEYS:
        if key in settings:
            settings[key] = BLANK
    return yaml.safe_dump(settings, sort_keys=True, allow_unicode=True).encode("utf-8")


def screen_lines() -> list[str]:
    """Screen and Roblox window sizes, from win/_user32's verified calls."""
    if os.name != "nt":
        return ["screen: only read on Windows"]
    lines: list[str] = []
    try:
        from hivemind.platform.win import _user32 as w
        from hivemind.platform.win.session import WINDOW_TITLE
        u = w.dll("user32")
        w.dpi_aware(u)                                # physical pixels, as the bot sees them
        lines.append(f"virtual screen (x, y, w, h): {w.virtual_screen(u)}")
        # ponytail: GetDpiForSystem (Windows 10 1607+) is not in _user32's
        # verified signatures; UNVERIFIED until a Windows run shows its line.
        dpi = getattr(u, "GetDpiForSystem", None)
        if dpi is not None:
            got = int(dpi())
            lines.append(f"system DPI: {got} (scale {got / 96:.0%})")
        found = 0
        for hwnd in w.top_windows(u):
            if w.window_title(u, hwnd) == WINDOW_TITLE and u.IsWindowVisible(hwnd):
                found += 1
                lines.append(f"Roblox window: rect {w.window_rect(u, hwnd)}, client "
                             f"{w.client_size(u, hwnd)}, monitor {w.monitor_rect(u, hwnd)}, "
                             f"fills it: {w.fills_its_monitor(u, hwnd)}")
        if not found:
            lines.append("Roblox window: none open")
    except Exception as exc:                          # a bundle without this line still helps
        lines.append(f"screen: could not read ({type(exc).__name__}: {exc})")
    return lines


def about() -> str:
    lines = [f"made {time.strftime('%Y-%m-%d %H:%M:%S %z')}",
             f"os: {platform.platform()}",
             f"python: {sys.version.split()[0]} {sys.executable}",
             f"utf8 mode: {sys.flags.utf8_mode}"]
    light = tuple(c for c in selftest.CHECKS if c[0] in
                  ("python packages", "opencv ml", "data files", "tesseract"))
    selftest.run(light, say=lines.append)
    try:
        import numpy
        lines.append(f"numpy {numpy.__version__}")
    except ImportError:
        pass
    return "\n".join(lines + screen_lines()) + "\n"


def pick(var: Path, runs: int) -> list[Path]:
    """The files to send, oldest log first."""
    night = var / "night"
    chosen = [p for p in (night / "attempts.log", var / "gui-run.log") if p.is_file()]
    logs = sorted(night.glob("run-*.log"))
    chosen += logs[-runs:] if runs > 0 else []
    incidents = [d for d in (var / "incidents").glob("*") if d.is_dir()]
    if incidents:
        newest = max(incidents, key=lambda d: d.stat().st_mtime)
        chosen += sorted(p for p in newest.rglob("*") if p.is_file())
    return chosen


def build(out: Path, var: Path, config: Path, runs: int = 3,
          about_text: str | None = None) -> tuple[Path, list[str]]:
    """Write the zip; returns it and the names left out because of a secret."""
    vals = secret_values(config)
    pattern = (re.compile(b"|".join(re.escape(v.encode("utf-8")) for v in vals), re.I)
               if vals else None)
    left_out: list[str] = []
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        members = [("about.txt", (about_text if about_text is not None else about()).encode("utf-8")),
                   ("settings.yaml", blanked_settings(config))]
        for path in pick(var, runs):
            try:
                members.append(("var/" + path.relative_to(var).as_posix(), path.read_bytes()))
            except OSError:
                continue
        for name, data in members:
            kept = clean(name, data, pattern)
            if kept is None:
                left_out.append(name)
            else:
                z.writestr(name, kept)
        if left_out:
            z.writestr("left-out.txt", "left out, they held a secret:\n" + "\n".join(left_out) + "\n")
    return out, left_out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--runs", type=int, default=3, help="how many run-NNN.log to include")
    args = ap.parse_args(argv)
    out = datapaths.var(f"debug-bundle-{time.strftime('%Y%m%d-%H%M%S')}.zip")
    path, left_out = build(out, datapaths.VAR_ROOT, datapaths.config_dir(), args.runs)
    print(f"wrote {path} ({path.stat().st_size // 1024} KB)")
    if left_out:
        print(f"left out {len(left_out)} file(s) that held a secret (listed in left-out.txt)")
    print("It holds frames of your game: send it privately, never in a public channel.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
