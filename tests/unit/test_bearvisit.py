"""Walking to a quest giver, writing down its prompt, pressing nothing."""
from __future__ import annotations

import json
import pathlib

import numpy as np

from hivemind.act.bearvisit import GIVERS, Learned, visit


def test_it_reads_the_panel_and_walks_back():
    said = []
    out = visit("black_bear", walk=lambda: True, back=lambda: True,
                read_panel=lambda frame=None: "Talk to Black Bear",
                frames=lambda: np.zeros((1080, 1920, 3), np.uint8),
                sleep=lambda s: None, on_note=said.append)
    assert out.walked and out.came_back
    assert out.panel == "Talk to Black Bear"
    assert any("Talk to Black Bear" in t for t in said)


def test_it_keeps_the_frame_when_asked(tmp_path):
    out = visit("polar_bear", walk=lambda: True, back=lambda: True,
                read_panel=lambda frame=None: "Talk to Polar Bear",
                frames=lambda: np.zeros((1080, 1920, 3), np.uint8),
                save_dir=tmp_path, sleep=lambda s: None)
    assert out.frame_path and pathlib.Path(out.frame_path).exists()


def test_a_route_that_does_not_run_reads_no_panel():
    looks = []
    out = visit("brown_bear", walk=lambda: False, back=lambda: True,
                read_panel=lambda frame=None: looks.append(1) or "x",
                sleep=lambda s: None)
    assert not out.walked and out.panel == "" and looks == []
    assert "did not complete" in out.reason


def test_a_panel_that_cannot_be_read_is_not_a_prompt():
    out = visit("honey_bee", walk=lambda: True, back=lambda: True,
                read_panel=lambda frame=None: None,
                frames=lambda: np.zeros((10, 10, 3), np.uint8), sleep=lambda s: None)
    assert out.panel == "" and out.walked


def test_failing_to_get_back_still_reports_the_words():
    out = visit("bucko_bee", walk=lambda: True, back=lambda: False,
                read_panel=lambda frame=None: "Talk to Bucko Bee",
                frames=lambda: np.zeros((10, 10, 3), np.uint8), sleep=lambda s: None)
    assert out.panel == "Talk to Bucko Bee" and not out.came_back
    assert "did NOT get back" in out.describe()


def test_what_has_been_learned_survives_and_says_what_is_left(tmp_path):
    store = Learned(tmp_path / "bear_panels.json").load()
    assert store.unknown() == list(GIVERS)
    store.prompts["black_bear"] = "Talk to Black Bear"
    store.save()
    again = Learned(tmp_path / "bear_panels.json").load()
    assert again.prompts["black_bear"] == "Talk to Black Bear"
    assert "black_bear" not in again.unknown()
    assert json.loads((tmp_path / "bear_panels.json").read_text())["black_bear"]


def test_a_broken_store_is_a_fresh_start(tmp_path):
    (tmp_path / "bear_panels.json").write_text("{not json")
    assert Learned(tmp_path / "bear_panels.json").load().unknown() == list(GIVERS)


# ---- pressing E at a giver, once its prompt is known ----------------------------

class Vin:
    def __init__(self): self.taps = []

    def tap(self, key): self.taps.append(key)


def _ask(text):
    class A:
        def __init__(self, t): self.text = t
    return lambda png, question: A(text)


def _boxed():
    """A frame with the dialogue box on it, in its own blue where it was
    measured (act/dialogue EXPECTED): `talk` keeps a dialogue's words only
    when a box was seen ("NO BOX, NO DIALOGUE", DESIGN 8a)."""
    import cv2
    from hivemind.act import dialogue as D
    frame = np.zeros((1080, 1920, 3), np.uint8)
    x, y, w, h = D.EXPECTED
    patch = np.full((h, w, 3), (108, 205, 168), np.uint8)
    frame[y:y + h, x:x + w] = cv2.cvtColor(patch, cv2.COLOR_HSV2BGR)
    return frame


def test_it_presses_e_only_when_the_panel_says_what_it_should():
    from hivemind.act.bearvisit import talk
    vin = Vin()
    out = talk("black_bear", expect="Talk to Black Bear",
               read_panel=lambda frame=None: "Open Shop",
               frames=lambda: np.zeros((1080, 1920, 3), np.uint8),
               ask=_ask("NONE"), vin=vin, sleep=lambda s: None)
    assert not out.pressed and vin.taps == []
    assert "never said 'Talk to Black Bear'" in out.reason, out.reason
    assert "Open Shop" in out.reason, "the reason must name what it did read"


def test_a_prompt_that_shows_up_late_is_still_found():
    """MEASURED 2026-09-23: the errand walked 162 studs to the Black Bear,
    read the shared top-centre panel ONCE, got "" and wrote itself off --
    `var/bear_dialogues.json` held `reason: the panel says '', not 'Talk to
    Black Bear'`. That panel carries receipts and level-ups too, so a single
    read can miss a prompt that is there."""
    from hivemind.act.bearvisit import talk
    reads = iter(["", "You've made 12,345 honey!", "", "Talk to Black Bear"])
    vin = Vin()
    out = talk("black_bear", expect="Talk to Black Bear",
               read_panel=lambda frame=None: next(reads),
               frames=_boxed,
               ask=_ask("Collect 500,000 pollen from the Sunflower Field"),
               vin=vin, sleep=lambda s: None)
    assert out.looks == 4, out.looks
    assert out.pressed and vin.taps == ["e"]
    assert "Sunflower" in out.dialogue


def test_it_still_gives_up_rather_than_looking_for_ever():
    from hivemind.act.bearvisit import talk, LOOK_TRIES
    vin = Vin()
    out = talk("black_bear", expect="Talk to Black Bear",
               read_panel=lambda frame=None: "",
               frames=lambda: np.zeros((1080, 1920, 3), np.uint8),
               ask=_ask("NONE"), vin=vin, sleep=lambda s: None)
    assert out.looks == LOOK_TRIES and not out.pressed and vin.taps == []


def test_it_reads_the_dialogue_and_never_presses_anything_to_dismiss_it():
    from hivemind.act.bearvisit import talk
    vin = Vin()
    walked = []
    out = talk("black_bear", expect="Talk to Black Bear",
               read_panel=lambda frame=None: "E Talk to Black Bear",
               frames=_boxed,
               ask=_ask("Black Bear: Bring me 3,000,000 white pollen. [Accept] [Decline]"),
               vin=vin, walk_away=lambda: walked.append(1), sleep=lambda s: None)
    assert out.pressed and vin.taps == ["e"], vin.taps
    assert out.opened and "Accept" in out.dialogue
    assert walked == [1]
    assert "e" in vin.taps and len(vin.taps) == 1, "nothing was pressed to dismiss it"


def test_a_dialogue_that_never_appears_is_reported_not_assumed():
    from hivemind.act.bearvisit import talk
    out = talk("black_bear", expect="Talk to Black Bear",
               read_panel=lambda frame=None: "Talk to Black Bear",
               frames=lambda: np.zeros((1080, 1920, 3), np.uint8),
               ask=_ask("NONE"), vin=Vin(), sleep=lambda s: None)
    assert out.pressed and not out.opened
    assert "no dialogue was read" in out.describe()


def test_whether_walking_away_closed_it_is_recorded(tmp_path):
    from hivemind.act.bearvisit import talk
    answers = iter(["Black Bear: hello [Okay]", "NONE"])
    left = {"yes": False}
    out = talk("black_bear", expect="Talk to Black Bear",
               read_panel=lambda frame=None: "Talk to Black Bear",
               # the box is up until the walk away, gone after it
               frames=lambda: np.zeros((1080, 1920, 3), np.uint8) if left["yes"] else _boxed(),
               ask=lambda png, q: type("A", (), {"text": next(answers)})(),
               vin=Vin(), walk_away=lambda: left.update(yes=True), save_dir=tmp_path,
               sleep=lambda s: None)
    assert out.opened and out.after_leaving == "NONE"
    assert "walking away closed it" in out.describe()
    assert len(out.frames) == 2 and all(pathlib.Path(f).exists() for f in out.frames)


def test_a_model_that_fails_does_not_break_the_visit():
    from hivemind.act.bearvisit import talk

    def broken(png, question):
        raise RuntimeError("the model is down")
    said = []
    out = talk("black_bear", expect="Talk to Black Bear",
               read_panel=lambda frame=None: "Talk to Black Bear",
               frames=lambda: np.zeros((1080, 1920, 3), np.uint8),
               ask=broken, vin=Vin(), sleep=lambda s: None, on_note=said.append)
    assert out.pressed and out.dialogue == ""
    assert any("could not read the dialogue" in t for t in said), said


# ---- an open dialogue eats the movement keys, so it is clicked shut --------
# MEASURED 2026-09-23 03:29: `talk` pressed E, read one page, ran
# `natro_back_black_bear` to leave -- and the frame taken afterwards is the
# same scene pixel for pixel, dialogue box included. The character never
# moved. The box's own small print says "Click to continue".

def test_the_dialogue_is_clicked_shut_and_every_page_is_kept():
    from hivemind.act.bearvisit import talk
    from hivemind.act import dialogue as D
    import cv2

    def painted():
        frame = np.zeros((1080, 1920, 3), np.uint8)
        x, y, w, h = D.EXPECTED
        patch = np.full((h, w, 3), (108, 205, 168), np.uint8)
        frame[y:y + h, x:x + w] = cv2.cvtColor(patch, cv2.COLOR_HSV2BGR)
        return frame

    # THE FRAME BUDGET, stated because getting it wrong looks like a bug in
    # the code under test: `talk` takes one frame to read the prompt, one to
    # photograph the opened dialogue, and then `advance` takes one per page
    # plus one more to see that the box has gone.
    shut = np.zeros((1080, 1920, 3), np.uint8)
    looks = {"n": 0}

    def next_frame():
        looks["n"] += 1
        return shut if looks["n"] >= 5 else painted()

    said = iter(["Black Bear Hello there. Click to continue",     # the photo
                 "Black Bear Hello there. Click to continue",     # page 1
                 "Black Bear Bring me pollen. Click to continue"])  # page 2
    clicks, walks = [], []
    vin = Vin()
    out = talk("black_bear", expect="Talk to Black Bear",
               read_panel=lambda frame=None: "Talk to Black Bear",
               frames=next_frame, ask=lambda png, q: next(said),
               vin=vin, sleep=lambda s: None,
               click=lambda x, y: clicks.append((x, y)),
               walk_away=lambda: walks.append("walked"))
    assert vin.taps == ["e"], vin.taps
    assert out.closed, out.describe()
    assert out.pages == ["Black Bear Hello there. Click to continue",
                         "Black Bear Bring me pollen. Click to continue"]
    assert clicks == [D.find(painted()).centre] * 2
    assert walks == [], "it walked away from a dialogue it had already closed"


def test_walking_away_is_still_tried_when_the_box_will_not_close():
    from hivemind.act.bearvisit import talk
    from hivemind.act import dialogue as D
    import cv2
    frame = np.zeros((1080, 1920, 3), np.uint8)
    x, y, w, h = D.EXPECTED
    patch = np.full((h, w, 3), (108, 205, 168), np.uint8)
    frame[y:y + h, x:x + w] = cv2.cvtColor(patch, cv2.COLOR_HSV2BGR)
    walks = []
    out = talk("black_bear", expect="Talk to Black Bear",
               read_panel=lambda frame=None: "Talk to Black Bear",
               frames=lambda: frame, ask=lambda png, q: "the same page",
               vin=Vin(), sleep=lambda s: None,
               click=lambda cx, cy: None,
               walk_away=lambda: walks.append("walked"))
    assert not out.closed
    assert walks == ["walked"], "the fallback did not run"


def test_no_clicker_means_the_old_behaviour_and_no_clicks():
    """A caller that passes no `click` must not have keys or buttons sent on
    its behalf -- the routine reads one page and leaves by walking."""
    from hivemind.act.bearvisit import talk
    walks = []
    vin = Vin()
    out = talk("black_bear", expect="Talk to Black Bear",
               read_panel=lambda frame=None: "Talk to Black Bear",
               frames=lambda: np.zeros((1080, 1920, 3), np.uint8),
               ask=_ask("Black Bear Hello"), vin=vin, sleep=lambda s: None,
               walk_away=lambda: walks.append("walked"))
    assert vin.taps == ["e"] and out.pages == [] and walks == ["walked"]


# ---- a prompt only shows when the thing is in front of you ----------------
# MEASURED 2026-09-23 04:09: `natro_out_bucko_bee` was run from the pad
# straight after a confirmed convert, and the frame it saved
# (`var/bears/bucko_bee-040928.jpg`) shows the character in the blue
# headquarters area looking at a flat cyan wall. It had arrived; it was facing
# the wrong way, and eight more looks at the same wall cannot help.

def test_it_turns_the_camera_when_the_panel_is_empty():
    from hivemind.act.bearvisit import visit
    reads = iter(["", "", "", "Talk to Bucko Bee"])
    taps = []
    out = visit("bucko_bee", walk=lambda: True, back=lambda: True,
                read_panel=lambda frame=None: next(reads),
                frames=lambda: np.zeros((1080, 1920, 3), np.uint8),
                sleep=lambda s: None, turn=lambda n: taps.append(n))
    assert out.panel == "Talk to Bucko Bee"
    assert out.turns == 3, out.turns
    assert taps == [1, 1, 1, -3], taps


def test_the_camera_goes_back_even_when_nothing_was_found():
    from hivemind.act.bearvisit import visit, TAPS_PER_FULL_TURN
    taps = []
    out = visit("bucko_bee", walk=lambda: True, back=lambda: True,
                read_panel=lambda frame=None: "",
                frames=lambda: np.zeros((1080, 1920, 3), np.uint8),
                sleep=lambda s: None, turn=lambda n: taps.append(n))
    assert out.panel == ""
    assert sum(taps) == 0, f"the camera was left {sum(taps)} tap(s) out: {taps}"
    assert out.turns <= TAPS_PER_FULL_TURN


def test_it_does_not_turn_past_a_full_turn():
    from hivemind.act.bearvisit import visit
    taps = []
    visit("bucko_bee", walk=lambda: True, back=lambda: True,
          read_panel=lambda frame=None: "",
          frames=lambda: np.zeros((1080, 1920, 3), np.uint8),
          sleep=lambda s: None, turn=lambda n: taps.append(n),
          tries=40, full_turn=8)
    assert [t for t in taps if t > 0] == [1] * 8, taps
    assert taps[-1] == -8


def test_a_camera_that_will_not_turn_does_not_stop_the_recon():
    from hivemind.act.bearvisit import visit

    def broken(n):
        raise RuntimeError("no camera")

    out = visit("bucko_bee", walk=lambda: True, back=lambda: True,
                read_panel=lambda frame=None: "",
                frames=lambda: np.zeros((1080, 1920, 3), np.uint8),
                sleep=lambda s: None, turn=broken, tries=3)
    assert out.looks == 3 and out.panel == ""


def test_no_turn_callback_means_the_old_behaviour():
    from hivemind.act.bearvisit import visit
    out = visit("black_bear", walk=lambda: True, back=lambda: True,
                read_panel=lambda frame=None: "Talk to Black Bear",
                frames=lambda: np.zeros((1080, 1920, 3), np.uint8),
                sleep=lambda s: None)
    assert out.panel == "Talk to Black Bear" and out.turns == 0


# ---- the owner's per-giver switches, wired at last ------------------------
# The eight `quests.<bear>` toggles sat in NOT_WIRED under the note "reading
# quests works; TALKING to a bear does not". That stopped being true on
# 2026-09-23: the Black Bear's dialogue was read and clicked through, and the
# errand now covers every giver Natro has a path to.

class _Switches:
    def __init__(self, off=()):
        self.off = set(off)

    def bool(self, key):
        return key not in self.off


def test_every_giver_is_visited_by_default():
    from hivemind.act.bearvisit import wanted_givers, GIVERS
    assert wanted_givers(_Switches(), GIVERS) == tuple(GIVERS)


def test_a_giver_switched_off_is_dropped():
    from hivemind.act.bearvisit import wanted_givers
    out = wanted_givers(_Switches(off={"quests.bucko"}),
                        ("bucko_bee", "black_bear"))
    assert out == ("black_bear",)


def test_a_name_with_no_switch_is_kept():
    """`blue_hq` is a shop, not a giver. This filters what the owner said no
    to and says nothing about anything else."""
    from hivemind.act.bearvisit import wanted_givers
    assert wanted_givers(_Switches(), ("blue_hq",)) == ("blue_hq",)


def test_unreadable_settings_keep_everything():
    """An errand not running is a quieter failure than a control that
    silently cancels it."""
    from hivemind.act.bearvisit import wanted_givers

    class Broken:
        def bool(self, key):
            raise RuntimeError("no settings file")

    assert wanted_givers(Broken(), ("bucko_bee",)) == ("bucko_bee",)


def test_the_order_given_is_the_order_returned():
    """The caller orders these by walk length, cheapest first."""
    from hivemind.act.bearvisit import wanted_givers
    order = ("bucko_bee", "black_bear", "brown_bear", "polar_bear")
    assert wanted_givers(_Switches(), order) == order


def test_every_mapped_setting_is_a_real_one():
    from hivemind.act.bearvisit import GIVER_SETTINGS
    from hivemind.world.settings import SECTIONS
    every = {e[0] for _, entries in SECTIONS for e in entries}
    missing = set(GIVER_SETTINGS.values()) - every
    assert not missing, f"these map to settings that do not exist: {missing}"


def test_the_wired_switches_are_out_of_the_unwired_list():
    from hivemind.act.bearvisit import GIVER_SETTINGS
    from hivemind.world.settings import NOT_WIRED
    still = set(GIVER_SETTINGS.values()) & NOT_WIRED
    assert not still, f"wired but still marked unwired: {sorted(still)}"


# ---- a failure must not erase an answer ------------------------------------
# MEASURED 2026-09-23 04:58: `var/bear_dialogues.json` held the Black Bear's
# real dialogue, read at 03:29, and by 04:58 the same file read dialogue="",
# closed=false, pages=[] — a later attempt that never reached the bear was
# written over the top. The store was written unconditionally, so every retry
# of a giver whose record is incomplete could destroy what the last one
# learned.

GOOD = {"dialogue": "Black Bear You know...", "pages": ["one", "two"],
        "closed": True}
HALF = {"dialogue": "Black Bear You know...", "pages": ["one"], "closed": False}
NONE = {"dialogue": "", "pages": [], "closed": False,
        "reason": "the panel never said 'Talk to Black Bear'"}


def test_a_failed_retry_does_not_replace_a_reading():
    from hivemind.act.bearvisit import further_dialogue
    assert further_dialogue(GOOD, NONE) is GOOD
    assert further_dialogue(HALF, NONE) is HALF


def test_a_better_reading_does_replace_the_old_one():
    from hivemind.act.bearvisit import further_dialogue
    assert further_dialogue(HALF, GOOD) is GOOD
    assert further_dialogue(NONE, HALF) is HALF


def test_closed_beats_open_even_with_fewer_pages():
    """An open box means the pages after it were never seen, so a reading
    that ended with the box gone is the more complete one."""
    from hivemind.act.bearvisit import further_dialogue
    shut = {"dialogue": "d", "pages": ["only"], "closed": True}
    open_but_longer = {"dialogue": "d", "pages": ["a", "b", "c"], "closed": False}
    assert further_dialogue(open_but_longer, shut) is shut


def test_a_tie_keeps_the_older_record():
    """A retry that learned nothing changes nothing."""
    from hivemind.act.bearvisit import further_dialogue
    same = dict(HALF)
    assert further_dialogue(HALF, same) is HALF


def test_an_empty_slot_is_a_tie_that_the_caller_resolves():
    """Two readings with nothing in them rank equal, so the tie rule keeps
    the older -- and the older is empty. The caller writes anyway, because it
    asks `kept is was AND was`: an empty `was` is nothing to keep."""
    from hivemind.act.bearvisit import further_dialogue
    kept = further_dialogue({}, NONE)
    assert kept is not NONE and not kept, kept
    assert further_dialogue(None, HALF) is HALF


def test_the_callers_guard_stores_a_first_failure():
    """A giver with no record at all should end up with the failure written
    down, reason and all -- that is a record, and it is how the next attempt
    knows what happened."""
    from hivemind.act.bearvisit import further_dialogue
    was = {}
    kept = further_dialogue(was, NONE)
    stores = not (kept is was and was)
    assert stores, "a first attempt's outcome was thrown away"


# ---- a shop is not a giver, and E at a shop spends honey -------------------
# The errand's route table carries `blue_hq` so the RECON can go and read its
# panel, which presses nothing. Talking is different: it presses E at whatever
# the learned prompt says, and the panel at the blue headquarters says
# `Open Shop` (var/place_panels.json, read 2026-09-23 04:10). Pressing E there
# opens a shop, and a shop is one keypress from spending the owner's honey.

def test_no_headquarters_is_a_quest_giver():
    from hivemind.act.bearvisit import GIVERS
    for shop in ("blue_hq", "red_hq", "mountain_hq"):
        assert shop not in GIVERS, f"{shop} would be pressed at"


def test_no_dispenser_or_shop_is_a_quest_giver():
    from hivemind.act.bearvisit import GIVERS
    for name in GIVERS:
        assert name.endswith(("_bear", "_bee")), (
            f"{name} is in GIVERS but is not a bear or a bee, and everything "
            f"in GIVERS gets E pressed at it")


def test_every_giver_has_a_settings_switch_or_no_route():
    """A giver that can be pressed at should be one the owner can switch off.
    The two without switches are the two with no recorded route."""
    from hivemind.act.bearvisit import GIVERS, GIVER_SETTINGS
    assert set(GIVERS) == set(GIVER_SETTINGS), (
        sorted(set(GIVERS) ^ set(GIVER_SETTINGS)))


# --- what counts as a prompt --------------------------------------------------
# MEASURED 2026-09-23 18:17: the banner region read the HUD -- 'Honey
# 20,750,759 (+13/sec) Pollen 1,958/1,113,750 (+69/sec)' -- and it was written
# down as the Bucko Bee's prompt. A prompt is short and carries no digits.

def test_the_hud_is_not_a_prompt():
    from hivemind.act.bearvisit import prompt_shaped
    assert not prompt_shaped("Honey 20,750,759 (+13/sec) Pollen 1,958/1,113,750 (+69/sec)")
    assert not prompt_shaped("")
    assert not prompt_shaped(None)
    assert prompt_shaped("Talk to Black Bear")
    assert prompt_shaped("  Make   Honey ")


def test_junk_in_the_panel_file_is_dropped_on_load_and_reported(tmp_path):
    import json
    from hivemind.act.bearvisit import Learned
    path = tmp_path / "bear_panels.json"
    path.write_text(json.dumps({
        "black_bear": "Talk to Black Bear",
        "bucko_bee": "Honey 20,750,759 (+13/sec) Pollen 1,958/1,113,750 (+69/sec)"}))
    store = Learned(path).load()
    assert store.prompts == {"black_bear": "Talk to Black Bear"}
    assert list(store.rejected) == ["bucko_bee"]
    assert "bucko_bee" in store.unknown()


def test_dropped_junk_is_written_out_of_the_file_at_once(tmp_path):
    import json
    from hivemind.act.bearvisit import Learned
    path = tmp_path / "bear_panels.json"
    path.write_text(json.dumps({"black_bear": "Talk to Black Bear",
                                "bucko_bee": "Honey 20,750,759 (+13/sec)"}))
    Learned(path).load()
    assert json.loads(path.read_text()) == {"black_bear": "Talk to Black Bear"}
    again = Learned(path).load()
    assert again.rejected == {}, "reported once, not at every start"


def test_the_hunt_starts_facing_a_quest_marker_the_round_saw():
    # MEASURED 2026-10-06: the Spirit Bear's route ended in four places in four
    # runs, one with her "!" up and to the right; the beacon only follows a "!"
    # on screen when the hunt starts
    from hivemind.act.bearvisit import visit
    taps, state, at_hunt = [], {"turned": 0}, []

    def turn(n):
        taps.append(n)
        state["turned"] += n
    out = visit("spirit_bear", walk=lambda: True, back=lambda: True,
                read_panel=lambda frame=None: "",
                frames=lambda: np.zeros((8, 8, 3), np.uint8),
                sleep=lambda s: None, turn=turn,
                marker=lambda frame: state["turned"] == 3,
                hunt=lambda: at_hunt.append(state["turned"]) or "")
    assert at_hunt == [3], (at_hunt, taps)
    assert state["turned"] == 0, f"the camera was left {state['turned']} tap(s) out: {taps}"
    assert out.panel == ""


def test_no_marker_no_change():
    from hivemind.act.bearvisit import visit
    taps, at_hunt = [], []
    visit("spirit_bear", walk=lambda: True, back=lambda: True,
          read_panel=lambda frame=None: "",
          frames=lambda: np.zeros((8, 8, 3), np.uint8),
          sleep=lambda s: None, turn=lambda n: taps.append(n),
          marker=lambda frame: False, hunt=lambda: at_hunt.append(sum(taps)) or "")
    assert at_hunt == [0] and sum(taps) == 0, taps


def test_at_place_runs_on_the_read_panel_before_the_walk_back():
    order = []
    out = visit("sticker_stack", walk=lambda: True,
                back=lambda: order.append("back") or True,
                read_panel=lambda frame=None: "Sticker Stack",
                frames=lambda: np.zeros((1080, 1920, 3), np.uint8),
                sleep=lambda s: None, at_place=lambda panel: order.append(panel))
    assert order == ["Sticker Stack", "back"] and out.came_back


def test_at_place_is_not_run_when_nothing_was_read():
    called = []
    visit("sticker_stack", walk=lambda: True, back=lambda: True,
          read_panel=lambda frame=None: "", frames=lambda: None,
          sleep=lambda s: None, tries=1, at_place=called.append)
    assert called == []
