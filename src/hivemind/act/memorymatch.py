"""Playing Memory Match: which tiles to turn, and turning them.

THE OWNER, 2026-09-28: "make it able to ... do memory match".

THE STRATEGY IS NATRO'S (natro_macro.ahk nm_SolveMemoryMatch): before a turn's
first click, a pair already seen is claimed; otherwise an unseen tile is
turned, and the second click is the seen tile holding the same prize if there
is one, else another unseen tile. Its timings too: the pointer rests on the
tile before the click, moves off the board after it (a hovered tile is not
what a picture of it shows), and the prize is read once the tile has stopped
being plain brown.

WHAT IT NEVER DOES: click anywhere but a tile's centre on a board whose title
reads "Memory Match" (vision/memorymatch), click a tile it has already paired,
or go on when a click did not turn a tile over -- that is a board it does not
understand, and it stops. Pressing E at the machine is the errand's (run_farm
`play_memory_match`); WHICH GAME, WHEN, AND AT WHAT PRICE is decided here, at
the bottom (GAMES, due, record), so it can be tested without the game.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..brain import calendar
from ..brain.buyer import SIDE_FROM_KEPT_SHARE
from ..vision import memorymatch as vm

# Natro's pauses: 400 ms on the tile before the click, about 500 ms after,
# up to 3 s for the prize to show, 300 ms more for it to settle.
REST_BEFORE_CLICK_S = 0.4
AFTER_CLICK_S = 0.5
SHOW_WAIT_S = 3.0
SHOW_POLL_S = 0.05
SETTLE_S = 0.3
# A FACE IS REMEMBERED ONLY ONCE IT HOLDS STILL: two looks SETTLE_S apart
# alike at SETTLED_MIN. MEASURED 2026-10-14 on the 31 boards kept with every
# tile face up (var/memorymatch/*, the last turn frame): a prize and its twin
# at rest read 0.987-1.000 (vision/memorymatch.likeness), two different prizes
# at most 0.80 (a Ticket beside "x5" Tickets) -- yet on 20261014-145107 the two
# "x3" Royal Jellies at tiles 2 and 4, both seen by turn 2, were never paired
# (a perfect memory claims them on turn 3 and finds 3 pairs, the game found
# 2). Natro's one look 300 ms after the brown goes caught them mid-flip.
SETTLED_MIN = 0.97
# after a turn, time for a pair that did not match to turn back over
TURN_BACK_S = 1.2
# no game has more turns than this (Natro plays at most 10)
MOST_TURNS = 12


class Solver:
    """Which tile to turn next, from the prizes seen so far."""

    def __init__(self, tiles: int, same=vm.same_prize):
        self.tiles = tiles
        self.same = same
        self.seen: dict[int, object] = {}     # tile -> its prize, not yet paired
        self.paired: set[int] = set()

    def unseen(self, besides: int | None = None) -> list[int]:
        return [t for t in range(self.tiles)
                if t not in self.seen and t not in self.paired and t != besides]

    def known_pair(self) -> tuple[int, int] | None:
        tiles = sorted(self.seen)
        for i, a in enumerate(tiles):
            for b in tiles[i + 1:]:
                if self.same(self.seen[a], self.seen[b]):
                    return a, b
        return None

    def first(self) -> int | None:
        pair = self.known_pair()
        if pair is not None:
            return pair[0]
        rest = self.unseen()
        return rest[0] if rest else None

    def saw(self, tile: int, prize) -> None:
        if tile not in self.paired and prize is not None:
            self.seen[tile] = prize

    def second(self, first: int) -> int | None:
        """The tile to turn after `first`, whose prize has been seen."""
        prize = self.seen.get(first)
        for tile in sorted(self.seen):
            if tile != first and prize is not None and self.same(prize, self.seen[tile]):
                return tile
        rest = self.unseen(besides=first)
        if rest:
            return rest[0]
        others = [t for t in sorted(self.seen) if t != first]
        return others[0] if others else None

    def settle(self, a: int, b: int) -> bool:
        """After a turn: a pair is claimed and never clicked again."""
        pa, pb = self.seen.get(a), self.seen.get(b)
        if pa is not None and pb is not None and self.same(pa, pb):
            self.paired |= {a, b}
            self.seen.pop(a, None)
            self.seen.pop(b, None)
            return True
        return False

    @property
    def done(self) -> bool:
        return len(self.paired) >= self.tiles


@dataclass
class Game:
    turns: int = 0
    pairs: int = 0
    stopped: str = ""                       # why it ended
    notes: list = field(default_factory=list)
    chances: int | None = None              # as read before the first turn
    faces: list = field(default_factory=list)   # (turn, tile, square, settled)


def play(capture, click, board: vm.Board, *, move_away=None, sleep=time.sleep,
         clock=time.monotonic, read_board=vm.read_board, face=vm.face,
         is_hidden=vm.is_hidden, same=vm.same_prize, most_turns: int = MOST_TURNS,
         stop=lambda: False, read_chances=vm.read_chances,
         likeness=vm.likeness) -> Game:
    """Play the board that is up. `capture()` is a frame, `click(x, y)` a
    click, `move_away()` puts the pointer off the board. It ends when the board
    closes, when the chances read 0 (the game shows every tile then, and a
    click on that is a click for nothing), or after `most_turns`."""
    solver = Solver(board.tiles, same=same)
    game = Game()

    def turn_over(tile: int):
        x, y = board.centres[tile]
        sleep(REST_BEFORE_CLICK_S)
        click(x, y)
        if move_away is not None:
            move_away()
        sleep(AFTER_CLICK_S)
        deadline = clock() + SHOW_WAIT_S
        best = None
        looks: list = []                   # (when, square) since it showed
        while True:
            frame = capture()
            square = face(frame, (x, y)) if frame is not None else None
            if square is not None and not is_hidden(square):
                now = clock()
                # SETTLED: alike to a look at least SETTLE_S older (the looks
                # are fast now, and two of a pop-up 50 ms apart can agree)
                older = [sq for t, sq in looks if now - t >= SETTLE_S]
                if older and likeness(older[-1], square) >= SETTLED_MIN:
                    game.faces.append((game.turns + 1, tile, square, True))
                    return square
                looks.append((now, square))
                if best is None or vm.content(square) > vm.content(best):
                    best = square
            elif best is not None:
                # SHOWN, THEN HIDDEN AGAIN before two looks agreed: the second
                # tile of a turn. MEASURED 2026-10-15 05:23 (var/memorymatch/
                # 20261015-052145): every second pick's face was the prize at
                # ~85% of its size (still popping up), so a Royal Jelly met
                # its twin at 0.70 and 4 known pairs were never claimed. The
                # fullest look it had is kept, not the first.
                game.faces.append((game.turns + 1, tile, best, False))
                return best
            if clock() >= deadline:
                if best is not None:
                    # turned over and never held still: remembered all the
                    # same, and kept so it can be measured
                    game.faces.append((game.turns + 1, tile, best, False))
                return best
            # fast looks once it shows: the second tile is up for a moment only
            sleep(SHOW_POLL_S)

    while game.turns < most_turns and not stop():
        frame = capture()
        if read_board(frame) is None:
            game.stopped = "the board closed"
            return game
        left = read_chances(frame, board) if frame is not None else None
        if game.turns == 0:
            game.chances = left
        if left == 0:
            game.stopped = "no chances left"
            return game
        first = solver.first()
        if first is None:
            game.stopped = "every tile is paired"
            return game
        prize = turn_over(first)
        if prize is None:
            game.stopped = f"tile {first + 1} did not turn over; stopped, pressing nothing else"
            return game
        solver.saw(first, prize)
        second = solver.second(first)
        if second is None:
            game.stopped = "no second tile to turn"
            return game
        other = turn_over(second)
        if other is None:
            game.stopped = f"tile {second + 1} did not turn over; stopped, pressing nothing else"
            return game
        solver.saw(second, other)
        game.turns += 1
        if solver.settle(first, second):
            game.pairs += 1
            game.notes.append(f"turn {game.turns}: tiles {first + 1} and {second + 1} match")
        else:
            game.notes.append(f"turn {game.turns}: tiles {first + 1} and {second + 1} differ")
        if solver.done:
            game.stopped = "every tile is paired"
            return game
        sleep(TURN_BACK_S)
    game.stopped = game.stopped or ("stop requested" if stop() else f"{most_turns} turns played")
    return game


# ---------------------------------------------- which game, when, what price --
# THE THREE MACHINES THE BOT HAS A ROUTE TO, in Natro's order (nm_Collect,
# natro_macro.ahk:11709-11711: Normal, Mega, Extreme), each with the panel E is
# pressed on -- MEASURED word for word on this account's own frames, the
# price in honey and nothing else:
#   normal  "Spend 25,000 Honey to Play Memory Match"
#           (var/places/memory_match-072340.jpg, 2026-10-12 07:23, and 11 more)
#   mega    "Spend 500,000 Honey to Play Mega Memory Match"
#           (var/places/mega_memory_match-140833.jpg, 2026-10-09 14:08, and 3 more)
#   extreme "Spend 25,000,000 Honey to Play Extreme Memory Match"
#           (var/places/extreme_memory_match-123903.jpg, 2026-10-12 12:39, and 4 more)
# The same three prices as the wiki's Memory_Match page (run_farm's
# PLACE_ROUTES comment). NO TICKETS: a panel that does not read exactly these
# words -- one asking for tickets, or a cooldown -- is never pressed, so the
# tickets saved for Star Treats and Diamond Eggs cannot be spent here.
# LEFT OFF: the Winter and Night games (calendar MEMORY_MATCH_COOLDOWN_S has
# them) -- data/world/natro_paths.yaml holds no route to either, and no frame
# of their panels exists, so their price is unread.
GAMES = {
    "normal": ("memory_match", 25_000, "Spend 25,000 Honey to Play Memory Match"),
    "mega": ("mega_memory_match", 500_000, "Spend 500,000 Honey to Play Mega Memory Match"),
    "extreme": ("extreme_memory_match", 25_000_000,
                "Spend 25,000,000 Honey to Play Extreme Memory Match"),
}
# A WALK OR A PANEL THAT MISSES waits the game's own cooldown, Natro's rule
# (natro_macro.ahk:12819-12821: two tries, then Last<Game>MemoryMatch stamped
# as if played), doubled for each further miss in a row.
# ponytail: Natro has no doubling or cap; a day is the cap so a route that
# lands 4 times in 15 (the Mega's frames) is still tried daily.
MISS_REST_MAX_S = 86400.0


# WHAT A GAME PAYS, MEASURED 2026-10-14: the reward feed (vision/feed) on the
# last frame of every game played 2026-10-12..14 (var/memorymatch/*), priced
# the way brain/value prices an errand -- a ticket 100,000 honey (value.PRICES),
# a Royal Jelly 1,000,000 (buyer.JELLY_PRICE_PLANNED) -- and every prize with
# no price (Treats, Honeysuckles, Moon Charms, Magic Beans, seeds, fruit,
# Micro-Converters, Field Dice, Oil) counted as NOTHING, the conservative side:
#   normal  17 games: 13 Royal Jelly, 11 tickets  ~ 830,000 a game for 25,000
#   mega    10 games: 15 Royal Jelly,  3 tickets  ~1,530,000 a game for 500,000
#   extreme  5 games: 50 Royal Jelly              ~10,000,000 a game for 25,000,000
# so the Extreme is NOT played on what it is known to pay: 25 Royal Jelly
# bought outright cost what one game does, and it pays them one game in two.
# A game with no row here is unknown, and an unknown is not played.
# ponytail: a fixed table; the haul of each game is now kept in
# var/memorymatch.json ("haul" on its try) to redo it from.
PAID = {                       # games seen, Royal Jelly, tickets
    "normal": (17, 13, 11),
    "mega": (10, 15, 3),
    "extreme": (5, 50, 0),
}
JELLY_HONEY, TICKET_HONEY = 1_000_000, 100_000


def pays(kind: str) -> float | None:
    """Honey a game of `kind` is measured to pay (priced prizes only)."""
    if kind not in PAID:
        return None
    games, jelly, tickets = PAID[kind]
    return (jelly * JELLY_HONEY + tickets * TICKET_HONEY) / games


def pick(kinds, honey, kept) -> tuple:
    """(the game to play, "") or (None, why none): the first of `kinds` (due,
    in Natro's order) that pays its price (`pays`), whose price the honey read
    covers -- and, for any game but the 25,000-honey one, covers ABOVE `kept`,
    the honey brain/buyer keeps for the next goal (None, not known: not
    played)."""
    why = []
    for kind in kinds:
        price = GAMES[kind][1]
        paid = pays(kind)
        if paid is None or paid < price:
            why.append(f"the {kind} pays ~{paid or 0:,.0f} of its {price:,} (unpriced prizes count 0)")
        elif honey is None or float(honey) < price:
            why.append(f"the {kind}'s {price:,} is more than the honey read "
                       f"({'unread' if honey is None else f'{float(honey):,.0f}'})")
        elif kind != "normal" and kept is None:
            why.append(f"the {kind}: the honey kept for the next goal is not known")
        # A GAME THAT PAYS ITS PRICE AND IS CHEAP BESIDE THE GOAL comes out of it,
        # as a cheap side purchase does (brain/buyer SIDE_FROM_KEPT_SHARE).
        # Research 2026-10-21: the 500k Mega (paid ~1.53M a game over 10) was
        # skipped 17 times that day for the 8.34B kept for the Diamond Mask,
        # 0.006% of it.
        elif (kind != "normal" and float(honey) - float(kept) < price
              and price >= SIDE_FROM_KEPT_SHARE * float(kept)):
            why.append(f"the {kind}'s {price:,} would eat into the {float(kept):,.0f} "
                       f"kept for the next goal")
        else:
            return kind, ""
    return None, "; ".join(why)


def refusal(words) -> str:
    """Why a panel is never pressed whatever game it names: a Robux price
    (the owner's rule, never anything that costs Robux) or a ticket one
    (tickets are kept for Star Treats and Diamond Eggs); "" otherwise."""
    w = str(words or "").lower()
    if "robux" in w or "r$" in w:
        return "it asks for Robux"
    if "ticket" in w:
        return "it asks for tickets"
    return ""


def cooling(kind: str, words) -> float | None:
    """Seconds left on `kind`'s own panel when it shows its timer -- "Spend
    500,000 Honey to Play Mega Memory Match (3:59:58)", MEASURED on
    var/memorymatch/20261014-145107 -- else None."""
    from .errands import countdown_seconds
    text = str(words or "")
    head = text.split("(")[0]
    if not letters(head) or letters(head) != letters(GAMES[kind][2]):
        return None
    return countdown_seconds(text)


def haul(lines) -> list:
    """The reward feed's lines that came from the game ("+3 Tickets (from
    Memory Match)"; tesseract drops the "f" and bends "Memory" -- MEASURED on
    the games' last frames, so "atch)" or "emor" is what is looked for)."""
    return [str(t).strip(" '|.\"") for t in lines or ()
            if "atch)" in str(t) or "emor" in str(t).lower()]


def letters(text) -> str:
    """Only the letters and digits, lower case: "25.000" and "25,000" (both
    seen from the reader) are the same price."""
    return "".join(ch for ch in str(text or "").lower() if ch.isalnum())


def names_game(kind: str, words) -> bool:
    """Does the panel read exactly `kind`'s measured prompt?"""
    return bool(words) and letters(words) == letters(GAMES[kind][2])


def due(state: dict, now: float) -> list:
    """The games to play now, Natro's order: no miss resting it
    (`state["next_at"]`), and brain/calendar says its cooldown is over -- or
    it has never been played, which the calendar makes no claim about (an
    unrecorded key, calendar.opportunities) and Natro treats as due (its
    Last<Game>MemoryMatch starts at 0, natro_macro.ahk:12802)."""
    last = state.get("last_play") or {}
    rest = state.get("next_at") or {}
    ready = {o.name for o in calendar.opportunities(now, {"memory_match_last_play": last})}
    # THE BOARD IS UNPROVEN HERE (vision/memorymatch is Natro's positions,
    # never checked on a frame of ours): until one game has been played
    # through, only the 25,000-honey game is risked, not 500,000 or 25M.
    proven = any(t.get("result") == "played" for t in state.get("tries") or [])
    return [kind for kind in GAMES
            if (proven or kind == "normal")
            and now >= float(rest.get(kind) or 0.0)
            and (kind not in last or f"memory_match_{kind}" in ready)]


def affordable(kind: str, honey) -> bool:
    """Enough honey read on the HUD for `kind`'s price (None: unread, no)."""
    return honey is not None and float(honey) >= GAMES[kind][1]


def record(state: dict, kind: str, result: str, now: float, pressed: bool,
           rest_s: float | None = None, won=None) -> dict:
    """The state after a try. `pressed`: E was pressed, so the game's own
    cooldown runs from now whatever followed. "played" clears any rest;
    anything else ("walk", "prompt", "unread", "raised") rests the game its
    cooldown, doubled for each miss in a row before it -- or `rest_s`, the
    timer its own panel showed ("cooling"). `won`: the haul's feed lines."""
    out = dict(state)
    entry = {"at": now, "kind": kind, "result": result, "pressed": pressed}
    if won:
        entry["haul"] = list(won)
    out["tries"] = (list(state.get("tries") or []) + [entry])[-30:]
    last = dict(state.get("last_play") or {})
    rest = dict(state.get("next_at") or {})
    if pressed:
        last[kind] = now
    if result == "played":
        rest.pop(kind, None)
    elif rest_s is not None:
        rest[kind] = now + float(rest_s)
    else:
        missed = 0
        for t in reversed(out["tries"]):
            if t.get("kind") != kind:
                continue
            if t.get("result") == "played":
                break
            missed += 1
        cooldown = calendar.MEMORY_MATCH_COOLDOWN_S[kind]
        rest[kind] = now + min(cooldown * 2 ** (missed - 1), MISS_REST_MAX_S)
    out["last_play"], out["next_at"] = last, rest
    return out


def load(path: Path) -> dict:
    try:
        body = json.loads(Path(path).read_text())
        return body if isinstance(body, dict) else {}
    except (OSError, ValueError):
        return {}


def save(path: Path, state: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1))
    os.replace(tmp, path)
