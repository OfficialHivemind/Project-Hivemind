"""Seeing tokens on the ground, so the bot can go and get them.

THE OWNER ASKED FOR THIS DIRECTLY: token vision. It is
what `gather.chase_tokens` and `gather.token_radius` act on, and what the
live view draws.

A TOKEN IS A COIN. An upright disc with a thick rim of its own colour and a
bold icon on each face, spinning about its vertical axis -- a full disc, an
ellipse or a thin edge depending on the moment. `vision/coins` finds them (a
HOG candidate stage and a small trained network; read it for how, and for
what it measured). This module is the interface the rest of the bot uses:
`detect` returns `Sighting`s, `nearest` picks the one worth walking to, and
`Kinds` names them from data/knowledge/tokens.yaml.

WHAT IT REPLACED, AND WHY IT IS GONE. Until 2026-09-28 this module looked
for "a cube with a white glyph and a dark outline" -- a description of a
Bee Swarm BEE, whose level number is drawn in white on its faces. It was
built from nine tokens on one frame and it found bees: MEASURED on 120
labelled frames (206 coins), 17.6 chaseable boxes a frame, 12% of them on a
coin; var/school/lessons.jsonl had 1,020 pickups in 9,433 chases. The owner
saw it on the live view: boxes "for things that arnt even tokens like it
thinks bees are". The glyph code is in the repository's history.

THE HUD IS MASKED BY POSITION (`world_box`), NOT BY LOOKS: the hotbar and the
reward feed hold icons a detector could take for anything.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import coindet, coins

# The part of a frame that is the game world, not the interface.
world_box = coins.world_box

# HOW SURE TO BE BEFORE WALKING SOMEWHERE, on `Sighting.confidence` -- the coin
# network's log-odds scaled to 0..1 (vision/coins): 0.5 is a probability of
# 0.99. `detect` reports everything down to coins.REPORT_P, because the live
# view shows the near-misses; `nearest` applies this cut, because THAT is the
# function whose answer becomes a walk. The owner's own number is
# `gather.chase_confidence` (act/chase.chase_confidence_from), 0.7 as set --
# p 0.9984. What each cut was measured to be worth is in
# data/models/coins.json `held_out`.
CHASE_CONFIDENCE = 0.5

# THE CHARACTER'S OWN BODY. The glyph detector's worst failure was the
# player's own bee: two white eyes, reaching confidence 0.86, picked as the
# nearest "token" in 14 of 18 frames at the hive (var/tokens_live). What
# separated them was TIME -- the avatar is rigid in screen space while the
# world moves -- and `vision.pinned` is that filter. It stays in the chaser's
# path: anything that never moves while the view does is not on the ground,
# whichever detector reported it.


@dataclass
class Sighting:
    """One token the detector believes it can see."""
    x: int
    y: int
    area: int = 0
    confidence: float = 0.0
    faces: int = 1                    # candidates merged into it (vision/coins.merge)
    why: str = ""
    # The colour a kind is named from (`Kinds.classify`), OpenCV HSV, or None.
    # The coin detector does not measure one: data/knowledge/tokens.yaml's
    # colours are the wiki icons', and MEASURED on 73 labelled honey coins
    # they named 3 honey and 55 "unknown" -- the game's lighting darkens them.
    face_hsv: tuple | None = None
    # How much of the icon is dark strokes, the tiebreak between kinds that
    # share a colour (Kinds.classify). Unmeasured by the coin detector: 0.
    dark: float = 0.0
    # "honey" where the coin detector's honey head is sure (vision/coins
    # `kinds_of`, measured by scripts/train_coins.py --kinds), else "unknown"
    # -- no kind is claimed that nothing measured.
    kind: str = "unknown"
    # The COIN's square, (left, top, width, height), in frame pixels.
    box: tuple[int, int, int, int] | None = None

    @property
    def centre(self) -> tuple[int, int]:
        return self.x, self.y


def detect(frame: np.ndarray, *, limit: int = 40,
           marks: list | None = None) -> list[Sighting]:
    """Tokens visible in this frame, most confident first -- one per coin,
    down to coins.REPORT_P.

    `marks`, when a list, receives every reported sighting's centre: what
    `vision.pinned` learns "never moves" from."""
    if frame is None or getattr(frame, "size", 0) == 0:
        return []
    found = [c for c in coindet.look(frame)          # vision/coins unless switched on
             if c[3] >= float(np.log(coins.REPORT_P / (1.0 - coins.REPORT_P)))]
    merged = coins.merge(found)[:limit]
    named = coins.kinds_of(frame, merged)
    out: list[Sighting] = []
    for (cx, cy, side, logit, stage1), kind in zip(merged, named):
        half = side / 2.0
        joined = sum(1 for c in found
                     if abs(c[0] - cx) < coins.MERGE_SHARE * side
                     and abs(c[1] - cy) < coins.MERGE_SHARE * side)
        p = 1.0 / (1.0 + np.exp(-logit))
        out.append(Sighting(
            x=int(round(cx)), y=int(round(cy)), area=int(side * side),
            confidence=round(coins.confidence_of(logit), 3), faces=max(1, joined),
            kind=kind,
            box=(int(round(cx - half)), int(round(cy - half)),
                 int(round(side)), int(round(side))),
            why=f"coin p {p:.4f} (logit {logit:.1f}), {side:.0f} px, "
                f"candidate score {stage1:.1f}"))
    if marks is not None:
        marks.extend((s.x, s.y) for s in out)
    return out


def nearest(found: list[Sighting], width: int, height: int,
            *, min_confidence: float = CHASE_CONFIDENCE,
            prefer: "Kinds | None" = None) -> Sighting | None:
    """The token most worth walking to: the closest one we are sure about --
    unless a kind worth more is in view, in which case the closest of THOSE.

    The character stands at the centre of the screen, a little below the
    middle, and closer on screen means closer on the ground, so distance is a
    straight screen-distance comparison. Turning a screen position into studs
    is `nav.geometry`'s job, not this module's.

    `prefer` is the kind table (data/knowledge/tokens.yaml). With it, sightings
    are ranked by the table's priority first and distance second, so a token
    that compounds permanently -- the owner's Tabby Love -- beats a closer
    ordinary one. Kinds the table cannot name rank last among themselves by
    distance, which is exactly the old behaviour.

    The confidence cut is applied HERE rather than in `detect` because this is
    the function whose answer turns into the character walking somewhere. See
    CHASE_CONFIDENCE for what the cut was measured to be worth.
    """
    sure = [s for s in found if s.confidence >= min_confidence]
    if not sure:
        return None
    ox, oy = width // 2, int(height * 0.62)
    if prefer is not None:
        for s in sure:
            s.kind = prefer.classify(s)
        # THE PLAYER'S OWN TABLE (Kinds.use_own) here too: Off is never walked
        # to, and its weights order the kinds in place of the priority.
        sure = [s for s in sure if not prefer.is_off(s.kind)]
        if not sure:
            return None
        rank = ((lambda k: -(prefer.own_weight(k) or 0.0)) if prefer.own
                else prefer.priority)
        return min(sure, key=lambda s: (rank(s.kind),
                                        (s.x - ox) ** 2 + (s.y - oy) ** 2))
    return min(sure, key=lambda s: (s.x - ox) ** 2 + (s.y - oy) ** 2)


# ---- naming a token ----------------------------------------------------------
UNKNOWN_PRIORITY = 1_000

# THE PER-HIVE RANKING (tokens.yaml `priority_by_hive`) IS LOOK-ONLY: with
# progression.hive defaulting to "blue" it re-ranks token_link 10 -> 3,
# baby_love 4, focus 5, blue_boost 7, haste / bomb_sync 9, which moves their
# tokenbrain weight and `pick`'s tie-break -- a chase change with no check
# yet (reviewer 2026-10-21). Until this is True `priority` reads `priority`.
PRIORITY_BY_HIVE_LIVE = False

# THE RANK A QUEST'S TOKEN GETS. `brain/tokenbrain.WEIGHT_BY_PRIORITY` maps
# priority 1 to the top weight, which is what "go out of your way for this"
# means in that file's arithmetic. It is the existing top tier rather than a
# new one, so nothing else has to know about quests.
QUEST_PRIORITY = 1
# The token brain's weight for that rank (brain/tokenbrain WEIGHT_BY_PRIORITY[1]);
# the player's own table may go above it, and a quest's kind still goes first.
QUEST_WEIGHT = 100.0


class Kinds:
    """The token-kind table: measured face colours and the order to chase them.

    Read from data/knowledge/tokens.yaml. An entry whose `face_hsv` is null is
    a kind we want and have not measured; it keeps its priority and matches
    nothing, so the gap is visible in the data rather than papered over with a
    guess. `classify` returns "unknown" for any sighting no measured entry is
    close to.
    """

    def __init__(self, kinds: dict | None = None, tolerance: dict | None = None,
                 dark_tolerance: float = 0.25, hive: str = "",
                 unknown_life_s: float | None = None):
        self.kinds = dict(kinds or {})
        # The hive colour (setting progression.hive): a row's
        # `priority_by_hive[hive]` ranks ahead of its plain `priority`.
        self.hive = str(hive or "")
        self.unknown_life_s = unknown_life_s
        # Kinds a quest still wants, which rank first for as long as it does.
        # Set by `want()`; see `priority`.
        self.wanted: set = set()
        # THE PLAYER'S OWN TABLE for this hive (setting gather.token_priority,
        # Settings > Token priority): {kind: {"weight": w, "off": bool}}. Set
        # by `use_own`; never written back to tokens.yaml.
        self.own: dict = {}
        tol = tolerance or {}
        self.tol = (int(tol.get("h", 8)), int(tol.get("s", 70)), int(tol.get("v", 90)))
        self.dark_tol = float(dark_tolerance)

    def priority(self, kind: str) -> int:
        """How much this kind is worth going out of the way for, lower first.

        A KIND A QUEST STILL WANTS RANKS FIRST, whatever the table says.
        `data/knowledge/tokens.yaml` holds a general ranking; a quest asking
        for 155 more of one kind is a specific, temporary reason to prefer
        that one, and `brain/tokenbrain` already turns priority 1 into the
        top weight. MEASURED 2026-09-23 from `var/quests.json`, read off the
        account's own menu: "Honey Bee's Honey Hunt -- Collect 2,000 Honey
        Tokens. 1,845/2,000". The bot was chasing whatever was nearest and
        picked up 18 honey tokens in two and a half hours.

        `wanted` is set by `want()` and is deliberately NOT written to the
        table: the file is the owner's standing ranking, and this is one
        session's errand.
        """
        if kind in self.wanted:
            return QUEST_PRIORITY
        row = self.kinds.get(kind) or {}
        by_hive = row.get("priority_by_hive") if PRIORITY_BY_HIVE_LIVE else None
        if not isinstance(by_hive, dict):
            by_hive = {}
        try:
            return int(by_hive.get(self.hive, row.get("priority", UNKNOWN_PRIORITY)))
        except (TypeError, ValueError):
            return UNKNOWN_PRIORITY

    def life_s(self, kind: str) -> float | None:
        """Seconds a token of this kind lies on the field (tokens.yaml
        `life_s`, wiki-sourced); `unknown_life_s` for an unnamed one; None
        when the table's row does not say.

        A KIND WITH NO ROW is as unnamed to this table as "unknown": the
        typed head (vision/tokentypes, gather.token_types) names
        black_blue_burst, item_treat, yellow_moon... which tokens.yaml has
        no row for, and those coins were "unknown" (4 s) before it named
        them. MEASURED 2026-10-27, runs 1254-1260 (typed head on since 01:08):
        205 of 801 chase decisions ("token brain: chase ...") went to such a
        kind and lost their life -- no urgency, no gate (and red_boost's 67,
        a row with no life_s). On our frames none of them lies in view
        longer than a 4 s kind (tools/analysis/token_lifespans.py,
        docs/pending/lifespans.md). ASSUMED for the item_* kinds: a 4 s
        life is what they had as "unknown", not a measured one."""
        row = self.kinds.get(kind)
        v = (row or {}).get("life_s", self.unknown_life_s if row is None or kind == "unknown"
                            else None)
        try:
            return None if v is None else float(v)
        except (TypeError, ValueError):
            return None

    def weight(self, kind: str) -> float | None:
        """This hive's tokenbrain weight for a kind (tokens.yaml
        `weight_by_hive`), or None: the priority ordering decides. A kind a
        quest wants is None too, so the quest's top rank stands."""
        by_hive = (self.kinds.get(kind) or {}).get("weight_by_hive")
        if kind in self.wanted or not isinstance(by_hive, dict) or self.hive not in by_hive:
            return None
        try:
            return float(by_hive[self.hive])
        except (TypeError, ValueError):
            return None

    def use_own(self, rows) -> None:
        """The player's table (setting gather.token_priority, checked by
        world/settings.token_priority): this hive's rows only."""
        self.own = {r["kind"]: {"weight": float(r["weight"]), "off": bool(r.get("off"))}
                    for r in rows or () if r.get("hive") == self.hive}

    def own_weight(self, kind: str) -> float | None:
        """The player's weight for a kind, or None (no row: the built-in
        one). A KIND A QUEST WANTS STILL GOES FIRST: above the table's top
        weight, which the player may set past the quest's QUEST_WEIGHT."""
        if kind in self.wanted:
            return max(QUEST_WEIGHT, *(r["weight"] + 1 for r in self.own.values())) if self.own else None
        row = self.own.get(kind)
        return None if row is None else row["weight"]

    def is_off(self, kind: str) -> bool:
        """The player turned this kind off -- unless a quest wants it."""
        return bool((self.own.get(kind) or {}).get("off")) and kind not in self.wanted

    def preempt_px(self, kind: str) -> float | None:
        """How near a token of this kind must be to beat any other pick
        (tokens.yaml `preempt_px`); None for most kinds."""
        v = (self.kinds.get(kind) or {}).get("preempt_px")
        try:
            return None if v is None else float(v)
        except (TypeError, ValueError):
            return None

    def want(self, kinds) -> tuple:
        """Rank these kinds first. Returns (recognised, unrecognised).

        A kind this table does not know is reported back rather than
        swallowed: a quest asking for something unrecognised must be visible,
        because a requirement quietly ignored looks exactly like one that
        does not exist.
        """
        asked = [str(k) for k in (kinds or ())]
        known = tuple(k for k in asked if k in self.kinds)
        unknown = tuple(k for k in asked if k not in self.kinds)
        self.wanted = set(known)
        return known, unknown

    def measured(self) -> list[str]:
        return sorted(k for k, r in self.kinds.items() if (r or {}).get("face_hsv"))

    def unmeasured(self) -> list[str]:
        return sorted(k for k, r in self.kinds.items() if not (r or {}).get("face_hsv"))

    def confirmed(self) -> list[str]:
        """Kinds whose colour a LIVE FRAME has agreed with, not just an icon."""
        return sorted(k for k, r in self.kinds.items()
                      if (r or {}).get("confirmed_in_game"))

    def classify(self, sighting: Sighting) -> str:
        """Name this sighting, or "unknown".

        Colour first; where several kinds share a colour -- and five pairs do,
        including Tabby Love and Scratch -- the dark share of the glyph's
        surround breaks the tie. If the dark shares of the candidates are
        themselves closer together than `dark_tolerance`, the tie is NOT
        broken and the nearest-by-colour answer stands: a guess between two
        kinds is still better than "unknown", and both are worth walking to.
        """
        face = sighting.face_hsv
        if face is None:
            # NO FACE COLOUR, NOTHING TO MATCH: a kind the coin detector named
            # itself (its honey head, vision/coins) stands -- run_farm names
            # every sighting through here, and "unknown" would overwrite it.
            return getattr(sighting, "kind", "") or "unknown"
        near = []
        for name, row in self.kinds.items():
            ref = (row or {}).get("face_hsv")
            if not ref or len(ref) != 3:
                continue
            dh = min(abs(face[0] - ref[0]), 180 - abs(face[0] - ref[0]))
            ds, dv = abs(face[1] - ref[1]), abs(face[2] - ref[2])
            if dh > self.tol[0] or ds > self.tol[1] or dv > self.tol[2]:
                continue
            d = (dh / self.tol[0]) ** 2 + (ds / self.tol[1]) ** 2 + (dv / self.tol[2]) ** 2
            near.append((d, name, row))
        if not near:
            return "unknown"
        near.sort(key=lambda r: r[0])
        best = near[0]
        rivals = [r for r in near if abs(r[0] - best[0]) < 1e-9 or r[0] < 1.0]
        if len(rivals) > 1:
            darks = [float((r[2] or {}).get("dark", 0.0)) for r in rivals]
            if max(darks) - min(darks) >= self.dark_tol:
                # The dark share can tell them apart, so use it.
                rivals.sort(key=lambda r: abs(float((r[2] or {}).get("dark", 0.0))
                                              - sighting.dark))
                return rivals[0][1]
        return best[1]

    def describe(self) -> str:
        m, u, c = self.measured(), self.unmeasured(), self.confirmed()
        bits = [f"{len(m)} token kind(s) with a colour from the official icons"]
        bits.append(f"{len(c)} confirmed on a live frame" if c
                    else "NONE confirmed on a live frame yet")
        if u:
            bits.append(f"{len(u)} still with no colour at all: {', '.join(u)}")
        top = sorted(((self.priority(k), k) for k in self.kinds), key=lambda r: r[0])[:2]
        if self.own:        # the player's table decides the order now
            top = sorted((-r["weight"], k) for k, r in self.own.items() if not r["off"])[:2]
        if top:
            bits.append("chasing " + " then ".join(k.replace('_', ' ') for _, k in top)
                        + " first")
        # SAY WHEN A QUEST IS THE REASON. Without this the line reads "chasing
        # tabby love then scratch first" from the table's standing ranking
        # while the brain is in fact walking for honey tokens, and the two
        # statements sit a line apart in the log contradicting each other.
        if self.own:
            off = sorted(k.replace('_', ' ') for k in self.own if self.is_off(k))
            bits.append(f"YOUR token table for the {self.hive} hive ({len(self.own)} kinds"
                        + (f"; off: {', '.join(off)}" if off else "") + ")")
        if self.wanted:
            bits.append("a quest wants "
                        + ", ".join(sorted(k.replace('_', ' ')
                                           for k in self.wanted))
                        + ", so those come first")
        return "; ".join(bits)


def load_kinds(path, hive: str = "") -> Kinds:
    """Read the kind table. A missing or broken file is an EMPTY table."""
    import yaml
    from pathlib import Path
    try:
        body = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return Kinds({}, hive=hive)
    return Kinds(body.get("kinds") or {}, body.get("default_tolerance") or {},
                 float(body.get("dark_tolerance", 0.25)), hive=hive,
                 unknown_life_s=body.get("unknown_life_s"))
