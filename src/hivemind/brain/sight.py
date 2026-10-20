"""What the shop windows SHOWED owned: CHECK, DON'T ASK (ROADMAP G13).

THE OWNER, 2026-10-19: "somtimes the questions feel super unnessesary... do
you have this certain gear? instead of asking that it will check, wether that
means going to the shop and checking or somthing else". Four kinds of card
asked him what he owns (progression's "Which boots do you wear?", owned's
"Did you buy the X?" and "did you buy one of these?", goals' "I bought it").
A shop's item panel already answers that, and act/shoplook already reads it:

  * OWNED -- the button is not a price. MEASURED in var/shoplook.json, the
    Mountain Top Shop's catalogue of 2026-10-03 05:50: "Beekeeper's Boots |
    15.000.000 Honey | Edguipped" (the dimmed teal button, worn), "Beekeeper's
    Mask | 20,000.000 Honey | Edguip" (owned, not worn -- a GREEN button, the
    same green as "Buy for", so only the words tell it), and the Ticket Tent's
    "Festive Bee Egg | 500 Tickets | Purchased" (06:10). "Owned" is taken too,
    though no saved frame shows it.
  * NOT OWNED -- a price: "Buy for 60,000,000 Honey", "Can't afford", "Craft
    Item" (the Blue HQ's, 2026-10-07), a bare "Purchase".
  * anything else is unknown, and says nothing.

A READ COUNTS ONLY FOR THE ITEM IT NAMES: the panel's name must be an item of
the price table under its own key, label or alias (brain/owned.item_key, the
same exact-name rule act/shoplook.buy holds a purchase to). A clipped or
misread name is nobody's evidence.

Every read goes into var/owned_by_sight.json with its time and its frame; the
newest of each state is kept per item. Gear in this game is never lost, so an
item seen owned once is owned (brain/owned.SEEN) and its question is not
asked. Nothing here presses anything: the shop errand that looks (run_farm,
`owned_check_due`) is the existing read-only look and browse.
"""
from __future__ import annotations

import contextlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

SIGHT_FILE = "owned_by_sight.json"
OWNED = "owned"
NOT_OWNED = "not owned"
# ONE VISIT PER ITEM PER DAY (ROADMAP G13): a shop walk takes a convert's
# errand, and what was not seen today can wait for tomorrow's look.
CHECK_EVERY_S = 24 * 3600.0
# "Equip", "Edguip", "Eguiph", "Equipped", "Edguipped": the OCR spells it a
# dozen ways (var/shoplook.json, 2026-10-03); anything starting e..p in the
# button's place. "Buy for" and "Can't afford" never match.
EQUIP = re.compile(r"^\s*e\S{0,3}u?i?\S{0,2}p", re.I)


def button_state(button) -> tuple[str, bool]:
    """(OWNED / NOT_OWNED / "", worn) from a window's button words."""
    low = " ".join(str(button or "").lower().split())
    letters = re.sub(r"[^a-z]+", "", low)
    if not letters:
        return "", False
    if letters.startswith("purchased") or letters.startswith("owned"):
        return OWNED, False
    if EQUIP.match(low):
        return OWNED, letters.endswith("ed")
    if ("buy for" in low or letters.startswith(("cant", "purchase", "craftitem"))
            or "afford" in letters):
        return NOT_OWNED, False
    return "", False


def shown(rec: dict) -> str:
    """How the button read, in the game's own words."""
    if rec.get("state") == NOT_OWNED:
        return f"a price ({rec.get('button')!r})"
    letters = re.sub(r"[^a-z]+", "", str(rec.get("button") or "").lower())
    if letters.startswith(("purchased", "owned")):
        return "Purchased" if letters[0] == "p" else "Owned"
    return "Equipped" if rec.get("worn") else "Equip"


def _when(at) -> str:
    return time.strftime("%d %b %H:%M", time.localtime(float(at or 0)))


def _shop(rec: dict) -> str:
    """The shop, from the look's key: "mountain_top_catalogue", "mts_buy:
    hive_slot:..." and the errand's "owned_check:mountain_top_shop:20261019"
    are all the Mountain Top Shop."""
    parts = str(rec.get("shop") or "?").split(":")
    stem = parts[1] if parts[0] == "owned_check" and len(parts) > 1 else parts[0]
    stem = re.sub(r"_(buy|catalogue)$", "", stem)
    stem = {"mts": "mountain_top_shop", "mountain_top": "mountain_top_shop"}.get(stem, stem)
    return stem.replace("_", " ")


# ---- recording ---------------------------------------------------------------
def _frames_of(entry: dict) -> tuple[str | None, dict]:
    """(the window's frame, {catalogue index: frame}) out of a look's kept
    paths: act/shoplook.look keeps "<stamp>-window.png", and browse's keep
    tags "browse-NN" (run_farm prefixes "mts-", "bluehq-")."""
    window, browse = None, {}
    for path in entry.get("kept") or []:
        path = str(path)
        if re.search(r"-window\.\w+$", path):
            window = path
        found = re.search(r"browse-(\d+)\.\w+$", path)
        if found:
            browse[int(found.group(1))] = path
    return window, browse


def reads_of(entry: dict, table: dict) -> list:
    """[(key, record)] for every item panel a shoplook.json entry read whose
    name is an item of `table` and whose button says owned or not."""
    from ..act.shoplook import item_name
    from .owned import item_key
    window, browse = _frames_of(entry)
    lines = [(str(entry.get("window") or ""), window)]
    lines += [(str(w or ""), browse.get(i)) for i, w in enumerate(entry.get("catalogue") or [])]
    out = []
    for text, frame in lines:
        parts = [p.strip() for p in text.split("|")]
        if len(parts) < 3:
            continue
        key = item_key(item_name(text), table)
        state, worn = button_state(parts[2])
        if key and state:
            out.append((key, {"state": state, "worn": worn, "button": parts[2],
                              "window": text[:200], "shop": str(entry.get("shop") or ""),
                              "at": float(entry.get("at") or 0.0), "frame": frame}))
    return out


def _merge(items: dict, reads: list) -> list:
    """Keep the newest read of each state per item; the keys that changed."""
    changed = []
    for key, rec in reads:
        body = items.setdefault(key, {})
        old = body.get(rec["state"])
        if old is None or float(old.get("at") or 0) <= rec["at"]:
            if old is None or (old.get("worn"), old.get("frame")) != (rec["worn"], rec["frame"]):
                changed.append(key)
            body[rec["state"]] = rec
    return changed


def _backfill(var_root: Path, table: dict) -> dict:
    """Every look already in var/shoplook.json, as evidence (in memory)."""
    try:
        looks = json.loads((var_root / "shoplook.json").read_text()).get("looks") or []
    except (OSError, ValueError, AttributeError):
        looks = []
    items: dict = {}
    for entry in looks:
        if isinstance(entry, dict):
            _merge(items, reads_of(entry, table))
    return items


def _read(var_root: Path) -> dict:
    try:
        body = json.loads((var_root / SIGHT_FILE).read_text())
        return body if isinstance(body, dict) else {}
    except (OSError, ValueError):
        return {}


@contextlib.contextmanager
def _locked(var_root: Path):
    from ..files import atomic_write, locked
    lock = var_root / f".{SIGHT_FILE}.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    with open(lock, "a") as handle, locked(handle):
        body = _read(var_root)
        yield body
        atomic_write(var_root / SIGHT_FILE, json.dumps(body, indent=1))


_CACHE: dict = {}


def load(var_root, table: dict | None = None) -> dict:
    """{key: {OWNED: rec, NOT_OWNED: rec}}. READ-ONLY (the planner and the
    window read it every heartbeat): a file never written yet is the saved
    looks' reads, computed here and written by the first `record_look`."""
    from .owned import prices
    var_root = Path(var_root)
    table = prices() if table is None else table
    stamps = []
    for name in (SIGHT_FILE, "shoplook.json"):
        try:
            stamps.append((var_root / name).stat().st_mtime_ns)
        except OSError:
            stamps.append(None)
    hit = _CACHE.get(str(var_root))
    if hit and hit[0] == (stamps, id(table)):
        return hit[1]
    body = _read(var_root)
    items = body.get("items") if isinstance(body.get("items"), dict) else {}
    if "backfill" not in body:
        items = _merge_into(_backfill(var_root, table), items)
    _CACHE[str(var_root)] = ((stamps, id(table)), items)
    return items


def record_look(var_root, entry: dict, clock=time.time) -> list:
    """One look (a var/shoplook.json entry) into var/owned_by_sight.json;
    the item keys whose evidence changed. Called by act/shoplook.record."""
    from .owned import prices
    var_root = Path(var_root)
    table = prices()
    reads = reads_of(entry, table)
    with _locked(var_root) as body:
        items = body.setdefault("items", {})
        if "backfill" not in body:
            body["items"] = items = _merge_into(_backfill(var_root, table), items)
            body["backfill"] = clock()
        return _merge(items, reads)


def _merge_into(base: dict, items: dict) -> dict:
    _merge(base, [(k, r) for k, b in items.items() if isinstance(b, dict)
                  for r in b.values() if isinstance(r, dict) and "at" in r])
    return base


# ---- reading it back -----------------------------------------------------------
def seen_owned(var_root, table: dict | None = None) -> dict:
    """{key: the newest OWNED read} for every item a window showed owned."""
    return {k: b[OWNED] for k, b in load(var_root, table).items()
            if isinstance(b, dict) and OWNED in b}


def checked_line(label: str, rec: dict) -> str:
    """The log line for a question the evidence answers."""
    return (f"checked: {label} shows {shown(rec)} at the {_shop(rec)}, "
            f"{_when(rec.get('at'))} (frame {rec.get('frame') or 'not kept'}) -- not asking")


def ask_note(var_root, keys, table: dict | None = None) -> str:
    """What was checked of `keys` and when, for a card still asked."""
    from .owned import prices
    table = prices() if table is None else table
    items = load(var_root, table)
    said, unseen = [], []
    for key in keys:
        body = items.get(key) or {}
        rec = body.get(NOT_OWNED)
        label = table[key].label if key in table else str(key)
        if rec:
            said.append(f"the {label} with {shown(rec)} at the {_shop(rec)}, "
                        f"{_when(rec.get('at'))}")
        else:
            unseen.append(label)
    out = []
    if said:
        out.append("Checked: a shop window showed " + "; ".join(said)
                   + " -- not owned then.")
    if unseen:
        out.append("Not checked yet: no shop window the bot has read showed "
                   + ", ".join(f"the {u}" for u in unseen) + ".")
    return " ".join(out)


# ---- the shop errand -----------------------------------------------------------
@dataclass
class Check:
    key: str
    label: str
    shop: str


def open_items(var_root, plan=None, typed: str = "") -> list:
    """The item keys an unanswered gear card is about, in no particular
    order of worth: progression's slot cards (every item offered), owned's
    inferred items and fall cards, and goals' asked "I bought it" cards."""
    from . import owned as owned_mod
    var_root = Path(var_root)
    table = owned_mod.prices()
    out: list = []
    for card in getattr(getattr(plan, "progress", None), "questions", None) or []:
        for opt in getattr(card, "options", None) or []:
            key = owned_mod.item_key(getattr(opt, "label", ""), table)
            if key:
                out.append(key)
    mine = {owned_mod.item_key(n, table) for n in owned_mod._names(typed)}
    state = owned_mod.load_state(var_root)
    for key, body in (state.get("items") or {}).items():
        if isinstance(body, dict) and body.get("state") == owned_mod.INFERRED and key not in mine:
            out.append(key)
    for drop in state.get("drops") or []:
        if isinstance(drop, dict) and drop.get("asked") and not drop.get("answered"):
            out += [k for k in drop.get("could_be") or [] if k not in mine]
    try:
        asked = json.loads((var_root / "goals.json").read_text()).get("asked") or {}
    except (OSError, ValueError, AttributeError):
        asked = {}
    out += [k for k, v in asked.items() if isinstance(v, dict) and not v.get("answered")
            and ":" not in k]
    return [k for k in dict.fromkeys(out) if k in table]


def errand(var_root, wanted, routed, clock=time.time) -> Check | None:
    """The first of `wanted` (item keys) not seen owned whose shop is in
    `routed` (the shops a recorded route reaches) and whose last check is
    over CHECK_EVERY_S old -- or None."""
    from .owned import prices
    table = prices()
    seen = seen_owned(var_root, table)
    done = (_read(Path(var_root)).get("errands") or {})
    for key in wanted:
        item = table.get(key)
        if item is None or key in seen or item.shop not in routed:
            continue
        if key in done and 0 <= clock() - float(done[key] or 0) < CHECK_EVERY_S:
            continue
        return Check(key, item.label, item.shop)
    return None


def errand_started(var_root, check: Check, wanted=(), clock=time.time) -> None:
    """Every wanted item of the check's shop is checked by this one visit
    (the catalogue is read round), so each waits CHECK_EVERY_S from now."""
    from .owned import prices
    table = prices()
    keys = {check.key} | {k for k in wanted if k in table and table[k].shop == check.shop}
    with _locked(Path(var_root)) as body:
        done = body.setdefault("errands", {})
        for key in keys:
            done[key] = clock()
