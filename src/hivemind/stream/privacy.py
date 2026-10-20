"""What the stream may show: the one gate every word passes, and the parts of
the game picture that are masked. No Qt in it, so it can be driven offline.

THE OWNER'S ASK: "make sure the stream window doesnt leak my priv info yk to
the public". The stream window draws the bot's own narration, and the bot
narrates for the owner, not for strangers. MEASURED over every
var/night/run-*.log (442 logs to run-452, 163,148 narrated lines -- the
timestamped ones `narrate` prints, which are the same words the socket
carries to the stream; scratchpad streamsafe/final/sweep.py, 26 September):

    /home/<user>/... paths       5 lines ("the frames are in /home/<user>/...")
    project file paths         152 lines ("written to var/bear_panels.json")
    memory and swap figures    220 lines ("only 8.9 GB free — unloaded ...")
    local clock times          411 lines ("booked for 12:19", DESIGN 8ec)
    the private-server code      0 lines, and no URL, IP, GUID, id, e-mail or
                                 bare domain at all, nor the Roblox username

With every rule on, 157 lines change, the 220 are dropped whole, and
162,771 pass unchanged.

The plain prints that never reach the socket carry far more (550 lines with
the home directory in tracebacks, 402 with the game's PID, 373 with the GUI
socket's path), and the Roblox client's own log, var/sober.log, carries the
server's JobId (a GUID), its IP and port, the account's user id and a join
URL. A clientlog reader is being built on feat/fieldsense; its events are
kept free of those by design, and this gate would catch them if one slipped.

So there is ONE gate, `Redactor`, and every piece of text the stream window
draws goes through it: each event at the door (`event`), each chat line
(`chat`), and every label and toast again as it is drawn (gui/stream_privacy).
A rule replaces what it matches with HIDDEN; a line that is only a system
detail is dropped whole. The defaults lean to hiding: anything shaped like a
path, a link, an address or an id is hidden unless it is one of the measured
harmless shapes (pollen/s, honey/hr, 45,000/1,215,000).

Chat cannot use this to make the stream print something private either: the
answers to !why !where !stats !goal are built from events that have passed the
gate, and are drawn through it again; a name chat suggests for a milestone is
text chat typed, and it is drawn through it too.

THE PRIVATE SERVER LINK is hidden by rules that no setting switches off: the
link shape (roblox.com/share?code=<32 hex>&type=Server, and the older
games/<id>?privateServerLinkCode=<code>), any code= or code: parameter, and
the share code's own shape, 32 hex digits, on its own. The rule is checked
against a fake link of the real shape (docs/pending/streamsafe.md); the real
one, in ~/.config/hivemind/server.yaml, is never read here.

DESIGN 8ec.
"""
from __future__ import annotations

import dataclasses
import datetime as dt
import getpass
import ipaddress
import re
import socket
import time
import unicodedata
from collections import Counter
from enum import Enum
from pathlib import Path

from ..telemetry.events import Frame, Log, Thought

HIDDEN = "[hidden]"

# ---- the rules ------------------------------------------------------------------

# THE FIRST PATH SEGMENTS THAT MARK A RELATIVE PATH as a path and not as a unit
# ("pollen/s") or a pair ("try/tries"): the project's own top-level folders and
# packages, and the system's. MEASURED: every slash token in the narration was
# pollen/s (31,257), honey/hr (258), a number pair (9,999/9,999 in its shapes),
# try/tries (15), or a path under var/, data/ or act/.
PATH_ROOTS = {
    "var", "data", "src", "scripts", "docs", "tools", "tests", "hivemind",
    "act", "behave", "brain", "cli", "economy", "gui", "ipc", "nav",
    "platform", "sim", "stream", "tasks", "telemetry", "vision", "world",
    "home", "run", "tmp", "usr", "etc", "opt", "proc", "sys", "dev", "mnt",
    "srv", "root", "nix", "media", "boot", "lib", ".config", ".cache",
    ".local", ".var", "flatpak", "org.vinegarhq.sober",
}
FILE_EXTENSION = re.compile(r"\.[A-Za-z0-9]{1,6}$")


def _not_a_path(match: re.Match) -> bool:
    """Is this slash token a unit or a pair (keep it) rather than a path?"""
    token = match.group(0).rstrip("/")
    parts = [p for p in token.split("/") if p]
    if len(parts) >= 3:
        return False
    if parts and parts[0].lower().lstrip(".") in {r.lstrip(".") for r in PATH_ROOTS}:
        return False
    return not (FILE_EXTENSION.search(token) and not token[:1].isdigit())


def _not_ipv6(match: re.Match) -> bool:
    """Keep a colon token that is not an IPv6 address: "12:34:56" is a time,
    and no narrated line has a "::" in it (MEASURED, DESIGN 8ec)."""
    token = match.group(0)
    if token.startswith("["):
        token = token[1:token.index("]")]
    try:
        ipaddress.IPv6Address(token.split("%")[0])
    except ValueError:
        return True
    return False


# THE STREAM'S OWN PLATFORM is public: its chat card says "reading
# twitch.tv/<channel>", the channel the viewers are watching.
PUBLIC_DOMAINS = ("twitch.tv",)


def _public_domain(match: re.Match) -> bool:
    host = match.group(0).split("/")[0].lower()
    return any(host == d or host.endswith("." + d) for d in PUBLIC_DOMAINS)


# THE ENDINGS OF A BARE DOMAIN ("example-shop.com", "bit.ly/3xYz",
# "discord.gg/abc123"): an e-mail's domain written on its own, a short link,
# an invite. MEASURED: no narrated line has a word.<one of these> in it
# (the rule fired on none of 161,507, to run-452), so it costs the narration
# nothing.
TLDS = ("com|net|org|gg|io|tv|me|co|au|uk|nz|ca|us|ly|app|dev|xyz|info|gl|link|"
        "to|be|de|fr|jp|live|site|online|shop|store|biz|ai|eu")

# (name, pattern, when, keep) -- `when` is "always" (no setting switches it
# off), "private" (stream.hide_private_text) or "drop" (the whole line goes
# when stream.hide_private_text is on); `keep(match)`, when given, keeps a
# match that is not what the rule is for. Checked in this order: a URL goes
# before the path inside it can be half-matched.
_I = re.IGNORECASE
RULES = [
    # THE PRIVATE SERVER LINK. The owner's is the share form (checked by its
    # shape only: https, www.roblox.com, /share, code= 32 lowercase hex,
    # type=Server); act/join and platform/session name the others.
    ("server link", re.compile(
        r"(?:\b[a-z][a-z0-9+.-]{1,20}:/{1,3})?(?:www\.|web\.)?roblox\.com/"
        r"[^\s'\"<>]*|\broblox(?:-player)?:[^\s'\"<>]+", _I), "always", None),
    # ...its code in any form: a parameter ("code=", "code: ") and the share
    # code's own shape on its own, 32 hex digits.
    ("server code", re.compile(
        r"\b(?:privateServerLinkCode|linkCode|accessCode|share_links|"
        r"gameInstanceId|jobId)\s*[=:]\s*[^\s&#'\"<>,;]+|"
        r"\bcode\s*[=:]\s*[^\s&#'\"<>,;]+|"
        r"(?<![0-9a-z])[0-9a-f]{32}(?![0-9a-z])", _I), "always", None),
    ("cookie", re.compile(r"_\|WARNING:-DO-NOT-SHARE-THIS[^\s'\"]*|"
                          r"\.ROBLOSECURITY\S*", _I), "always", None),
    # Any other link: a scheme (https, roblox, roblox-player, file, ws) or
    # a bare www. host.
    ("link", re.compile(r"\b[a-z][a-z0-9+.-]{1,20}://[^\s'\"<>]+|"
                        r"\bwww\.[a-z0-9-]+\.[^\s'\"<>]+", _I), "private", None),
    ("windows path", re.compile(r"\b[a-z]:\\[^\s'\"<>]*|\\\\[^\s'\"<>]+", _I),
     "private", None),
    ("path", re.compile(
        r"(?<![\w.:/~])/(?:[\w.@+-]+/)+[\w.@+-]*|"
        r"(?<![\w.:/~])/(?:home|run|tmp|usr|etc|var|opt|proc|sys|dev|mnt|root)"
        r"\b[\w./@+-]*|"
        r"(?<![\w/])~[\w.-]*/[^\s'\"<>)]*"), "private", None),
    ("relative path", re.compile(
        r"(?<![\w./-])(?:\.{1,2}/)?[A-Za-z_.][\w.-]*(?:/[\w.@+-]+)+/?"),
     "private", _not_a_path),
    ("email", re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "private", None),
    ("guid", re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-"
                        r"[0-9a-f]{12}\b", _I), "private", None),
    ("address", re.compile(
        r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?(?![\d.])|"
        r"\b(?:[0-9a-f]{1,4}:){4,7}[0-9a-f]{1,4}\b|"
        r"\b(?:localhost|(?:[a-z0-9-]+\.)+[a-z]{2,}):\d{2,5}\b", _I), "private", None),
    # IPv6 as it is usually written: compressed ("2001:db8::8a2e:370:7334"),
    # or in brackets with a port ("[fe80::1ff:fe23:4567:890a]:49152"). A
    # candidate is kept unless `ipaddress` parses it.
    ("ipv6", re.compile(
        r"\[[0-9a-f:.%\w]+\](?::\d{1,5})?|"
        r"(?<![\w:.])[0-9a-f]{0,4}(?::[0-9a-f]{0,4}){2,7}(?:%\w+)?(?![\w:])", _I),
     "private", _not_ipv6),
    ("domain", re.compile(
        r"(?<![\w.@/:-])(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+(?:" + TLDS +
        r")(?![\w-])(?:/[^\s'\"<>]*)?", _I), "private", _public_domain),
    ("long hex", re.compile(r"(?<![0-9a-z])[0-9a-f]{16,}(?![0-9a-z])", _I),
     "private", None),
    # A key or a token: 20+ characters mixing capitals, small letters and
    # digits, or 32+ letters and digits. The project's own long names
    # (natro_out_pine_tree_via_red_cannon) are lower case, and stay.
    ("token", re.compile(
        r"(?<![\w+/=-])(?=[\w+/=-]*\d)(?=[\w+/=-]*[a-z])(?=[\w+/=-]*[A-Z])"
        r"[\w+/=-]{20,}(?![\w+/=-])|"
        r"(?<![\w-])(?=[A-Za-z0-9]*\d)(?=[A-Za-z0-9]*[A-Za-z])[A-Za-z0-9]{32,}"
        r"(?![\w-])"), "private", None),
    # AN ID NAMED AS ONE, however its digits are grouped ("userId
    # 5,123,456,789"): a comma-grouped number on its own is a count.
    ("named id", re.compile(
        r"\b(?:user|player|place|universe|game|job|server|asset|group|creator|"
        r"account)[ _-]?id\b\s*[:=#]?\s*\d[\d,.]*", _I), "private", None),
    # AN ID, NOT A COUNT. The narration writes counts with commas (honey
    # 104,608,004); MEASURED, its bare digit runs are 6 to 8 long (48 lines,
    # OCR'd pollen pairs). Roblox user ids and place ids are 9 to 10 digits.
    # ...and whatever letters and digits are glued to it: "0123456789abcde"
    # (a 15-hex code) left "abcde" beside the HIDDEN.
    ("id number", re.compile(r"(?<![\d,.])\d{9,}[0-9A-Za-z]*(?![\d,])"), "private", None),
    ("process id", re.compile(r"\bpid\s*[:=]?\s*\d+\b", _I), "private", None),
    # SYSTEM DETAILS drop the whole line: "only 8.9 GB free — unloaded the
    # vision model, now 16.0 GB" is about the owner's machine, and there is
    # nothing left of it for a viewer once the numbers are gone.
    ("system detail", re.compile(
        r"\b\d+(?:\.\d+)?\s?[KMGT]i?B\b|\bswap\b|\bRSS\b|\bOOM\b|oom-kill|"
        r"MemoryMax|\bcgroup|Traceback \(most recent|^\s*File \"|\[Errno \d+\]",
        _I), "drop", None),
]

# ---- names ---------------------------------------------------------------------

# Look-alikes an OCR read or a vision model's answer can swap in for a
# letter of a name (a 4 read as A, a 0 as O or D, a g as q, an M as N, an n
# as r), and a viewer can type on purpose.
LOOKALIKE = {"a": "a4@", "o": "o0d", "i": "i1l|!", "l": "l1i|", "e": "e3",
             "s": "s5$", "t": "t7", "b": "b8", "g": "g9q", "z": "z2",
             "m": "mn", "n": "nr"}
SEPARATORS = "_-. "
# BETWEEN ANY TWO CHARACTERS OF A NAME: nothing, or up to three of these
# ("M-4ng0", "M4 ng0", "X - Y"; a zero-width space or a soft hyphen is taken
# out before the match, see `_fold`).
GAP = r"[\s_.\-]{0,3}"
# A NAME THIS LONG is hidden inside a longer word too ("xNAMEs"); a shorter
# one only as a word of its own, or glued before a capital ("AliceSmith").
GLUED_AT = 8

# CHARACTERS THAT DRAW LIKE LATIN ONES: Cyrillic and Greek capitals and small
# letters a viewer can type in place of the owner's name's letters, after
# NFKC has already turned fullwidth forms into ASCII.
CONFUSABLE = str.maketrans({
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O",
    "Р": "P", "С": "C", "Т": "T", "Х": "X", "У": "Y", "І": "I", "Ј": "J",
    "Ѕ": "S", "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y",
    "х": "x", "і": "i", "ј": "j", "ѕ": "s", "ԁ": "d", "ɡ": "g", "п": "n",
    "г": "r", "м": "m", "т": "t", "к": "k", "в": "b", "һ": "h",
    "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H", "Ι": "I", "Κ": "K",
    "Μ": "M", "Ν": "N", "Ο": "O", "Ρ": "P", "Τ": "T", "Υ": "Y", "Χ": "X",
    "α": "a", "ο": "o", "ν": "v", "ρ": "p", "τ": "t", "υ": "u", "χ": "x",
    "ι": "i", "κ": "k", "ϲ": "c",
})


def _alikes(ch: str) -> set:
    low = ch.lower()
    chars = {low} | set(LOOKALIKE.get(low, ""))
    for letter, alikes in LOOKALIKE.items():
        if low in alikes:
            chars |= {letter} | set(alikes)
    return chars | {c.upper() for c in chars}


def fuzzy_word(word: str) -> str:
    """A pattern for `word` that also matches its look-alike spellings, any
    case, with or without separators between its characters. Case is spelled
    out in each class (the pattern is not compiled IGNORECASE), so the end
    of a word can tell "AliceSmith" (a capital: another word) from
    "Alicely" (the same word going on)."""
    chars = [c for c in str(word) if c not in SEPARATORS]
    body = GAP.join("[" + "".join(re.escape(c) for c in sorted(_alikes(c))) + "]"
                    for c in chars)
    if len(chars) >= GLUED_AT:
        return body
    return r"(?<![A-Za-z0-9])" + body + r"(?:'?s)?(?![a-z0-9])"


def name_pattern(names) -> re.Pattern | None:
    """One pattern for every name, and for each part of it that has a digit
    in it: "B4ker_Bee" hides "B4ker_Bee", "Baker Bee", "B4kEr_B3e" and "B4ker"
    on its own.

    NOT A PLAIN-WORD PART. MEASURED with the owner's username: hiding its
    second, plain-word half on its own hid 22 narrated lines about one of
    the game's tokens, which are not his name."""
    alternatives = []
    for name in names:
        name = str(name or "").strip().lstrip("@")
        if len(name) < 2:
            continue
        alternatives.append(fuzzy_word(name))
        pieces = [p for p in re.split(r"[\s_.\-]+", name)
                  if len(p) >= 4 and any(c.isdigit() for c in p)]
        if len(pieces) > 1 or (pieces and pieces[0] != name):
            alternatives += [fuzzy_word(p) for p in pieces]
    if not alternatives:
        return None
    alternatives.sort(key=len, reverse=True)
    return re.compile("|".join(alternatives))


def _fold(text: str):
    """(the text a name is looked for in, the index in `text` of each of its
    characters). Fullwidth and other compatibility forms become ASCII (NFKC),
    Cyrillic and Greek look-alikes their Latin letters, and invisible
    characters -- a zero-width space, a soft hyphen, a combining accent --
    are taken out. None for an ASCII text, which is looked in as it is."""
    if text.isascii():
        return None
    out, where = [], []
    for i, ch in enumerate(text):
        if ch.isascii():
            out.append(ch)
            where.append(i)
            continue
        if unicodedata.category(ch) in ("Cf", "Mn", "Me"):
            continue
        folded = unicodedata.normalize("NFKC", ch).translate(CONFUSABLE)
        if folded and all(c.isascii() and (c.isalnum() or c in SEPARATORS)
                          for c in folded):
            out.extend(folded)
            where.extend([i] * len(folded))
        else:
            out.append(ch)
            where.append(i)
    return "".join(out), where


def _canon() -> dict:
    """Each look-alike to one letter for its whole group: m, n and r are one
    group (M read as N, n as r), and so are i, l, 1, | and !."""
    group = {}
    for letter, alikes in LOOKALIKE.items():
        members = {letter} | set(alikes)
        merged = set(members)
        for m in members:
            merged |= group.get(m, set())
        for m in merged:
            group[m] = merged
    return {ch: min(members) for ch, members in group.items()}


CANON = _canon()


def skeleton(text: str) -> str:
    """A name's letters and digits, folded and lower-cased, with every
    look-alike made its group's letter: what `too_close` compares."""
    folded = _fold(str(text or ""))
    text = folded[0] if folded else str(text or "")
    return "".join(CANON.get(ch, ch) for ch in text.lower()
                   if ch.isalnum() or ch in CANON)


def near_substring(needle: str, hay: str) -> int:
    """The fewest edits that make `needle` a substring of `hay` (Sellers)."""
    previous = [0] * (len(hay) + 1)
    for i, a in enumerate(needle, 1):
        current = [i]
        for j, b in enumerate(hay, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1,
                               previous[j - 1] + (a != b)))
        previous = current
    return min(previous)


def machine_names() -> list[str]:
    """The names this computer knows its owner by: the login name (on this
    machine, the owner's first name) and the host name. Read at run time, so
    no name is written into the code."""
    names = set()
    for get in (getpass.getuser, lambda: Path.home().name, socket.gethostname):
        try:
            value = str(get() or "").strip()
        except Exception:
            continue
        if len(value) >= 3 and value.lower() not in {"root", "user", "localhost"}:
            names.add(value)
    return sorted(names)


def _words(setting) -> list[str]:
    return [w.strip() for w in str(setting or "").split(",") if w.strip()]


REPEATS = re.compile(r"(?:\[hidden\][\s,;:/·—-]*){2,}")

# ---- the clock the stream shows -----------------------------------------------------
#
# A LOCAL TIME GIVES AWAY THE TIME ZONE, which narrows down where the owner
# lives. MEASURED: 411 narrated lines carry one ("booked for 12:19",
# "(the HUD, 26 Sep 11:19)"), and the stream draws its own (the header clock,
# every feed row, "Wealth Clock at ...", the records' times and a recap at
# local midnight). With stream.utc_times the stream shows every one of them
# in UTC, and its days are UTC days.
_SHOW_UTC = [False]


def show_utc(on: bool) -> None:
    """The open stream window says which clock it shows."""
    _SHOW_UTC[0] = bool(on)


def utc_shown() -> bool:
    return _SHOW_UTC[0]


def moment(at: float):
    """`at` as the stream shows it: a struct_time in UTC or local time."""
    return time.gmtime(at) if _SHOW_UTC[0] else time.localtime(at)


def clock_text(at: float, fmt: str = "%H:%M", zone: bool = False) -> str:
    return time.strftime(fmt, moment(at)) + (" UTC" if zone and _SHOW_UTC[0] else "")


def date_text(at: float, fmt: str) -> str:
    """strftime at `moment(at)`, where "%-d" is the day of the month with no
    leading zero on every OS: glibc does it, Windows raises ValueError:
    Invalid format string (MEASURED 2026-10-21)."""
    tm = moment(at)
    return time.strftime(fmt.replace("%-d", str(tm.tm_mday)), tm)


def day_start(at: float) -> float:
    """The midnight at or before `at`, on the clock the stream shows."""
    if _SHOW_UTC[0]:
        return float(int(at // 86400) * 86400)
    day = dt.datetime.fromtimestamp(at).date()
    return dt.datetime.combine(day, dt.time()).timestamp()


MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct",
          "Nov", "Dec")
# EVERY CLOCK TIME IN THE NARRATION. MEASURED, the 467 in it are all
# times of day ("booked for", "due at", "after", "since", "until", "ready
# at", "(the HUD, 26 Sep 11:19)"); none is a duration.
CLOCK_TIME = re.compile(
    r"(?<![\d:.])(?:(\d{1,2}) (" + "|".join(MONTHS) + r") )?"
    r"([01]?\d|2[0-3]):([0-5]\d)(?::([0-5]\d))?(?![\d:])")


def utc_clock(text: str, now: float | None = None) -> str:
    """The narration's local clock times as UTC ones, with the offset in
    force now (a time from the other side of a daylight-saving change is off
    by that hour)."""
    if ":" not in text:
        return text
    now = time.time() if now is None else now
    local = dt.datetime.fromtimestamp(now)
    offset = dt.timedelta(seconds=time.localtime(now).tm_gmtoff)

    def to_utc(m: re.Match) -> str:
        day, month, hour, minute, second = m.groups()
        try:
            when = local.replace(hour=int(hour), minute=int(minute),
                                 second=int(second or 0), microsecond=0)
            if day:
                when = when.replace(month=MONTHS.index(month) + 1, day=int(day))
        except ValueError:
            return m.group(0)
        utc = when - offset
        text = utc.strftime("%H:%M:%S" if second else "%H:%M")
        if day:
            text = f"{utc.day} {MONTHS[utc.month - 1]} {text}"
        return text + " UTC"
    return CLOCK_TIME.sub(to_utc, text)


class Redactor:
    """The one gate. `scrub(text)` is the text a viewer may see, or None for
    a line that is dropped whole; `counts` is how often each rule fired."""

    CACHE = 4096

    def __init__(self, settings=None, machine=None):
        self.counts: Counter = Counter()
        self.dropped = 0
        self._machine = list(machine) if machine is not None else machine_names()
        self.configure(settings or {})

    def configure(self, settings) -> None:
        get = settings.get if hasattr(settings, "get") else (lambda k, d=None: d)
        self.private = bool(get("stream.hide_private_text", True))
        hide_user = bool(get("stream.hide_username", True))
        self.utc = bool(get("stream.utc_times", False))
        people = list(self._machine)
        if hide_user:
            people.append(str(get("account.username", "") or ""))
        people += _words(get("stream.private_words", ""))
        self._people = [p for p in people if len(str(p).strip()) >= 2]
        self._names = name_pattern(people)
        self._close = [s for s in (skeleton(p) for p in self._people) if s]
        self._cache: dict = {}

    # ---- text ----------------------------------------------------------------
    def scrub(self, text) -> str | None:
        """What may be drawn of `text`; None when the whole line is dropped."""
        if text is None:
            return None
        text = str(text)
        if not text:
            return text
        hit = self._cache.get(text, self)
        if hit is not self:
            return hit
        out = self._scrub(text)
        if len(self._cache) >= self.CACHE:
            self._cache.clear()
        self._cache[text] = out
        return out

    def text(self, text) -> str:
        """`scrub` for a label: a dropped line draws as nothing."""
        out = self.scrub(text)
        return "" if out is None else out

    def _scrub(self, text: str) -> str | None:
        for name, pattern, when, keep in RULES:
            if when != "always" and not self.private:
                continue
            if when == "drop":
                if pattern.search(text):
                    self.counts[name] += 1
                    self.dropped += 1
                    return None
                continue
            if keep is not None:
                hits = []

                def hide(m, hits=hits, keep=keep):
                    if keep(m):
                        return m.group(0)
                    hits.append(1)
                    return HIDDEN
                text = pattern.sub(hide, text)
                n = len(hits)
            else:
                text, n = pattern.subn(HIDDEN, text)
            if n:
                self.counts[name] += 1
        if self._names is not None:
            text, n = self._hide_names(text)
            if n:
                self.counts["name"] += 1
        return REPEATS.sub(HIDDEN + " ", text).rstrip() if HIDDEN in text else text

    def _hide_names(self, text: str):
        folded = _fold(text)
        if folded is None:
            return self._names.subn(HIDDEN, text)
        shadow, where = folded
        spans = [(where[m.start()], where[m.end() - 1] + 1)
                 for m in self._names.finditer(shadow) if m.end() > m.start()]
        for start, end in reversed(spans):
            text = text[:start] + HIDDEN + text[end:]
        return text, len(spans)

    def too_close(self, words: str) -> bool:
        """Is `words` one of the hidden names spelt some other way? A name of
        GLUED_AT letters or more may be one edit off ("B4ker_Bea" for
        "B4ker_Bee"), a shorter one must match once folded."""
        have = skeleton(words)
        if not have:
            return False
        for name in self._close:
            slack = 1 if len(name) >= GLUED_AT else 0
            if len(have) + slack >= len(name) and near_substring(name, have) <= slack:
                return True
        return False

    # ---- events --------------------------------------------------------------
    def event(self, event):
        """The event with every string in it scrubbed, or None to drop it (a
        Log or Thought whose line is only a system detail). A Frame keeps its
        path and pixels; only its detection labels are words to draw."""
        if event is None:
            return None
        if isinstance(event, Frame):
            return self.frame(event)
        if isinstance(event, (Log, Thought)):
            main = event.message if isinstance(event, Log) else event.text
            if main and self.scrub(main) is None:
                return None
        return self._value(event, door=True)

    def frame(self, frame: Frame) -> Frame:
        """A Frame whose detection labels have passed the gate: the live view
        draws each one on the picture (panels/liveview). The same Frame when
        nothing in it changes, which is every frame today (the labels are
        fixed words: pollen, honey, token, mob health bar)."""
        out, changed = [], False
        for det in frame.detections or ():
            if isinstance(det, dict):
                label = det.get("label", det.get("kind", ""))
                if isinstance(label, str) and label:
                    clean = self.text(label)
                    if clean != label:
                        det, changed = {**det, "label": clean}, True
            out.append(det)
        return dataclasses.replace(frame, detections=out) if changed else frame

    def data(self, value):
        """Anything read from a file -- a ledger row, var/quests.json -- with
        every string in it scrubbed; a dropped line becomes ""."""
        return self._value(value)

    def _value(self, value, door: bool = False):
        # an Enum first: Level and Autonomy are str Enums, and stay Enums
        if isinstance(value, Enum) or value is None or isinstance(value, (int, float)):
            return value
        if isinstance(value, str):
            out = self.text(value)
            # THE NARRATION'S CLOCK TIMES, at the door only: a label's own
            # "1:59" is the vote's countdown, not a time of day.
            return utc_clock(out) if door and self.utc and out else out
        if isinstance(value, list):
            return [self._value(v, door) for v in value]
        if isinstance(value, tuple):
            return tuple(self._value(v, door) for v in value)
        if isinstance(value, dict):
            return {k: self._value(v, door) for k, v in value.items()}
        if dataclasses.is_dataclass(value) and not isinstance(value, type):
            changes = {}
            for f in dataclasses.fields(value):
                if not f.init:
                    continue
                old = getattr(value, f.name)
                new = self._value(old, door)
                if new is not old and new != old:
                    changes[f.name] = new
            return dataclasses.replace(value, **changes) if changes else value
        return value

    def chat(self, line):
        """A chat line with the words a viewer sees scrubbed: its text, and
        the name it is shown under. NOT ITS KEYS: `id` is Twitch's message
        UUID, which a moderator's CLEARMSG names to take that one message
        back, and `user` is the login votes, calls and the leaderboard are
        kept under. The "guid" rule turned every id into HIDDEN, so every
        message was remembered under one key and a CLEARMSG took back the
        wrong one (review/chat_id_drive.py, DESIGN 8ec); a user shown is
        shown by `name`, and every label scrubs again as it draws.

        A "!name" whose words are a hidden name spelt another way is refused
        here: the words become HIDDEN, which `show.NAME_OK` does not accept."""
        if not dataclasses.is_dataclass(line):
            return line
        changes = {}
        text = getattr(line, "text", None)
        if isinstance(text, str):
            command, _, rest = text.strip().partition(" ")
            if command.lower() == "!name" and self.too_close(rest):
                text = f"{command} {HIDDEN}"
            changes["text"] = self.text(text)
        name = getattr(line, "name", None)
        if isinstance(name, str):
            # an empty name is shown as the login (stream/show), so the login
            # is what is scrubbed into it
            changes["name"] = self.text(name or getattr(line, "user", "") or "")
        changes = {k: v for k, v in changes.items() if v != getattr(line, k)}
        return dataclasses.replace(line, **changes) if changes else line


# ---- the game picture -------------------------------------------------------------
#
# Regions in the coordinates of the 1920x1080 frame the bot captures, as
# (x, y, w, h). Each was measured on saved frames; a frame of another size
# (feat/streamfps decodes 960x540 for a view that small) is scaled to them.
FRAME_W, FRAME_H = 1920, 1080

# THE ROBLOX CHAT. Its window opens under the top bar at the top left, and
# the chat icon's unread badge (blue, about RGB 55,90,245) is drawn only while
# that window is shut. MEASURED over 358,353 saved frames under var/ (every
# incident, route, homing and school frame): the badge was there on every
# frame with the top bar except 150, all of one Sober loading screen
# (incidents/192818-refused). So the chat window has never been open on a saved
# frame, and its size could not be measured. Roblox's legacy chat opened at
# 30% by 25% of the screen (ChatSettings.DefaultWindowSizeDesktop), 576x270
# here, and players can scale it; the region holds 1.5 times that, 864x405,
# and its input bar: x 0-880, from under the top bar to half-way down.
TOPBAR_PILL = (72, 14, 128, 36)     # the dark pill holding menu, chat, mic
CHAT_BADGE = (140, 18, 18, 20)      # the unread badge on the chat icon
CHAT_REGION = (0, 56, 880, 484)

# ROBLOX'S MENU PANEL: the Esc menu opens on People, which lists everyone in
# the server by display name and @username -- the owner's included
# (tests/fixtures/screens/escape_menu.png shows his display name and
# @username there; loading_escape_menu.png four players). The bot opens it at
# every respawn (act/routes._reset: Escape, then R 0.5 s later), and the
# respawn confirmation is drawn in the same panel. MEASURED on those fixtures
# and reset_dialog.png: the panel's edges are at x=540 and x=1380, its top at
# 182 and its bottom at 916 on all three.
MENU_PANEL = (540, 182, 840, 734)
# THE PANEL IS A DARKENING, NOT A COLOUR. MEASURED on the three fixtures and
# on incidents/183123-death 000-001 (the only real menu frames saved): just
# inside each of its four edges the luma is 0.29 to 0.33 of the luma just
# outside, at outside luma from 44 to 79 -- a multiplication, whatever the
# game under it. So each edge is tested as a ratio, on all four edges, and an
# edge too dark outside to show a ratio (under EDGE_FLOOR) abstains.
MENU_ROWS = tuple(range(260, 850, 20))              # the side edges' rows
MENU_COLUMNS = tuple(range(600, 1320, 24))          # the top and bottom's
MENU_LEFT_IN, MENU_LEFT_OUT = (544, 8), (526, 8)       # (x, width)
MENU_RIGHT_IN, MENU_RIGHT_OUT = (1368, 8), (1384, 8)
MENU_TOP_IN, MENU_TOP_OUT = (186, 8), (170, 8)         # (y, height)
MENU_BOTTOM_IN, MENU_BOTTOM_OUT = (904, 8), (920, 8)
EDGE_RATIO = 0.8        # inside against outside (0.29-0.33 measured)
EDGE_SHARE = 0.7        # of an edge's judged rows
EDGE_FLOOR = 6.0        # outside luma a ratio can be read from
EDGE_ROWS = 8           # judged rows an edge needs to take part
EDGE_NEED = 2           # edges that must take part
# THE PANEL'S SELECTED BUTTON is opaque, so it reads the same over any game,
# a dark one included, where the edges' darkening cannot be read (MEASURED:
# of the menu composited over 4,832 saved frames, the edges alone missed 48
# at full opacity, every one a night or wall-facing scene). Both pages the
# bot shows have one, the same blue under the same 3-px white border:
#   - People's Resume: RGB (29, 47, 111) +-1 over x 1099-1359, y 849-896 on
#     both People fixtures, the border at y 843-845;
#   - the respawn confirmation's Respawn: RGB (26, 52, 109) over x 750-949,
#     y 460-507 on reset_dialog.png, the border at y 452-454; on all 15 real
#     confirmations saved (var/respawn/*-unknown 7, homing/attempt-450 8),
#     sampled as the guard samples it, the fill's median was within 14 of
#     that on every channel, every pixel within RESUME_TOLERANCE, and the
#     border lit.
# The border is sampled five rows deep and read by its brightest row: at a
# half-size decode three rows become one and a half.
RESUME_FILL = (29, 47, 111)
RESUME_FILL_AT = (1110, 855, 250, 36)    # sampled clear of its label
RESUME_LABEL_X = (1180, 1290)            # the label, not sampled
RESUME_BORDER_AT = (1110, 842, 240, 5)
RESPAWN_FILL_AT = (760, 466, 180, 36)
RESPAWN_LABEL_X = (810, 890)
RESPAWN_BORDER_AT = (770, 451, 160, 5)
MENU_BUTTONS = ((RESUME_FILL_AT, RESUME_LABEL_X, RESUME_BORDER_AT),
                (RESPAWN_FILL_AT, RESPAWN_LABEL_X, RESPAWN_BORDER_AT))
RESUME_TOLERANCE = 28   # per channel: a button at 90% opacity over white
RESUME_SHARE = 0.8
# MEASURED with these rules (fix/menu_eval3.py, button_eval.py, over 26,724
# saved frames: 9,155 route, 167 respawn, 1,540 homing, 2,850 death-incident
# and every 25th of the mob-sighting incidents, 13,012): every fire is a
# real menu or respawn confirmation (3 respawn frames, the 2 of 183123, the 3
# fixtures), none a game frame. Over the menu composited onto the 9,322
# route and respawn frames at the darkening measured from 183123, the
# People page is found on all of them at full opacity and at 90%.
MENU_HOLD_SECONDS = 1.0         # a mask stays this long after its last sign
# THE BOT SAYS WHEN IT OPENS THE MENU (telemetry/events.GameMenu, from
# act/routes._reset), so the panel is covered from before the Escape until
# this long after it says the menu is shut; a menu whose closing is never
# said is uncovered after MENU_EVENT_MOST_S.
MENU_AFTER_SECONDS = 1.0
MENU_EVENT_MOST_S = 20.0
MENU_LINE_SECONDS = 3.0         # from a "respawning" line (`MenuWatch`)

# THE BLUR: a region is shrunk this many times and drawn back up smoothly.
# MEASURED offscreen on saved frames: 0.09 ms for the chat region, 0.14 ms
# for the menu panel (median of 100). At 16x a 14-px chat line is under a
# pixel.
BLUR_FACTOR = 16


def luma(rgb):
    """Rec. 601 luma of an (..., 3) RGB array, as float32."""
    import numpy as np
    rgb = np.asarray(rgb, dtype=np.float32)
    return rgb[..., 0] * 0.299 + rgb[..., 1] * 0.587 + rgb[..., 2] * 0.114


def chat_may_be_open(pill_rgb, badge_rgb) -> bool:
    """True when the top bar is up and its chat icon has no unread badge:
    the chat window may be open (or nothing is unread, which never happened
    on a saved frame; a blur then costs nothing)."""
    import numpy as np
    pill = np.asarray(pill_rgb, dtype=np.int16)
    badge = np.asarray(badge_rgb, dtype=np.int16)
    if pill.size == 0 or badge.size == 0:
        return False
    # the pill: 74-79% of its box under 60 on every channel, measured
    if (pill.max(axis=-1) < 60).mean() < 0.5:
        return False
    blue = ((badge[..., 2] > 190) & (badge[..., 0] < 110)
            & (badge[..., 1] > 50) & (badge[..., 1] < 140))
    return blue.mean() < 0.08


def menu_edges(pairs) -> bool:
    """The menu panel's darkening on its edges. `pairs` are (inside,
    outside) luma arrays, one value per sampled row or column, for the left,
    right, top and bottom edges."""
    import numpy as np
    judging = 0
    for inside, outside in pairs:
        i = np.asarray(inside, np.float32)
        o = np.asarray(outside, np.float32)
        if i.size == 0 or i.shape != o.shape:
            continue
        lit = o >= EDGE_FLOOR
        judged = int(lit.sum())
        if judged < EDGE_ROWS:
            continue                      # too dark to tell: abstains
        judging += 1
        if ((i <= EDGE_RATIO * o) & lit).sum() < EDGE_SHARE * judged:
            return False
    return judging >= EDGE_NEED


def resume_button(fill_rgb, border_rgb) -> bool:
    """A selected menu button (People's Resume, the confirmation's Respawn):
    its blue fill and its white border."""
    import numpy as np
    fill = np.asarray(fill_rgb, np.float32).reshape(-1, 3)
    border = np.asarray(border_rgb, np.float32).reshape(-1, 3)
    if fill.size == 0 or border.size == 0:
        return False
    near = (np.abs(fill - np.asarray(RESUME_FILL, np.float32))
            <= RESUME_TOLERANCE).all(axis=-1).mean()
    lit = (border >= 200).all(axis=-1).mean()
    return bool(near >= RESUME_SHARE and lit >= RESUME_SHARE)


def menu_open(left_in, left_out, right_in, right_out, top=None, bottom=None,
              fill=None, border=None) -> bool:
    """Is Roblox's menu panel up? Its edges' darkening (`menu_edges`), or
    the People page's Resume button (`resume_button`)."""
    pairs = [(left_in, left_out), (right_in, right_out)]
    pairs += [p for p in (top, bottom) if p is not None]
    if menu_edges(pairs):
        return True
    return fill is not None and border is not None and resume_button(fill, border)


def menu_in_frame(frame) -> bool:
    """`menu_open` on a whole BGR frame (numpy, as the bot captures it): the
    gui's `_menu_seen` without Qt, for the bot's own looks (act/bootstrap)."""
    import cv2
    import numpy as np
    if frame is None or getattr(frame, "ndim", 0) != 3:
        return False
    bgr = frame[:, :, :3]
    if bgr.shape[:2] != (FRAME_H, FRAME_W):
        bgr = cv2.resize(bgr, (FRAME_W, FRAME_H), interpolation=cv2.INTER_AREA)
    y = luma(bgr[..., ::-1])
    rows, cols = list(MENU_ROWS), list(MENU_COLUMNS)
    pairs = [tuple(y[rows, x:x + w].mean(axis=1) for x, w in edge)
             for edge in ((MENU_LEFT_IN, MENU_LEFT_OUT), (MENU_RIGHT_IN, MENU_RIGHT_OUT))]
    pairs += [tuple(y[r:r + h, cols].mean(axis=0) for r, h in edge)
              for edge in ((MENU_TOP_IN, MENU_TOP_OUT), (MENU_BOTTOM_IN, MENU_BOTTOM_OUT))]
    if menu_edges(pairs):
        return True
    rgb = bgr[..., ::-1]
    for (fx, fy, fw, fh), (lx0, lx1), (bx, by, bw, bh) in MENU_BUTTONS:
        fill = rgb[fy:fy + fh, fx:fx + fw]
        fill = np.concatenate([fill[:, :lx0 - fx].reshape(-1, 3),
                               fill[:, lx1 - fx:].reshape(-1, 3)])
        border = rgb[by:by + bh, bx:bx + bw]
        border = border[int(np.argmax(luma(border).mean(axis=1)))]
        if resume_button(fill, border):
            return True
    return False


def menu_strips(frame_luma):
    """The four side-edge strips of a whole-frame luma array, one value a
    row (the drives' offline form of what gui/stream_privacy reads)."""
    rows = list(MENU_ROWS)
    out = []
    for x, w in (MENU_LEFT_IN, MENU_LEFT_OUT, MENU_RIGHT_IN, MENU_RIGHT_OUT):
        out.append(frame_luma[rows][:, x:x + w].mean(axis=1))
    return out


# THE ROBLOX APP ITSELF: its home page shows the account's display name and
# the whole friends list (var/join/*.png, all eight classified app_home by
# vision/screenstate). The live view starts after the join (scripts/run_farm
# starts it once in game), so it shows the app only if the game falls back to
# it mid-run. The frame's own `screen` says so; MEASURED, 1 of 8,852 route
# frames and 1 of 2,297 incident first frames were called app_home in the
# game world (a bright hive wall), so a cover is held a little and costs a
# second of picture when it is wrong.
APP_SCREENS = {"app_home"}
APP_HOLD_SECONDS = 2.0
# KEY COLOUR: OBS draws its own capture of the game's window under the
# stream's green, live, at 60 fps -- every screen of every rejoin included
# (MEASURED, run-447: the app home at 8 s, the game at 38 s; 41 rejoins on
# 25 September). With no Frame for this long the stream cannot see what that
# capture shows, so the whole picture is covered.
KEYED_BLIND_SECONDS = 1.5


class MenuWatch:
    """Is Roblox's menu up, by the bot's word or by its pixels? Held a
    little past the last sign of it (MENU_HOLD_SECONDS, MENU_AFTER_SECONDS):
    a frame reaches the stream after the screen showed it."""

    def __init__(self, clock=time.time):
        self.clock = clock
        self._said_at: float | None = None   # the bot said it is opening it
        self._until = 0.0

    def hear(self, event) -> None:
        now = self.clock()
        if getattr(event, "kind", "") != "game_menu":
            # A BOT THAT PREDATES THE MENU WORD still says "respawning (...)"
            # just before its reset: MEASURED in run-452, 8.6-9.0 s before
            # "respawned onto our own pad", which is the reset's 0.1 + 0.5 +
            # 0.5 s of menu and its 7.5 s settle.
            text = (event.message if isinstance(event, Log) else
                    event.text if isinstance(event, Thought) else None)
            if isinstance(text, str) and text.startswith("respawning"):
                self._until = max(self._until, now + MENU_LINE_SECONDS)
            return
        if getattr(event, "up", False):
            self._said_at = now
        else:
            self._said_at = None
            self._until = max(self._until, now + MENU_AFTER_SECONDS)

    def seen(self) -> None:
        self._until = max(self._until, self.clock() + MENU_HOLD_SECONDS)

    def said(self) -> bool:
        return (self._said_at is not None
                and self.clock() - self._said_at < MENU_EVENT_MOST_S)

    def up(self) -> bool:
        return self.said() or self.clock() < self._until
