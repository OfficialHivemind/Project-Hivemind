"""R7: which Memory Match game the errand plays, when, and only for honey.

act/memorymatch GAMES/due/affordable/record/names_game -- the pure half of
run_farm's `play_memory_match`; the board itself is test_memorymatch.py's.
"""
from __future__ import annotations

from hivemind.act import memorymatch as mm
from hivemind.brain import calendar

NOW = 1_800_000_000.0
H = 3600.0


def test_only_the_cheap_game_until_a_board_is_proven():
    assert mm.due({}, NOW) == ["normal"]
    s = mm.record({}, "normal", "unread", NOW, pressed=True)
    assert mm.due(s, NOW + 30 * H) == ["normal"]           # a failed board proves nothing
    s = mm.record({}, "normal", "played", NOW, pressed=True)
    assert mm.due(s, NOW) == ["mega", "extreme"]            # Natro's order after that


def test_a_game_waits_its_calendar_cooldown():
    s = mm.record({}, "normal", "played", NOW, pressed=True)
    assert "normal" not in mm.due(s, NOW + 1)
    assert "normal" not in mm.due(s, NOW + 2 * H - 1)
    assert "normal" in mm.due(s, NOW + 2 * H + 1)
    s = mm.record({}, "extreme", "played", NOW, pressed=True)
    assert "extreme" not in mm.due(s, NOW + 7 * H)
    assert "extreme" in mm.due(s, NOW + calendar.MEMORY_MATCH_COOLDOWN_S["extreme"] + 1)


def test_misses_rest_doubled_and_a_play_clears():
    s = mm.record({}, "mega", "walk", NOW, pressed=False)
    assert "mega" not in s["last_play"]                 # nothing spent
    assert s["next_at"]["mega"] == NOW + 4 * H
    s = mm.record(s, "mega", "prompt", NOW, pressed=False)
    assert s["next_at"]["mega"] == NOW + 8 * H
    s = mm.record(s, "normal", "walk", NOW, pressed=False)   # another game's miss
    s = mm.record(s, "mega", "walk", NOW, pressed=False)
    assert s["next_at"]["mega"] == NOW + 16 * H
    s = mm.record(s, "mega", "walk", NOW, pressed=False)
    assert s["next_at"]["mega"] == NOW + mm.MISS_REST_MAX_S
    s = mm.record(s, "mega", "played", NOW, pressed=True)
    assert "mega" not in s["next_at"] and s["last_play"]["mega"] == NOW


def test_e_pressed_on_an_unread_board_still_starts_the_cooldown():
    s = mm.record({}, "normal", "unread", NOW, pressed=True)
    assert s["last_play"]["normal"] == NOW
    assert "normal" not in mm.due(s, NOW + 2 * H - 1)


def test_honey_price_and_unread_honey():
    assert mm.affordable("normal", 25_000) and not mm.affordable("normal", 24_999)
    assert not mm.affordable("extreme", 24_999_999) and mm.affordable("extreme", 451_931_222)
    assert not mm.affordable("normal", None)


def test_presses_only_on_its_own_exact_honey_prompt():
    assert mm.names_game("normal", "Spend 25,000 Honey to Play Memory Match")
    assert mm.names_game("normal", "Spend 25.000 Honey to Play Memory Match")   # as drawn
    assert mm.names_game("extreme", "Spend 25,000,000 Honey to Play Extreme Memory Match")
    assert not mm.names_game("mega", "Spend 25,000 Honey to Play Memory Match")
    assert not mm.names_game("normal", "Spend 25,000,000 Honey to Play Extreme Memory Match")
    assert not mm.names_game("normal", "Spend 1 Ticket to Play Memory Match")
    assert not mm.names_game("normal", "")
    assert not mm.names_game("normal", None)
    assert all("Honey" in prompt and "Ticket" not in prompt for _m, _p, prompt in mm.GAMES.values())


def test_state_round_trip(tmp_path):
    path = tmp_path / "var" / "memorymatch.json"
    assert mm.load(path) == {}
    s = mm.record({}, "normal", "played", NOW, pressed=True)
    mm.save(path, s)
    assert mm.load(path) == s


def test_measured_16_tile_card_is_not_called_20():
    # 2026-10-12 18:03: the real 16-tile card's gold bar is 384 px wide
    from hivemind.vision import memorymatch as vm
    assert 384 <= vm.BAR_WIDE_FROM < 384 + 80
    assert vm.centres(16)[0] == (840, 420) and vm.centres(16)[-1] == (1080, 660)


def test_a_machine_price_is_prompt_shaped_but_the_hud_is_not():
    from hivemind.act.bearvisit import prompt_shaped
    assert prompt_shaped("Spend 25,000,000 Honey to Play Extreme Memory Match")
    assert prompt_shaped("Spend 25,000 Honey to Play Memory Match (1:59:58)")
    assert not prompt_shaped("Honey 20,750,759 (+13/sec) Pollen 1,958/1,113,750 (+69/sec)")


def test_board_size_is_read_off_the_tiles():
    # face-down tiles at a layout's centres decide 16 vs 20, whatever the bar
    import numpy as np
    from hivemind.vision import memorymatch as vm
    for tiles in (16, 20):
        frame = np.full((1080, 1920, 3), (40, 180, 230), np.uint8)   # card gold
        for x, y in vm.centres(tiles):
            frame[y - 35:y + 35, x - 35:x + 35] = vm.HIDDEN_BGR
        assert vm._tiles(frame, bar_width=384) == tiles
        assert vm._tiles(frame, bar_width=470) == tiles


def test_the_walk_to_the_machine_is_booked_for_its_route():
    # research 2026-10-21: 18 "the walk missed it" were never booked, so the
    # route was never quarantined; record() books it now (a raise or a stop not)
    import re
    from pathlib import Path
    src = (Path(mm.__file__).resolve().parents[3] / "scripts" / "run_farm.py").read_text()
    body = src[src.index("        def play_memory_match(cycle"):]
    body = body[:body.index("\n        def ", 10)]
    assert re.search(r'errand_verdict\(walked\["route"\], result != "walk"\)', body)
    assert 'result != "raised" and not stop.is_set()' in body
    assert body.index('walked["route"] = route') < body.index("routes_errand_walk(route)")


def test_a_cheap_game_that_pays_comes_out_of_the_goals_honey():
    # research 2026-10-21: 3B held, 8B kept for the Diamond Mask; the 500k
    # Mega (paid ~1.53M a game) was skipped 17 times, the 25M Extreme pays ~10M
    kind, _why = mm.pick(["mega"], 3_000_000_000, 8_000_000_000)
    assert kind == "mega"
    kind, why = mm.pick(["extreme"], 3_000_000_000, 8_000_000_000)
    assert kind is None and "pays" in why
    # dear beside a small goal: still kept
    kind, why = mm.pick(["mega"], 1_000_000, 5_000_000)
    assert kind is None and "kept for the next goal" in why
