"""What a player does with the items they hold: keep, use, or spend because it pays.

THE OWNER, 2026-10-01: it should play and think like a player -- save some
items for crafting, use others when it has plenty, or when using them (a boost)
is really worth it. So for every
item this answers one question -- use one now, or not -- from what is known,
and says why, the way the planner says why it picked a field:

  1. WHAT A GOAL STILL NEEDS IS KEPT. brain/goals reserves materials for the
     gear the owner wants next; using them would undo the saving.
  2. A FEW TIME SAVERS ARE KEPT FOR WHEN THINGS GO WRONG. A Whirligig takes
     the character home with its bag; on a walk home that has failed it
     replaces a rejoin (75 s and the Wealth Clock's streak), which is worth far
     more than a routine walk's 45 s. RESCUE_KEEP of each stay back.
  3. AN ITEM AT ITS CAP IS USED: the next one the game hands out is wasted.
  4. THE REST IS USED WHEN THE USE PAYS: its measured worth (seconds saved
     times the session's honey rate, a boost's measured gain) above nothing.

Nothing here presses anything. The callers (run_farm's walk home, the gather)
ask, act on the answer, and tell it what they used (`spent`), so the counts
stay right between inventory reads.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

# Kept back for a walk home that has gone wrong (see rule 2).
RESCUE_KEEP = {"whirligig": 2}

# HOW PICKY A USE MUST BE, AS THE STOCK RUNS DOWN: the share of what the use
# risks that it must gain on top, from GAIN_SHARE_FULL at the item's cap to
# GAIN_SHARE_LAST at the last one. A player spends freely from a full stack
# and keeps the last few for the moments that pay most. MEASURED 2026-10-02:
# Micro-Converters went 15 -> 8 in five hours, three of them on bags that
# gained 0.06-0.13M over the bar while one Pine Tree boost paid 2.9M a use.
GAIN_SHARE_FULL = 0.10
GAIN_SHARE_LAST = 0.30


def gain_share(have: int | None, cap: int | None) -> float:
    """The bar for one more use of an item held `have` of `cap`."""
    if not have or not cap or cap <= 0:
        return GAIN_SHARE_LAST
    full = min(1.0, max(0.0, float(have) / float(cap)))
    return GAIN_SHARE_LAST - (GAIN_SHARE_LAST - GAIN_SHARE_FULL) * full


def measured_pay(uses, last: int = 5) -> float | None:
    """The median pay of an item's last `last` MEASURED uses. A use whose pay
    did not read is skipped, not counted against the window: 2026-10-02 05:02
    the one measured Micro-Converter fell out of "the last five uses" behind
    five unread ones, and the pricing switched itself off."""
    ratios = []
    for use in uses or []:
        try:
            ratio = float(use.get("ratio") or 0)
        except (AttributeError, TypeError, ValueError):
            continue
        if ratio > 0:
            ratios.append(ratio)
    ratios = sorted(ratios[-last:])
    if not ratios:
        return None
    mid = len(ratios) // 2
    return ratios[mid] if len(ratios) % 2 else (ratios[mid - 1] + ratios[mid]) / 2.0


@dataclass
class Holding:
    key: str
    label: str
    role: str
    have: int | None                 # None: the inventory read did not count it
    cap: int | None = None
    reserved: int = 0                # what the goals still need of it
    keep: int = 0                    # rescue reserve (RESCUE_KEEP)
    reserved_for: str = ""           # the goal(s) it is kept for, by name

    @property
    def spare(self) -> int | None:
        """How many can go without touching a goal or the rescue reserve."""
        if self.have is None:
            return None
        return max(0, self.have - self.reserved - self.keep)

    @property
    def at_cap(self) -> bool:
        return bool(self.cap and self.have is not None and self.have >= self.cap)

    def describe(self) -> str:
        if self.have is None:
            return f"{self.label}: not counted"
        bits = [f"{self.label} {self.have:,}" + (f"/{self.cap:,}" if self.cap else "")]
        if self.reserved:
            bits.append(f"{self.reserved:,} kept for the "
                        + (self.reserved_for or "goals"))
        if self.keep:
            bits.append(f"{self.keep} kept for a walk home that goes wrong")
        return ", ".join(bits)


@dataclass
class Verdict:
    use: bool
    why: str


@dataclass
class Stash:
    """The items held, as the last inventory read counted them, less what the
    bot has used since (`spent`)."""
    catalogue: dict = field(default_factory=dict)   # key -> {label, role, cap?}
    counts: dict = field(default_factory=dict)      # key -> count
    caps: dict = field(default_factory=dict)        # key -> cap
    reserved: dict = field(default_factory=dict)    # key -> what goals need
    reserved_for: dict = field(default_factory=dict)  # key -> the goals' names
    read_at: float = 0.0
    used: dict = field(default_factory=dict)        # key -> used since the read
    used_path: Path | None = None                   # where `used` is kept
    refused: set = field(default_factory=set)       # keys the game refused since the read

    @classmethod
    def from_files(cls, catalogue_path: Path, inventory_path: Path,
                   reserved: dict | None = None,
                   used_path: Path | None = None,
                   reserved_for: dict | None = None) -> "Stash":
        import yaml
        try:
            catalogue = (yaml.safe_load(Path(catalogue_path).read_text()) or {}).get("items") or {}
        except (OSError, ValueError):
            catalogue = {}
        counts, caps, read_at = {}, {}, 0.0
        try:
            body = json.loads(Path(inventory_path).read_text())
            counts = {k: int((v or {}).get("count")) for k, v in (body.get("items") or {}).items()
                      if (v or {}).get("count") is not None}
            caps = {k: int(v) for k, v in (body.get("caps") or {}).items()}
            read_at = float(body.get("read_at") or 0.0)
            # TWO READINGS THAT DISAGREE GIVE A FLOOR, NOT NOTHING (act/
            # inventory keeps them as `unsure`). MEASURED 2026-10-03 00:12:
            # Glitter read 18 by the transcription and 54 by the closed
            # question (Blue Extract's count, a row away), so it went
            # uncounted and none was ever spare. The smaller reading is
            # all that is used: if either is true, at least that many held.
            for k, seen in (body.get("unsure") or {}).items():
                if k in counts:
                    continue
                nums = []
                for v in seen if isinstance(seen, list) else [seen]:
                    try:
                        nums.append(int(str(v).replace(",", "")))
                    except ValueError:
                        continue
                if nums:
                    counts[k] = min(nums)
        except (OSError, ValueError, TypeError):
            pass
        stash = cls(catalogue=dict(catalogue), counts=counts, caps=caps,
                    reserved=dict(reserved or {}), read_at=read_at,
                    used_path=Path(used_path) if used_path else None,
                    reserved_for=dict(reserved_for or {}))
        # WHAT WAS USED SINCE THAT READ, by an earlier process: a new process
        # would count the read's whole stock again. MEASURED run-566 23:35:
        # "Whirligig 8/100 ... 6 spare" after run-565 had used four of the
        # eight the 22:29 read counted. Kept only against the same read.
        if stash.used_path is not None:
            try:
                body = json.loads(stash.used_path.read_text())
                if float(body.get("read_at") or -1) == read_at:
                    stash.used = {str(k): int(v) for k, v in (body.get("used") or {}).items()}
            except (OSError, ValueError, TypeError, AttributeError):
                pass
        return stash

    def holding(self, key: str) -> Holding:
        entry = self.catalogue.get(key) or {}
        have = self.counts.get(key)
        if have is not None:
            have = max(0, have - int(self.used.get(key, 0)))
        cap = self.caps.get(key) or entry.get("cap")
        return Holding(key=key, label=str(entry.get("label") or key.replace("_", " ")),
                       role=str(entry.get("role") or "unknown"), have=have,
                       cap=int(cap) if cap else None,
                       reserved=int(self.reserved.get(key, 0) or 0),
                       keep=int(RESCUE_KEEP.get(key, 0)),
                       reserved_for=str(self.reserved_for.get(key, "") or ""))

    def spent(self, key: str, n: int = 1) -> None:
        self.used[key] = int(self.used.get(key, 0)) + int(n)
        if self.used_path is not None:
            try:
                from ..files import atomic_write
                atomic_write(self.used_path, json.dumps(
                    {"read_at": self.read_at, "used": self.used}, indent=1))
            except Exception:
                pass

    def refused_press(self, key: str) -> None:
        """The game did not take a press on `key`'s greyed tile: none held, as
        far as this read goes. A new inventory read builds a new Stash, so the
        next count clears it."""
        self.refused.add(key)

    # ---- the field consumables, used from the inventory -------------------
    # (act/inventory.use_item). THE IN-GAME WORDS, read off the inventory
    # 2026-10-02: Glitter "Boosts the field you're standing in, granting
    # +100% pollen for 15 minutes"; Glue "Grants x1.25 Pollen From Bee
    # Gathering and Tools for 10 minutes"; Blue Extract "Grants x1.25 Blue
    # Pollen for 10 minutes"; Enzymes x1.25 Convert Rate for 10 minutes (wiki).
    #
    # GLITTER WHEN NO BOOST RUNS: its +100% for 15 minutes is the same gain
    # whenever it runs, but a full bag caps a trip and the walk home spends
    # boosted time, so boosts spread out gather more than boosts stacked.
    # THE x1.25 ITEMS IN A BOOST: they multiply the rate, so a boosted rate
    # makes each worth more (the research's honey_tactics B7).
    # A MAGIC BEAN ANY TRIP: it plants a sprout at the field's centre whose
    # counter the field's own gathering runs down, and at zero it scatters
    # tokens over the field (wiki Sprout) -- tickets, jelly, treats by day,
    # Moon Charms and Glitter by night (the playbook's `sprouts_from_beans`).
    # One at a time: a sprout untouched five minutes despawns, and the trip
    # that plants it gathers there for longer than that.
    #
    # G6, THE HELD ONES NEVER USED (inventory read 2026-10-12 20:00: 14 Field
    # Dice, 92 Jelly Beans, 9 Red Extract, 2 Tropical Drinks; the wiki's own
    # pages via api.php the same day):
    # RED EXTRACT "Grants x1.25 Red Pollen for 10 minutes" -- in a red field,
    # on a quest step owing more red pollen than the trip gathers (`red_step`,
    # run_farm's), where all of it moves the step; a blue field's few red
    # flowers are not worth one (the Crimson Guard's 100 are kept once it is a
    # next goal, rule 1).
    # TROPICAL DRINK "x1.25 White Pollen, +10% Instant Conversion and +5%
    # Critical Chance for 10 minutes" and JELLY BEANS (11-13 beans thrown on
    # the flowers ahead, each a minute of +25% blue, red or white pollen, or a
    # rarer convert buff; cooldown 30 s; "cap = 100"): multipliers, so in a
    # boost like the x1.25 items -- and Jelly Beans at their cap, the next ones
    # a quest hands out being lost (rule 3). Neither is in a goal's recipe.
    # FIELD DICE "Boosts a random field, granting +100% pollen for 15
    # minutes"; a dice boost replaces the last DICE boost (wiki Field_Dice):
    # rolled at the pad when no boost a trip would gather in runs
    # (`home_boosted`, run_farm's `roll_a_field_dice`), never again while its
    # boost lasts, and the trip follows it where it pays (boostwindow).
    FIELD_USES = {"glitter": 900.0, "glue": 600.0, "blue_extract": 600.0, "enzymes": 600.0,
                  "magic_bean": 900.0, "red_extract": 600.0, "tropical_drink": 600.0,
                  "jelly_beans": 60.0, "field_dice": 900.0}

    def field_use(self, key: str, *, home_boosted: bool, last_used: float | None,
                  now: float, red_step: str = "") -> Verdict:
        """Use one `key` from the inventory at the start of this trip?
        `red_step`: why this trip is a red-pollen quest step, '' when not."""
        h = self.holding(key)
        lasts = self.FIELD_USES.get(key)
        if lasts is None:
            return Verdict(False, f"{h.label} is not a field consumable")
        if last_used is not None and now - last_used < lasts:
            return Verdict(False, f"{h.label} is still working ({(lasts - (now - last_used)) / 60:.0f} min left)")
        if h.have is None:
            return Verdict(False, f"{h.label} not counted yet")
        if h.at_cap:
            return Verdict(True, f"{h.describe()} — at its cap")
        if not h.spare:
            return Verdict(False, f"{h.describe()} — none spare")
        if key == "magic_bean":
            return Verdict(True, f"{h.describe()} — {h.spare} spare: a sprout in the field, "
                                 f"run down by this trip's gathering, its tokens over the field")
        if key == "glitter":
            if home_boosted:
                return Verdict(False, f"{h.describe()} — a boost already runs here; "
                                      f"Glitter waits so the boosts spread out")
            return Verdict(True, f"{h.describe()} — {h.spare} spare, and no boost runs "
                                 f"here: +100% for 15 minutes")
        if key == "field_dice":
            if home_boosted:
                return Verdict(False, f"{h.describe()} — a boost a trip would gather in "
                                      f"already runs; the dice waits for it to end")
            return Verdict(True, f"{h.describe()} — {h.spare} spare: +100% for 15 minutes "
                                 f"on a random field, followed where it pays")
        if key == "red_extract":
            if not red_step:
                return Verdict(False, f"{h.describe()} — kept for a red-pollen quest step "
                                      f"in a red field")
            return Verdict(True, f"{h.describe()} — {h.spare} spare, {red_step}: x1.25 red "
                                 f"pollen for 10 minutes")
        if not home_boosted:
            return Verdict(False, f"{h.describe()} — kept for a boost, where its x1.25 pays most")
        return Verdict(True, f"{h.describe()} — {h.spare} spare, in a boost: x1.25 on a boosted rate")

    # ---- the decisions ------------------------------------------------------
    def routine_use(self, key: str, worth: float | None, *, on_hotbar: bool) -> Verdict:
        """Use one `key` for an ordinary job (a walk home it replaces), worth
        `worth` honey (None when not measured yet)?"""
        h = self.holding(key)
        if not on_hotbar:
            return Verdict(False, f"no {h.label} on the hotbar")
        if h.have is None:
            # NOT COUNTED, but on the hotbar, so at least one is there; a
            # reserve cannot be honoured without a count, so only a rescue
            # may use it (`rescue_use`).
            return Verdict(False, f"{h.label} not counted yet — not used until "
                                  f"the inventory read counts them")
        if h.at_cap:
            return Verdict(True, f"{h.describe()} — at its cap, so the next one "
                                 f"the game hands out would be wasted")
        if not h.spare:
            return Verdict(False, f"{h.describe()} — none spare")
        if worth is not None and worth <= 0:
            return Verdict(False, f"{h.describe()} — it would not pay here")
        return Verdict(True, f"{h.describe()} — {h.spare} spare"
                             + (f", worth about {worth:,.0f} honey this time"
                                if worth else ""))

    def rescue_use(self, key: str, *, on_hotbar: bool, greyed: bool = False) -> Verdict:
        """Use one `key` to rescue a walk home that has failed (rule 2)?
        `greyed`: its hotbar tile is greyed (vision/hotbar_items GREYED TILES)."""
        h = self.holding(key)
        if not on_hotbar:
            return Verdict(False, f"no {h.label} on the hotbar")
        if greyed:
            # A GREYED TILE IS DRAWN AT 0 AND NOT REDRAWN when more come
            # (MEASURED 2026-10-13: Whirligig "x2" greyed at 13:31:57, 2
            # counted at 13:13 and 13:43), so the tile cannot say whether any
            # are left; only the inventory's count can.
            if h.have is not None and h.have <= 0:
                return Verdict(False, f"{h.label} greyed on the hotbar and none counted")
            if h.have is None and key in self.refused:
                # AND NOT AGAIN AFTER THE GAME REFUSED ONE. MEASURED run-1048
                # 07:23-07:38: three rescues pressed the uncounted greyed
                # Whirligig and the game took none of the three ("the greyed
                # tile stayed greyed"); 9 of 11 such presses 2026-10-18/21.
                return Verdict(False, f"{h.label} greyed on the hotbar, not counted, "
                                      f"and the game refused the last press on it")
            if h.have is None:
                # NOT COUNTED YET IS NO REASON TO REJOIN: a press on a greyed
                # tile is told taken or refused (act/hotbar), a refused one
                # costs a second, and the rejoin costs the Wealth Clock streak.
                # MEASURED 2026-10-13 19:30:37: "greyed ... not counted yet --
                # the rejoin goes ahead", the first trip after a restart.
                return Verdict(True, f"{h.label} greyed on the hotbar and not counted "
                                     f"yet — pressed anyway, as a refused press only "
                                     f"costs a second")
            return Verdict(True, f"{h.describe()} — greyed on the hotbar (drawn when "
                                 f"there were none, not redrawn), but counted; a "
                                 f"rescue is what the reserve is for")
        if h.have is not None and h.have <= 0:
            return Verdict(False, f"{h.label}: none left")
        return Verdict(True, f"{h.describe()} — a rescue is what the reserve is for")

    def describe(self, keys=None) -> str:
        keys = list(keys or self.catalogue)
        parts = [self.holding(k).describe() for k in keys if self.counts.get(k) is not None]
        age = (time.time() - self.read_at) / 60.0 if self.read_at else None
        return ("; ".join(parts) or "nothing counted yet") + (
            f" (counted {age:.0f} min ago)" if age is not None else "")
