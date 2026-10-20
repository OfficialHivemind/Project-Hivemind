"""Server hopping for the Vicious Bee (ROADMAP M10; the owner asked for it,
2026-10-15). Off by default, and LOOK-ONLY while HOP_LIVE is False.

WHY. Twenty hunts in a private server, 16-19 Oct, all "absent"
(var/vicious.json). Other macros hop public servers at night until one
has the bee.

WHAT IT COSTS, every time: their private server is left, the Wealth Clock's
streak (1, 2, 3, 4, then 5 tickets an hour, platform/session) starts again
at 1 and its hour again from the join (run_farm CLOCK_FROM_JOIN_SECONDS),
and a deploy that keeps the game keeps the PUBLIC one. So it hops only on
purpose -- a quest or a goal wants the bee, the hunt here found nothing, at
night -- within a budget, and goes back to the private server after.

HOW A PUBLIC SERVER IS JOINED: by the run ending (no keep-the-game) with
`next: public` written here, and the watchdog's relaunch starting Sober with
`roblox://placeId=1537690962` (act/bootstrap `start(private=False)`).
MEASURED (DESIGN 8a, "PUBLIC joins work, by both URI forms"): that link
reached a live server. [ASSUMED] that Roblox's matchmaking puts each such join
in a DIFFERENT server, so the server's JobId digest is read back from Sober's
session log after the join and a repeat is said. A CHOSEN server (`choose`,
the public server list, below) goes by its gameInstanceId link instead once
PICK_LIVE is on -- not before, as that link has never been seen working on
Sober (platform/lastserver) -- and a join that lands elsewhere is "wrong
server". Roblox's in-game menu has no
"server hop"; Bee Swarm has none either. The way BACK is the usual private
join (the Servers drawer, act/join): `next` is one-shot, so any relaunch not
ordered by a hop -- a crash, a deploy, a stop -- goes home too.

All functions are pure over a small state dict (var/hop.json) and `now`.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from ..platform import lastserver
from ..platform.lastserver import BSS_PLACE_ID

OFF, VICIOUS = "off", "vicious hunt at night"
CHOICES = [OFF, VICIOUS]
# LOOK-ONLY: the decision is made and said ("hop would: ..."), nothing leaves.
HOP_LIVE = False
PUBLIC_URI = f"roblox://placeId={BSS_PLACE_ID}"
# A "night" of the budget: local noon to noon, so one overnight run is one.
NIGHT_TURNS_AT_HOUR = 12
# Home before the public server's Wealth Clock hour comes up (it counts from
# the join, run_farm CLOCK_FROM_JOIN_SECONDS = 1 h), with a walk's margin.
RETURN_BEFORE_S = 50 * 60.0
# An order to hop older than this is not obeyed: the run that wrote it is long gone.
NEXT_FRESH_S = 10 * 60.0
STREAK_MAX = 5                 # tickets an hour at the top of the streak
STREAK_HORIZON_H = 5


@dataclass(frozen=True)
class Budget:
    per_night: int = 3          # server.hop_per_night
    minutes: int = 6            # server.hop_minutes: in one public server
    return_private: bool = True  # server.hop_return

    @staticmethod
    def from_settings(settings) -> "Budget":
        """Read at every use; anything unreadable is the default."""
        out = Budget()
        try:
            out = Budget(max(0, int(settings.int("server.hop_per_night"))), out.minutes,
                         out.return_private)
        except Exception:
            pass
        try:
            out = Budget(out.per_night, max(1, int(settings.int("server.hop_minutes"))),
                         out.return_private)
        except Exception:
            pass
        try:
            out = Budget(out.per_night, out.minutes, bool(settings.bool("server.hop_return")))
        except Exception:
            pass
        return out


def mode(settings) -> str:
    try:
        got = str(settings.get("server.hop") or OFF).strip()
    except Exception:
        return OFF
    return got if got in CHOICES else OFF


def load(path) -> dict:
    try:
        got = json.loads(Path(path).read_text())
        return got if isinstance(got, dict) else {}
    except (OSError, ValueError):
        return {}


def save(path, state: dict) -> None:
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(state, indent=1))
    except OSError:
        pass


def night_key(now: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(now - NIGHT_TURNS_AT_HOUR * 3600))


def hops_tonight(state: dict, now: float) -> int:
    return int(state.get("hops") or 0) if state.get("night") == night_key(now) else 0


def in_public(state: dict) -> bool:
    return bool(state.get("out_since"))


def streak_cost(hours_in_server: float, horizon_h: int = STREAK_HORIZON_H) -> tuple[int, str]:
    """(tickets, sentence): what leaving now costs the Wealth Clock over the
    next `horizon_h` hours, an ESTIMATE from the owner's word (2026-09-23:
    1, 2, 3, 4, then 5 tickets an hour until you leave) and the hours this
    server session has lasted -- not the clock's own reading."""
    held = max(0, int(hours_in_server))
    kept = sum(min(STREAK_MAX, held + i) for i in range(1, horizon_h + 1))
    fresh = sum(min(STREAK_MAX, i) for i in range(1, horizon_h + 1))
    lost = kept - fresh
    return lost, (f"the Wealth Clock streak goes back to 1 (this server: {hours_in_server:.1f} h, "
                  f"streak ~{min(STREAK_MAX, held)}) — about {lost} ticket(s) over the next "
                  f"{horizon_h} h [estimate]")


def should_hop(*, hop_mode: str, wanted: int, goal_wants: bool, hunt: str, night: bool,
               handin: bool, memory_ok: bool, memory_note: str, hops: int,
               budget: Budget) -> tuple[bool, str]:
    """From where the bot is (private or public), after a hunt: hop to a
    public server? (go, why). Every refusal says its reason."""
    if hop_mode != VICIOUS:
        return False, "server.hop is off"
    if not (wanted or goal_wants):
        return False, "no quest or goal wants a Vicious Bee"
    if hunt != "absent":
        return False, f"the hunt here ended '{hunt or 'not at all'}', not empty"
    if not night:
        return False, "it is not night"
    if handin:
        return False, "a quest hand-in is queued or under way"
    if not memory_ok:
        return False, f"the memory gate: {memory_note}"
    if hops >= budget.per_night:
        return False, f"{hops} of {budget.per_night} hop(s) tonight are used"
    why = (f"quest wants {wanted} kill(s)" if wanted else "a goal wants stingers")
    return True, f"{why}; the hunt here found nothing; hop {hops + 1} of {budget.per_night} tonight"


def in_public_step(state: dict, now: float, *, budget: Budget, hunt: str, wanted: int,
                   goal_wants: bool) -> tuple[str, str]:
    """In a public server the bot hopped to: ("stay" | "hop" | "return", why).
    `hunt` is the last hunt's result IN THIS SERVER ("" for none yet)."""
    out_s = now - float(state.get("out_since") or now)
    here_s = now - float(state.get("server_since") or now)
    left = hops_tonight(state, now) < budget.per_night
    home = "return" if budget.return_private else "stay"
    if budget.return_private and out_s >= RETURN_BEFORE_S:
        return "return", (f"{out_s / 60:.0f} min out of the private server — home before "
                          f"this server's Wealth Clock hour")
    if hunt == "killed":
        return home, "the Vicious Bee is beaten"
    if not (wanted or goal_wants):
        return home, "nothing wants a Vicious Bee any more"
    if hunt and hunt != "absent":
        return home, f"the hunt here ended '{hunt}' (a loss is not hopped on)"
    if hunt == "absent" or here_s >= budget.minutes * 60:
        why = ("the hunt here found nothing" if hunt == "absent"
               else f"{here_s / 60:.0f} min here with no hunt")
        if left:
            return "hop", why
        return home, why + f"; the night's {budget.per_night} hop(s) are used"
    return "stay", f"{here_s / 60:.0f} of {budget.minutes} min here"


def order(state: dict, now: float, where: str, *, hours_in_server: float = 0.0) -> dict:
    """The state with `where` ("public" | "private") ordered for the next
    start, a hop counted, and the streak loss (leaving private) kept."""
    out = dict(state)
    out["next"], out["next_at"] = where, now
    if where == "public":
        if out.get("night") != night_key(now):
            out["night"], out["hops"] = night_key(now), 0
        out["hops"] = int(out.get("hops") or 0) + 1
        if not in_public(state):
            lost, _ = streak_cost(hours_in_server)
            out["streak_resets"] = int(out.get("streak_resets") or 0) + 1
            out["tickets_lost_est"] = int(out.get("tickets_lost_est") or 0) + lost
    return out


def start_kind(state: dict, now: float, *, hop_mode: str, live: bool = HOP_LIVE,
               kept: bool = False) -> tuple[bool, dict]:
    """(join a public server?, the state with the order taken). One-shot: the
    order is cleared whatever it said, so anything else goes home. `kept`: a
    kept game will be attached to (a deploy), which stays where it was --
    `went_home` clears that if the attach fails."""
    want = state.get("next")
    fresh = now - float(state.get("next_at") or 0) <= NEXT_FRESH_S
    public = bool(live and hop_mode == VICIOUS and want == "public" and fresh)
    out = {k: v for k, v in state.items() if k not in ("next", "next_at")}
    if public:
        out.setdefault("out_since", now)
        out["server_since"] = now
    elif not kept:
        out = went_home(out)
    return public, out


def went_home(state: dict) -> dict:
    """The state once the bot is in its private server again."""
    return {k: v for k, v in state.items() if k not in ("out_since", "server_since")}


def fresh_server(state: dict, last_try_at) -> bool:
    """A public server hopped to after the last hunt: its night is its own,
    so the hunt's wait (var/vicious.json next_at) does not hold it."""
    return in_public(state) and float(state.get("server_since") or 0) > float(last_try_at or 0)


def last_hunt(tries, since: float) -> str:
    """The result of the newest hunt at or after `since`, else ""."""
    for t in reversed(list(tries or [])):
        if isinstance(t, dict) and float(t.get("at") or 0) >= since:
            return str(t.get("result") or "")
    return ""


def arrived(state: dict, digest: str | None) -> tuple[dict, bool]:
    """(state, a server seen before): the public server's JobId digest kept,
    and the arrival counted (act/vichunt's counters, the Bosses card)."""
    out = dict(state)
    out["arrivals"] = int(out.get("arrivals") or 0) + 1
    seen = list(out.get("servers") or [])
    again = bool(digest) and digest in seen
    if digest:
        out["servers"] = (seen + [digest])[-20:]
    return out, again


# PICK A SERVER, NOT A RANDOM JOIN (ROADMAP M10/M11): Roblox's public server
# list for the place, the emptiest fit one not tried in the last 20 min, joined
# by its gameInstanceId (lastserver.LastServer.uri, act/bootstrap's link path).
# MEASURED 2026-10-26 ~22:55 from this PC (tests/fixtures/serverlist/, raw pages
# kept off-repo): the endpoint answers anonymously; rows are {id, maxPlayers 6,
# playing, fps, ping, ...}; sortOrder=Asc sorts by `playing`, so page 1 is the
# emptiest (100 rows of 1-2 players; Desc pages 1-2 were all 5 of 6); a few
# just-started rows have no fps/ping (asc page 1: 2 without fps, 4 without
# ping); requests got 429 with "Retry-After: 5" after 3-5 in under a minute
# (the 6th of a run 10 s apart). [ASSUMED] `ping` is the server's
# players' ping (Roblox's docs do not say), so it only breaks ties.
# PICK_LIVE False: the hop (if HOP_LIVE) still joins a random server by the
# placeId link and says "hop would: join <digest> (...)" -- the gameInstanceId
# link has NOT been seen working on Sober yet (ROADMAP M10b blocker (1)).
PICK_LIVE = False
SERVERS_URL = (f"https://games.roblox.com/v1/games/{BSS_PLACE_ID}/servers/Public"
               f"?sortOrder=Asc&excludeFullGames=true&limit=100")
TRIED_S = 20 * 60.0            # a tried server is not picked again for this long
# Pages read for a fit untried one: 100 a page, and a night tries 3 (Budget),
# so page 1 nearly always has one. With TRIES_429 and MAX_WAIT_429_S this
# bounds a choose() at about a minute even when every request times out.
PAGES = 2
TRIES_429 = 2                  # requests per page before giving up on 429s
MAX_WAIT_429_S = 10.0          # MEASURED Retry-After: 5
# A server whose own frame rate is under this is laggy (ghost tokens, ROADMAP
# M10 'Ghost token'). [ASSUMED] threshold; MEASURED over the 700 rows read:
# 698 had fps, 646 at 59+, 2 under 55 (53.3, 54.4).
MIN_FPS = 55.0
UUID = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def _get_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": "Hivemind", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _page(url: str, get, sleep) -> tuple[dict | None, str]:
    """One page, waiting out a 429 by its Retry-After (else 5, 10 s)."""
    for i in range(TRIES_429):
        try:
            return get(url), ""
        except urllib.error.HTTPError as exc:
            if exc.code != 429:
                return None, f"the server list answered HTTP {exc.code}"
            try:
                wait = float((exc.headers or {}).get("Retry-After") or 0)
            except (TypeError, ValueError):
                wait = 0.0
            if i + 1 < TRIES_429:
                sleep(min(MAX_WAIT_429_S, wait or 5.0 * (i + 1)))
        except (OSError, ValueError) as exc:
            return None, f"the server list could not be read ({type(exc).__name__})"
    return None, f"the server list said 'too many requests' {TRIES_429} times"


def _tried(state: dict, now: float) -> dict:
    return {d: at for d, at in dict(state.get("tried") or {}).items()
            if now - float(at) < TRIED_S}


def fit(row, tried: dict) -> bool:
    try:
        return (bool(UUID.fullmatch(str(row.get("id") or "")))
                and int(row["playing"]) < int(row["maxPlayers"])
                and lastserver.LastServer(row["id"], "", 0.0, "").digest not in tried
                and (row.get("fps") is None or float(row["fps"]) >= MIN_FPS))
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


def pick(rows, state: dict, now: float):
    """The fit row with the fewest players, then the lowest ping (none
    last), or None. Fewest: more free hives (6 per server) and fewer
    players racing for the bee."""
    tried = _tried(state, now)
    ok = [r for r in rows or [] if isinstance(r, dict) and fit(r, tried)]
    return min(ok, key=lambda r: (int(r["playing"]), 9999.0 if r.get("ping") is None
                                   else float(r["ping"])),
               default=None)


def choose(state: dict, now: float, *, get=_get_json, sleep=time.sleep):
    """(lastserver.LastServer to join | None, what to say): the public list
    read page by page (cursor) until a fit untried server is found. The
    JobId goes into Sober's argv only; the sentence names its digest."""
    cursor, seen = "", 0
    for _ in range(PAGES):
        got, why = _page(SERVERS_URL + (f"&cursor={urllib.parse.quote(cursor)}" if cursor else ""),
                         get, sleep)
        if got is None:
            return None, why
        rows = got.get("data") or []
        seen += len(rows)
        row = pick(rows, state, now)
        if row is not None:
            server = lastserver.LastServer(row["id"], "", now, "public server list")
            ping = row.get("ping")
            return server, (f"server {server.digest} ({row['playing']}/{row['maxPlayers']} "
                            f"players, ping {ping if ping is not None else '?'} ms)")
        cursor = str(got.get("nextPageCursor") or "")
        if not cursor:
            break
    return None, f"no fit untried server in {seen} listed"


def picked(state: dict, server, now: float) -> dict:
    """The state with `server` (its digest only) tried now."""
    out = dict(state)
    out["tried"] = {**_tried(state, now), server.digest: now}
    return out


def landed(state: dict, wanted: str, joined: str | None) -> tuple[dict, bool]:
    """(state, the join landed in the picked server): digests compared;
    a wrong one is counted (`wrong_server`)."""
    ok = bool(joined) and joined == wanted
    out = dict(state)
    if not ok:
        out["wrong_server"] = int(out.get("wrong_server") or 0) + 1
    return out, ok


def goal_wants_stingers(plan) -> bool:
    """A goal not owned yet that is short of stingers (brain/goals plan)."""
    try:
        return any(n.material == "stinger" for r in plan.rows if not r.owned for n in r.missing)
    except Exception:
        return False
