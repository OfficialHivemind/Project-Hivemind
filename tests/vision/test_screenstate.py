"""Screen classification, against real captured frames.

These fixtures are the ground truth for the whole project and are checked in
rather than left in a scratch directory, because they are not reproducible: each
one is a specific moment (a join error, a cold splash, the app home) that costs a
two-minute game launch to recreate.

`app_home.png` earns its place twice over. An earlier brightness-and-saturation
classifier called that exact frame "world loaded", and the private-server test
built on it reported success while the game had never been entered. Any change
here that lets it read as IN_GAME again breaks this test.
"""
import pathlib

import cv2
import numpy as np
import pytest

from hivemind.vision.digits import TemplateSet
from hivemind.vision import screenstate as ss
from hivemind.vision.screenstate import (HONEY_REGION, POLLEN_REGION,
                                         Screen, classify, find_modal,
                                         hud_present)

SCREENS = pathlib.Path(__file__).resolve().parents[1] / "fixtures/screens"
TEMPLATES = pathlib.Path(__file__).resolve().parents[2] / "data" / "templates" / "digits"

EXPECTED = {
    "in_game": Screen.IN_GAME,
    "modal_join_error": Screen.MODAL,
    "app_home": Screen.APP_HOME,
    "loading_splash": Screen.LOADING,
    "loading_escape_menu": Screen.LOADING,
    "loading_headless": Screen.LOADING,
}


@pytest.fixture(scope="module")
def templates():
    if not (TEMPLATES / "index.json").exists():
        pytest.skip("digit templates not extracted yet")
    return TemplateSet.load(TEMPLATES)


def frame(name: str):
    path = SCREENS / f"{name}.png"
    if not path.exists():
        pytest.skip(f"fixture {name}.png not captured")
    return cv2.imread(str(path))


@pytest.mark.parametrize("name,expected", EXPECTED.items())
def test_classifies_every_captured_screen(name, expected, templates):
    assert classify(frame(name), templates) is expected


def test_app_home_is_never_in_game(templates):
    """The exact regression that made a failed join look like a success."""
    assert classify(frame("app_home"), templates) is not Screen.IN_GAME


def test_join_error_modal_geometry():
    modal = find_modal(frame("modal_join_error"))
    assert modal is not None
    # MEASURED from the capture: panel (706,313) 638x361, button (780,609) 360x36
    assert (modal.x, modal.y) == (706, 313)
    assert len(modal.buttons) == 1
    cx, cy = modal.button_centre(0)
    assert 940 <= cx <= 980 and 600 <= cy <= 650


def test_modal_body_excludes_the_button():
    modal = find_modal(frame("modal_join_error"))
    _, top, _, height = modal.body
    assert top + height <= modal.buttons[0][1]


def test_splash_is_not_a_modal():
    """A grey panel with no button is a splash, not a dialog to click through."""
    assert find_modal(frame("loading_splash")) is None


def test_in_game_hud_panel_is_not_a_modal():
    """In-game panels sit off-centre; only centred dialogs count."""
    assert find_modal(frame("in_game")) is None


def test_classify_without_templates_still_separates_modal_from_home():
    assert classify(frame("modal_join_error"), None) is Screen.MODAL
    assert classify(frame("app_home"), None) is Screen.APP_HOME


def test_in_game_detected_with_no_digit_templates_at_all():
    """The regression that recorded two successful joins as failures.

    The counter read "10,216,20?" on a live frame because the glyph 9 had never
    been seen, so confidence fell below threshold and a real join was logged as
    a timeout. Detecting the HUD structurally must not depend on the templates.
    """
    assert classify(frame("in_game"), None) is Screen.IN_GAME


@pytest.mark.parametrize("name", ["app_home", "modal_join_error",
                                  "loading_splash", "loading_escape_menu",
                                  "loading_headless"])
def test_hud_absent_on_every_non_game_screen(name):
    assert hud_present(frame(name)) is False


def test_hud_present_in_game():
    assert hud_present(frame("in_game")) is True


# --- hud_present must honour the regions it is GIVEN ------------------------

def test_hud_present_uses_the_supplied_pollen_region():
    """The slash test used to re-slice the module constant.

    It is the structural half of the check -- the part that stops the Bee
    Swarm store page classifying as IN_GAME -- and it always ran against the
    hard-coded 1920x1080 rectangle whatever the caller passed. Any layout
    carried by data/calib/regions.yaml therefore got a silent false negative
    on a genuine in-game frame.
    """
    img = frame("in_game")
    assert hud_present(img), "the unshifted frame must still pass"

    shift = 400
    moved = np.roll(img, shift, axis=1)
    regions = ((HONEY_REGION[0] + shift,) + HONEY_REGION[1:],
               (POLLEN_REGION[0] + shift,) + POLLEN_REGION[1:])
    assert hud_present(moved, regions), "ignored the supplied regions"
    assert not hud_present(moved), "the default regions must now miss it"


# --- the respawn confirmation, which gates an irreversible keystroke --------

def test_the_reset_dialog_is_recognised():
    """Return may only be pressed when THIS screen is up."""
    assert hud_present is not None            # module imported cleanly
    from hivemind.vision.screenstate import reset_dialog_present
    assert reset_dialog_present(frame("reset_dialog"))


def test_the_escape_menu_is_NOT_mistaken_for_it():
    """The in-game menu carries **Leave**, and Escape from the confirmation
    goes back to it — so this is exactly where a false positive would fire a
    Return at the wrong button. Measured template scores: confirmation 1.000,
    escape menu 0.326."""
    from hivemind.vision.screenstate import reset_dialog_present
    assert not reset_dialog_present(frame("escape_menu"))


def test_an_ordinary_game_frame_is_not_the_reset_dialog():
    from hivemind.vision.screenstate import reset_dialog_present
    assert not reset_dialog_present(frame("in_game"))


def test_a_missing_template_means_do_not_press(tmp_path, monkeypatch):
    """Not knowing must never read as permission."""
    import hivemind.vision.screenstate as ss_mod
    monkeypatch.setattr(ss_mod, "data",
                        lambda *parts: tmp_path.joinpath(*parts))
    assert not ss_mod.reset_dialog_present(frame("reset_dialog"))


# --- the HUD font SCALES, so no test on it may use absolute pixels ---------
# MEASURED: Bee Swarm shrinks the Pollen text to fit more characters.
#
#     "445,372/660,000"   digits h 11 w 8    slash h 16 w 5
#     "0/660,000"         digits h 15 w 11   slash h 21 w 7
#
# The slash test used `slash_w <= 6`, which passes the first and fails the
# second -- so the HUD went undetected on every frame with a SHORT pollen
# count. That is every frame just after converting, which is exactly when the
# farm loop starts: it waited 60s for a HUD that was on screen the whole time
# and then stopped. Proportions are stable where pixels are not.

def test_the_hud_is_found_at_both_font_sizes():
    """A short pollen count renders larger. Both must be recognised."""
    for name in ("in_game", "hive_short_pollen"):
        img = frame(name)
        assert hud_present(img), f"{name}: HUD missed at this font size"


def test_the_slash_test_is_relative_not_absolute():
    from hivemind.vision.screenstate import SLASH_NARROWER, SLASH_TALLER
    assert 0 < SLASH_NARROWER < 1, "width test must be a ratio, not pixels"
    assert SLASH_TALLER > 1
    assert not hasattr(ss_module(), "SLASH_MAX_W"), (
        "an absolute slash width is what broke short pollen counts")


def ss_module():
    import hivemind.vision.screenstate as module
    return module


def test_a_short_pollen_count_still_parses():
    from hivemind.vision import digits
    img = frame("hive_short_pollen")
    x, y, w, h = POLLEN_REGION
    text, score = digits.read(img[y:y + h, x:x + w],
                              TemplateSet.load(TEMPLATES))
    assert digits.parse_fraction(text) is not None, f"{text!r} at {score:.3f}"


# ---- the game prints its own rate, and nothing was reading it ---------------
# MEASURED 2026-09-23 08:15 from `var/hotbar/hotbar-slot1-after-081519.jpg`:
#
#     Honey  24,471,762  (+9/sec)     Pollen  21,401/1,191,713  (+71/sec)
#
# Every field rate in `brain/fieldnotes` is INFERRED instead -- counter deltas
# over long windows, with all the trouble that brings: illegible digits above
# a million (8aq), a token pickup landing as a lump inside one interval (8av),
# and a numerator and denominator that have to be kept describing the same
# seconds (8au). This is the same quantity, printed by the game.

RATE_FRAMES = (
    ("hotbar-slot1-after-081519.jpg", 71, 9),
    ("hotbar-slot1-before-081518.jpg", 78, 9),
)


@pytest.mark.parametrize("name,pollen,honey", RATE_FRAMES)
def test_the_rate_is_read_off_the_hud(name, pollen, honey):
    import pathlib
    root = pathlib.Path(__file__).resolve().parents[2]
    path = root / "var" / "hotbar" / name
    if not path.exists():
        pytest.skip(f"{name} is not in the repo")
    frame = cv2.imread(str(path))
    if frame is None:
        pytest.skip(f"{name} could not be read")
    templates = ss.load_templates(root / "data/templates/digits")
    assert ss.rate_in(frame, ss.POLLEN_REGION, templates) == pollen
    assert ss.rate_in(frame, ss.HONEY_REGION, templates) == honey


def test_the_digits_are_the_anchor_not_the_slash():
    """What the digit reader actually returns: the slash is recognised in
    `(+71/sec)` and not in `(+9/sec)`, so it cannot be the anchor."""
    assert ss.rate_from_text("??71/????") == 71
    assert ss.rate_from_text("??9?????") == 9
    assert ss.rate_from_text("??1,234/????") is None, "a comma splits the run"


def test_two_separate_runs_are_refused():
    """Two numbers in a box that can only hold one means something was
    misread, and a rate that was never on screen is worse than none."""
    assert ss.rate_from_text("?7?1?") is None
    assert ss.rate_from_text("12?34") is None


def test_the_s_of_sec_read_as_a_digit_does_not_refuse_the_rate():
    """MEASURED over the saved windows: `(+758/sec)` reads `??758/5???` on
    nearly every frame. The rate is the run ending at the slash; what
    follows the slash is letters, whatever the reader made of them."""
    assert ss.rate_from_text("??758/5???") == 758
    assert ss.rate_from_text("??1594/5???") == 1594
    assert ss.rate_from_text("??71/????") == 71
    assert ss.rate_from_text("???/5???") is None, "no digits before the slash"


def test_no_digits_at_all_is_none():
    assert ss.rate_from_text("") is None
    assert ss.rate_from_text("??????") is None
    assert ss.rate_from_text(None) is None


def test_no_frame_is_not_a_crash():
    assert ss.rate_in(None, ss.POLLEN_REGION, None) is None


# --- the hive pad's own prompt, cheaply -------------------------------------
# act/hiverow polls this ten times a second while holding a key along the
# hive row, so it is a template in a band rather than a model read. Measured
# scores in vision/screenstate: 0.836-0.839 on the pad, 0.245-0.313 off it.

def test_make_honey_is_seen_on_the_pad():
    from hivemind.vision.screenstate import make_honey_present
    assert make_honey_present(frame("hive_make_honey"))


def test_make_honey_is_not_seen_off_the_pad():
    from hivemind.vision.screenstate import make_honey_present
    assert not make_honey_present(frame("in_game"))
    assert not make_honey_present(frame("field_earning"))
    assert not make_honey_present(frame("reset_dialog"))


def test_the_empty_bag_banner_is_the_pad_too():
    """MEASURED 2026-09-23 20:39: with 0 pollen the pad says "To Make Honey,
    Collect Pollen From Flower Fields" in a blue banner, and the E-prompt
    template reads 0.29 against it. Either means we are standing on it."""
    from hivemind.vision.screenstate import make_honey_present
    assert make_honey_present(frame("hive_make_honey_empty"))
    assert make_honey_present(frame("hive_make_honey"))


def test_the_empty_bag_banner_is_seen_through_jpeg_and_a_honeycomb_background():
    """MEASURED over 4,529 frames: the banner scores 0.63-0.69 on the q70
    route frames because it is translucent over the honeycomb wall. This
    fixture is one of them (attempt 324's route-out start, 0.655)."""
    from hivemind.vision.screenstate import make_honey_present
    assert make_honey_present(frame("hive_make_honey_empty_q70"))


def test_the_banner_drawn_ten_pixels_lower_over_the_name_is_still_the_pad():
    """The weakest true banner in the corpus: 0.608 at (782, 70), the owner's
    name on the wall showing through it (03:19, attempt 281). First read as a
    different notification; the frame says otherwise."""
    from hivemind.vision.screenstate import make_honey_present
    assert make_honey_present(frame("hive_make_honey_empty_shifted"))


def test_a_template_passed_in_is_the_only_one_tried():
    import cv2
    from hivemind.vision import screenstate as ss_mod
    empty_only = cv2.imread(str(ss_mod.data("templates", "ui", ss_mod.MAKE_HONEY_EMPTY_TEMPLATE)))
    assert ss_mod.make_honey_present(frame("hive_make_honey_empty"), template=empty_only)
    assert not ss_mod.make_honey_present(frame("hive_make_honey"), template=empty_only)


def test_a_missing_make_honey_template_means_not_there(tmp_path, monkeypatch):
    """A held key is released on this answer; not knowing must not release it."""
    import hivemind.vision.screenstate as ss_mod
    monkeypatch.setattr(ss_mod, "data", lambda *parts: tmp_path.joinpath(*parts))
    assert not ss_mod.make_honey_present(frame("hive_make_honey"))


def test_a_view_from_inside_the_world_is_blind():
    # MEASURED 2026-10-02: clipped frames read 70-100% near-black in the world
    # box, ordinary ones 7-35%
    import numpy as np
    from hivemind.vision import screenstate as ss_
    black = np.zeros((1080, 1920, 3), np.uint8)
    assert ss_.world_blind(black)
    field = np.full((1080, 1920, 3), (60, 160, 70), np.uint8)       # a lit field
    assert not ss_.world_blind(field)
    half = field.copy()
    half[130:540, :] = 0                                            # half the view dark
    assert not ss_.world_blind(half)
    hud_only = black.copy()
    hud_only[130:950, 200:1720] = (60, 160, 70)                     # dark only outside the box
    assert not ss_.world_blind(hud_only)
