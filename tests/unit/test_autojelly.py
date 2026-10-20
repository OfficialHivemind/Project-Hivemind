"""act/autojelly on drawn frames: the gear check, the row by OCR, the state,
look-only never clicks the switch, unsure clicks nothing but the gear."""
import json
import shutil
from pathlib import Path

import cv2
import numpy as np
import pytest

from hivemind.act import autojelly as aj
from hivemind.vision import questmenu

GEAR = questmenu.button_at(questmenu.BUTTONS.index("settings"))


def world():
    f = np.zeros((1080, 1920, 3), np.uint8)
    f[:] = (40, 150, 190)                                  # the gold floor
    rng = np.random.default_rng(1)
    f[300:, 400:] = rng.integers(0, 255, (780, 1520, 3), dtype=np.uint8)
    t = cv2.imread(str(aj.GEAR_TEMPLATE), cv2.IMREAD_GRAYSCALE) > 127
    for i, (x, y) in enumerate(questmenu.button_at(k) for k in range(6)):
        if i == 4:
            cell = f[y - 28:y + 28, x - 28:x + 28]
            cell[t] = (225, 235, 235)
        else:
            cv2.circle(f, (x, y), 18, (225, 235, 235), -1)
    return f


ON_BRIGHT, ON_FADED = (89, 145, 72), (196, 199, 167)        # BGR, MEASURED 2026-10-14
OFF_BRIGHT, OFF_FADED = (84, 90, 205), (196, 184, 208)
REAL_PAGE = Path(__file__).resolve().parents[1] / "fixtures" / "autojelly_settings_page.jpg"


REAL_SECTION = REAL_PAGE.with_name("autojelly_section_page.jpg")
FIRST = 694                       # Until Legendary's row in the drawn tab


def layout(state="on", header="Auto-Jelly Settings:"):
    """[(label, state, y)]: two options, then the section's four rows under a
    header 44 px above, 50 px apart, as the real tab lays them out.
    `state` is Until Legendary's; the other three are OFF."""
    rows = [("Music", "on", 510), ("Pollen Text", "on", 560)]
    rows += [(name, state if i == 0 else "off", FIRST + 50 * i)
             for i, name in enumerate(aj.SECTION_ROWS)]
    return rows, header


def panel(state="on", header="Auto-Jelly Settings:"):
    f = world()
    f[170:970, 0:310] = (200, 190, 175)
    rows, _h = layout(state, header)
    for _text, st, y in rows:
        on = ON_BRIGHT if st == "on" else ON_FADED
        off = OFF_BRIGHT if st == "off" else OFF_FADED
        if st is None:
            on, off = ON_FADED, OFF_FADED                     # neither bright: unsure
        cv2.rectangle(f, (aj.ON_X - 25, y - 14), (aj.ON_X + 25, y + 14), on, -1)
        cv2.rectangle(f, (aj.OFF_X - 24, y - 14), (aj.OFF_X + 24, y + 14), off, -1)
    return f


def near(point) -> bool:
    """Until Legendary's OFF button: x exact, y within the row-centre's slack."""
    return point is not None and point[0] == aj.OFF_X and abs(point[1] - FIRST) <= 3


def labels_of(state="on", header="Auto-Jelly Settings:"):
    rows, h = layout(state, header)

    def read(frame, y):
        if abs(y - (FIRST - aj.HEADER_ABOVE)) <= 6:
            return h
        return next((t for t, _st, ry in rows if abs(ry - y) <= 6), "")
    return read


class Game:
    """The screen as the clicks leave it."""

    def __init__(self, state="on", label="Auto-Jelly Settings:", gear=True, sticky=False):
        self.open, self.state, self.label, self.sticky = False, state, label, sticky
        self.gear, self.clicks, self.scrolls = gear, [], 0

    def click(self, x, y):
        self.clicks.append((x, y))
        if (x, y) == GEAR:
            self.open = not self.open
        elif self.open and not self.sticky and self.state == "on":
            self.state = "off"
        return True

    def move_mouse(self, x, y):
        pass

    def scroll(self, n):
        self.scrolls += 1

    def frame(self):
        if not self.open:
            f = world()
            if not self.gear:
                f[100:156, 223:279] = (225, 235, 235)        # a white blob, no gear
            return f
        return panel(self.state, self.label)

    def read(self, frame, y):
        return labels_of(self.state, self.label)(frame, y) if self.open else ""


def run(game, tmp_path, mode="look"):
    class S:
        def get(self, key, fallback=None):
            return mode
    return aj.switch_off(game, game.frame, settings=S(), read=game.read,
                         sleep=lambda s: None, keep_dir=tmp_path, stamp="t")


def test_gear_template_passes_and_blob_refused():
    assert aj.gear_check(world())[0]
    f = world()
    f[100:156, 223:279] = (225, 235, 235)
    assert not aj.gear_check(f)[0]
    assert not aj.gear_check(world()[:720])[0]               # another size: unsure


def test_section_found_under_its_header():
    f = panel("on")
    rows = aj.option_rows(f, labels_of("on"))
    assert [r.state for r in rows] == ["on", "on", "on", "off", "off", "off"]
    sec, why = aj.find_section(f, rows, labels_of("on"))
    assert [r.state for r in sec] == ["on", "off", "off", "off"] and why == ""
    assert near((aj.OFF_X, sec[0].y))
    noisy = labels_of("on", "Avto-Jely Settngs |")                 # as tesseract read it
    assert aj.find_section(f, rows, noisy)[0] is not None
    f = panel(None)
    rows = aj.option_rows(f, labels_of(None))
    sec, why = aj.find_section(f, rows, labels_of(None))
    assert sec is None and "Until Legendary not plainly" in why
    f = panel("on", "Graphics")
    rows = aj.option_rows(f, labels_of("on", "Graphics"))
    assert aj.find_section(f, rows, labels_of("on", "Graphics")) == (None, "")


def test_look_only_never_clicks_the_switch(tmp_path):
    g = Game("on")
    out = run(g, tmp_path, "look")
    assert out.state == "on" and near(out.would_click[0]) and len(out.would_click) == 1 and not out.clicked
    assert g.clicks == [GEAR, GEAR] and g.state == "on" and not out.menu_open
    assert "would switch it off (look-only)" in out.describe()
    assert (tmp_path / "t" / "page-00.jpg").exists()
    assert json.loads((tmp_path / "last.json").read_text())["state"] == "on"


def test_act_clicks_once_and_verifies_off(tmp_path):
    g = Game("on")
    out = run(g, tmp_path, "act")
    assert out.now_off and len(g.clicks) == 3 and g.clicks[::2] == [GEAR, GEAR] and near(g.clicks[1])


def test_act_does_not_click_twice_when_it_stays_on(tmp_path):
    g = Game("on", sticky=True)
    out = run(g, tmp_path, "act")
    assert not out.now_off and len(g.clicks) == 3 and g.clicks[::2] == [GEAR, GEAR] and near(g.clicks[1])
    assert "not clicking again" in out.reason


def test_already_off_and_unsure_click_only_the_gear(tmp_path):
    for game in (Game("off"), Game(None), Game("on", "Graphics")):
        out = run(game, tmp_path, "act")
        assert game.clicks == [GEAR, GEAR] and not out.clicked


def test_no_gear_no_click(tmp_path):
    g = Game("on", gear=False)
    out = run(g, tmp_path, "act")
    assert g.clicks == [] and "gear" in out.reason


def test_not_settings_backs_out(tmp_path):
    g = Game("on")
    g.frame_open = g.frame
    g.frame = lambda: world() if g.open else world()            # opens, but no option rows
    g.open = False
    out = run(g, tmp_path, "act")
    assert "does not look like Settings" in out.reason or "nothing opened" in out.reason
    assert not any(near(c) for c in g.clicks)


def test_due(tmp_path):
    jelly = tmp_path / "jelly.json"
    assert aj.due(tmp_path, jelly)                                    # never looked
    (tmp_path / "last.json").write_text(json.dumps({"at": 1000.0}))
    assert not aj.due(tmp_path, jelly, clock=lambda: 9000.0)
    jelly.write_text(json.dumps({"auto_jelly_at": 2000.0}))
    assert aj.due(tmp_path, jelly, clock=lambda: 9000.0)
    assert not aj.due(tmp_path, jelly, clock=lambda: 2500.0)         # within the hour
    aj.mark_box(tmp_path, clock=lambda: 9500.0)
    jelly.write_text("{}")
    assert aj.due(tmp_path, jelly, clock=lambda: 9600.0)


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="no tesseract")
def test_the_real_settings_page():
    """var/autojelly/20261014-225554/page-00.jpg: the first look at the tab."""
    f = cv2.imread(str(REAL_PAGE))
    rows = aj.option_rows(f)
    assert [(r.label, r.state) for r in rows][:3] == [
        ("Music", "on"), ("Pollen Text", "on"), ("Abbreviate Pollen", "on")]
    assert [r.state for r in rows] == ["on"] * 4 + ["off"] * 2
    assert "Hide Other Bees" in [r.label for r in rows]
    assert aj.looks_like_settings(rows) and aj.find_section(f, rows) == (None, "")   # below: scroll


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="no tesseract")
def test_the_real_auto_jelly_section():
    """var/autojelly/20261014-233540/page-05.jpg: Until Legendary ON."""
    f = cv2.imread(str(REAL_SECTION))
    sec, why = aj.find_section(f, aj.option_rows(f))
    assert why == "" and [r.state for r in sec] == ["on", "off", "off", "off"]
    assert abs(sec[0].y - 790) <= 3
