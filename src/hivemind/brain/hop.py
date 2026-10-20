"""Server hopping for the Vicious Bee (ROADMAP M10; the owner, 2026-10-15: "i
want server hopping"). Off by default, and LOOK-ONLY while HOP_LIVE is False.

WHY. Twenty hunts in his private server, 16-19 Oct, all "absent"
(var/vicious.json). Other bots ("vic hop") hop public servers
at night until one has the bee.

WHAT IT COSTS, every time: his private server is left, the Wealth Clock's
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
in a DIFFERENT server: nothing here can choose one (no server list is read,
and the gameInstanceId link has never been seen working on Sober,
platform/lastserver), so the server's JobId digest is read back from Sober's
session log after the join and a repeat is said. Roblox's in-game menu has no
"server hop"; Bee Swarm has none either. The way BACK is the usual private
join (the Servers drawer, act/join): `next` is one-shot, so any relaunch not
ordered by a hop -- a crash, a deploy, a stop -- goes home too.

All functions are pure over a small state dict (var/hop.json) and `now`.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

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
    """(state, a server seen before): the public server's JobId digest kept."""
    out = dict(state)
    seen = list(out.get("servers") or [])
    again = bool(digest) and digest in seen
    if digest:
        out["servers"] = (seen + [digest])[-20:]
    return out, again


def goal_wants_stingers(plan) -> bool:
    """A goal not owned yet that is short of stingers (brain/goals plan)."""
    try:
        return any(n.material == "stinger" for r in plan.rows if not r.owned for n in r.missing)
    except Exception:
        return False
