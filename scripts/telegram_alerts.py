#!/usr/bin/env python3
"""Telegram alerts for the owner, through their own bot (@my_hive_bot).

Tails the newest var/night/run-*.log and sends the lines they would act on or
want to hear about; says once when the farm has been down 10 minutes without
their STOP, and again when it is back. Pure stdlib, read-only on the bot.

WHAT IS SENT is their choice: the telegram.* switches of settings.yaml (the GUI's
Telegram tab), read again at every alert, so a switch counts at once. Each
alert carries one of those keys as its kind.

The token and the chat live in ~/.config/hivemind/telegram.env (chmod 600):
TELEGRAM_TOKEN=... and TELEGRAM_CHAT=..., the chat learned from the first
private message they send the bot (or the Telegram tab's Detect chat). Runs as
the systemd user service hivemind-telegram, on /usr/bin/python3.

  telegram_alerts.py            watch and alert (the service)
  telegram_alerts.py --send T   send T once (the build loop's own messages)
  telegram_alerts.py --listen   print their messages to the bot (Claude's monitor)
                                and answer their commands (/status, /pause...)
  telegram_alerts.py --check    the patterns against sample log lines
  telegram_alerts.py --discord-test   one test post to the Discord webhook

THE OUTBOX: a send that fails for the network is kept in var/outbox.jsonl and
sent again by the watch (`outbox_flush`), so an outage delays an alert
instead of losing it. The watch also starts the hourly stats card
(telegram.hourly_card, off by default) at the top of each hour.

DISCORD (ROADMAP U21, viewer mouseinapizzabox): the same alerts also go to the
user's OWN Discord webhook when ~/.config/hivemind/discord.env (chmod 600)
holds DISCORD_WEBHOOK=https://discord.com/api/webhooks/... and, optionally,
DISCORD_PING=<a Discord user id to mention>. The URL is a secret: never
printed, never in an error.
"""
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
from hivemind.datapaths import config_dir, runtime_dir, var  # noqa: E402  (stdlib only)
# HIVEMIND_TELEGRAM_ENV: another file, for tests and offscreen renders, which
# must never read or write the real token.
ENV = Path(os.environ.get("HIVEMIND_TELEGRAM_ENV")
           or config_dir() / "telegram.env")
SETTINGS = config_dir() / "settings.yaml"
NIGHT = Path.home() / "Hivemind/var/night"
# THE BOT'S OWN RESULT LINES, as the stream's toasts read them (stream/show
# CAPTURED ... HANDED_IN) -- one set of patterns. hivemind.stream.show imports
# on the system python (stdlib only, 2026-10-14; --check says so); if a change
# there ever breaks that, those alerts go quiet and the rest still work.
try:
    from hivemind.stream import show
except Exception as exc:                     # never costs the alerts below
    show = None
    print(f"telegram: no result-line alerts (hivemind.stream.show: "
          f"{type(exc).__name__}: {exc})", file=sys.stderr, flush=True)

# A PICTURE TOO, for these (the owner asked for a screenshot of any
# Mythic bee, 2026-10-09): the live view at that moment, with the caption.
MYTHICS = "Buoyant|Fuzzy|Precise|Spicy|Tadpole|Vector"
# (kind -- the settings key that switches it --, log pattern, message -- {0}
# is the pattern's first group --, seconds before the same pattern is sent
# again, as a picture). The first match in a line is the one sent.
ALERTS = [
    # a Mythic is sent whatever telegram.royal_jelly says: the master switch only
    ("telegram.alerts", rf"now holds the ({MYTHICS}) Bee",
     "MYTHIC BEE! A Royal Jelly roll just made a {0} Bee.", 0, True),
    # THE GIFTED BASIC GRINDER STOPPING (ROADMAP H16, brain/grinder.STOPPED):
    # a gifted Basic, a lucky roll kept, or the session's budget spent -- the
    # master switch only, with a picture, and a Discord ping (PING_IF)
    ("telegram.alerts", r"^gifted basic grinder: STOPPED — (.+)$",
     "Gifted Basic grinder stopped: {0}", 0, True),
    # A RARE DROP (ROADMAP TG4, brain/itemreport.rare_lines): an item of
    # data/knowledge/rare_drops.yaml whose count a later read confirmed rose;
    # the item and its count only. No picture: it is an hour after the drop.
    ("telegram.alerts", r"^rare drop: (.+)$", "Rare drop: {0}", 0, False),
    # WHAT THE BOT DECIDED ON ITS OWN, said not asked (the owner, 2026-10-26, asked
    # for fewer questions; brain/owned
    # decided_line, brain/goals): every one, so no gap
    ("telegram.needs_you", r"^(?:goals|owned|progression): decided: (.+)$",
     "Decided on its own: {0}", 0, False),
    # a goal whose honey is there: once each time it becomes affordable
    ("telegram.purchases", r"^goals: ((?:Ready to buy|The honey for) .+)$", "{0}", 0, False),
    ("telegram.terms", r"Updated Agreements", "Roblox wants its new terms accepted. "
     "Open Roblox on your phone and press I Agree; the bot tries again every 15 min.", 3600, False),
    ("telegram.rejoin", r"asking for a rejoin", "Stranded with pollen, so it is "
     "rejoining the server (the Wealth Clock streak restarts).", 1800, False),
    # A DISCONNECT AND WHAT COMES NEXT (ROADMAP A10, run_farm stop_for_loss and
    # the start's network wait): one line each, "disconnect:" / "network:"
    ("telegram.rejoin", r"^\s*disconnect: (?:the Roblox client's log says )?(.+)$",
     "Disconnected: {0}", 60, False),
    ("telegram.rejoin", r"^\s*network: (.+)$", "Network: {0}", 0, False),
    # THE RUN STUCK (run_farm main_stalled, telemetry/stallwatch): one line
    ("telegram.error", r"^\s*stall: the run (.+?) — it looks stuck",
     "The bot looks stuck: the run {0}.", 1800, False),
    # a knock-out is told 2-4 times within 26 s (stream/show DEATH_TOAST_GAP_SECONDS)
    ("telegram.knocked_out", r"^died: .*?([\d,]+) (?:pollen )?lost",
     "Knocked out: {0} pollen lost.", 60, False),
    ("telegram.error", r"Traceback", "The bot hit an error; the watchdog restarts it.", 1800, False),
    # telemetry/storage.LOW_DISK_LINE: said once a process, sent once a day
    ("telegram.error", r"^low disk: ([\d.]+) GB free", "The disk is nearly full ({0} GB "
     "free): the bot has stopped saving debug frames. Free some space, or set "
     "Advanced > Storage.", 86400, False),
    # THE MEMORY GATE REFUSING A START (ROADMAP A31): 18 Oct runs 1060-1066
    # never got in, swap full and ~6 GB free, and nobody was told
    ("telegram.error", r"memory: not enough memory to start the game: ([\d.]+) GB available",
     "Not enough free memory to start the game ({0} GB free). Close what you are "
     "not using (Steam, OBS, browser tabs); the bot keeps retrying by itself.", 3600, False),
    ("telegram.quest", r"Ant Challenge: .*the challenge is over",
     "Played the Ant Challenge (for the Army Ants quest).", 0, False),
    ("telegram.self_review", r"self-review: (.+)$", "{0}", 0, False),   # laid out by review_text
    # THE DAY'S PROGRESSION PROOF (telemetry/milestones.summary), once a day:
    # the master switch only. The per-milestone lines have no date and stay
    # in the feed (a purchase already has its own "Bought" line).
    ("telegram.alerts", r"^progress proof: (\d{4}-\d\d-\d\d: .+)$",
     "Progress proof for {0}", 0, False),
    # the game guard's pause (platform/gameguard, A14): the master switch, as a
    # pause they must undo themselves is never optional news
    ("telegram.alerts", r"^game guard: (paused: .+)$", "{0}", 0, False),
    # S3, telemetry/readhealth BREAK_LINE: many reads broke at once (safe mode
    # or paused) -- they must look, so a needs-you ping with the live view; and
    # DRIFT_LINE, a template's score sliding over days -- quiet, once a day
    ("telegram.needs_you", r"^game update\? (the game may have updated: .+)$",
     "{0}. Check the frames, then re-cut the templates or press Resume.", 1800, True),
    ("telegram.alerts", r"^read drift: (.+)$", "Early warning, reads drifting: {0}", 86400, False),
    ("telegram.royal_jelly", r"autojelly on' -- answered No", "Royal Jelly roll skipped: "
     "Auto-Jelly is ON. Turn it off (Settings tab, near the bottom) and the bot rolls "
     "one at a time.", 21600, False),
] + ([
    ("telegram.quest", show.HANDED_IN, "Quest handed in at the {0}.", 0, False),
    ("telegram.commando", show.CAPTURED, "Commando Chick captured after {0} min of fighting.", 0, False),
    ("telegram.blender", show.CRAFTED, "The Blender crafted {0} {1}.", 0, False),
    ("telegram.planter", show.HARVESTED, "Harvested the {0} in the {1} field.", 0, False),
    ("telegram.planter", show.PLANTED, "Planted a {0} in the {1} field.", 0, False),
    # WITH THE PRICE (ROADMAP TG11): "Bought: Hive Slot." hid a 2.0B spend
    # from the owner on 2026-10-15; the panel's own words carry the price
    ("telegram.purchases", r"^buying [^:]+: bought it — '([^|']+?)\s*\|\s*([^|']+?)\s*\|",
     "💸 Bought: {0} for {1}.", 0, False),
    ("telegram.purchases", show.BOUGHT, "Bought: {0}.", 0, False),
    ("telegram.royal_jelly", show.ROLLED, "Royal Jelly: a {1} ({0} rolled).", 0, False),
] if show else [])
# THE SWITCHES' DEFAULTS, as world/settings SECTIONS declares them (a test
# holds the two equal): this python cannot import that module (PyYAML).
# U15b: the master switch, commands and the card ship OFF.
DEFAULTS = {
    "telegram.alerts": False, "telegram.needs_you": True, "telegram.terms": True,
    "telegram.rejoin": True, "telegram.knocked_out": True, "telegram.error": True,
    "telegram.quest": True, "telegram.commando": True, "telegram.blender": False,
    "telegram.planter": False, "telegram.purchases": True, "telegram.royal_jelly": True,
    "telegram.self_review": False, "telegram.commands": False,
    "telegram.stats_cards": "off", "telegram.hourly_card": False,
}
DOWN_S = 600.0
LIVE_VIEW = runtime_dir() / "hivemind-live.jpg"
# CLAUDE'S EAR: --listen touches BEAT every poll (at most ~50 s apart). Silent
# this long, the session is not reading, and the alerts service says so.
BEAT = ENV.with_name("telegram.listening")
QUIET_S = 300.0


# Files the owner sends, kept out of the repo and out of /tmp.
INBOX = Path.home() / "Hivemind" / "var" / "telegram_inbox"

# COMMANDS FROM THEIR PHONE (start, pause, stop, screenshot and report, the
# usual remote-control set). A message that is
# exactly one of these, from TELEGRAM_CHAT and nobody else, while
# telegram.commands is on, is acted on through the bot's own controls -- the
# socket's Command, as the GUI's buttons send it, and the watchdog's STOP
# file -- never a shell, a settings write or a signal. No /start of a stopped
# bot: launching beside another big game has crashed a PC; Play in Hivemind does it.
# (Telegram's own Start button sends /start, so it gets the help.)
#
# WHO POLLS. --listen (Claude's monitor) is the one getUpdates consumer while
# it runs, and answers commands itself; two long polls on one bot fight (409).
# While it is silent (BEAT older than LISTEN_GONE_S) the alerts service polls
# instead (`serve_commands`): it answers commands and, Claude's session being
# away, leaves their other messages unread for it -- or, with no Claude on this
# machine at all (no BEAT file), takes them and answers with the help.
# HANDLED keeps the update ids already answered, so the one that polls next
# never does a command twice.
#
# THE PLAN (choose-design 2026-10-26): /plan shows what it works on (NOW, WHY,
# NEXT, GOAL), /why the reason for the current field, and `/plan honey` /
# `/plan quests bucko` / `/plan undo` change it -- the one command that takes
# words after it. The change is a socket Command (Action.SET_PLAN) that the
# running bot carries out itself (run_farm's on_command -> brain/plan.remote),
# so this file still writes no setting.
#
# SETTINGS FROM THE PHONE (ROADMAP tgset): /settings [word] reads them (on the
# venv: this python has no PyYAML), /set <name> <value> and /preset <name>
# go to the bot as /plan does (Action.SET_SETTING / SET_PRESET), which writes
# them through world/remote_settings and its deny-list; /logs is the run log's
# last lines through the stream's privacy gate.
COMMANDS = ("status", "screenshot", "pause", "resume", "stop", "report", "goals",
            "undo", "plan", "why", "settings", "set", "preset", "logs", "help", "start")
WITH_WORDS = ("plan", "settings", "set", "preset")
HELP = ("Commands: /status (what it is doing), /screenshot (the live view), "
        "/pause, /resume, /stop (the same clean stop as Hivemind's Stop), "
        "/report (today's honey/hr and the stats card), /goals (the session goals: possible or not), "
        "/undo (take back the newest thing the bot counted as bought on its own), "
        "/plan (what it works on and why), /why (why this field), "
        "/plan honey (change the plan: progress, item <name>, honey, quests <bear>, "
        "tickets, macro, fuzzy_alt, tad_alt, hybrid, custom; /plan undo puts it back), "
        "/settings (the main switches; /settings quests finds names), "
        "/set gather.convert_at 90 (change one), /preset <name> (a saved preset), "
        "/logs (the run log's last 30 lines, private details hidden). "
        "Starting a stopped bot is Hivemind's Play button.")
COMMAND_MAX_AGE_S = 600.0        # an older one (a poller was away) is not acted on
LISTEN_GONE_S = 120.0            # --listen touches BEAT at most ~80 s apart
HANDLED = ENV.with_name("telegram.handled")
LIVE_FRESH_S = 120.0


def env() -> dict:
    """The token and the chat; {} before the Telegram tab has saved any."""
    out = {}
    if not ENV.exists():
        return out
    for line in ENV.read_text().splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def api(method: str, token: str | None = None, wait: float = 70, **params):
    """One Bot API call (`wait`: seconds before it gives up). The token is
    only ever in the URL, and no error raised here quotes the URL."""
    token = token or env().get("TELEGRAM_TOKEN")
    if not token:
        raise RuntimeError("no bot token saved yet (Hivemind's Telegram tab)")
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = urllib.parse.urlencode(params).encode()
    with urllib.request.urlopen(url, data, timeout=wait) as r:
        return json.load(r)


def toggles(path: Path | None = SETTINGS) -> dict:
    """The telegram.* settings, over DEFAULTS; a missing file is the defaults.
    settings.yaml is yaml.safe_dump's flat `key: value` lines (gui/panels/
    settings), so the telegram ones are read here line by line.
    ponytail: a hand-written flow mapping or a multi-line value for these keys
    is not read (the default stands); PyYAML if this ever runs on the venv."""
    out = dict(DEFAULTS)
    try:
        lines = path.read_text().splitlines() if path else []
    except OSError:
        lines = []
    for line in lines:
        key, _, value = line.partition(":")
        value = value.split(" #")[0].strip().strip("'\"")
        if key not in out:
            continue
        if isinstance(out[key], str):
            out[key] = value
        elif value.lower() in ("true", "yes", "on", "false", "no", "off"):
            out[key] = value.lower() in ("true", "yes", "on")
    return out


def wanted(kind: str, settings: Path | None = SETTINGS) -> bool:
    """Is an alert of `kind` switched on, the master switch with it?"""
    on = toggles(settings)
    return bool(on["telegram.alerts"] and on.get(kind, True))


def private_chat(updates: list):
    """The first PRIVATE chat in getUpdates' result, as (id, first name), or
    None. Anyone can add a bot to a group; alerts go to one person."""
    for u in updates:
        chat = (u.get("message") or {}).get("chat") or {}
        if chat.get("type") == "private" and chat.get("id"):
            return chat["id"], chat.get("first_name") or ""
    return None


DISCORD_ENV = ENV.with_name("discord.env")
DISCORD_HOSTS = ("https://discord.com/api/webhooks/", "https://discordapp.com/api/webhooks/",
                 "https://ptb.discord.com/api/webhooks/", "https://canary.discord.com/api/webhooks/")


def discord_env() -> dict:
    out = {}
    try:
        lines = DISCORD_ENV.read_text().splitlines()
    except OSError:
        return out
    for line in lines:
        if "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    url = out.get("DISCORD_WEBHOOK", "")
    if not url.startswith(DISCORD_HOSTS):      # only a real Discord webhook is posted to
        out.pop("DISCORD_WEBHOOK", None)
    return out


# PING ONLY WHAT NEEDS THEM (the owner, 2026-10-19: ping only for alerts
# that need attention or for a real discovery): these alerts, plus `--discord-ping` sends. Everything else
# posts silently.
# (A "Decided on its own" line posts silently: it is news, not a question.)
PING_IF = re.compile(r"Agreements|I Agree|Not enough free memory|"
                     r"disk is nearly full|hit an error|MYTHIC BEE|not running|stopped|"
                     r"Gifted Basic grinder|game may have updated")


def honey_line(now: float | None = None, path: Path | None = None) -> str:
    """"🍯 Total honey: 1,234,567,890 (read 4 min ago)" from the bot's last HUD
    read (var/balance.json), or "" when there is none. THE OWNER, 2026-10-22:
    "make hivemind alerts channel show my total honey every time"; the age is
    said so an old read is never passed off as now."""
    try:
        got = json.loads((path or var("balance.json")).read_text(encoding="utf-8"))
        honey, at = int(got["honey"]), float(got["at"])
    except (OSError, ValueError, KeyError, TypeError):
        return ""
    mins = max(0, int(((now or time.time()) - at) // 60))
    age = "just now" if mins < 1 else f"{mins} min ago" if mins < 120 else f"{mins // 60} h ago"
    return f"🍯 Total honey: {honey:,} (read {age})"


def discord_send(text: str, image: Path | None = None, ping: bool | None = None,
                 keep: bool = True) -> bool:
    """The alert to their Discord webhook, if one is saved; True when sent.
    `ping` None = only when PING_IF matches. Errors name curl's exit code or
    Discord's status, never the URL. Not sent for the network, it goes to
    the outbox (`keep`)."""
    e = discord_env()
    url = e.get("DISCORD_WEBHOOK")
    if not url:
        return False
    asked = ping
    ping = e.get("DISCORD_PING", "").strip() if (
        PING_IF.search(text) if ping is None else ping) else ""
    honey = honey_line()
    content = (f"<@{ping}> " if ping.isdigit() else "") + "🐝 " + text + (f"\n{honey}" if honey else "")
    payload = json.dumps({"content": content[:1990], "username": "Hivemind",
                          "allowed_mentions": {"users": [ping] if ping.isdigit() else []}})
    cmd = ["curl", "-s", "-m", "30", "-o", "/dev/null", "-w", "%{http_code}"]
    if image is not None and Path(image).exists():
        cmd += ["-F", f"payload_json={payload}", "-F", f"files[0]=@{image}"]
    else:
        cmd += ["-H", "Content-Type: application/json", "-d", payload]
    try:
        r = subprocess.run(cmd + [url], capture_output=True, text=True, timeout=40)
    except (OSError, subprocess.SubprocessError) as exc:
        kept = keep and isinstance(exc, subprocess.TimeoutExpired) and outbox_add(
            "discord", text, image, asked)
        print(f"discord: not sent ({type(exc).__name__}){KEPT if kept else ''}",
              file=sys.stderr, flush=True)
        return False
    code = r.stdout.strip()
    ok = r.returncode == 0 and code in ("200", "204")
    if not ok:
        # curl's own failure (6: no DNS, 7: no connection, 28: timed out) or
        # Discord's 429/5xx is the network; a 4xx is the webhook: not kept
        kept = keep and (r.returncode != 0 or code == "429" or code.startswith("5")) \
            and outbox_add("discord", text, image, asked)
        print(f"discord: not sent (curl {r.returncode}, HTTP {code or '-'})"
              f"{KEPT if kept else ''}", file=sys.stderr, flush=True)
    return ok


def send(text: str, keep: bool = True) -> None:
    """A line to their chat. Not sent for the network, it goes to the outbox
    (`keep`); with keep=False (the outbox's own retry) the error is raised."""
    try:
        api("sendMessage", chat_id=env()["TELEGRAM_CHAT"], text="🐝 " + text)
    except Exception as exc:                 # the alert is not worth a crash
        if not keep:
            raise
        kept = offline(exc) and outbox_add("telegram", text)
        print(f"telegram: not sent ({exc}){KEPT if kept else ''}: {text}",
              file=sys.stderr, flush=True)


class Offline(RuntimeError):
    """Not sent for the network (curl could not reach Telegram, or its
    429/5xx), not for what was sent: worth sending again."""


def post_photo(path: Path, caption: str, keep: bool = True) -> None:
    """A picture to their chat, through curl (multipart). Raises RuntimeError
    when it was not sent -- with curl's exit code or Telegram's own words,
    NEVER the command line, which holds the token -- and Offline, after
    keeping it in the outbox (`keep`), when the network was the reason."""
    e = env()
    r = subprocess.run(["curl", "-s", "-m", "60", "-F", f"chat_id={e['TELEGRAM_CHAT']}",
                        "-F", f"photo=@{path}", "-F", f"caption={caption}",
                        f"https://api.telegram.org/bot{e['TELEGRAM_TOKEN']}/sendPhoto"],
                       capture_output=True, text=True)
    try:
        if r.returncode:
            raise Offline(f"curl exit {r.returncode}")
        try:
            body = json.loads(r.stdout)
        except ValueError:
            raise RuntimeError("Telegram's answer was not JSON") from None
        if not body.get("ok"):
            why, code = str(body.get("description") or "refused"), int(body.get("error_code") or 0)
            raise Offline(why) if code == 429 or code >= 500 else RuntimeError(why)
    except Offline as exc:
        if keep and outbox_add("telegram", caption.removeprefix("🐝 "), path):
            raise Offline(f"{exc}{KEPT}") from None
        raise


# THE OUTBOX (ROADMAP outbox). MEASURED (journalctl --user -u
# hivemind-stats-card, 2026-10-24..27): the 09:00, 13:00 and 17:00 cards of
# 2026-10-26 were lost to "curl exit 6" (the name did not resolve) -- 3 of the
# 10 cards in the journal -- while the alerts service's own Telegram poll
# failed 2,564 times that day (URLError); nothing tried them again. So a send
# that fails for the NETWORK (never a missing token or a refusal) is kept
# here and sent again by the watch: OUTBOX_FIRST_S after, then twice as long
# each time up to OUTBOX_LONGEST_S, said with the time it was meant for. One
# copy of the same message per channel; at most OUTBOX_MAX (the oldest goes)
# and none older than OUTBOX_AGE_S (a day-old alert is no longer news). A
# picture is copied beside it: the live view and the card are overwritten.
OUTBOX = var("outbox.jsonl")
OUTBOX_MAX = 50
OUTBOX_AGE_S = 86400.0
OUTBOX_FIRST_S = 60.0
OUTBOX_LONGEST_S = 3600.0
KEPT = " -- kept in the outbox, sent again when the network is back"


def offline(exc: BaseException) -> bool:
    """Did a send fail for the network? Telegram's 429/5xx, or no answer at
    all (DNS, refused, timed out: an OSError, which URLError is)."""
    if isinstance(exc, urllib.error.HTTPError):
        return exc.code == 429 or exc.code >= 500
    return isinstance(exc, (OSError, Offline))


def _outbox_rows() -> list:
    try:
        lines = OUTBOX.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows = []
    for line in lines:
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue
    return rows


def _outbox_write(rows: list) -> None:
    keep = {r["id"] for r in rows}
    for row in _outbox_rows():               # the pictures of those leaving
        if row.get("image") and row["id"] not in keep:
            Path(row["image"]).unlink(missing_ok=True)
    tmp = OUTBOX.with_name(OUTBOX.name + ".tmp")
    tmp.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    os.replace(tmp, OUTBOX)


class _Locked:
    """The outbox's lock across processes (the service, the card, the GUI)."""
    # ponytail: no flock on Windows, so two writers at one instant can lose a row

    def __enter__(self):
        OUTBOX.parent.mkdir(parents=True, exist_ok=True)
        self.f = open(OUTBOX.with_name(OUTBOX.name + ".lock"), "a", encoding="utf-8")
        try:
            import fcntl
            fcntl.flock(self.f, fcntl.LOCK_EX)
        except ImportError:
            pass
        return self

    def __exit__(self, *_):
        self.f.close()                       # closing lets the lock go


def outbox_add(channel: str, text: str, image=None, ping=None, now: float | None = None) -> bool:
    """Keep a send that failed for the network; True when it is kept (or
    already was). Never raises: a full disk is not worth the alert's crash."""
    now = time.time() if now is None else now
    try:
        with _Locked():
            rows = [r for r in _outbox_rows() if now - r["at"] < OUTBOX_AGE_S]
            if any(r["channel"] == channel and r["text"] == text for r in rows):
                return True
            row = {"id": f"{now:.6f}-{channel}", "channel": channel, "text": text,
                   "image": None, "ping": ping, "at": now, "tries": 0,
                   "next": now + OUTBOX_FIRST_S}
            if image is not None and Path(image).exists():
                kept = OUTBOX.with_name("outbox") / f"{row['id']}{Path(image).suffix}"
                kept.parent.mkdir(exist_ok=True)
                shutil.copyfile(image, kept)
                row["image"] = str(kept)
            _outbox_write((rows + [row])[-OUTBOX_MAX:])
        return True
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"outbox: not kept ({type(exc).__name__})", file=sys.stderr, flush=True)
        return False


def _resend(row: dict) -> bool:
    """One kept send, once more; True when it went (or never can)."""
    text = time.strftime("⏳ from %H:%M: ", time.localtime(row["at"])) + row["text"]
    if row["channel"] == "discord":
        if not discord_env().get("DISCORD_WEBHOOK"):     # the webhook was removed: never will
            return True
        return discord_send(text, row.get("image"), row.get("ping"), keep=False)
    try:
        if row.get("image"):
            post_photo(Path(row["image"]), "🐝 " + text, keep=False)
        else:
            send(text, keep=False)
        return True
    except Exception as exc:                 # a token gone, a refusal: never will
        return not offline(exc)


def outbox_flush(now: float | None = None) -> int:
    """Send what is due, oldest first; the first that fails again ends its
    channel's round (that service is still out of reach; the other channel
    still goes) and waits twice as long. Returns how many went."""
    now = time.time() if now is None else now
    with _Locked():
        due = [r for r in _outbox_rows() if r["next"] <= now and now - r["at"] < OUTBOX_AGE_S]
    sent, failed = set(), {}                 # failed: channel -> the row that failed
    for row in due:                          # sent outside the lock: a send takes seconds
        if row["channel"] in failed:
            continue
        if _resend(row):
            sent.add(row["id"])
        else:
            failed[row["channel"]] = row["id"]
    with _Locked():
        rows = []
        for r in _outbox_rows():             # read again: others may have added
            if r["id"] in sent or now - r["at"] >= OUTBOX_AGE_S:
                continue
            if r["id"] in failed.values():
                r["tries"] += 1
                r["next"] = now + min(OUTBOX_LONGEST_S, OUTBOX_FIRST_S * 2 ** r["tries"])
            rows.append(r)
        if rows or OUTBOX.exists():
            _outbox_write(rows)
    if sent:
        print(f"outbox: sent {len(sent)} kept message(s) late", file=sys.stderr, flush=True)
    return len(sent)


def send_photo(caption: str) -> None:
    """The live view as a photo; falls back to text."""
    try:
        snap = ENV.with_name("telegram-photo.jpg")
        snap.write_bytes(LIVE_VIEW.read_bytes())
        post_photo(snap, "🐝 " + caption)
    except Offline as exc:                   # kept, picture and all: not twice as text
        print(f"telegram: photo not sent ({exc})", file=sys.stderr, flush=True)
    except Exception as exc:                 # KeyError/OSError/RuntimeError: no token in any
        print(f"telegram: photo not sent ({type(exc).__name__}: {exc})",
              file=sys.stderr, flush=True)
        send(caption)


def learn_chat() -> None:
    """Wait (long polls) for their first private message to the bot; keep its
    chat. The Telegram tab's Detect chat does the same, so whichever sees
    the message first writes it, and this stops waiting."""
    while "TELEGRAM_CHAT" not in env():
        try:
            found = private_chat(api("getUpdates", timeout=50).get("result", []))
            if found and "TELEGRAM_CHAT" not in env():
                with ENV.open("a") as f:
                    f.write(f"TELEGRAM_CHAT={found[0]}\n")
                send("Hivemind alerts are on. Choose what you hear about in "
                     "Hivemind's Telegram tab.")
                return
        except Exception as exc:              # no token yet, offline, a 409
            print(f"telegram: getUpdates failed ({type(exc).__name__}: {exc})",
                  file=sys.stderr, flush=True)
            time.sleep(30)


def triage(line: str, last_sent: dict, now: float, settings: Path | None = SETTINGS):
    """(kind, as a picture, message) for a run-log line they want to hear
    about, else None. The first alert whose pattern matches decides: switched
    off, or sent less than its gap ago (`last_sent`, per pattern), nothing is
    sent for the line. The settings are read only on a match."""
    text = re.sub(r"^\s*\d\d:\d\d:\d\d  ", "", line.rstrip("\n"))
    for kind, pat, msg, gap, photo in ALERTS:
        m = re.search(pat, text)
        if not m:
            continue
        if not wanted(kind, settings) or now - last_sent.get(pat, -1e9) < gap:
            return None
        last_sent[pat] = now
        said = msg.format(*((g or "").strip() for g in m.groups()))
        return kind, photo, review_text(said) if kind == "telegram.self_review" else said
    return None


# THE HOURLY SELF-REVIEW, LAID OUT. The owner, 2026-10-21, asked for hourly
# self-reviews that are easy to read, not a blob of text.
# run_farm writes one line: the hour's tally "; "-separated, " -- the one to
# fix next: ...", then " | "-separated parts (lessons, "My plan: a; b",
# "Learning: ..."). Each becomes a labelled line, lists as bullets.
REVIEW_LABELS = (("what cost me:", "⚠️ Cost me time:"), ("my plan:", "🗺 Plan now:"),
                 ("learning:", "🧪 Testing:"))


RATE = re.compile(r"\(([\d.]+)([kMB])/h\)")
_LAST_RATE: list = []           # the previous review's pollen/h, this process
# ponytail: kept in memory, so the first review after a restart has no "vs"


def _rate(text: str) -> float | None:
    m = RATE.search(text)
    return float(m.group(1)) * {"k": 1e3, "M": 1e6, "B": 1e9}[m.group(2)] if m else None


def review_text(line: str) -> str:
    parts = [p.strip() for p in line.split(" | ") if p.strip()]
    if not parts:
        return "🐝 Hourly self-review"
    head, _, fix = parts[0].partition(" -- the one to fix next: ")
    out = ["🐝 Hourly self-review"]
    for bit in (b.strip() for b in head.split("; ") if b.strip()):
        label = next((new for old, new in REVIEW_LABELS if bit.lower().startswith(old)), None)
        out.append(f"{label} {bit.split(':', 1)[1].strip()}" if label else f"📊 {bit}")
    rate = _rate(head)
    if rate and _LAST_RATE:
        change = (rate / _LAST_RATE[-1] - 1) * 100
        out.append(f"{'📈' if change >= 0 else '📉'} vs last hour: {change:+.0f}% pollen/h")
    if rate:
        _LAST_RATE[:] = [rate]
    if fix:
        out.append(f"🔧 Fix next: {fix}")
    lessons, sections = [], []
    for part in parts[1:]:
        label = next((new for old, new in REVIEW_LABELS if part.lower().startswith(old)), None)
        if label is None:
            lessons.append(f"  • {part}")
        else:
            sections += [label] + [f"  • {i.strip()}" for i in part.split(":", 1)[1].split("; ")
                                   if i.strip()]
    if lessons:
        out += ["💡 Learned:"] + lessons
    out += sections
    return "\n".join(out)


def command_in(msg: dict, settings=...):
    """The command a message is, exactly ('/pause', '/pause@hisbot'), or
    None: anything else, or telegram.commands off (then it is an ordinary
    message). Who sent it is the caller's check. `settings`: SETTINGS as it
    is when called; None is the defaults."""
    m = re.fullmatch(r"/([A-Za-z]+)(?:@\w+)?(\s+.+)?", (msg.get("text") or "").strip(),
                     re.S)
    if not m or m[1].lower() not in COMMANDS or (m[2] and m[1].lower() not in WITH_WORDS):
        return None
    on = toggles(SETTINGS if settings is ... else settings)["telegram.commands"]
    return m[1].lower() if on else None


def from_owner(update: dict, mine: str) -> bool:
    return str(((update.get("message") or {}).get("chat") or {}).get("id")) == mine


def handled() -> set:
    try:
        return set(json.loads(HANDLED.read_text()))
    except (OSError, ValueError, TypeError):
        return set()


def mark_handled(update_id: int) -> None:
    HANDLED.write_text(json.dumps(sorted(handled() | {update_id})[-200:]))


def bot_socket(command=None, read_s: float = 0.0, **fields):
    """Talk to the running bot over its event socket, as the GUI does: send a
    run-control Command (Action value; `fields` for its goal/target) or any
    event (an Answer: /undo), and/or read the state it replays to whoever
    connects for `read_s` seconds. The JSON events read (dicts), or None when
    no bot is listening."""
    from hivemind.ipc.bus import connect          # unix socket; Windows: TCP + token (RL6)
    from hivemind.telemetry.events import Action, Command
    rows, buf = [], b""
    try:
        with connect() as s:
            if command:
                event = command if hasattr(command, "to_json") else Command(
                    action=Action(command), reason="requested from Telegram", **fields)
                s.sendall((event.to_json() + "\n").encode())
            end = time.monotonic() + read_s
            while time.monotonic() < end:
                s.settimeout(max(0.05, end - time.monotonic()))
                try:
                    chunk = s.recv(65536)
                except (socket.timeout, TimeoutError):
                    break
                if not chunk:
                    break
                buf += chunk
    except OSError:
        return None
    for line in buf.split(b"\n"):
        try:
            rows.append(json.loads(line))
        except ValueError:
            pass
    return [r for r in rows if isinstance(r, dict)]


def status_text() -> str:
    """One short paragraph: run state, honey, honey/hr, the current task."""
    rows = bot_socket(read_s=1.0)
    if rows is None:
        if farm_running():
            return "The bot is starting or between runs (not connected yet)."
        if (NIGHT / "STOP").exists():
            return "The bot is stopped (Stop was pressed)."
        return "The bot is not running."
    last = {}
    for r in rows:                           # the replay: the newest of each
        key = r.get("kind") if r.get("kind") != "metric" else "metric:" + str(r.get("name"))
        last[key] = r
    st = last.get("status") or {}
    state = ("handed over to you" if st.get("handed_over") else
             "paused" if st.get("paused") else
             "running" if st.get("running") else "connected")
    parts = [f"The bot is {state}"
             + (f" ({st['note']})" if st.get("note") else "") + "."]
    honey = (last.get("metric:honey") or {}).get("value")
    rate = (last.get("metric:honey_per_hour") or {}).get("value")
    if honey is not None:
        parts.append(f"Honey {float(honey):,.0f}"
                     + (f", {float(rate):,.0f} an hour." if rate is not None else "."))
    task = last.get("task") or {}
    if task.get("name"):
        parts.append(f"Now: {task['name']}" + (f" -- {task['detail']}" if task.get("detail") else "")
                     + (f" ({task['status']})" if task.get("status") else "") + ".")
    return " ".join(parts)


def stop_bot() -> str:
    """Hivemind's Stop without the process supervision: STOP so the watchdog
    does not relaunch the farm (only while a watchdog is alive, as gui/
    launcher does), then the Command STOP the GUI sends -- brain/controls
    lifts every key and the run ends. Nothing is signalled or killed."""
    from hivemind.gui.launcher import BotProcess
    bp = BotProcess(root=ROOT)
    # START ON BOOT's countdown (gui/autostart, ROADMAP U13): the window
    # watches this file, and a /stop during the 60 s removes it.
    pending = bp.night / "autostart.pending"
    if pending.exists():
        try:
            pending.unlink()
            return "Cancelled: Hivemind will not start farming. Press Start when you want it."
        except OSError:
            pass
    watchdog = bp.watchdog_pid() is not None
    if watchdog:
        try:
            bp.night.mkdir(parents=True, exist_ok=True)
            bp.stop_file.touch()
        except OSError:
            watchdog = False
    sent = bot_socket("stop") is not None
    if not sent and not watchdog:
        return "Nothing to stop: the bot is not running."
    return ("Stopping: " + ("the bot lifts every key and ends its run" if sent
                            else "the bot was not connected")
            + ("; STOP is set, so the watchdog will not relaunch it" if watchdog else "")
            + ". Start it again with Play in Hivemind.")


def undo_last(var_root=None) -> str:
    """/undo: "Not right? Undo" on the newest thing the bot counted as bought
    on its own (brain/owned: var/owned.json, an INFERRED item with its
    decided_at), sent to the running bot as the window's button sends it.
    Read-only here: the bot writes the file (the price table needs PyYAML,
    which this python may lack)."""
    from hivemind.telemetry.events import UNDO, Answer
    try:
        items = json.loads(((var_root or var()) / "owned.json").read_text(
            encoding="utf-8")).get("items") or {}
    except (OSError, ValueError, AttributeError):
        items = {}
    decided = [(float(b.get("decided_at") or 0), k, b) for k, b in items.items()
               if isinstance(b, dict) and b.get("state") == "inferred" and b.get("decided_at")]
    if not decided:
        return "Nothing to undo: the bot has not counted anything as bought on its own."
    _at, key, body = max(decided, key=lambda d: d[0])
    label = body.get("label") or key.replace("_", " ")
    if bot_socket(Answer(id=f"owned:{key}", choice=UNDO)) is None:
        return (f"The bot is not running, so the {label} was not undone. Press "
                f"\"{UNDO}\" on its card in Hivemind, or undo it here once it runs.")
    return f"Undone: the {label} no longer counts as yours, and the bot saves for it again."


MARK = {"yes": "done", "no": "not yet", "?": "can't tell yet"}
PLAN_REPLY_S = 3.0               # how long /plan <choice> waits for the bot's answer


def plan_status() -> dict:
    from hivemind.brain import plan
    from hivemind.world.settings import Settings
    return plan.status(var(), Settings(SETTINGS))


def plan_text() -> str:
    """/plan: NOW, WHY, NEXT and GOAL, in plain words."""
    st = plan_status()
    goal = st["goal"]
    lines = [f"Plan: {goal['label']}" + (f" ({goal['target']})" if goal["target"] else "")
             + f". {goal['line']}",
             "NOW: " + (st["now"] or "nothing measured yet"),
             "WHY: " + (st["why"] or "no reason written yet")]
    if st["next"]:
        lines.append("NEXT: " + "; ".join(f"{r['what']} ({MARK.get(r['state'], '?')})"
                                          for r in st["next"][:5]))
    if goal.get("hive"):
        lines.append(f"Hive: {goal['hive']} ({goal['hive_why']})")
    if st["proof"]:
        lines.append("Done lately: " + "; ".join(st["proof"][:3]))
    lines.append("Change it: /plan honey (or progress, item <name>, quests <bear>, "
                 "tickets, macro, custom). /plan undo puts it back.")
    return "\n".join(lines)


def why_text() -> str:
    st = plan_status()
    return ("WHY: " + st["why"] + (f" (now: {st['now']})" if st["now"] else "")
            if st["why"] else "No reason written yet: the bot has not finished a trip.")


def set_plan(words: str, msg: dict) -> str:
    """/plan <choice> [target]: checked here for a quick answer, then sent to
    the running bot, which writes it (Action.SET_PLAN). Only the owner's chat
    (checked again here, beside the pollers' own check)."""
    from hivemind.brain import plan
    if str((msg.get("chat") or {}).get("id")) != str(env().get("TELEGRAM_CHAT")):
        return "Only the owner's chat can change the plan."
    choice, _, target = words.strip().partition(" ")
    choice, target = choice.lower(), target.strip()
    bad = "" if choice == "undo" else plan.check(choice, target)
    if bad:
        return bad + " Nothing was changed."
    said = ask_bot("set_plan", "plan", goal=choice, target=target)
    if said is None:
        return ("The bot is not running, so the plan was not changed. "
                "Set it on Hivemind's Play page, or send this again while it runs.")
    return said or "Sent to the bot. /plan shows it once it is set."


def ask_bot(action: str, source: str, **fields):
    """Send a Command to the running bot and wait PLAN_REPLY_S for its answer
    (a Log from `source`): the answer, "" when none came in time, or None
    when no bot is listening."""
    t0 = time.time()
    rows = bot_socket(action, read_s=PLAN_REPLY_S, **fields)
    if rows is None:
        return None
    said = [r.get("message") for r in rows
            if r.get("kind") == "log" and r.get("source") == source
            and float(r.get("at") or 0) >= t0 - 1]
    return said[-1] if said else ""


def settings_text(words: str = "") -> str:
    """/settings [word]: world/remote_settings' overview, or the settings
    matching `word`, run on the venv (PyYAML), as /report runs its tools."""
    py = ROOT / ".venv" / "bin" / "python"
    try:
        r = subprocess.run([str(py if py.exists() else sys.executable), "-m",
                            "hivemind.world.remote_settings", *words.split()[:1],
                            "--config", str(SETTINGS)],
                           capture_output=True, text=True, timeout=60,
                           env={**os.environ, "PYTHONPATH": str(SRC)})
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"Could not read the settings ({type(exc).__name__})."
    if r.returncode != 0:
        return ("Could not read the settings ("
                + ((r.stderr or "").strip().splitlines() or ["no reason given"])[-1] + ").")
    return r.stdout.strip()


def change_setting(name: str, words: str, msg: dict) -> str:
    """/set <name> <value> and /preset <name>: sent to the running bot, which
    checks and writes them (world/remote_settings). Only the owner's chat
    (checked again here, beside the pollers' own check)."""
    if str((msg.get("chat") or {}).get("id")) != str(env().get("TELEGRAM_CHAT")):
        return "Only the owner's chat can change settings."
    words = " ".join(words.split())
    if name == "set":
        key, _, value = words.partition(" ")
        if not key or not value:
            return ("Use: /set <name> <value>, for example /set gather.convert_at 90. "
                    "/settings <word> finds the names.")
        said = ask_bot("set_setting", "remote", key=key, value=value)
    else:
        if not words:
            return "Use: /preset <name>. /settings lists the saved presets."
        said = ask_bot("set_preset", "remote", value=words)
    if said is None:
        return ("The bot is not running, so nothing was changed. Change it in "
                "Hivemind, or send this again while it runs.")
    return said or "Sent to the bot. /settings shows it once it is set."


LOG_LINES = 30
LOG_CHARS = 3900                 # one Telegram message holds 4096


def setting_line(key: str, path: Path | None = None) -> str:
    """One flat `key: value` line of settings.yaml, read as `toggles` reads them."""
    try:
        lines = (path or SETTINGS).read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""
    for line in lines:
        k, _, value = line.partition(":")
        if k == key:
            return value.split(" #")[0].strip().strip("'\"")
    return ""


def logs_text(night: Path | None = None) -> str:
    """/logs: the newest run log's last LOG_LINES lines through the stream's
    privacy gate with every rule on (stream/privacy.Redactor: links, the
    server code, paths, ids, the Roblox username, this PC's names, their own
    private words). MEASURED 2026-10-27 over the last 30 lines of 200 run
    logs: 123 of 5,410 raw lines held their name, home path, host or a pid;
    through the gate none did (658 changed, 291 system-detail lines left out).
    ponytail: a multi-line stream.private_words is not read (setting_line)."""
    from hivemind.stream import privacy
    try:
        runs = sorted((night or NIGHT).glob("run-*.log"), key=lambda p: p.stat().st_mtime)
        with open(runs[-1], "rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 65536))
            tail = f.read().decode("utf-8", "replace").splitlines()[-LOG_LINES:]
    except (OSError, IndexError):
        return "No run log yet."
    gate = privacy.Redactor({"stream.hide_private_text": True, "stream.hide_username": True,
                             "account.username": setting_line("account.username"),
                             "stream.private_words": setting_line("stream.private_words")})
    kept = [gate.scrub(line) for line in tail]
    dropped = sum(line is None for line in kept)
    return (f"{runs[-1].stem}, last {len(tail)} lines"
            + (f" ({dropped} system-detail lines left out)" if dropped else "") + ":\n"
            + "\n".join(line for line in kept if line is not None)[-LOG_CHARS:])


def run_command(name: str, msg: dict, now: float | None = None) -> str:
    """Act on one of the owner's commands and answer them. Returns the
    answer (for --listen's line)."""
    now = time.time() if now is None else now
    if now - float(msg.get("date") or now) > COMMAND_MAX_AGE_S:
        reply = (f"/{name} from {time.strftime('%H:%M', time.localtime(msg['date']))} "
                 "was not acted on: it is over 10 minutes old.")
    elif name in ("help", "start"):
        reply = HELP
    elif name == "status":
        reply = status_text()
    elif name in ("pause", "resume"):
        if bot_socket(name) is None:
            reply = f"The bot is not connected, so there is nothing to {name}."
        else:
            reply = ("Pausing: the bot finishes its step, lifts every key and waits. "
                     "/resume to go on." if name == "pause" else "Resumed.")
    elif name == "stop":
        reply = stop_bot()
    elif name == "undo":
        reply = undo_last()
    elif name in ("plan", "why"):
        words = re.sub(r"^/\w+(?:@\w+)?", "", (msg.get("text") or "").strip())
        try:
            reply = (set_plan(words, msg) if words.strip() else
                     plan_text() if name == "plan" else why_text())
        except Exception as exc:             # a broken file never kills the poller
            reply = f"Could not read the plan: {exc}"
    elif name in ("settings", "set", "preset"):
        words = re.sub(r"^/\w+(?:@\w+)?", "", (msg.get("text") or "").strip())
        reply = settings_text(words) if name == "settings" else change_setting(name, words, msg)
    elif name == "logs":
        reply = logs_text()
    elif name == "goals":                    # session goals (ROADMAP G9)
        try:
            from hivemind.brain import session_goals
            reply = session_goals.report()
        except Exception as exc:             # a broken file never kills the poller
            reply = f"Could not check the session goals: {exc}"
    elif name == "screenshot":
        try:
            fresh = time.time() - LIVE_VIEW.stat().st_mtime < LIVE_FRESH_S
        except OSError:
            fresh = False
        if fresh:
            reply = "The live view, " + time.strftime("%H:%M:%S") + "."
            send_photo(reply)
            return reply
        reply = "No live view right now: the bot is not capturing the game."
    else:                                    # report
        py = ROOT / ".venv" / "bin" / "python"
        reply = status_text()
        try:                                 # ROADMAP P4: the day's honey/h on top
            r = subprocess.run([str(py), str(ROOT / "scripts" / "benchmark.py"), "--today"],
                               capture_output=True, text=True, timeout=60)
            head = (r.stdout or "").strip() if r.returncode == 0 else ""
        except (OSError, subprocess.TimeoutExpired):
            head = ""                        # (the card below still says it)
        if head:
            reply = head + "\n" + reply
        try:                                 # ROADMAP M5: vic hop's counters
            from hivemind.act import vichunt
            vic = vichunt.summary_of(var())
        except Exception:
            vic = ""
        if vic:
            reply += "\n" + vic
        try:                                 # ROADMAP ITEM-REP: today's items
            from hivemind.brain import itemreport
            reply += "\n" + itemreport.report_text(var("inventory.json"))
        except Exception as exc:             # a broken file never kills the poller
            reply += f"\nItems: could not read them ({type(exc).__name__})"
        send(reply)
        try:
            r = subprocess.run([str(py), str(ROOT / "scripts" / "daily_card.py"),
                                "--send", "--now"], capture_output=True, text=True,
                               timeout=180)
            bad = r.returncode != 0
            why = (r.stderr.strip().splitlines() or ["no reason given"])[-1]
        except (OSError, subprocess.TimeoutExpired) as exc:
            bad, why = True, type(exc).__name__
        if bad:
            send(f"The stats card was not sent ({why}).")
        return reply
    send(reply)
    return reply


def serve_commands(claude_here: bool) -> None:
    """The alerts service's poll while --listen is not running: answer the
    owner's commands. Their other messages are left unread for Claude's
    session (`claude_here`); with no session on this machine they are taken
    and answered with the help. Others' messages are dropped."""
    off_file = ENV.with_name("telegram.offset")
    try:
        offset = int(off_file.read_text()) if off_file.exists() else 0
        got = api("getUpdates", offset=offset, timeout=0, wait=20).get("result", [])
        mine = str(env()["TELEGRAM_CHAT"])
    except Exception as exc:                 # offline, a 409, no chat yet
        print(f"telegram: command poll failed ({type(exc).__name__})",
              file=sys.stderr, flush=True)
        return
    done, moving = handled(), True
    for u in got:
        uid, msg = u["update_id"], u.get("message") or {}
        name = command_in(msg) if from_owner(u, mine) else None
        if name and uid not in done:
            mark_handled(uid)
            run_command(name, msg)
        elif from_owner(u, mine) and not name and not claude_here and moving:
            send(HELP)
        if moving and (name or not from_owner(u, mine) or not claude_here):
            offset = uid + 1
        else:
            moving = False                   # their message, kept for Claude
    off_file.write_text(str(offset))


def listener_state() -> tuple:
    """(--listen is polling now, a Claude session uses this machine)."""
    try:
        return time.time() - BEAT.stat().st_mtime < LISTEN_GONE_S, True
    except FileNotFoundError:
        return False, False


# THE HOURLY STATS CARD (ROADMAP outbox; telegram.hourly_card, off by
# default): the watch starts scripts/daily_card.py --hourly at the top of each
# hour, on the venv's python (this one has no OpenCV), and does not wait for
# it. Checked here first, so an hour with the switch off costs no process.
def hourly_card(running):
    """The card's process, started when the switch is on and the last one has
    ended; else `running` as it was."""
    if not toggles().get("telegram.hourly_card") or (running and running.poll() is None):
        return running
    try:
        return subprocess.Popen([str(ROOT / ".venv" / "bin" / "python"),
                                 str(ROOT / "scripts" / "daily_card.py"),
                                 "--hours", "1", "--send", "--hourly"], cwd=ROOT,
                                stdout=subprocess.DEVNULL)
    except OSError as exc:
        print(f"telegram: no hourly card ({type(exc).__name__})", file=sys.stderr, flush=True)
        return None


def farm_running() -> bool:
    # -u: the alt's bot runs as another user (tools/alt) and is not this farm
    return subprocess.run(["pgrep", "-u", str(os.getuid()), "-f", "scripts/[r]un_farm"],
                          capture_output=True).returncode == 0


def watch() -> None:
    learn_chat()
    path, pos = None, 0
    last_sent: dict = {}
    up_at, said_down = time.monotonic(), False
    covered, next_peek, next_poll = False, 0.0, 0.0
    hour, card = time.localtime().tm_hour, None
    while True:
        if time.monotonic() >= next_poll:
            next_poll = time.monotonic() + 5
            listening, claude = listener_state()
            if not listening:
                serve_commands(claude)
        if time.monotonic() >= next_peek:
            next_peek = time.monotonic() + 60
            covered = cover_for_claude(covered)
            try:
                outbox_flush()
            except Exception as exc:         # never costs the alerts below
                print(f"outbox: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
            if time.localtime().tm_hour != hour:
                hour, card = time.localtime().tm_hour, hourly_card(card)
        logs = sorted(NIGHT.glob("run-*.log"), key=lambda p: p.stat().st_mtime)
        if logs and logs[-1] != path:
            # a new run's log from its start; the first one from its end
            pos = 0 if path is not None else logs[-1].stat().st_size
            path = logs[-1]
        if path is not None:
            with path.open(errors="ignore") as f:
                f.seek(pos)
                for line in f:
                    hit = triage(line, last_sent, time.monotonic())
                    if hit:
                        (send_photo if hit[1] else send)(hit[2])
                        discord_send(hit[2], LIVE_VIEW if hit[1] else None)
                pos = f.tell()
        if farm_running():
            if said_down and wanted("telegram.error"):
                send("The bot is running again.")
            up_at, said_down = time.monotonic(), False
        elif (not said_down and time.monotonic() - up_at > DOWN_S
              and not (NIGHT / "STOP").exists()):
            if wanted("telegram.error"):
                send("The bot has been down for 10 minutes and nobody pressed Stop.")
            said_down = True
        time.sleep(2)


def cover_for_claude(covered: bool) -> bool:
    """While Claude's session is not listening (BEAT older than QUIET_S), tell
    them once that their messages are saved -- read at the stored offset, which
    confirms nothing new, so the session still gets them when it is back.
    Returns whether this outage has been covered."""
    try:
        if time.time() - BEAT.stat().st_mtime < QUIET_S:
            return False
    except FileNotFoundError:
        return False                         # no Claude session on this machine
    if covered:
        return True
    off_file = ENV.with_name("telegram.offset")
    try:
        offset = int(off_file.read_text()) if off_file.exists() else 0
        got = api("getUpdates", offset=offset, timeout=0).get("result", [])
        mine = str(env()["TELEGRAM_CHAT"])
    except Exception:
        return False
    if any(str((u.get("message") or {}).get("chat", {}).get("id")) == mine for u in got):
        send("Claude's session isn't reading Telegram right now (the app may be "
             "closed or restarting). Your messages are saved and get answered when "
             "it is back.")
        return True
    return False


def listen() -> None:
    """Print each message the owner sends the bot, one line each, for Claude's
    monitor; only their chat (anyone can message a bot). The offset is kept on
    disk, so a monitor that expires and is re-armed misses and repeats
    nothing -- Telegram holds unread messages for 24 h."""
    off_file = ENV.with_name("telegram.offset")
    offset = int(off_file.read_text()) if off_file.exists() else 0
    mine = str(env()["TELEGRAM_CHAT"])
    while True:
        BEAT.touch()
        try:
            got = api("getUpdates", offset=offset, timeout=50).get("result", [])
        except Exception as exc:
            print(f"telegram: getUpdates failed ({exc})", file=sys.stderr, flush=True)
            time.sleep(30)
            continue
        for u in got:
            offset = u["update_id"] + 1
            msg = u.get("message") or {}
            if str(msg.get("chat", {}).get("id")) != mine:
                continue
            name = command_in(msg)
            if name:                         # answered here, not for Claude
                if u["update_id"] not in handled():
                    mark_handled(u["update_id"])
                    print(f"telegram command from the owner: /{name} -- answered: "
                          + run_command(name, msg).replace("\n", " / "), flush=True)
                continue
            if msg.get("text"):
                print("telegram from the owner: " + msg["text"].replace("\n", " / "),
                      flush=True)
            # A FILE, TOO (2026-10-14: an HTML file they sent was skipped -- only
            # text was printed, and the offset moved past it for good). Saved
            # under INBOX and announced with its caption.
            item = msg.get("document") or (msg.get("photo") or [None])[-1] \
                or msg.get("audio") or msg.get("video") or msg.get("voice")
            if item:
                print("telegram file from the owner: " + _save(item, msg)
                      + (" / caption: " + msg["caption"].replace("\n", " / ")
                         if msg.get("caption") else ""), flush=True)
        off_file.write_text(str(offset))


def _save(item: dict, msg: dict) -> str:
    """Download a file the owner sent into INBOX; where it went, or why not."""
    name = Path(item.get("file_name") or
                f"{msg.get('message_id', 'file')}-{item.get('file_unique_id', '')}").name
    try:
        path = api("getFile", file_id=item["file_id"])["result"]["file_path"]
        INBOX.mkdir(parents=True, exist_ok=True)
        dest = INBOX / f"{time.strftime('%Y%m%d-%H%M%S')}-{name}"
        url = f"https://api.telegram.org/file/bot{env()['TELEGRAM_TOKEN']}/{path}"
        with urllib.request.urlopen(url, timeout=120) as r:
            dest.write_bytes(r.read())
        return f"{name} saved to {dest}"
    except Exception as exc:                 # e.g. over the Bot API's 20 MB
        return f"{name} ({item.get('file_size', '?')} bytes) NOT saved: {exc}"


def check() -> None:
    """The patterns against sample log lines, at the default switches with
    the master switch on (it ships off since U15b)."""
    import tempfile
    on = Path(tempfile.mkdtemp()) / "settings.yaml"
    on.write_text("telegram.alerts: true\n")
    cmds = on.with_name("commands.yaml")          # telegram.commands ships off too
    cmds.write_text("telegram.commands: true\n")

    def hit(line):
        return triage(line, {}, 0.0, settings=on)
    assert show is not None, "hivemind.stream.show did not import on this python"
    assert hit("    22:01:02  a dialogue was read at the Polar Bear, so it leaves the "
               "hand-in queue") == ("telegram.quest", False, "Quest handed in at the Polar Bear.")
    assert hit("21:58:09  Ant Challenge: 42 look(s) in 109s — the amulet table is "
               "up — the challenge is over; the frames")[0] == "telegram.quest"
    assert hit("could not reach the hive 1 times while carrying pollen — asking for "
               "a rejoin, which lands")[0] == "telegram.rejoin"
    assert hit("    01:04:04  disconnect: the Roblox client's log says the connection to "
               "the server ended (connection lost — reason 277, lost connection to the "
               "game server, at 01:04:02) — stopping")[2].startswith(
        "Disconnected: the connection to the server ended (connection lost — reason 277")
    assert hit("  network: the internet is back after 1003 min — starting the game "
               "now")[:2] == ("telegram.rejoin", False)
    assert hit("    disconnect would: end the process (exit 1)") is None
    assert hit("    14:38:00  stall: the run has not finished a step in 20 min (not "
               "paused, not handed over) — it looks stuck; every thread's stack "
               "follows")[1:] == (False, "The bot looks stuck: the run has not "
                                 "finished a step in 20 min (not paused, not handed over).")
    assert hit("    stall would: keep the game and end the process (exit 1)") is None
    assert hit("    stall watch: the main thread has been at x.py:1 for 600 s") is None
    assert hit("    10:25:00  died: pollen fell 1,502 -> 0 (1,502 lost)")[2] == \
        "Knocked out: 1,502 pollen lost."
    assert hit("21:56:13  ant_pass: used it") is None
    assert hit("    01:57:52  rare drop: +1 Star Jelly (now 3)")[1:] == (
        False, "Rare drop: +1 Star Jelly (now 3)")
    assert hit("    00:01:02  progress proof: 2026-10-26: 2 bought; 2 of 2 proven by a "
               "frame (var/progression)")[2].startswith("Progress proof for 2026-10-26: 2 bought")
    assert hit("    06:47:26  progress proof: bought: Hive Slot (proven, frame kept)") is None
    assert hit("    22:10:00  low disk: 18.4 GB free under /home/user/Hivemind/var/"
               "incidents (less than 20 GB) -- the debug")[2].startswith(
        "The disk is nearly full (18.4 GB free)")
    assert hit("    12:09:30  buying gumdrops: bought it — '300 Gumdrops | 100 Tickets "
               "| Buy for 100 Tickets'")[2] == "💸 Bought: 300 Gumdrops for 100 Tickets."
    assert hit("    12:00:00  buying at the Mountain Top Shop: bought it — 'Hive Slot | "
               "2.0B Honey | Buy for 2.0B Honey'")[2] == "💸 Bought: Hive Slot for 2.0B Honey."
    assert hit("royal jelly: 5 rolled on the cell at (962, 165); it now holds the "
               "Tadpole Bee")[:2] == ("telegram.alerts", True)
    assert hit("royal jelly: 5 rolled on the cell at (962, 165); it now holds the "
               "Brave Bee")[:2] == ("telegram.royal_jelly", False)
    assert hit("  memory: not enough memory to start the game: 6.5 GB available of 30, "
               "swap 4.0/4 GB (100%)")
    assert hit("    22:10:00  game guard: paused: you're playing Minecraft — press "
               "Resume or /resume after")[2].startswith("paused: you're playing Minecraft")
    assert hit("    03:10:00  game update? the game may have updated: honey digits 9/9 failed, "
               "hotbar tile 8/8 failed in 10 min — safe mode")[:2] == ("telegram.needs_you", True)
    assert PING_IF.search(hit("game update? the game may have updated: x")[2])
    drift = hit("    06:00:00  read drift: hotbar tile median score 0.90 over the last 3 days")
    assert drift[:2] == ("telegram.alerts", False) and not PING_IF.search(drift[2])
    assert command_in({"text": " /Pause@my_hive_bot "}, cmds) == "pause"
    assert command_in({"text": "/pause now"}, cmds) is None
    assert command_in({"text": "/rm"}, cmds) is None
    assert command_in({"text": "/goals"}, cmds) == "goals"
    assert command_in({"text": "/plan quests bucko"}, cmds) == "plan"
    assert command_in({"text": "/why not"}, cmds) is None
    from hivemind.telemetry.events import Action
    assert all(Action(c) for c in ("pause", "resume", "stop", "set_plan"))
    print("ok")


if __name__ == "__main__":
    if sys.argv[1:2] == ["--send"]:
        send(" ".join(sys.argv[2:]))
    elif sys.argv[1:2] == ["--listen"]:
        listen()
    elif sys.argv[1:2] == ["--discord-ping"] and len(sys.argv) > 2:
        print("sent" if discord_send(" ".join(sys.argv[2:]), ping=True) else "not sent")
    elif sys.argv[1:2] == ["--discord-test"]:
        print("sent" if discord_send("Hivemind is connected to this channel. "
                                     "Alerts will appear here.") else
              "not sent: no valid DISCORD_WEBHOOK in ~/.config/hivemind/discord.env")
    elif sys.argv[1:2] == ["--check"]:
        check()
    else:
        watch()
