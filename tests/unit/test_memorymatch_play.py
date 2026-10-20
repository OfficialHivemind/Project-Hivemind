"""Memory Match played end to end, offline: the chances and the faces read on
this account's own saved games (var/memorymatch, 2026-10-12..14), a board drawn
here whose tiles flip in over a few looks, and the money rules -- never Robux,
never tickets, the Extreme not played on what it pays, the Mega only above the
honey kept for the next goal."""
from __future__ import annotations

import random
from pathlib import Path

import cv2
import numpy as np
import pytest

from hivemind.act import memorymatch as mm
from hivemind.vision import memorymatch as vm


def _fake_time():
    """A clock that a sleep moves on, so act/memorymatch's settle gap
    (SETTLE_S between two alike looks) passes without waiting for real."""
    now = [0.0]

    def sleep(s):
        now[0] += s
    return {"sleep": sleep, "clock": lambda: now[0]}

GAMES = Path.home() / "Hivemind/var/memorymatch"
RUN_FARM = (Path(__file__).resolve().parents[2] / "scripts" / "run_farm.py").read_text()


def _frame(game: str, name: str):
    path = GAMES / game / name
    if not path.exists():
        pytest.skip(f"{path} is not on this machine")
    return cv2.imread(str(path))


# ---- measured on the saved games ------------------------------------------------------
def test_the_chances_read_on_real_boards():
    sixteen = vm.Board(16, vm.centres(16))
    assert vm.read_chances(_frame("20261014-145107", "0057.2-board0.jpg"), sixteen) == 6
    assert vm.read_chances(_frame("20261014-145107", "0072.9-turn05.jpg"), sixteen) == 2
    assert vm.read_chances(_frame("20261014-145107", "0080.7-turn07.jpg"), sixteen) == 0
    twenty = vm.Board(20, vm.centres(20))
    assert vm.read_chances(_frame("20261014-050739", "0033.8-board0.jpg"), twenty) == 5   # 'D'
    assert vm.read_chances(_frame("20261014-050739", "0037.8-turn02.jpg"), twenty) == 4   # 'A'
    # nothing gold there: no number at all
    assert vm.read_chances(np.zeros((1080, 1920, 3), np.uint8), sixteen) is None


def test_faces_at_rest_pair_and_differ_on_a_real_board():
    # 145107's last frame, every tile up: the four "x3" Royal Jellies (tiles
    # 2, 4, 14, 16) are one prize, the yellow "x25" (3, 11) another
    frame = _frame("20261014-145107", "0080.7-turn07.jpg")
    faces = [vm.face(frame, c) for c in vm.centres(16)]
    for a, b in ((2, 4), (2, 14), (14, 16), (3, 11), (7, 12)):
        assert vm.same_prize(faces[a - 1], faces[b - 1]), (a, b)
    for a, b in ((2, 3), (4, 5), (3, 9), (10, 12)):
        assert not vm.same_prize(faces[a - 1], faces[b - 1]), (a, b)
    assert vm.likeness(faces[1], faces[1]) >= mm.SETTLED_MIN


def test_one_ticket_is_not_five_tickets():
    # 092437's last frame (measured 0.80): the count is part of the prize
    frame = _frame("20261013-092437", "0073.2-turn07.jpg")
    faces = [vm.face(frame, c) for c in vm.centres(16)]
    assert vm.same_prize(faces[0], faces[15]) and vm.same_prize(faces[3], faces[9])
    assert not vm.same_prize(faces[0], faces[3]) and not vm.same_prize(faces[0], faces[9])


# ---- a drawn board whose tiles flip in -----------------------------------------------------
def _prizes(n, seed):
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(n):
        p = np.zeros((vm.FACE, vm.FACE, 3), np.uint8)
        for _ in range(6):
            colour = tuple(int(c) for c in rng.integers(40, 255, 3))
            centre = tuple(int(c) for c in rng.integers(8, vm.FACE - 8, 2))
            cv2.circle(p, centre, int(rng.integers(5, 14)), colour, -1)
        out.append(p)
    return out


class FlippingBoard:
    """16 tiles, 8 pairs, `chances` turns; a tile clicked shows its prize
    squashed for its first 0-3 looks (the flip, a different length each
    click, as lag makes it), then at rest. The chances are drawn nowhere --
    `chances_left` is what the reader is told."""

    def __init__(self, seed, chances=6, tiles=16):
        self.board = vm.Board(tiles, vm.centres(tiles))
        self.prizes = _prizes(tiles // 2, seed)
        self.layout = [i // 2 for i in range(tiles)]
        random.Random(seed).shuffle(self.layout)
        self.up, self.paired, self.turn = set(), set(), []
        self.looks, self.flip = {}, {}
        self.rng = random.Random(seed + 100)
        self.chances, self.turns, self.clicks = chances, 0, []

    def click(self, x, y):
        tile = next(i for i, c in enumerate(self.board.centres) if c == (x, y))
        assert tile not in self.paired and self.turns < self.chances
        self.clicks.append(tile)
        if len(self.turn) == 2:
            a, b = self.turn
            if self.layout[a] != self.layout[b]:
                self.up -= {a, b}
            self.turn = []
        self.up.add(tile)
        self.looks[tile] = 0
        self.flip[tile] = self.rng.choice((0, 1, 2, 3))
        self.turn.append(tile)
        if len(self.turn) == 2:
            self.turns += 1
            a, b = self.turn
            if self.layout[a] == self.layout[b]:
                self.paired |= {a, b}

    def capture(self):
        frame = np.full((1080, 1920, 3), 90, np.uint8)
        h = vm.FACE // 2
        for i, (cx, cy) in enumerate(self.board.centres):
            cv2.rectangle(frame, (cx - 35, cy - 35), (cx + 35, cy + 35), vm.HIDDEN_BGR, -1)
            if i in self.up:
                prize = self.prizes[self.layout[i]]
                n, flip = self.looks.get(i, 9), self.flip.get(i, 0)
                self.looks[i] = n + 1
                if n < flip:                # mid-flip: a narrow strip of it
                    w = max(4, vm.FACE * (n + 1) // (flip + 2))
                    prize = cv2.resize(prize, (w, vm.FACE))
                    frame[cy - h:cy + h, cx - w // 2:cx - w // 2 + w] = prize
                else:
                    frame[cy - h:cy + h, cx - h:cx + h] = prize
        return frame

    def read_board(self, frame):
        return self.board if len(self.paired) < 16 else None

    def chances_left(self, frame, board):
        return self.chances - self.turns


def _play(fb, **kw):
    return mm.play(fb.capture, fb.click, fb.board, **_fake_time(),
                   read_board=fb.read_board, read_chances=fb.chances_left, **kw)


@pytest.mark.parametrize("seed", range(6))
def test_mid_flip_faces_are_not_remembered_and_known_pairs_are_claimed(seed):
    fb = FlippingBoard(seed, chances=30)
    game = _play(fb, most_turns=30)
    assert fb.paired == set(range(16)), game.stopped
    assert game.turns <= 15, f"{game.turns} turns for 8 pairs"
    assert all(settled for *_x, settled in game.faces)


@pytest.mark.parametrize("seed", range(6))
def test_never_clicks_once_the_chances_are_spent(seed):
    fb = FlippingBoard(seed, chances=6)
    game = _play(fb)
    assert game.chances == 6 and game.turns == 6
    assert game.stopped in ("no chances left", "every tile is paired")
    assert len(fb.clicks) == 12, "two clicks a chance and not one more"


def test_a_pair_seen_is_claimed_before_anything_new():
    # the layout of 145107: Royal Jelly at tiles 2 and 4 (column by column)
    fb = FlippingBoard(0, chances=6)
    fb.layout = [0, 1, 2, 1, 0, 3, 4, 3, 5, 6, 2, 4, 5, 1, 6, 1]
    game = _play(fb)
    assert fb.clicks[4:6] == [1, 3], "turn 3 claims the Royal Jelly seen on turns 1 and 2"
    assert game.pairs == 3                        # the live game found 2


def test_a_tile_that_does_not_turn_over_stops_everything():
    fb = FlippingBoard(1)
    game = mm.play(fb.capture, lambda x, y: fb.clicks.append((x, y)), fb.board,
                   **_fake_time(), read_board=fb.read_board,
                   read_chances=fb.chances_left)
    assert "did not turn over" in game.stopped and len(fb.clicks) == 1


# ---- the money rules ----------------------------------------------------------------------
def test_robux_and_tickets_are_refused_whatever_the_game():
    assert mm.refusal("Spend 25 Robux to Play Memory Match") == "it asks for Robux"
    assert mm.refusal("Play Mega Memory Match for R$ 49") == "it asks for Robux"
    assert mm.refusal("Spend 1 Ticket to Play Night Memory Match") == "it asks for tickets"
    assert mm.refusal("Spend 25,000 Honey to Play Memory Match") == ""
    assert not mm.names_game("normal", "Spend 25 Robux to Play Memory Match")
    body = RUN_FARM[RUN_FARM.index("        def play_memory_match("):]
    body = body[:body.index("\n        def ", 10)]
    # the refusal is decided before, and apart from, the E
    assert body.index("mm_mod.refusal(words)") < body.index('inp.tap("e")')
    assert 'record("refused")' in body


def test_its_own_timer_rests_it_exactly_that_long():
    words = "Spend 500.000 Honey to Play Mega Memory Match (3:59:58)"   # as drawn
    assert mm.cooling("mega", words) == 3 * 3600 + 59 * 60 + 58
    assert mm.cooling("normal", words) is None
    assert mm.cooling("mega", "Spend 500,000 Honey to Play Mega Memory Match") is None
    s = mm.record({}, "mega", "cooling", 1000.0, pressed=False, rest_s=600.0)
    assert s["next_at"]["mega"] == 1600.0 and "mega" not in s["last_play"]


def test_which_game_by_what_it_pays_and_the_honey_kept():
    honey, kept = 2_900_000_000, 10_000_000
    assert mm.pick(["normal", "mega", "extreme"], honey, kept) == ("normal", "")
    assert mm.pick(["mega", "extreme"], honey, kept) == ("mega", "")
    kind, why = mm.pick(["extreme"], honey, kept)
    assert kind is None and "pays ~10,000,000 of its 25,000,000" in why
    assert mm.pick(["mega"], honey, None)[0] is None             # reserve unknown
    assert mm.pick(["mega"], 10_400_000, 10_000_000)[0] is None  # would eat into it
    assert mm.pick(["normal"], 25_000, None) == ("normal", "")   # the cheap one: price only
    assert mm.pick(["normal"], None, None)[0] is None


def test_the_haul_is_read_off_the_feed():
    lines = ["t13 Tickets rom Memory Match)", "*25,000 Honey rom Honey Gifte)",
             "I 42 Micro-Converters (from Merfiofz Match) |"]
    assert mm.haul(lines) == ["t13 Tickets rom Memory Match)",
                              "I 42 Micro-Converters (from Merfiofz Match)"]
    s = mm.record({}, "normal", "played", 1.0, pressed=True, won=mm.haul(lines))
    assert s["tries"][-1]["haul"][0].startswith("t13 Tickets")


def test_the_switch_and_the_survey_say_so():
    from hivemind.world import settings as schema
    assert schema.wired("economy.memory_match")
    assert schema.takes_effect("economy.memory_match") == "at its next use"
    due = RUN_FARM[RUN_FARM.index("        def memorymatch_due("):]
    due = due[:due.index("\n        def ", 10)]
    assert 'settings.bool("economy.memory_match")' in due and "mm_mod.pick(" in due
    assert "played by the Memory Match errand" in RUN_FARM


def test_a_face_still_popping_up_holds_less_prize_than_the_full_one():
    """var/memorymatch/20261015-052145: the second pick's Royal Jelly at ~85%
    of its size (likeness 0.70 to its twin, so the pair was never claimed);
    play() keeps the fullest look of a tile that hides again."""
    import cv2
    from pathlib import Path
    from hivemind.vision import memorymatch as vm
    here = Path(__file__).resolve().parents[1] / "fixtures" / "memorymatch"
    full, popping, flash = (cv2.imread(str(here / n))
                            for n in ("rj_full.jpg", "rj_popping.jpg", "flash.jpg"))
    assert vm.content(full) > vm.content(popping) > 0.1 > vm.content(flash)
