"""Reading the hive: the bee menu's list of types and counts, opened and shut.

2026-10-01: the owner asked for the bot to judge which bees in the hive are
good and to follow the blue-hive guide. The only count the bot had was a typed
one (account.yaml, e.g. a 26-bee hive), and the hive is what every bee gate and
every one of the guide's stages is judged on.

IT IS act/inventory'S ERRAND ON THE MENU BESIDE IT, under the same rules
(act/inventory's note says why each exists): one click on the measured HUD
button -- the third, the smiley (vision/questmenu.BUTTONS), never the Robux
shop three to its right -- pixels before words, the wheel only over the list,
out by the button it came in by, a menu left open said to be. Nothing on the
list is clicked: a bee's face opens its card, and a drag from the list is how
jelly is used, so this module never clicks or drags inside it.

WHAT IS BELIEVED. Each page is transcribed while open; with the menu shut,
every type a page names is believed at a count two readings agree on -- two
overlapping pages' transcriptions, or one and a closed question on the same
picture -- the inventory's rule for its extras. The header's "You Have N
Bees" is read from the top page and asked once more; the read is VERIFIED
when the agreed counts add up to it, and only a verified read replaces the
owner's screenshot as the hive's count (`count_for_gates`).
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..telemetry import readhealth
from ..vision import beemenu as bm
from . import inventory

KEEP_DIR = Path(__file__).resolve().parents[3] / "var" / "beemenu"
MENU = inventory.Menu("bee menu", bm.BUTTON_INDEX, bm.looks_like_bee_list,
                      bm.TRANSCRIBE, bm.bee_rows)


@dataclass
class BeeRead(inventory.InventoryRead):
    total: int | None = None          # "You Have N Bees", two readings agreeing
    total_reads: list = field(default_factory=list)
    types_seen: int | None = None     # "You've Discovered N Types of Bees"
    # the per-type counts read before the sum check threw them out: kept for
    # the record, never believed (`count_bees`)
    rejected: dict = field(default_factory=dict)
    # the pages, held for `count_bees` to read after the menu is shut, off the
    # pad (`read_bees(defer=True)`)
    held: list = field(default_factory=list)
    counted_yet: bool = True
    # the types whose row shows the dark star: a gifted one in the hive
    # (vision/beemenu gifted_star)
    gifted: set = field(default_factory=set)

    @property
    def counted(self) -> int:
        return sum(int(v) for v in self.counts.values())

    @property
    def verified(self) -> bool:
        """The agreed counts add up to the header's total."""
        return bool(self.ok and self.total and self.counted == self.total)

    def describe(self) -> str:
        if not self.ok:
            return f"did not read the bee menu: {self.reason}"
        names = bm.types()
        rows = ", ".join(f"{names.get(k, {}).get('label', k)} x{v}"
                         for k, v in sorted(self.counts.items(),
                                            key=lambda kv: (-kv[1], kv[0])))
        head = (f"{self.total} bees by the menu's own header"
                + (f", {self.types_seen} types discovered" if self.types_seen else "")
                if self.total else "the header's bee count not agreed")
        check = ("; the rows add up to it" if self.verified else
                 (f"; the rows' counts read add up to "
                  f"{sum(self.rejected.values()):,}, not {self.total}, so none "
                  f"is believed" if self.rejected and self.total else
                  "; no row's count was read"))
        return (f"read {self.pages} page(s) of the bee menu in "
                f"{self.seconds:.0f}s: {head}{check}"
                + (f" — {rows}" if rows else "")
                + (f"; unsure of {', '.join(sorted(self.unsure))}"
                   if self.unsure else "")
                + (" — MENU STILL OPEN" if self.menu_open else ""))


def read_bees(vin, frames, ask, *, sleep=time.sleep, on_note=None,
              keep_dir: Path | None = None, clock=time.time,
              defer: bool = False) -> BeeRead:
    """Open the bee menu, picture every page, close it, and count -- or,
    with `defer`, hold the pages (`held`) for `count_bees` to read later: a
    model call per row's name and count is a minute of standing on the pad."""
    def hold(pages, _ask, _note, result):
        result.held = list(pages)
        result.counted_yet = False
    return inventory.read_list(vin, frames, ask, menu=MENU,
                               count=hold if defer else count_bees,
                               result=BeeRead(), sleep=sleep, on_note=on_note,
                               keep_dir=keep_dir or KEEP_DIR, clock=clock)


def count_held(result: BeeRead, ask, note) -> BeeRead:
    """`count_bees` on the pages `read_bees(defer=True)` held."""
    if not result.counted_yet:
        count_bees(result.held, ask, note, result)
        result.counted_yet = True
        result.held = []
    return result


# THE TRY'S WORDS for pages pictured and not counted (run_farm read_the_bees)
NOT_COUNTED = "the pages were pictured; the rows were not counted before this process ended"


def left_uncounted(tried: dict, bees: dict, now: float | None = None,
                   max_age: float = 3600.0) -> BeeRead | None:
    """The pages the last try pictured and its process never counted, read
    back from their folder (`kept`) as `read_bees(defer=True)` holds them, or
    None. Only while no read has been written since, and only pages at most
    `max_age` old (run_farm's BEES_RETRY_SECONDS): counting hours-old pages
    would then block a fresh read for BEES_SKIP_SECONDS. MEASURED runs
    1067-1167: 8 of 22 pictured reads ended so, each an hour's wait."""
    import cv2
    kept = Path(str(tried.get("kept") or ""))
    now = time.time() if now is None else now
    if (now - float(tried.get("at") or 0.0) > max_age
            or tried.get("ok", True) or tried.get("reason") != NOT_COUNTED
            or not str(tried.get("kept") or "") or not kept.is_dir()
            or float(bees.get("read_at") or 0.0) >= float(tried.get("at") or 0.0)):
        return None
    pages = []
    for png in sorted(kept.glob("page-*.png")):
        image = cv2.imread(str(png))
        if image is None:
            return None
        text = png.with_suffix(".txt")
        pages.append((image, text.read_text(encoding="utf-8") if text.exists() else ""))
    if not pages:
        return None
    return BeeRead(ok=True, pages=len(pages), held=pages, counted_yet=False,
                   kept=str(kept), complete=bool(tried.get("complete", True)))


def _ask(ask, image, question, note):
    try:
        return ask(image, question)
    except Exception as exc:
        note(f"bee menu: the model did not answer ({exc})")
        return None


def count_bees(pages, ask, note, result: BeeRead, ocr=None) -> None:
    """The counts of `pages` [(image, transcription)] into `result`.

    THE TOTAL is the header's, read by tesseract (vision/beemenu.ocr_header),
    believed when two pages' reads agree or one and a closed question do.
    EACH ROW is asked about on its own crop -- its name, and the count drawn on
    it, "none" for a type not in the hive (vision/beemenu ROW_*: the model
    invented counts when it transcribed a whole page, and did not when asked
    of one row). A count stands on two agreeing readings: the same row on two
    overlapping pages, or a second phrasing on the one crop. And the counts
    stand only TOGETHER, when they add up to the header: two of the model's
    readings can agree on one invention, and a sum that matches the game's
    own total cannot be invented by accident. A read that does not add up
    keeps them in `rejected`, and nothing is judged from it."""
    header_of = ocr or bm.ocr_header
    reads: dict = {}          # type -> [count or None, ...]
    crops: dict = {}          # type -> the first crop it was read on
    for i, (image, _text) in enumerate(pages):
        try:
            total, kinds = header_of(image)
        except Exception:
            total, kinds = None, None
        readhealth.note("bee menu header", total is not None)
        if total is not None:
            result.total_reads.append((i, total))
        if kinds is not None and result.types_seen is None:
            result.types_seen = kinds
        if not hasattr(image, "shape"):
            continue
        for _top, row in bm.row_crops(image):
            key = bm.match_name(_ask(ask, row, bm.ROW_NAME_QUESTION, note))
            if key is None:
                continue
            count = inventory.inv.answer_count(_ask(ask, row, bm.ROW_COUNT_QUESTION, note))
            reads.setdefault(key, []).append(count)
            if bm.gifted_star(row):
                result.gifted.add(key)
            crops.setdefault(key, row)
    for key, got in sorted(reads.items()):
        if len(got) == 1:
            got = got + [inventory.inv.answer_count(
                _ask(ask, crops[key], bm.ROW_COUNT_AGAIN, note))]
        if len(set(got)) == 1:
            if got[0]:
                result.counts[key] = int(got[0])
        else:
            result.unsure[key] = [str(v) for v in got]
    result.seen = sorted(reads)
    # THE HEADER: the page it was read on, asked once more.
    if result.total_reads:
        i, total = result.total_reads[0]
        others = [t for _i, t in result.total_reads[1:]]
        if total in others:
            result.total = total
        else:
            answer = _ask(ask, pages[i][0], bm.TOTAL_QUESTION, note)
            if inventory.inv.answer_count(answer) == total:
                result.total = total
    # THE SUM CHECK: the rows' counts stand only together, and only on it.
    if result.counts and (result.total is None
                          or sum(result.counts.values()) != result.total):
        result.rejected = dict(result.counts)
        for key, value in result.counts.items():
            result.unsure.setdefault(key, [str(value)])
        result.counts = {}


def write(path: Path, result: BeeRead, clock=time.time, taken_at=None) -> None:
    """var/bees.json: the agreed counts, the header, whether they add up.
    `taken_at`: when the pages were pictured -- the rows are counted later,
    off the pad -- which is what the counts are true of."""
    from ..files import atomic_write
    if not result.ok:
        return
    taken = float(taken_at) if taken_at is not None else clock()
    body = {
        "read_at": taken, "total": result.total,
        "types_discovered": result.types_seen,
        "verified": result.verified, "counted": result.counted,
        "bees": dict(sorted(result.counts.items())),
        "rejected": dict(sorted(result.rejected.items())),
        "unsure": result.unsure, "pages": result.pages,
        "gifted": sorted(result.gifted),
        "complete": result.complete, "kept": result.kept}
    # A CHANGE MARKED AFTER THE PAGES WERE PICTURED STANDS (act/inventory
    # mark_dirty). MEASURED 2026-10-06: the menu pictured at 03:07, slot 38's
    # egg hatched at 03:08, the rows counted at 03:11 -- and this write wiped
    # the hatch's mark, so 37 bees stood as fresh and slot 39 waited.
    old = load(path)
    if old.get("dirty") and float(old.get("dirty_at") or 0.0) > taken:
        body["dirty"], body["dirty_at"] = old["dirty"], old["dirty_at"]
    atomic_write(Path(path), json.dumps(body, indent=1))


def load(path: Path) -> dict:
    try:
        body = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return {}
    return body if isinstance(body, dict) else {}


# THE HIVE'S PLAYER MOVESPEED: a gifted Hasty Bee's hive bonus is +15% (wiki
# Hasty_Bee: the only gifted bonus to player movespeed). MEASURED 2026-10-09:
# the one rolled on the test account on 10-07 overshot every timed walk 15%
# (errand walks 27/33 -> 7/45) while move.walkspeed said 28. The owner asked
# for the bot to check for the gifted Hasty rather than assume it -- so the
# walkspeed follows the bee menu's star.
GIFTED_HASTY_MOVESPEED = 1.15


def movespeed_bonus(path: Path) -> tuple[float, str]:
    """(the factor on move.walkspeed, why) from var/bees.json. A read without
    stars goes by whether a Hasty Bee is counted; no read at all keeps the
    bonus -- the hive as last seen (2026-10-09) has the gifted Hasty."""
    body = load(path)
    if "gifted" in body:
        on = "hasty" in (body.get("gifted") or [])
        why = ("a gifted Hasty Bee in the hive (its dark star in the bee menu)" if on
               else "no gifted Hasty Bee in the bee menu")
    else:
        counts = body.get("bees") or body.get("rejected") or {}
        on = bool(counts.get("hasty")) if counts else True
        why = ("a Hasty Bee counted, taken as the gifted one (no star read yet)" if on and counts
               else "no Hasty Bee counted" if counts
               else "no bee menu read yet: the gifted Hasty of 2026-10-09 assumed")
    return (GIFTED_HASTY_MOVESPEED if on else 1.0), why


def count_for_gates(path: Path) -> int | None:
    """The hive's bee count from the menu's own header, read by two agreeing
    readings (`count_bees`), None otherwise: what the bee gates are held
    against. The header is the game's own number; the rows need not add up
    for it to stand."""
    body = load(path)
    try:
        return int(body.get("total")) if body.get("total") else None
    except (TypeError, ValueError):
        return None
