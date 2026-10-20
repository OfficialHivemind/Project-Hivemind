"""Reading stream chat, and nothing else: Twitch anonymously, YouTube with an
API key, or a file.

READ-ONLY BY CONSTRUCTION. The Twitch reader logs in as `justinfan` plus
digits, which is Twitch's anonymous nick: it needs no account and no token,
and an anonymous connection cannot send to chat at all (discuss.dev.twitch.com
/t/anonymous-connection-using-justinfan/2046). The only lines this file ever
writes to the socket are the handshake, the JOIN and the PONG the server
demands. So there is no path from here to anyone's chat -- the bot's or the
owner's -- and `safety.never_chat`, which is about the GAME's chat, is not
even in reach.

THE PROTOCOL, from dev.twitch.tv/docs/chat/irc:
    irc.chat.twitch.tv:6697 over TLS
    CAP REQ :twitch.tv/tags twitch.tv/commands   (display names; moderation)
    NICK justinfan12345
    JOIN #channel
    server: PING :tmi.twitch.tv   ->  us: PONG :tmi.twitch.tv
    @tags :login!login@login.tmi.twitch.tv PRIVMSG #channel :text

`twitch.tv/commands` is asked for because it carries CLEARCHAT (a user timed
out or banned) and CLEARMSG (one message deleted). The stream honours both: a
moderator's decision reaches the overlay too, so a name chat suggested for a
milestone disappears with the person who suggested it.

THE YOUTUBE READER is the YouTube
Data API v3's public read of a live chat. It makes GET requests to four list
endpoints and nothing else, so it cannot post either: an API key alone cannot
insert a chat message (that takes OAuth). Its rules -- the key, the quota,
moderation -- are with the class below. DESIGN 8ed.

THE FILE READER is for every other platform: any tool that appends chat to a
text file, one "name: message" per line. It starts at the END, so a stream
opened after a long chat never replays the whole backlog as fresh votes.
DESIGN 8dv.
"""
from __future__ import annotations

import collections
import http.client
import json
import math
import os
import random
import re
import socket
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

HOST = "irc.chat.twitch.tv"
PORT = 6697                       # TLS; dev.twitch.tv/docs/chat/irc

# A Twitch login: letters, digits and underscores, at most 25 characters
# (Twitch's username rules). Anything else is refused before it can reach the
# socket, which is also what makes a channel name unable to smuggle a second
# IRC command in: no space, no comma, no CR or LF can pass.
CHANNEL = re.compile(r"^[a-z0-9_]{1,25}$")

# Twitch caps a chat message at 500 characters (the Twitch chat limit). A line
# longer than that did not come from Twitch chat, and one from the file reader
# is cut to the same length so both sources are bounded alike.
MESSAGE_MAX = 500
LINE_MAX = 8192                   # IRC tags make a line long; nothing is longer

# RECONNECTING. Doubling from 1 s to a 64 s cap: the cap is only how late the
# reader notices the network is back, and nothing waits on it. A session that
# had joined starts the doubling again: its drop is a routine one (Twitch's
# RECONNECT, the silence rule below), not a failing server, and a 24/7 stream
# sees enough of them to reach the cap -- 64 s deaf, half a 120 s vote.
BACKOFF_FIRST = 1.0
BACKOFF_CAP = 64.0

# A SILENT SOCKET IS A DEAD ONE after this long. The server PINGs a connection
# it wants kept (dev.twitch.tv/docs/chat/irc, "Keepalive messages"); to know
# without waiting on its schedule, the reader sends its own PING every
# PING_EVERY seconds -- read-only clients may -- and gives up on a connection
# that has said nothing at all for two of them.
PING_EVERY = 60.0
SILENT_LIMIT = 2 * PING_EVERY

# The file reader looks for new lines this often. A human reads chat in
# seconds; a second is well inside that and costs one stat() call.
FILE_POLL_SECONDS = 1.0

CONTROL = re.compile(r"[\x00-\x1f\x7f]")


@dataclass
class ChatLine:
    """One chat message, cleaned. `user` is the identity -- a lower-case
    Twitch login, or "yt:" and the author's YouTube channel id, which is
    case-sensitive and so kept as it is; `name` is how to show it."""
    user: str
    text: str
    name: str = ""
    platform: str = "twitch"
    at: float = field(default_factory=time.time)
    id: str = ""


@dataclass
class Moderation:
    """A moderator removed a user (`user`) or one message (`id`). `ban` is a
    CLEARCHAT with no `ban-duration` tag: a ban, where one with a duration is
    a timeout (dev.twitch.tv/docs/chat/irc, "CLEARCHAT tags"). No user and no
    id is a /clear of the whole chat. YouTube's are `youtube_message`'s: a
    tombstone is one message, a userBannedEvent a user, and a "temporary"
    ban is a timeout."""
    user: str = ""
    id: str = ""
    platform: str = "twitch"
    ban: bool = False


def clean(text: str, limit: int = MESSAGE_MAX) -> str:
    """Printable, single-line, bounded."""
    return " ".join(CONTROL.sub(" ", str(text or "")).split())[:limit]


def channel_from(setting) -> str | None:
    """The channel name the setting holds, or None if it is not one.

    Accepts "name", "#name" and a pasted "twitch.tv/name" URL, because that
    is what people paste.
    """
    text = str(setting or "").strip().lower()
    text = re.sub(r"^(https?://)?(www\.)?twitch\.tv/", "", text).strip("/# ")
    return text if CHANNEL.match(text) else None


def _unescape_tag(value: str) -> str:
    # dev.twitch.tv/docs/chat/irc: \s space, \: semicolon, \\ backslash
    out, i = [], 0
    while i < len(value):
        c = value[i]
        if c == "\\" and i + 1 < len(value):
            nxt = value[i + 1]
            out.append({"s": " ", ":": ";", "\\": "\\", "r": "", "n": ""}.get(nxt, nxt))
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def parse(line: str):
    """One IRC line -> (command, tags, prefix, params, trailing)."""
    line = line.rstrip("\r\n")
    tags: dict[str, str] = {}
    if line.startswith("@"):
        raw, _, line = line[1:].partition(" ")
        for part in raw.split(";"):
            key, _, value = part.partition("=")
            tags[key] = _unescape_tag(value)
    prefix = ""
    if line.startswith(":"):
        prefix, _, line = line[1:].partition(" ")
    head, sep, trailing = line.partition(" :")
    parts = head.split()
    command = parts[0].upper() if parts else ""
    return command, tags, prefix, parts[1:], trailing if sep else ""


def message_from(line: str, platform: str = "twitch"):
    """A ChatLine, a Moderation, or None, from one raw IRC line."""
    command, tags, prefix, params, trailing = parse(line)
    if command == "PRIVMSG":
        login = prefix.split("!", 1)[0].lower()
        if not CHANNEL.match(login):
            return None
        name = clean(tags.get("display-name") or login, 25) or login
        return ChatLine(user=login, text=clean(trailing), name=name,
                        platform=platform, id=tags.get("id", ""))
    if command == "CLEARCHAT":
        # With a trailing login, one user; without, the whole chat was cleared.
        user = trailing.strip().lower()
        return Moderation(user=user, platform=platform,
                          ban=bool(user) and "ban-duration" not in tags)
    if command == "CLEARMSG":
        return Moderation(id=tags.get("target-msg-id", ""),
                          user=tags.get("login", "").lower(), platform=platform)
    return None


class TwitchReader:
    """Reads one channel's chat on its own thread; never raises at the caller.

    `on_line(ChatLine | Moderation)` and `on_state(text)` are called on the
    reader thread -- the GUI hands them to Qt through a signal.
    `connect(host, port)` exists so a test can hand in a fake socket.
    """

    def __init__(self, channel: str, on_line, on_state=None, connect=None,
                 clock=time.monotonic):
        self.channel = channel_from(channel)
        self.on_line = on_line
        self.on_state = on_state or (lambda text: None)
        self._connect = connect or self._tls
        self.clock = clock
        self._stop = threading.Event()
        self._sock = None
        self.connected = False
        self.lines = 0

    @staticmethod
    def _tls(host: str, port: int):
        raw = socket.create_connection((host, port), timeout=10.0)
        # THE CERTIFICATE IS CHECKED. `create_default_context` verifies the
        # chain and the host name, so a network in the middle cannot pose as
        # Twitch and feed the stream invented votes.
        return ssl.create_default_context().wrap_socket(raw, server_hostname=host)

    def start(self) -> "TwitchReader":
        if self.channel is None:
            self.on_state("no Twitch channel set")
            return self
        threading.Thread(target=self._loop, daemon=True,
                         name="twitch-chat").start()
        return self

    def stop(self) -> None:
        self._stop.set()
        sock = self._sock
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass

    def _send(self, sock, text: str) -> None:
        sock.sendall((text + "\r\n").encode("utf-8"))

    def _loop(self) -> None:
        backoff = BACKOFF_FIRST
        while not self._stop.is_set():
            try:
                self._session()
                backoff = BACKOFF_FIRST
            except Exception as exc:              # a reader must not die
                if self.connected:
                    backoff = BACKOFF_FIRST
                self.connected = False
                if self._stop.is_set():
                    break           # stop() closed the socket: nothing to say
                self.on_state(f"chat: {type(exc).__name__}: {exc}"[:160])
            self.connected = False
            if self._stop.is_set():
                break
            self.on_state(f"chat: reconnecting in {backoff:.0f}s")
            self._stop.wait(backoff)
            backoff = min(BACKOFF_CAP, backoff * 2)

    def _session(self) -> None:
        sock = self._connect(HOST, PORT)
        self._sock = sock
        try:
            sock.settimeout(1.0)
            nick = f"justinfan{random.randint(10000, 99999)}"
            self._send(sock, "CAP REQ :twitch.tv/tags twitch.tv/commands")
            self._send(sock, f"NICK {nick}")
            self._send(sock, f"JOIN #{self.channel}")
            buf = b""
            heard = pinged = self.clock()
            while not self._stop.is_set():
                now = self.clock()
                if now - heard > SILENT_LIMIT:
                    raise TimeoutError(f"nothing from Twitch for {SILENT_LIMIT:.0f}s")
                if now - pinged > PING_EVERY:
                    self._send(sock, "PING :hivemind")
                    pinged = now
                try:
                    chunk = sock.recv(4096)
                except (socket.timeout, TimeoutError):
                    continue
                if not chunk:
                    raise ConnectionError("Twitch closed the connection")
                heard = self.clock()
                buf += chunk
                if len(buf) > LINE_MAX * 4 and b"\n" not in buf:
                    buf = b""                   # a line that never ends
                while b"\n" in buf:
                    raw, buf = buf.split(b"\n", 1)
                    self._line(sock, raw[:LINE_MAX].decode("utf-8", "replace"))
        finally:
            self._sock = None
            try:
                sock.close()
            except OSError:
                pass

    def _line(self, sock, line: str) -> None:
        command, _tags, _prefix, params, trailing = parse(line)
        if command == "PING":
            self._send(sock, f"PONG :{trailing or 'tmi.twitch.tv'}")
            return
        if command == "RECONNECT":
            raise ConnectionError("Twitch asked for a reconnect")
        if command == "JOIN" and not self.connected:
            self.connected = True
            self.on_state(f"reading twitch.tv/{self.channel}")
            return
        if command == "NOTICE" and "failed" in trailing.lower():
            self.on_state(f"chat: {clean(trailing, 120)}")
            return
        message = message_from(line)
        if message is not None:
            self.lines += 1
            self.on_line(message)


# ---- YouTube ----------------------------------------------------------------
# THE API, researched 2026-09-26. The YouTube Data API v3 reads a PUBLIC live
# chat with an API key -- no OAuth, no account signed in to anything
# (developers.google.com/youtube/v3/live/docs/liveChatMessages/list;
# gist.github.com/w3cj/4f1fa02b26303ae1e0b1660f2349e705). The reader makes
# GET requests to these four list endpoints and to nothing else:
#     channels.list?part=id,contentDetails&forHandle=@name   a @handle -> its
#                                          channel and its uploads playlist
#     playlistItems.list?playlistId=UU..     -> its newest uploads (YT_LOOK_EVERY)
#     search.list?channelId=..&eventType=live&type=video   -> its live video
#     videos.list?part=liveStreamingDetails&id=..    -> activeLiveChatId
#     liveChat/messages?liveChatId=..&part=snippet,authorDetails
# The last returns the messages, `nextPageToken` (where the next request
# starts) and `pollingIntervalMillis` ("the amount of time ... that the client
# should wait before polling again"). "The initial request made without a
# continuation token will only contain the most recent messages" -- the
# backlog, which is skipped, as the file reader starts at the end.
YT_HOST = "www.googleapis.com"
YT_API = f"https://{YT_HOST}/youtube/v3/"
YT_CHAT = "liveChat/messages"

# THE QUOTA (developers.google.com/youtube/v3/determine_quota_cost, page
# updated 2026-09-15): "a default quota allocation of 100 search.list calls,
# 100 videos.insert calls, and 10,000 units per day combined for all other
# endpoints"; liveChatMessages.list, videos.list and channels.list cost 1
# unit each; "Daily quotas reset at midnight Pacific Time (PT)". A reader
# that runs all day must therefore poll no faster than 86,400 s over the
# units it may spend. 1,000 of the 10,000 are kept back for the lookups
# (a video, a handle, one per restart of the reader) and for anything else
# the owner runs on the same key, so the floor is 86,400 / 9,000 = 9.6 s
# between polls, whatever `pollingIntervalMillis` says. A vote runs 120 s,
# so chat is heard twelve times over inside one.
YT_DAILY_UNITS = 10_000
YT_RESERVE_UNITS = 1_000
YT_POLL_FLOOR = 86_400 / (YT_DAILY_UNITS - YT_RESERVE_UNITS)       # 9.6 s
YT_POLL_CAP = 300.0             # a pollingIntervalMillis past this is not used
# search.list's own bucket is 100 calls a day, so a search is made at most
# once every 15 minutes in this process -- 96 a day -- and only while no chat
# is being read. That is why a pasted live-stream link connects at once and a
# channel can take up to 15 minutes after going live.
YT_SEARCH_EVERY = 900.0
# ...SO THE CHANNEL'S UPLOADS ARE LOOKED AT FIRST, every minute. MEASURED
# 2026-09-26, minutes after a test stream went live: the reader, whose one
# search had run before the stream began, said "waiting for a live stream on
# @yourchannel" and would have for the rest of its 15 minutes, while
# the channel's uploads playlist (channels.list contentDetails.
# relatedPlaylists.uploads) already had the live video as its newest item,
# and videos.list gave it an activeLiveChatId. A look is two 1-unit calls
# (playlistItems.list, videos.list), made only while no chat is being read:
# 2,880 units on a day with no stream at all, and the chat's 9,000 are spent
# only while there is one, so a day never passes the 9,000. search.list stays
# behind the look, at its 15 minutes, for a stream the playlist does not show.
YT_LOOK_EVERY = 60.0
YT_LOOK_VIDEOS = 5              # the newest uploads a look asks about
YT_VIDEO_EVERY = 300.0          # a pasted video that is not live (1 unit a look)
YT_KEY_EVERY = 600.0            # a rejected key is tried again (1 unit a try)
YT_RESET_MARGIN = 120.0         # after midnight Pacific before trying again
# A quota refusal in the first hour after the reset means the clock or the
# reset is off; waiting for the next midnight would lose a day, so the reader
# tries every 15 minutes instead.
YT_JUST_RESET = 23 * 3600.0
# NETWORK TROUBLE doubles from 5 s to 5 minutes. For the first minute the
# card keeps saying "reading": the page token resumes exactly where the last
# good poll stopped, so a short outage delays chat but loses none of it.
YT_BACKOFF_FIRST = 5.0
YT_BACKOFF_CAP = 300.0
YT_GRACE = 60.0
# ...but after a longer gap (a quota wait, a long outage) the reader starts at
# the chat's end again, as it does on a fresh start: messages older than one
# vote (120 s) must not arrive as fresh votes. The gap is counted past the
# wait the last poll set, not from the poll itself: a pollingIntervalMillis
# of 150,000 is YouTube's own pace, inside YT_POLL_CAP, and a reader that
# called each of those polls stale would restart at the end every time and
# never hear a message (review of 8ed, measured with 150,000 ms: 7 polls,
# none with a pageToken, 0 lines).
YT_STALE = 120.0
YT_TIMEOUT = 15.0
YT_BODY_MAX = 4 << 20           # a page of 2,000 messages is well under this
YT_WAIT_CAP = 60.0              # the thread re-checks at least this often
# THE SUBSCRIBER COUNT (stream/subs): channels.list part=statistics, 1 unit,
# this often -- 40 units an hour of the 10,000 a day, read on the chat's own
# thread with the chat's own key once the channel is known (a handle is
# looked up by `_find` on the first step).
YT_SUBS_EVERY = 90.0

# The shapes each id has, checked before anything is sent: a channel is "UC"
# and 22 characters; a video 11; a handle 3 to 30 letters, digits, "_", "-"
# or "." (YouTube's handle rules, non-Latin letters included). A Google API
# key is 39 URL-safe characters ("AIza" and 35); anything outside
# [A-Za-z0-9_-] is refused, so a key can never break the header it rides in.
YT_CHANNEL_ID = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
YT_UPLOADS_ID = re.compile(r"^UU[A-Za-z0-9_-]{22}$")
YT_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
YT_HANDLE = re.compile(r"^[\w.-]{3,30}$")
YT_KEY = re.compile(r"^[A-Za-z0-9_-]{30,100}$")
YT_TOKEN = re.compile(r"^[A-Za-z0-9_\-=+/.]{1,300}$")
YT_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com",
            "studio.youtube.com", "youtu.be", "www.youtu.be"}

# THE REFUSALS, by the reasons Google's error bodies carry: `error.errors[]
# .reason` (the YouTube API's own, developers.google.com/youtube/v3/docs/
# errors: quotaExceeded is a 403) and `error.details[].reason` (Google's
# ErrorInfo: API_KEY_INVALID and the rest). Either spelling counts.
YT_QUOTA = {"quotaExceeded", "dailyLimitExceeded"}
YT_RATE = {"rateLimitExceeded", "userRateLimitExceeded", "RATE_LIMIT_EXCEEDED"}
YT_BAD_KEY = {"keyInvalid", "keyExpired", "API_KEY_INVALID", "API_KEY_EXPIRED",
              "ipRefererBlocked", "API_KEY_SERVICE_BLOCKED",
              "API_KEY_HTTP_REFERRER_BLOCKED", "API_KEY_IP_ADDRESS_BLOCKED",
              "API_KEY_ANDROID_APP_BLOCKED", "API_KEY_IOS_APP_BLOCKED"}
YT_NOT_ENABLED = {"accessNotConfigured", "SERVICE_DISABLED"}
YT_PAGE_BAD = {"pageTokenInvalid", "invalidPageToken"}

# A GOOGLE API KEY INSIDE OTHER TEXT: "AIza" and the rest of its 39
# characters (a few short, in case it was cut when pasted). What a chat
# setting says on the card is checked against it first, because the card is
# on the stream and a key pasted into the wrong box -- the chat file row sits
# right above the YouTube rows -- must not be drawn there (review of 8ed).
YT_KEY_IN = re.compile(r"AIza[0-9A-Za-z_-]{20,}")


def looks_secret(text) -> bool:
    """True if `text` holds something shaped like a Google API key."""
    return bool(YT_KEY_IN.search(str(text or "")))

# A sentinel from `youtube_message`: the chat itself is over.
ENDED = "chat ended"


def youtube_target(setting):
    """("video" | "channel" | "handle", id) from what the owner typed, or None.

    Takes what people paste: "@name", a youtube.com/@name link, a channel id
    (UC...) or its youtube.com/channel/ link, a live stream's link (watch?v=,
    youtu.be/, youtube.com/live/, Studio's /video/<id>/livestreaming) or its
    bare 11-character id. Any other bare word is taken as a handle typed
    without its "@".
    """
    text = str(setting or "").strip()
    if not text or any(c.isspace() for c in text):
        return None
    lowered = text.lower()
    if "youtube.com" in lowered or "youtu.be" in lowered:
        parts = urllib.parse.urlsplit(text if "://" in text else f"https://{text}")
        host = (parts.hostname or "").lower()
        if host not in YT_HOSTS:
            return None
        path = [urllib.parse.unquote(p) for p in parts.path.split("/") if p]
        if host.endswith("youtu.be"):
            return _yt_video(path[0]) if path else None
        if path and path[0] == "watch":
            return _yt_video((urllib.parse.parse_qs(parts.query).get("v") or [""])[0])
        if len(path) >= 2 and path[0] in ("live", "video", "embed"):
            return _yt_video(path[1])
        if len(path) >= 2 and path[0] == "channel":
            return ("channel", path[1]) if YT_CHANNEL_ID.match(path[1]) else None
        if path and path[0].startswith("@"):
            return _yt_handle(path[0][1:])
        return None
    if text.startswith("@"):
        return _yt_handle(text[1:])
    if YT_CHANNEL_ID.match(text):
        return ("channel", text)
    if YT_VIDEO_ID.match(text):
        return ("video", text)
    return _yt_handle(text)


def _yt_video(text: str):
    return ("video", text) if YT_VIDEO_ID.match(text or "") else None


def _yt_handle(text: str):
    return ("handle", text) if YT_HANDLE.match(text or "") else None


def _uploads_of(channel) -> str:
    """A channels.list item's uploads playlist ("UU..."), or "" without one."""
    details = channel.get("contentDetails") if isinstance(channel, dict) else None
    lists = details.get("relatedPlaylists") if isinstance(details, dict) else None
    uploads = lists.get("uploads") if isinstance(lists, dict) else None
    return uploads if isinstance(uploads, str) and YT_UPLOADS_ID.match(uploads) else ""


def _yt_user(channel_id) -> str:
    """A YouTube viewer's identity: "yt:" and their channel id, so they can
    never share a leaderboard row with a Twitch login spelt the same."""
    return f"yt:{channel_id}" if isinstance(channel_id, str) \
        and YT_CHANNEL_ID.match(channel_id) else ""


def youtube_message(item, platform: str = "youtube"):
    """A ChatLine, a Moderation, ENDED or None, from one liveChatMessage.

    FROM THE RESOURCE'S OWN DOCUMENTATION (developers.google.com/youtube/v3/
    live/docs/liveChatMessages, read 2026-09-26):
      - textMessageEvent: `snippet.textMessageDetails.messageText`. A Super
        Chat's and a member milestone's own words are their `userComment`.
      - tombstone: "a message used to exist with this id and publish time,
        but it has since been deleted" -- CLEARMSG's twin, the same id.
      - messageDeletedEvent (`messageDeletedDetails.deletedMessageId`) is
        still read, but the API's revision history of 2026-06-23 removed it
        "as these events are not being returned by the API".
      - userBannedEvent: `userBannedDetails.bannedUserDetails.channelId`,
        `banType` "permanent" or "temporary" (a timeout, as on Twitch: only
        a permanent ban also takes the viewer off the saved leaderboard).
      - chatEndedEvent: "the chat has ended and no more messages can be
        inserted after this one".
    Everything else (stickers, memberships, polls, gifts) says nothing to
    the games and is dropped.
    """
    if not isinstance(item, dict):
        return None
    snippet = item.get("snippet") if isinstance(item.get("snippet"), dict) else {}
    author = item.get("authorDetails") if isinstance(item.get("authorDetails"), dict) else {}
    kind = snippet.get("type")
    message_id = str(item.get("id") or "")[:200]
    if kind == "chatEndedEvent":
        return ENDED
    if kind == "tombstone":
        return Moderation(id=message_id, user=_yt_user(snippet.get("authorChannelId")),
                          platform=platform) if message_id else None
    if kind == "messageDeletedEvent":
        gone = (snippet.get("messageDeletedDetails") or {}).get("deletedMessageId")
        return Moderation(id=str(gone)[:200], platform=platform) if gone else None
    if kind == "userBannedEvent":
        details = snippet.get("userBannedDetails") or {}
        user = _yt_user((details.get("bannedUserDetails") or {}).get("channelId"))
        return Moderation(user=user, platform=platform,
                          ban=details.get("banType") == "permanent") if user else None
    if kind == "textMessageEvent":
        text = (snippet.get("textMessageDetails") or {}).get("messageText") \
            or snippet.get("displayMessage")
    elif kind == "superChatEvent":
        text = (snippet.get("superChatDetails") or {}).get("userComment")
    elif kind == "memberMilestoneChatEvent":
        text = (snippet.get("memberMilestoneChatDetails") or {}).get("userComment")
    else:
        return None
    user = _yt_user(author.get("channelId") or snippet.get("authorChannelId"))
    text = clean(text)
    if not user or not text:
        return None
    return ChatLine(user=user, text=text, platform=platform, id=message_id,
                    name=clean(author.get("displayName"), 25) or "viewer")


def quota_reset(now: float) -> float:
    """The next midnight Pacific after `now`: when the day's quota comes back
    ("Daily quotas reset at midnight Pacific Time (PT)", determine_quota_cost).
    """
    try:
        from zoneinfo import ZoneInfo
        pacific = ZoneInfo("America/Los_Angeles")
        tomorrow = datetime.fromtimestamp(now, pacific).date() + timedelta(days=1)
        return datetime(tomorrow.year, tomorrow.month, tomorrow.day,
                        tzinfo=pacific).timestamp()
    except Exception:
        # No time-zone database: Pacific Standard Time, UTC-8, all year --
        # an hour late in summer, which YT_JUST_RESET then retries through.
        day, offset = 86_400, 8 * 3600
        return (math.floor((now - offset) / day) + 1) * day + offset


def _at(moment: float) -> str:
    """A moment as the owner's clock shows it."""
    return time.strftime("%H:%M", time.localtime(moment))


class SearchBudget:
    """search.list's bucket, shared by every reader in this process: at most
    one search per YT_SEARCH_EVERY, and none at all while YouTube has said
    the bucket is empty. Shared, because the stream window restarts its
    readers whenever a chat setting changes, and each new reader must not
    spend a search the last one already spent.

    It also keeps WHAT THE SEARCHES FOUND: the video last seen live on each
    channel. A new reader for that channel asks videos.list about it (1
    unit) before it searches. Without that, a restart while the owner was
    live -- the window reopened, the Twitch box edited, the key replaced --
    found the search spent and left YouTube chat unread for up to 15 minutes
    of a stream that never stopped (review of 8ed: 751 s)."""

    def __init__(self, every: float = YT_SEARCH_EVERY):
        self.every = every
        self._last = None
        self._held = 0.0
        self._live: dict[str, str] = {}         # channel id -> video id
        self._lock = threading.Lock()

    def remember(self, channel: str, video: str) -> None:
        with self._lock:
            self._live[channel] = video

    def recall(self, channel) -> str:
        with self._lock:
            return self._live.get(channel, "")

    def forget(self, channel, video: str) -> None:
        """Only if it is still that video: another reader may have found a
        newer one since."""
        with self._lock:
            if video and self._live.get(channel) == video:
                del self._live[channel]

    def wait(self, now: float) -> float:
        """Seconds until a search may be made."""
        with self._lock:
            due = self._held
            if self._last is not None and self._last <= now:
                due = max(due, self._last + self.every)
            return max(0.0, due - now)

    def spend(self, now: float) -> None:
        with self._lock:
            self._last = now

    def hold(self, until: float) -> None:
        with self._lock:
            self._held = max(self._held, until)


SEARCHES = SearchBudget()


class YouTubeError(Exception):
    """YouTube answered with an HTTP error. Carries the status, the endpoint
    and the reasons from the error body -- never the request, the URL or the
    body's own words, so nothing about the key can reach a message."""

    def __init__(self, code: int, method: str, reasons=()):
        super().__init__(f"HTTP {code} from {method}")
        self.code = int(code or 0)
        self.method = method
        self.reasons = set(reasons)


def subscriber_count(data) -> int | None:
    """statistics.subscriberCount of a channels.list answer, or None: no such
    channel, a count the channel hides (`hiddenSubscriberCount`), or an
    answer that is not one. YouTube sends the count as a string."""
    items = [i for i in (data or {}).get("items") or [] if isinstance(i, dict)] \
        if isinstance(data, dict) else []
    stats = items[0].get("statistics") if items else None
    if not isinstance(stats, dict) or stats.get("hiddenSubscriberCount"):
        return None
    raw = str(stats.get("subscriberCount", "")).strip()
    if not raw.isdigit() or len(raw) > 10:
        return None
    return int(raw)


def _reasons(body: bytes) -> set:
    try:
        error = json.loads(body.decode("utf-8", "replace")).get("error") or {}
    except (ValueError, AttributeError):
        return set()
    if not isinstance(error, dict):
        return set()
    found = set()
    for part in ("errors", "details"):
        for entry in error.get(part) or []:
            if isinstance(entry, dict) and entry.get("reason"):
                found.add(str(entry["reason"])[:80])
    if "API key not valid" in str(error.get("message") or ""):
        found.add("keyInvalid")
    return found


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    """urllib copies a request's headers onto the redirect it follows, the
    key's header included. Google's API does not redirect, so a redirect is
    refused (it becomes an HTTPError) and the key never goes anywhere but
    www.googleapis.com."""

    def redirect_request(self, *args, **kwargs):
        return None


class YouTubeReader:
    """Reads one YouTube live chat on its own thread; never raises at the caller.

    The same interface as TwitchReader: `start()`, `stop()`, `connected`
    (true only while a live chat is being read), `lines`, and
    `on_line(ChatLine | Moderation)` / `on_state(text)` called on the reader
    thread. `opener` (anything with `.open(request, timeout=)`), `clock`
    (wall time: the quota resets on the wall clock) and `searches` exist so a
    test can replay YouTube's answers; `step()` does one poll, or the
    lookups that find the chat, and returns the seconds until the next.

    THE KEY. It is sent in the `x-goog-api-key` header, which Google gives as
    the way to send one ("To include an API key with a REST API call, use
    the x-goog-api-key HTTP header"; "the key query parameter ... includes
    your API key in the URL, exposing your key to theft through URL scans",
    docs.cloud.google.com/docs/authentication/api-keys-use), so it is never
    part of a URL. It goes only to www.googleapis.com: every request is to
    YT_API and redirects are refused. It is never in a state line or an
    exception's text -- the states are this class's own sentences and
    YouTubeError holds only a status and reasons -- and it is not kept in
    anything `repr` shows.
    """

    def __init__(self, api_key, target, on_line, on_state=None, opener=None,
                 clock=time.time, searches: SearchBudget | None = None,
                 on_subs=None):
        key = str(api_key or "").strip()
        self.__key = key if YT_KEY.match(key) else ""
        self._malformed = bool(key) and not self.__key
        self._setting = str(target or "").strip()
        self.target = youtube_target(target)
        kind, value = self.target or ("", "")
        # a bare 11-character word is tried as a video first, then as a handle
        self._maybe_handle = (kind == "video" and str(target or "").strip() == value
                              and bool(YT_HANDLE.match(value)))
        self.label = f"@{value}" if kind == "handle" else value
        self.on_line = on_line
        self.on_state = on_state or (lambda text: None)
        self._opener = opener or urllib.request.build_opener(_NoRedirects)
        self.clock = clock
        self.searches = searches or SEARCHES
        self._stop = threading.Event()
        self.connected = False
        self.lines = 0
        self.calls: collections.Counter = collections.Counter()
        self._channel = value if kind == "channel" else None
        self._uploads = None            # its uploads playlist; "" if it has none
        self._chat = None               # the liveChatId being read
        self._video = ""                # its video, kept while it is re-checked
        self._page = None               # where the next poll starts...
        self._page_of = None            # ...in this chat, and no other
        self._ended_chat = None         # a chat YouTube has said is over
        self._offline = False
        self._searched = False
        self._backoff = YT_BACKOFF_FIRST
        self._read_at = 0.0
        self._due = 0.0                 # the wait the last poll set
        self._next_at = 0.0
        self._said = None
        # the channel's subscriber count, handed to `on_subs(int)` on this
        # thread (stream/subs); None until YouTube has said one
        self.on_subs = on_subs
        self.subscribers: int | None = None
        self._subs_at = 0.0

    def __repr__(self) -> str:
        return f"YouTubeReader({self.label!r}, connected={self.connected})"

    def same(self, api_key, target) -> bool:
        """Whether this reader already reads what these settings ask for.
        The stream window keeps such a reader when some other chat setting
        changes, rather than stopping it and starting its twin."""
        return (str(api_key or "").strip() == self.__key and bool(self.__key)
                and str(target or "").strip() == self._setting)

    @property
    def state(self) -> str:
        """The last state line this reader said."""
        return self._said or ""

    # ---- the thread ----------------------------------------------------------
    def start(self) -> "YouTubeReader":
        if not self.__key:
            self._say("YouTube API key is malformed" if self._malformed
                      else "no YouTube API key set")
            return self
        if self.target is None:
            self._say("no YouTube channel set")
            return self
        threading.Thread(target=self._loop, daemon=True,
                         name="youtube-chat").start()
        return self

    def stop(self) -> None:
        self._stop.set()
        self.connected = False

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                delay = self.step()
            except Exception as exc:              # a reader must not die
                delay = self._retry(f"YouTube chat: {type(exc).__name__}")
                self._next_at = self.clock() + delay
            self._stop.wait(min(YT_WAIT_CAP, max(0.5, delay)))

    def step(self) -> float:
        """One poll, or the lookups that find the chat; the seconds until
        the next step may make a request."""
        now = self.clock()
        self._subs_due(now)
        if now < self._next_at:
            return self._next_at - now
        try:
            delay = self._read() if self._chat else self._find()
        except YouTubeError as exc:
            delay = self._refused(exc)
        except TimeoutError:
            delay = self._retry("YouTube chat: timed out")
        except (OSError, http.client.HTTPException):
            # urllib.error.URLError is an OSError: no network, no DNS
            delay = self._retry("YouTube chat: no connection")
        except ValueError:
            delay = self._retry("YouTube chat: an answer it could not read")
        self._next_at = self.clock() + delay
        self._subs_due(self.clock())      # the first, as soon as the channel is known
        return delay

    def _subs_due(self, now: float) -> None:
        """The subscriber count, every YT_SUBS_EVERY, on its own schedule and
        with its own failures: a read that is refused or lost is skipped
        until the next and never touches the chat's backoff or its state
        line. A quota refusal waits for the quota to come back."""
        if self.on_subs is None or not self._channel or now < self._subs_at \
                or self._stop.is_set():
            return
        self._subs_at = now + YT_SUBS_EVERY
        try:
            data = self._get("channels", part="statistics", id=self._channel)
        except YouTubeError as exc:
            if exc.reasons & YT_QUOTA:
                self._subs_at = max(self._subs_at, quota_reset(now))
            return
        except (TimeoutError, OSError, http.client.HTTPException, ValueError):
            return
        count = subscriber_count(data)
        if count is not None and not self._stop.is_set():
            self.subscribers = count
            self.on_subs(count)

    # ---- saying so -------------------------------------------------------------
    def _say(self, text: str) -> None:
        """A stopped reader says nothing: its window has a new one."""
        if self._stop.is_set() or text == self._said:
            return
        self._said = text
        self.on_state(text)

    def _set_connected(self, on: bool, text: str) -> None:
        """Every change to `connected` comes with a state line, because the
        window re-reads `connected` when a state line arrives."""
        self.connected = bool(on) and not self._stop.is_set()
        self._say(text)

    def _emit(self, message) -> None:
        if self._stop.is_set():
            return
        self.lines += 1
        self.on_line(message)

    # ---- the requests ----------------------------------------------------------
    def _get(self, method: str, **params) -> dict:
        url = YT_API + method + "?" + urllib.parse.urlencode(params)
        if urllib.parse.urlsplit(url).hostname != YT_HOST:
            raise ValueError("not YouTube's API")        # never: YT_API is fixed
        request = urllib.request.Request(url, method="GET", headers={
            "x-goog-api-key": self.__key,
            "Accept": "application/json",
            "User-Agent": "Hivemind-stream/1 (reads public live chat)"})
        self.calls[method] += 1
        try:
            with self._opener.open(request, timeout=YT_TIMEOUT) as response:
                body = response.read(YT_BODY_MAX + 1)
        except urllib.error.HTTPError as exc:
            try:
                body = exc.read(65536)
            except Exception:
                body = b""
            raise YouTubeError(exc.code, method, _reasons(body or b"")) from None
        if len(body) > YT_BODY_MAX:
            raise ValueError("answer too long")
        data = json.loads(body.decode("utf-8", "replace"))
        if not isinstance(data, dict):
            raise ValueError("answer is not an object")
        return data

    def _live_chat(self, videos) -> tuple:
        """(liveChatId, video id) of the first of `videos` that has an active
        chat, or (None, why not).

        "ended" only on YouTube's word that the broadcast is over:
        `actualEndTime`, which "will not be available until the broadcast is
        over" (the videos resource, liveStreamingDetails). A chat YouTube has
        said is over -- its chatEndedEvent, a 403 liveChatEnded -- is not
        opened again, whatever videos.list still says, and is "chat ended".
        A chat that only went missing (a 404) is not written off: if
        videos.list still has it as the activeLiveChatId, it is opened again.
        """
        data = self._get("videos", part="liveStreamingDetails", id=",".join(videos))
        items = [i for i in data.get("items") or [] if isinstance(i, dict)]
        why = "missing" if not items else "not live"
        for item in items:
            details = item.get("liveStreamingDetails")
            if not isinstance(details, dict):
                continue
            chat = details.get("activeLiveChatId")
            usable = isinstance(chat, str) and bool(YT_TOKEN.match(chat))
            if details.get("actualEndTime"):
                why = "ended"
            elif usable and chat != self._ended_chat:
                return chat, str(item.get("id") or "")
            else:
                why = "chat ended" if usable else "no chat"
        return None, why

    # ---- finding the chat --------------------------------------------------------
    def _find(self) -> float:
        kind, value = self.target
        if kind == "handle" and self._channel is None:
            # contentDetails in the same call (still 1 unit): the uploads
            # playlist the look reads
            data = self._get("channels", part="id,contentDetails",
                             forHandle=f"@{value}")
            found = [i for i in data.get("items") or [] if isinstance(i, dict)
                     and isinstance(i.get("id"), str)
                     and YT_CHANNEL_ID.match(i["id"])]
            if not found:
                self._set_connected(False, f"no YouTube channel {self.label}")
                return YT_SEARCH_EVERY
            self._channel = found[0]["id"]
            self._uploads = _uploads_of(found[0])
        if kind == "video":
            chat, video_or_why = self._live_chat([value])
            if chat is not None:
                return self._open(chat, video_or_why)
            if video_or_why == "missing" and self._maybe_handle:
                self._maybe_handle = False
                self.target, self.label = ("handle", value), f"@{value}"
                return 0.0
            self._set_connected(False, {
                "missing": "no YouTube video with that ID",
                "ended": "that YouTube live stream has ended",
                "chat ended": "the chat on that YouTube stream has ended",
                "no chat": "no live chat on that YouTube stream",
            }.get(video_or_why, "that YouTube video is not a live stream"))
            return YT_VIDEO_EVERY
        # A CHANNEL: THE VIDEO LAST SEEN LIVE ON IT FIRST, with videos.list
        # (1 unit), before a search that may have to wait 15 minutes -- this
        # reader's own, whose chat went missing, or the one the last reader
        # in this process found (the window restarts its readers when a
        # setting changes, and when it is opened again). Only if that video
        # is no longer live is it forgotten and the channel searched.
        video = self._video or self.searches.recall(self._channel)
        if video:
            chat, _why = self._live_chat([video])
            if chat is not None:
                return self._open(chat, video)
            self._video = ""
            self.searches.forget(self._channel, video)
        found = self._look()
        if found is None and self.searches.wait(self.clock()) <= 0:
            found = self._search()
        if isinstance(found, tuple):
            return self._open(*found)
        self._set_connected(False, f"waiting for a live stream on {self.label}")
        return YT_LOOK_EVERY

    def _look(self):
        """(chat, video) of a live stream among the channel's newest uploads,
        or None: videos.list on what playlistItems.list lists (2 units), and
        once a reader, channels.list for the playlist of a channel id."""
        if self._uploads is None:
            data = self._get("channels", part="contentDetails", id=self._channel)
            items = [i for i in data.get("items") or [] if isinstance(i, dict)]
            self._uploads = _uploads_of(items[0]) if items else ""
        if not self._uploads:
            return None
        try:
            data = self._get("playlistItems", part="contentDetails",
                             playlistId=self._uploads, maxResults=YT_LOOK_VIDEOS)
        except YouTubeError as exc:
            if exc.reasons & (YT_QUOTA | YT_RATE | YT_BAD_KEY | YT_NOT_ENABLED):
                raise
            if exc.code in (403, 404):  # nothing uploaded yet; not listable
                return None             # -- the search behind it still runs
            raise
        videos = []
        for item in data.get("items") or []:
            details = item.get("contentDetails") if isinstance(item, dict) else None
            video = details.get("videoId") if isinstance(details, dict) else None
            if isinstance(video, str) and YT_VIDEO_ID.match(video):
                videos.append(video)
        if not videos:
            return None
        chat, video = self._live_chat(videos)
        return (chat, video) if chat is not None and chat != self._chat else None

    def _search(self):
        """The channel's live stream: (chat, video), None when there is none,
        or the seconds to wait before a search may be made."""
        now = self.clock()
        wait = self.searches.wait(now)
        if wait > 0:
            if not self._chat:
                self._set_connected(False, (
                    f"waiting for a live stream on {self.label}" if self._searched
                    else f"looking for a live stream on {self.label} "
                         f"at {_at(now + wait)}"))
            return wait
        self.searches.spend(now)
        self._searched = True
        data = self._get("search", part="id", channelId=self._channel,
                         eventType="live", type="video", maxResults=5)
        videos = []
        for item in data.get("items") or []:
            video = (item.get("id") or {}).get("videoId") if isinstance(item, dict) else None
            if isinstance(video, str) and YT_VIDEO_ID.match(video):
                videos.append(video)
        chat, video = self._live_chat(videos) if videos else (None, "none")
        if chat is not None and chat != self._chat:
            return chat, video
        if not self._chat:
            self._set_connected(False, f"waiting for a live stream on {self.label}")
        return None

    def _open(self, chat: str, video: str) -> float:
        # A new chat starts at its end: `_read` uses a page token only in the
        # chat it came from. The same chat opened again after a 404 resumes
        # at its token, so nothing said in between is lost.
        self._chat, self._video, self._offline = chat, video, False
        if self._channel:
            self.searches.remember(self._channel, video)
        return 0.0

    # ---- reading it --------------------------------------------------------------
    def _read(self) -> float:
        if self._page is not None and (
                self._page_of != self._chat
                or self.clock() - self._read_at > self._due + YT_STALE):
            self._page = None       # after a long wait what chat said is old news
        params = {"liveChatId": self._chat, "part": "snippet,authorDetails"}
        first = self._page is None
        if first:
            params["maxResults"] = 200      # the backlog, skipped: the API's least
        else:
            params["pageToken"] = self._page
        data = self._get(YT_CHAT, **params)
        token = data.get("nextPageToken")
        if isinstance(token, str) and YT_TOKEN.match(token):
            self._page, self._page_of = token, self._chat
        self._backoff = YT_BACKOFF_FIRST
        self._read_at = self.clock()
        ended = False
        for item in data.get("items") or []:
            message = youtube_message(item)
            if message is ENDED:
                ended = True
            elif message is not None and not first:
                self._emit(message)
        if ended:
            return self._chat_over("that YouTube live stream has ended")
        # "offlineAt ... is only present if the stream is already offline":
        # the chat is still read (a stream that comes back is the same chat),
        # but the games do not listen to a stream nobody is watching.
        self._offline = bool(data.get("offlineAt"))
        if self._offline:
            self._set_connected(False, "the YouTube live stream is offline")
            if self.target[0] != "video":
                # a restarted stream is a new video: look for it, as a search
                # allows, and move to it if there is one
                found = self._search()
                if isinstance(found, tuple):
                    return self._open(*found)
        else:
            self._set_connected(True, "reading YouTube chat")
        try:
            asked = float(data.get("pollingIntervalMillis") or 0) / 1000.0
        except (TypeError, ValueError):
            asked = 0.0
        self._due = max(YT_POLL_FLOOR, min(YT_POLL_CAP, asked))
        return self._due

    def _chat_over(self, text: str) -> float:
        """YouTube said this chat is over: a chatEndedEvent, or a 403
        liveChatEnded. Only then is it written off for good."""
        if self._channel:
            self.searches.forget(self._channel, self._video)
        self._ended_chat, self._chat, self._page = self._chat, None, None
        self._video, self._offline = "", False
        self._set_connected(False, text)
        return 0.0

    def _chat_lost(self) -> float:
        """The poll answered 404 (liveChatNotFound). That is not YouTube
        saying the chat ended, so the chat is only put down: the next step
        asks videos.list (1 unit) whether the video still has it as its
        activeLiveChatId with no actualEndTime, and reads it again, at its
        page token, if so. The wait doubles while it keeps happening, as
        network trouble does, and is never under the poll floor. Written
        off at the first 404, a live stream stayed "ended" for the reader's
        life (review of 8ed: 45 minutes, and never polled again)."""
        self._chat, self._offline = None, False
        return max(YT_POLL_FLOOR, self._retry("YouTube chat not found"))

    # ---- refusals ----------------------------------------------------------------
    def _refused(self, exc: YouTubeError) -> float:
        reasons, code, now = exc.reasons, exc.code, self.clock()
        if reasons & YT_QUOTA:
            until = quota_reset(now) + YT_RESET_MARGIN
            if until - now > YT_JUST_RESET:
                until = now + YT_SEARCH_EVERY
            if exc.method == "search":
                # its own bucket: a chat already open is not affected
                self.searches.hold(until)
                if not self._chat:
                    self._set_connected(False, f"YouTube search quota used up "
                                               f"until {_at(until)}")
                return YT_POLL_FLOOR if self._chat else until - now
            self._set_connected(False, f"YouTube quota used up until {_at(until)}")
            return until - now
        if reasons & (YT_BAD_KEY | YT_NOT_ENABLED):
            self._set_connected(False, "YouTube API key rejected" + (
                " (API not enabled)" if reasons & YT_NOT_ENABLED else ""))
            return YT_KEY_EVERY
        if exc.method == YT_CHAT and reasons & YT_PAGE_BAD:
            self._page = None
            return YT_POLL_FLOOR
        if exc.method == YT_CHAT and "liveChatEnded" in reasons:
            return self._chat_over("that YouTube live stream has ended")
        if exc.method == YT_CHAT and "liveChatDisabled" in reasons:
            # The owner turned chat off, and may turn it on again: the video
            # is looked at again every 5 minutes, as a pasted one is.
            self._chat = None
            self._set_connected(False, "chat is off on that YouTube stream")
            return YT_VIDEO_EVERY
        if exc.method == YT_CHAT and ("liveChatNotFound" in reasons or code == 404):
            return self._chat_lost()
        if code == 429 or reasons & YT_RATE:
            return max(YT_POLL_FLOOR, self._retry("YouTube chat: too many requests"))
        if code == 404:
            self._set_connected(False, "no YouTube channel or video with that ID")
            return YT_VIDEO_EVERY
        if code in (401, 403):
            self._chat = None
            self._set_connected(False, "YouTube refused to show that chat")
            return YT_KEY_EVERY
        return self._retry(f"YouTube chat: YouTube error {code}")

    def _retry(self, what: str) -> float:
        wait = self._backoff
        self._backoff = min(YT_BACKOFF_CAP, self._backoff * 2)
        if self.connected and self.clock() - self._read_at < YT_GRACE:
            return wait                 # nothing is lost: the page token resumes
        self._set_connected(False, f"{what}, retrying in {wait:.0f}s")
        return wait


class FileChat:
    """Tails a text file of "name: message" lines on its own thread."""

    def __init__(self, path, on_line, on_state=None,
                 poll: float = FILE_POLL_SECONDS):
        self.path = Path(os.path.expanduser(str(path or ""))) if path else None
        self.on_line = on_line
        self.on_state = on_state or (lambda text: None)
        self.poll = poll
        self._stop = threading.Event()
        self.lines = 0
        # True while the file is there to read (the GUI's `listening`).
        self.connected = False

    def start(self) -> "FileChat":
        if self.path is None:
            return self
        threading.Thread(target=self._loop, daemon=True, name="file-chat").start()
        return self

    def stop(self) -> None:
        self._stop.set()

    @staticmethod
    def line_from(text: str) -> ChatLine | None:
        text = clean(text)
        if not text:
            return None
        name, sep, said = text.partition(":")
        name = name.strip()
        if not sep or not name or len(name) > 25 or " " in name:
            return ChatLine(user="chat", name="chat", text=text, platform="file")
        user = re.sub(r"[^a-z0-9_]", "", name.lower())[:25] or "chat"
        return ChatLine(user=user, name=clean(name, 25), text=said.strip(),
                        platform="file")

    def _loop(self) -> None:
        position = None
        pending = ""
        while not self._stop.is_set():
            try:
                size = self.path.stat().st_size
                if position is None or size < position:
                    # first look, or the file was truncated/rotated: start
                    # from its end rather than replaying it
                    position = size
                    pending = ""
                    self.connected = True
                    self.on_state("reading the chat file"
                                  if looks_secret(self.path.name)
                                  else f"reading {self.path.name}")
                elif size > position:
                    with self.path.open("rb") as handle:
                        handle.seek(position)
                        data = handle.read(min(size - position, 1 << 20))
                    position += len(data)
                    pending += data.decode("utf-8", "replace")
                    *lines, pending = pending.split("\n")
                    pending = pending[-LINE_MAX:]
                    for raw in lines:
                        line = self.line_from(raw)
                        if line is not None:
                            self.lines += 1
                            self.on_line(line)
            except OSError as exc:
                position = None
                self.connected = False
                # the system's words, never str(exc): that quotes the path
                self.on_state(f"chat file: {exc.strerror or type(exc).__name__}")
            self._stop.wait(self.poll)
