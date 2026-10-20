"""The quest rows (gui/panels/quests): "all done" only when the count
reaches the target, and an ETA from a near-zero rate is capped, not printed
as "104166d" (UI render pass 2026-10-21)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from hivemind.gui.panels.quests import QuestsPanel  # noqa: E402
from hivemind.telemetry.events import QuestStep  # noqa: E402

APP = QApplication.instance() or QApplication([])
BIG = 999_999_999_999


def test_one_short_of_the_target_is_not_done_and_a_huge_eta_is_capped():
    panel = QuestsPanel()
    panel.update_quest(QuestStep(giver="Bear", step="Collect", done=BIG - 1, total=BIG,
                                 eta_s=9e9))
    row = next(iter(panel._rows.values()))
    assert not row.complete and panel._badge.text() == "1 left"
    assert row._eta.text() == "over a week"
    panel.update_quest(QuestStep(giver="Bear", step="Collect", done=BIG, total=BIG, eta_s=90))
    assert row.complete and panel._badge.text() == "all done"
    assert row._eta.text() and "week" not in row._eta.text()


def test_an_empty_panel_is_illustrated_and_says_why():
    from hivemind.gui.panels.sentinel import SentinelPanel
    from hivemind.gui.widgets import EmptyState
    quests, sentinel = QuestsPanel(), SentinelPanel()
    assert isinstance(quests._empty, EmptyState) and quests._empty.title.text() == "No quests yet"
    sentinel.explain("the buff bar is not read yet")
    assert sentinel._empty.line.text() == "the buff bar is not read yet"
    quests.update_quest(QuestStep(giver="Bear", step="Collect", done=1, total=2))
    assert quests._empty is None                      # gone once there is a row
