"""T17 Pattern Studio data: the strict check, share codes, the library, and
that the bot runs a saved pattern through the route runner's own ops."""
from __future__ import annotations

import base64
import json
import random
import zlib

import pytest

from hivemind.world import userpatterns as up

GOOD = {"name": "Wide zigzag", "author": "a community member", "version": 2, "size": 1.5,
        "steps": [{"move": "w", "studs": 20}, {"turn": "left"},
                  {"repeat": 3, "steps": [{"move": "aw", "studs": 6}, {"move": "s", "studs": 20}]},
                  {"turn": "right"}]}


def _code(body: bytes, crc: int | None = None) -> str:
    payload = base64.urlsafe_b64encode(zlib.compress(body)).decode().rstrip("=")
    return f"HMP1:{payload}.{(zlib.crc32(body) if crc is None else crc):08x}"


def test_a_good_pattern_is_canonical():
    c = up.validate(GOOD)
    assert c.ok and not c.errors and not c.notes
    assert c.pattern["steps"][2]["steps"][0] == {"move": "wa", "studs": 6.0}   # aw -> wa
    assert c.pattern["schema"] == "hmp"
    assert up.studs(c.pattern) == pytest.approx((20 + 3 * 26) * 1.5)


def test_compiles_to_the_route_runners_own_ops_only():
    ops = up.compile_steps(up.validate(GOOD).pattern)
    assert {o["op"] for o in ops} == {"walk", "camera"}
    assert ops[0] == {"op": "walk", "keys": "w", "studs": 30.0}
    assert ops[1] == {"op": "camera", "direction": "left"}
    assert len(ops) == 1 + 1 + 6 + 1


@pytest.mark.parametrize("bad, said", [
    ({**GOOD, "steps": [{"move": "q", "studs": 5}]}, "move"),
    ({**GOOD, "steps": [{"move": "ws", "studs": 5}]}, "move"),          # opposite keys
    ({**GOOD, "steps": [{"move": "space", "studs": 5}]}, "move"),
    ({**GOOD, "steps": [{"jump": True}]}, "one of move"),
    ({**GOOD, "steps": [{"move": "w", "studs": 5, "op": "raw"}]}, "unknown keys"),
    ({**GOOD, "steps": [{"move": "w", "studs": "5"}]}, "not a number"),
    ({**GOOD, "steps": [{"move": "w", "studs": float("nan")}]}, "not a number"),
    ({**GOOD, "steps": [{"move": "w", "studs": True}]}, "not a number"),
    ({**GOOD, "steps": [{"turn": "up"}, {"move": "w", "studs": 5}]}, "turn"),
    ({**GOOD, "steps": [{"turn": "left"}, {"move": "w", "studs": 5}]}, "must cancel"),
    ({**GOOD, "steps": [{"repeat": 2, "steps": [{"repeat": 2, "steps": [{"move": "w", "studs": 1}]}]}]}, "inside a repeat"),
    ({**GOOD, "steps": [{"repeat": 2.5, "steps": [{"move": "w", "studs": 1}]}]}, "whole number"),
    ({**GOOD, "steps": []}, "at least one step"),
    ({**GOOD, "steps": [{"turn": "left"}, {"turn": "right"}]}, "at least one move"),
    ({**GOOD, "exec": "rm -rf /"}, "unknown keys"),
    ({**GOOD, "schema": "ahk"}, "schema"),
    ({**GOOD, "name": "!!!"}, "name"),
    ({**GOOD, "steps": [{"move": "w", "studs": 1}] * 65}, "the most is 64"),
    ({**GOOD, "steps": [{"repeat": 20, "steps": [{"move": "w", "studs": 100}, {"move": "s", "studs": 100}]}]}, "length"),
    ("not a dict", "JSON object"),
])
def test_the_validator_refuses(bad, said):
    c = up.validate(bad)
    assert not c.ok and c.pattern is None
    assert any(said in e for e in c.errors), c.errors


def test_numbers_out_of_range_are_clamped_and_said():
    c = up.validate({**GOOD, "size": 99, "version": -4,
                     "steps": [{"move": "w", "studs": 500}, {"move": "s", "studs": 0.01},
                               {"repeat": 999, "steps": [{"move": "a", "studs": 1}]}]})
    assert c.ok
    assert c.pattern["size"] == up.MAX_SIZE and c.pattern["version"] == 1
    assert c.pattern["steps"][0]["studs"] == up.MAX_STUDS_STEP
    assert c.pattern["steps"][1]["studs"] == up.MIN_STUDS_STEP
    assert c.pattern["steps"][2]["repeat"] == up.MAX_REPEAT
    assert len(c.notes) == 4


def test_names_and_authors_are_plain_short_text():
    c = up.validate({**GOOD, "name": "a\x1b[31mb\n" + "x" * 99, "author": "‮evil" + "y" * 99})
    assert c.ok
    assert all(ch.isprintable() for ch in c.pattern["name"] + c.pattern["author"])
    assert len(c.pattern["name"]) <= up.MAX_NAME and len(c.pattern["author"]) <= up.MAX_AUTHOR


def _junk(rng, depth=0):
    pick = rng.randrange(9 if depth < 3 else 6)
    return [lambda: rng.choice([None, True, 0, -1, 1e308, float("inf"), 3.5]),
            lambda: rng.choice(["w", "wa", "left", "repeat", "", "x" * 50, "\x00"]),
            lambda: rng.randint(-10**9, 10**9),
            lambda: rng.random() * 300 - 50,
            lambda: rng.choice(["move", "turn", "steps"]),
            lambda: {"move": rng.choice("wasdq"), "studs": rng.random() * 200},
            lambda: [_junk(rng, depth + 1) for _ in range(rng.randrange(5))],
            lambda: {rng.choice(["move", "turn", "repeat", "steps", "studs", "name", "size", "x"]):
                     _junk(rng, depth + 1) for _ in range(rng.randrange(4))},
            lambda: {"repeat": rng.randrange(-3, 30), "steps": [_junk(rng, depth + 1)]}][pick]()


def test_fuzz_the_validator_never_raises_and_whatever_passes_is_within_limits():
    rng = random.Random(1717)
    passed = 0
    for _ in range(4000):
        raw = {k: _junk(rng) for k in rng.sample(sorted(up.TOP_KEYS), rng.randrange(7))}
        if rng.random() < 0.6:
            raw["steps"] = [rng.choice([_junk(rng), {"move": rng.choice(up.MOVE_KEYS), "studs": rng.random() * 150},
                                        {"turn": "left"}, {"turn": "right"}]) for _ in range(rng.randrange(1, 12))]
            raw["name"] = "fuzz"
        c = up.validate(raw)
        if not c.ok:
            assert c.errors
            continue
        passed += 1
        legs = up.legs(c.pattern)
        assert len(legs) <= up.MAX_LEGS and up.studs(c.pattern) <= up.MAX_TOTAL_STUDS
        for op in up.compile_steps(c.pattern):
            assert set(op) in ({"op", "keys", "studs"}, {"op", "direction"})
            assert op["op"] in ("walk", "camera")
            if op["op"] == "walk":
                assert op["keys"] in up.MOVE_KEYS
                assert 0 < op["studs"] <= up.MAX_STUDS_STEP * up.MAX_SIZE
            else:
                assert op["direction"] in ("left", "right")
        assert up.validate(c.pattern).pattern == c.pattern      # a fixed point
        assert up.decode(up.encode(c.pattern)).pattern == c.pattern
    assert passed > 20


def test_share_code_round_trip_and_is_stable():
    code = up.encode(GOOD)
    assert code.startswith("HMP1:") and len(code) < 400
    assert up.decode(code).pattern == up.validate(GOOD).pattern
    assert up.encode(up.decode(code).pattern) == code
    # pasted from Discord: wrapped, indented, with spaces around
    assert up.decode("  " + code[:40] + "\n  " + code[40:] + " \n").ok


def test_encode_refuses_an_invalid_pattern():
    with pytest.raises(ValueError):
        up.encode({**GOOD, "steps": []})


@pytest.mark.parametrize("code", [
    "", "HMP1:", "HMP1:.", "hello", "HMP2:abc.00000000", "HMP1:abc", "HMP1:@@@@.00000000",
    "HMP1:" + "A" * 9000 + ".00000000", None, 12, b"HMP1:", ["HMP1:"],
    _code(b'{"name":"x"}', crc=0),                                     # checksum wrong
    _code(b"\xff\xfe not json"),
    "HMP1:" + base64.urlsafe_b64encode(b"not zlib at all").decode().rstrip("=") + ".00000000",
])
def test_malicious_or_broken_codes_raise_only_invalid_code(code):
    with pytest.raises(up.InvalidCode):
        up.decode(code)


@pytest.mark.parametrize("depth", [50, 5000, 16000])
def test_deep_nesting_is_refused_cleanly(depth):
    try:
        c = up.decode(_code(b"[" * depth + b"]" * depth))
    except up.InvalidCode:
        return
    assert not c.ok


def test_a_zip_bomb_is_refused():
    body = b'{"name":"' + b"a" * 5_000_000 + b'"}'
    with pytest.raises(up.InvalidCode, match="too big"):
        up.decode(_code(body))


def test_a_well_formed_code_of_a_bad_pattern_says_why():
    body = json.dumps({"name": "x", "steps": [{"op": "raw", "text": "os.system"}]}).encode()
    c = up.decode(_code(body))
    assert not c.ok and c.errors


def test_fuzz_mutated_codes_never_raise_anything_else():
    rng = random.Random(7)
    code = up.encode(GOOD)
    alphabet = "ABCabc019-_.:=+/ \n\x00é"
    for _ in range(3000):
        s = list(code)
        for _ in range(rng.randrange(1, 6)):
            op = rng.randrange(3)
            i = rng.randrange(len(s) + 1)
            if op == 0 and s:
                del s[min(i, len(s) - 1)]
            elif op == 1:
                s.insert(i, rng.choice(alphabet))
            elif s:
                s[min(i, len(s) - 1)] = rng.choice(alphabet)
        try:
            up.decode("".join(s))
        except up.InvalidCode:
            pass


def test_the_library_saves_lists_deletes_and_skips_bad_files(tmp_path):
    path = up.save(GOOD, tmp_path)
    assert path.name == "wide_zigzag.json"
    (tmp_path / "evil.json").write_text(json.dumps({"name": "evil", "steps": [{"op": "raw"}]}))
    (tmp_path / "broken.json").write_text("{nope")
    mine = up.load_user(tmp_path)
    assert list(mine) == ["wide_zigzag"]
    assert up.routines(tmp_path) == {"user_pattern_wide_zigzag": {
        "steps": up.compile_steps(mine["wide_zigzag"]), "studs": up.studs(mine["wide_zigzag"])}}
    up.delete("Wide zigzag", tmp_path)
    assert up.load_user(tmp_path) == {}
    assert up.load_user(tmp_path / "missing") == {}


def test_the_library_lives_under_the_config_dir():
    from hivemind.datapaths import config_dir
    assert up.folder() == config_dir() / "patterns"


def test_builtins_are_listed_and_all_pass_the_check():
    names = [p["name"] for p in up.builtins()]
    assert {"Snake, wide", "Snake, short", "Square, small"} <= set(names)
    assert any(n.startswith("Classic ") for n in names)
    for p in up.builtins():
        assert p["route"]
        assert up.validate({k: v for k, v in p.items() if k != "route"}).ok, p["name"]


def test_route_names_and_the_macro_setting():
    from hivemind.world.settings import macro_fields, macro_pattern_label
    assert up.route_name(GOOD) == "user_pattern_wide_zigzag"
    assert up.is_route_name("user_pattern_wide_zigzag")
    assert not up.is_route_name("user_pattern_../../x") and not up.is_route_name("farm_mobs")
    ok, problems = macro_fields([{"field": "Clover", "pattern": "user_pattern_wide_zigzag"},
                                 {"field": "Clover", "pattern": "user_pattern_a b"}])
    assert [e["pattern"] for e in ok] == ["user_pattern_wide_zigzag"]
    assert len(problems) == 1 and "unknown pattern" in problems[0]
    assert macro_pattern_label("user_pattern_wide_zigzag") == "Yours: wide zigzag"
    assert macro_pattern_label("farm_square").startswith("Square")


def test_run_farm_loads_saved_patterns_into_the_router():
    """The bot side, by source: run_farm puts every saved pattern into the
    router as a Routine (so the macro's `in router.routines` finds it)."""
    import pathlib
    import hivemind
    root = pathlib.Path(hivemind.__file__).resolve().parents[2]
    text = (root / "scripts" / "run_farm.py").read_text()
    assert "userpatterns.routines()" in text
    assert 'if macro["pattern"] in router.routines:' in text


# ---- enter / exit legs (own gather patterns, act/patterns) -----------------
ENDED = {**GOOD, "enter": [{"move": "s", "studs": 10}, {"move": "a", "studs": 10}],
         "exit": [{"move": "d", "studs": 10}, {"move": "w", "studs": 10}]}


def test_enter_and_exit_are_checked_and_compiled_apart(tmp_path):
    c = up.validate(ENDED)
    assert c.ok, c.errors
    assert up.compile_steps(c.pattern, "enter") == [
        {"op": "walk", "keys": "s", "studs": 15.0}, {"op": "walk", "keys": "a", "studs": 15.0}]
    assert up.compile_steps(c.pattern) == up.compile_steps(up.validate(GOOD).pattern)
    assert up.compile_steps(up.validate(GOOD).pattern, "exit") == []
    up.save(ENDED, tmp_path)
    assert set(up.routines(tmp_path)) == {"user_pattern_wide_zigzag",
                                          "user_pattern_wide_zigzag_enter",
                                          "user_pattern_wide_zigzag_exit"}
    assert up.decode(up.encode(ENDED)).pattern == c.pattern


def test_a_pattern_without_ends_keeps_its_old_code():
    assert "enter" not in up.validate(GOOD).pattern
    assert up.encode({**GOOD, "enter": [], "exit": []}) == up.encode(GOOD)


@pytest.mark.parametrize("ends, said", [
    ({"enter": [{"move": "s", "studs": 10}]}, "walk back"),
    ({"enter": [{"turn": "left"}], "exit": [{"turn": "right"}]}, "moves only"),
    ({"enter": [{"repeat": 2, "steps": [{"move": "s", "studs": 1}]}]}, "inside a repeat"),
    ({"exit": "w"}, "a list of moves"),
])
def test_bad_ends_are_refused(ends, said):
    c = up.validate({**GOOD, **ends})
    assert not c.ok and any(said in e for e in c.errors), c.errors


def test_drift_counts_like_the_route_runner():
    from hivemind.act.routes import pass_drift
    p = up.validate({**GOOD, "size": 1.0}).pattern
    assert up.drift(up.legs(p)) == pytest.approx(pass_drift(up.compile_steps(p)))
