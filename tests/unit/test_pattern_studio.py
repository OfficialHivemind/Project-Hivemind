"""T17 the Pattern Studio page, offscreen, against a temporary folder."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from hivemind.gui.panels.patterns import PatternStudio, trace  # noqa: E402
from hivemind.world import userpatterns as up  # noqa: E402

APP = QApplication.instance() or QApplication([])


@pytest.fixture
def page(tmp_path):
    p = PatternStudio(tmp_path)
    p.resize(1100, 640)
    yield p
    p.close()
    p.deleteLater()


def test_it_lists_builtins_read_only_and_starts_on_a_valid_blank(page, tmp_path):
    texts = [page.list.item(i).text() for i in range(page.list.count())]
    assert "Snake, wide" in texts and any(t.startswith("Classic ") for t in texts)
    page.list.setCurrentRow(texts.index("Snake, wide"))
    assert page.read_only and not page.add_move.isEnabled()
    assert page.save_button.text() == "Save a copy"
    assert page.share_code().startswith("HMP1:")          # a built-in can be shared


def test_edit_add_group_reorder_and_live_validation(page):
    page.new()
    assert page.check().ok
    n = len(page.current["steps"])
    page.steps.clearSelection()
    page.key.setCurrentIndex(page.key.findData("wd"))
    page.studs.setValue(12)
    page.add_move.click()
    assert page.current["steps"][-1] == {"move": "wd", "studs": 12.0}
    page.turn_left.click()
    assert "must cancel" in page.verdict.text() and not page.save_button.isEnabled()
    page.turn_right.click()
    assert page.check().ok and page.save_button.isEnabled()
    # group the first two into a repeat, then ungroup it again
    page.steps.clearSelection()
    for i in (0, 1):
        page.steps.item(i).setSelected(True)
    page.times.setValue(4)
    page.repeat_button.click()
    assert page.current["steps"][0]["repeat"] == 4 and len(page.current["steps"]) == n + 2
    page.times.setValue(5)                                  # edits the picked repeat
    assert page.current["steps"][0]["repeat"] == 5
    page.ungroup_button.click()
    assert len(page.current["steps"]) == n + 3
    # reorder and remove
    first = page.current["steps"][0]
    page.steps.clearSelection()
    page.steps.item(0).setSelected(True)
    page.down_button.click()
    assert page.current["steps"][1] == first
    page.remove_button.click()
    assert first not in page.current["steps"][:2]
    # editing a picked move in place
    page.steps.clearSelection()
    page.steps.item(0).setSelected(True)
    if "move" in page.current["steps"][0]:
        page.studs.setValue(33)
        assert page.current["steps"][0]["studs"] == 33


def test_save_lists_it_and_tells_the_macro_list(page, tmp_path):
    told = []
    page.saved.connect(lambda: told.append(1))
    page.new()
    page.name.setText("Big square")
    page.name.textEdited.emit("Big square")
    assert page.save()
    assert (tmp_path / "big_square.json").exists() and told
    assert page.list.currentItem().text() == "Big square"
    assert not page.read_only and page.delete_button.isEnabled()
    page.delete()
    assert not (tmp_path / "big_square.json").exists() and len(told) == 2


def test_a_builtin_saved_as_a_copy(page, tmp_path):
    texts = [page.list.item(i).text() for i in range(page.list.count())]
    page.list.setCurrentRow(texts.index("Square, small"))
    assert page.save()
    assert (tmp_path / "square_small_copy.json").exists()


def test_import_previews_and_checks_before_saving(page, tmp_path):
    good = up.encode({"name": "From discord", "author": "a community member",
                      "steps": [{"move": "a", "studs": 30}, {"move": "d", "studs": 30}]})
    dialog = page.open_import()
    dialog.code.setPlainText("HMP1:garbage.00000000")
    assert not dialog.save_button.isEnabled() and "invalid" in dialog.verdict.text().lower()
    dialog.code.setPlainText(good)
    assert dialog.save_button.isEnabled() and "From discord" in dialog.verdict.text()
    assert dialog.preview.pattern["name"] == "From discord"
    assert not (tmp_path / "from_discord.json").exists()     # nothing saved yet
    dialog.save_button.click()
    assert (tmp_path / "from_discord.json").exists()
    assert page.list.currentItem().text() == "From discord"


def test_import_never_overwrites_one_of_yours(page, tmp_path):
    up.save({"name": "Zig", "steps": [{"move": "w", "studs": 5}]}, tmp_path)
    page.reload()
    other = {"name": "Zig", "steps": [{"move": "s", "studs": 9}]}
    page._imported(up.validate(other).pattern)
    assert sorted(p.name for p in tmp_path.glob("*.json")) == ["zig.json", "zig_imported.json"]


def test_the_trace_follows_keys_and_camera_turns():
    pts = trace({"size": 2.0, "steps": [{"move": "w", "studs": 10}, {"move": "d", "studs": 5}]})
    assert pts == [(0, 0), (0, -20), (10, -20)]
    turned = trace({"size": 1.0, "steps": [{"turn": "right"}, {"turn": "right"},
                                           {"move": "w", "studs": 10}]})
    assert turned[-1][0] == pytest.approx(10) and turned[-1][1] == pytest.approx(0)


def test_record_is_a_stub_that_says_so(page):
    assert not page.record_button.isEnabled() and page.record_button.isHidden()
    assert "coming" in page.record_button.toolTip()


def test_it_paints_offscreen(page):
    page.show()
    QApplication.processEvents()
    assert not page.grab().isNull()
