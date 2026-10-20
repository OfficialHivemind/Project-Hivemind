"""The Bee Swarm server this account was last in, from Sober's own session logs.

THE OWNER, 2026-09-29: a mode where Start plays in the server the player is
already in -- after following a friend into the friend's server, Start always
went to the private server (act/join).

WHERE IT IS WRITTEN. Sober keeps one log per session in SESSION_LOGS, their
sessions and the bot's alike (platform/clientlog reads the bot's copy), and
each join is one line, MEASURED on a session of 2026-09-29 (six joins):

    [FLog::Output] ! Joining game '<JobId>' place 1537690962 at <address>

with the app's own request logged just before it, as a WebView "launchGame"
command: "requestType":"RequestPrivateGame" (with its accessCode) for their
private server's list, "RequestFollowUser" for a friend's server list. A
private-server join is left to the usual private join, which needs no code;
any other is joined again by its JobId with Roblox's documented deep link
(creator-docs production/promotion/deeplinks.md, read 2026-09-29): the
"direct to app" form roblox://placeId=<id>, which act/bootstrap already
launches for a public join, with its `gameInstanceId` parameter, "the unique
identifier of the game instance to join, also called the DataModel.JobId".
NOT YET SEEN WORKING HERE: act/bootstrap falls back to the private join when
the link does not reach the world, and a server that failed is not tried again
(`note_result`).

PRIVACY, as platform/clientlog: the JobId goes into Sober's command line and
nowhere else; what is said and kept is its six-character digest. A log older
than FRESH_S is not believed: that server is likely gone.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

from ..datapaths import newest_session_log, session_logs_dir, var

BSS_PLACE_ID = "1537690962"
SESSION_LOGS = session_logs_dir()
JOIN = re.compile(r"! Joining game '([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                  r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12})' place (\d+)")
LAUNCH = re.compile(r'"functionName"\s*:\s*"launchGame"')
REQUEST = re.compile(r'"requestType"\s*:\s*"(\w+)"')
# How old the newest session log may be for its last server to be joined.
FRESH_S = 60 * 60.0
# The last server tried by its link, and whether the world was reached.
RECORD = var("last_server.json")


@dataclass(frozen=True)
class LastServer:
    job: str              # the JobId: into Sober's argv only, never said
    request: str          # the app's requestType for that join, "" if none
    at: float             # the log's last write
    log: str

    @property
    def private(self) -> bool:
        return self.request == "RequestPrivateGame"

    @property
    def digest(self) -> str:
        return hashlib.sha1(self.job.encode()).hexdigest()[:6]

    def uri(self) -> str:
        return f"roblox://placeId={BSS_PLACE_ID}&gameInstanceId={self.job}"


@dataclass(frozen=True)
class ShareLink:
    """A private server's share link (`account.share_link`, "https://www.
    roblox.com/share?code=...&type=Server"): the alt's way in. Its home page
    has no Bee Swarm tile to reach the Servers drawer by -- MEASURED 2026-10-13
    19:03 and 19:04, "never found the Servers row" twice -- and the link opens
    the owner's own server with no menu at all."""
    code: str             # into Sober's argv only, never said
    # "link" = the long ...?privateServerLinkCode=<digits> link (2026-10-19:
    # on Windows the share link opened Roblox and never joined; Natro joins
    # private servers by placeId + linkCode, the long link's code).
    kind: str = "share"

    @property
    def private(self) -> bool:
        return True

    @property
    def digest(self) -> str:
        return hashlib.sha1(self.code.encode()).hexdigest()[:6]

    def uri(self) -> str:
        if self.kind == "link":
            return f"roblox://placeId={BSS_PLACE_ID}&linkCode={self.code}"
        return f"roblox://navigation/share_links?code={self.code}&type=Server"


@dataclass(frozen=True)
class FollowUser:
    """Join a friend wherever they are playing (`account.follow_user`): the
    alt follows the main into the main's own private server. Roblox's own
    "join user" link (roblox://experiences/start?userId=..., RoSeal's
    deeplink parser, 2026-10-13). WHY: the share link never got the alt in --
    MEASURED 2026-10-13 run-004..006, Sober's log shows no sign of it and the
    app sat on its home page -- while the alt's home page lists the main
    (the owner) as a friend, in Bee Swarm. Needs the private server to let
    friends in (Configure -> Friends Allowed) and the main to be in a game."""
    user_id: str          # public, but only its digest is printed

    @property
    def private(self) -> bool:
        return True

    @property
    def digest(self) -> str:
        return hashlib.sha1(self.user_id.encode()).hexdigest()[:6]

    def uri(self) -> str:
        return f"roblox://experiences/start?userId={self.user_id}"


def follow_user(text) -> "FollowUser | None":
    """A Roblox user id (digits only) out of the setting, else None."""
    t = str(text or "").strip()
    return FollowUser(t) if t.isdigit() else None


def share_link(text) -> "ShareLink | None":
    """The code out of a pasted share link (or the bare code), or the long
    private-server link's privateServerLinkCode, else None."""
    import re
    m = re.search(r"privateServerLinkCode=([0-9]+)", str(text or ""))
    if m:
        return ShareLink(m.group(1), kind="link")
    m = re.search(r"(?:code=)?\b([0-9a-f]{32})\b", str(text or ""))
    return ShareLink(m.group(1)) if m else None


def newest_log(folder: Path = SESSION_LOGS) -> Path | None:
    """The newest session log; never a crash handler's or an installer's
    (datapaths.NOT_SESSION_LOGS: on Windows those are written beside it)."""
    return newest_session_log(folder)


def last_server(folder: Path = SESSION_LOGS, *, place: str = BSS_PLACE_ID,
                now: float | None = None, fresh_s: float = FRESH_S) -> LastServer | None:
    """The last server of `place` joined in the newest session log, or None
    when there is none, or the log is older than `fresh_s`."""
    log = newest_log(folder)
    if log is None:
        return None
    try:
        at = log.stat().st_mtime
        text = log.read_text(errors="replace")
    except OSError:
        return None
    if (time.time() if now is None else now) - at > fresh_s:
        return None
    found, request = None, ""
    for line in text.splitlines():
        if LAUNCH.search(line):
            m = REQUEST.search(line)
            request = m.group(1) if m else ""
            continue
        m = JOIN.search(line)
        if m:
            if m.group(2) == place:
                found = (m.group(1), request)
            request = ""          # a request belongs to the join after it
    if found is None:
        return None
    return LastServer(job=found[0], request=found[1], at=at, log=log.name)


def tried_and_failed(server: LastServer, record: Path | None = None) -> bool:
    """Did the last try at this very server fail? Then it is not tried again."""
    try:
        was = json.loads(Path(record or RECORD).read_text())
    except (OSError, ValueError):
        return False
    return was.get("digest") == server.digest and not was.get("ok", False)


def note_result(server: LastServer, ok: bool, record: Path | None = None,
                clock=time.time) -> None:
    record = Path(record or RECORD)
    try:
        record.parent.mkdir(parents=True, exist_ok=True)
        record.write_text(json.dumps(
            {"digest": server.digest, "ok": bool(ok), "at": clock()}))
    except OSError:
        pass


# WHICH SERVER START JOINS (`server.join`, ROADMAP M11; the owner, 2026-10-16:
# a link swapped into server.yaml did nothing, because act/join always clicks
# the drawer's first blue Join -- their own private server).
MY_SERVER, BY_LINK, BY_NAME, FOLLOW_ME = (
    "my private server", "this share link", "a named server", "follow me")
JOIN_CHOICES = [MY_SERVER, BY_LINK, BY_NAME, FOLLOW_ME]


@dataclass(frozen=True)
class Target:
    """Where Start goes. `server` rides Sober's argv (act/bootstrap's link
    path) or is None for the Servers drawer; `name` is the drawer row to join
    ("" = the first private Join, their own); `said` is the run log's line --
    never the link, the code or a JobId, only digests."""
    server: object | None
    name: str
    said: str


def target(join, link="", name="", *, last=None, failed=None) -> Target:
    """The server `server.join` asks for, or their own private server with the
    reason it fell back. `last()` is `last_server` and `failed(server)`
    `tried_and_failed`, passed in for the tests."""
    join = str(join or MY_SERVER).strip()
    name = " ".join(str(name or "").split())
    last = last or last_server
    failed = failed or tried_and_failed
    own = "your own private server"
    if join == BY_LINK:
        linked = share_link(link)
        if linked is None:
            return Target(None, "", f"server.join is '{BY_LINK}' but server.link holds "
                                    f"no share-link code — {own} instead")
        if failed(linked):
            return Target(None, name, f"the share link (server {linked.digest}) did not "
                                      f"reach the world last time — "
                                      + (f"the drawer row '{name}'" if name else own)
                                      + " instead (save a new link to try one again)")
        return Target(linked, name, f"joining by the share link (server {linked.digest})"
                                    + (f", then the drawer row '{name}' if it lands "
                                       f"on the home" if name else ""))
    if join == BY_NAME:
        if not name:
            return Target(None, "", f"server.join is '{BY_NAME}' but server.name is "
                                    f"empty — {own} instead")
        return Target(None, name, f"joining the Servers drawer's row '{name}'")
    if join == FOLLOW_ME:
        found = last()
        if found is None:
            return Target(None, "", f"follow me: no server in the newest Sober session "
                                    f"log of the last hour — {own}")
        if found.private:
            return Target(None, name, f"follow me: server {found.digest} is a private "
                                      f"server, which no link joins (DESIGN 8a: Error "
                                      f"524) — "
                                      + (f"the drawer row '{name}'" if name else own))
        if failed(found):
            return Target(None, "", f"follow me: server {found.digest} did not let the "
                                    f"bot in last time — {own}")
        return Target(found, "", f"follow me: back to server {found.digest}, the last "
                                 f"one you were in")
    return Target(None, "", f"joining {own}")
