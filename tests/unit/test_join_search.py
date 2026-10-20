"""When Bee Swarm's tile is not on the app's home, search for it -- but Enter
only after the box reads back the query (2026-10-21 01:20)."""
import numpy as np

from hivemind.act import join


class FakeInp:
    def __init__(self, did):
        self.did = did

    def type_text(self, text):
        self.did.append(("type", text))


class FakeUI:
    def __init__(self):
        self.did = []
        self.inp = FakeInp(self.did)

    def click(self, x, y, settle=1.2):
        self.did.append(("click", x, y))

    def frame(self):
        return np.zeros((720, 1280, 3), np.uint8)

    def search(self, text):
        self.did.append(("search", text))

    def submit(self):
        self.did.append("enter")

    def back(self):
        self.did.append("escape")


def test_enter_only_when_the_box_reads_the_query(monkeypatch):
    import hivemind.act.shoplook as shoplook
    ui = FakeUI()
    monkeypatch.setattr(shoplook, "_ocr_line", lambda f, box, psm=7: "Discover avatars")
    assert join.search_for_the_game(ui, np.zeros((10, 10, 3), np.uint8), lambda t: None) is None
    assert "enter" not in ui.did and "escape" in ui.did


def test_a_read_back_query_presses_enter_and_clicks_only_a_matching_tile(monkeypatch):
    import hivemind.act.shoplook as shoplook
    ui = FakeUI()
    monkeypatch.setattr(shoplook, "_ocr_line", lambda f, box, psm=7: "Bee Swarm Simulator")
    monkeypatch.setattr(join, "TILE_LOOK_SECONDS", 0.0)
    monkeypatch.setattr(join, "find_bss_tile", lambda frame, tile: None)
    assert join.search_for_the_game(ui, np.zeros((10, 10, 3), np.uint8), lambda t: None) is None
    assert ui.did[0][0] == "click" and ui.did[1] == ("type", join.SEARCH_QUERY)
    assert ui.did[2] == "enter"


def test_a_1280_frame_position_is_clicked_in_the_1920_output():
    """2026-10-21 01:36: a click at the 1280 frame's x 675 landed at ~455."""
    small = np.zeros((720, 1280, 3), np.uint8)
    big = np.zeros((1080, 1920, 3), np.uint8)
    assert join.to_input(small, 675, 27) == (1012, 40)
    assert join.to_input(big, 675, 27) == (675, 27)        # a full frame is unchanged


def test_the_top_result_is_opened_only_when_it_reads_bee_swarm_by_onett():
    """2026-10-21 02:17: the results lead with a large card the thumbnail
    template cannot match; its title line is read instead."""
    frame = np.zeros((720, 1280, 3), np.uint8)
    hit = join.top_result_is_bss(frame, ocr=lambda f, box: "Bee Swarm Simulator By Onett g")
    assert hit is not None and hit.centre == (380, 320)
    assert join.top_result_is_bss(frame, ocr=lambda f, box: "Bee Swarm Simulator Ascended") is None
    assert join.top_result_is_bss(frame, ocr=lambda f, box: "Build A Bee Empire Sponsored") is None
