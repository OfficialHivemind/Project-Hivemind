"""U4: Simple mode's mini-map lights the field the bot's compass names (and
nothing when it does not know), and the honey/hour tile draws its live line.
Offscreen; the fields come from the package's data/world/fields.yaml."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from hivemind.gui.panels.minimap import MiniMap, field_from_where, load_zones  # noqa: E402
from hivemind.telemetry.events import Metric, Thought  # noqa: E402

APP = QApplication.instance() or QApplication([])


def test_zones_read_summit_first_with_every_field():
    zones = load_zones()
    names = [z for z, _ in zones]
    assert names[0] == "Summit" and names[-1] == "Around the Hive"
    assert any(f == "Pine Tree" for _, fields in zones for f, _ in fields)


def test_where_text_names_the_field_or_nothing():
    assert field_from_where("I am in the pine tree field, 4s ago (feed)") == "pine tree"
    assert field_from_where("in the blue_flower field (landmark)") == "blue flower"
    assert field_from_where("I do not know where I am, 3 fixes so far") is None
    m = MiniMap()
    m.set_where("I am in the rose field, 1s ago (feed)")
    assert m.current == "rose"
    m.set_where("I do not know where I am")
    assert m.current is None
    m.resize(440, m.height())
    m.grab()                                   # paints without raising


def test_simple_page_feeds_the_map_and_the_rate_line(tmp_path):
    from hivemind.gui.simple import SimplePage
    page = SimplePage(var_root=tmp_path)
    page.handle(Thought(topic="where", text="I am in the pine tree field, 2s ago (feed)"))
    assert page.minimap.current == "pine tree"
    for value in (100.0, 100.0, 250.0):
        page.handle(Metric(name="honey_per_hour", value=value))
    assert list(page.rate_spark._values) == [100.0, 250.0]   # repeats are not new points
