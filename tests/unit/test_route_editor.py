"""ROADMAP G10, the editor (gui/panels/route.RouteEditor): put goals first,
skip some, add your own, name the route, Save / Import / Export. Offscreen Qt;
every route file goes to tmp_path (HIVEMIND_CONFIG)."""
from __future__ import annotations

import os

import pytest
import yaml

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6.QtWidgets")
from PySide6.QtWidgets import QApplication  # noqa: E402

from hivemind.brain import progression as prog  # noqa: E402
from hivemind.world.settings import Settings  # noqa: E402


@pytest.fixture
def editor(tmp_path, monkeypatch):
    monkeypatch.setenv("HIVEMIND_CONFIG", str(tmp_path / "config"))
    from hivemind.gui.panels.route import RouteEditor
    QApplication.instance() or QApplication([])
    values = {"progression.hive": "blue", "progression.plan": ""}
    saved = []

    def save(name):
        saved.append(name)
        values["progression.plan"] = name
    ed = RouteEditor(values, save=save)
    ed.saved = saved
    yield ed
    ed.close()


def _shown(ed, stage: int) -> list:
    head = ed.tree.topLevelItem(stage)
    return [head.child(k).text(0) for k in range(head.childCount())]


def test_shows_the_base_route_by_stage_and_nothing_is_written(editor, tmp_path):
    blue = prog.load("blue")
    assert editor.tree.topLevelItemCount() == len(blue["stages"])
    assert editor.tree.topLevelItem(0).childCount() == len(blue["stages"][0]["goals"])
    assert not (tmp_path / "config").exists()
    assert editor.new_stage.count() == len(blue["stages"])
    assert editor.name.property("read_on_click") and editor.new_stage.property("read_on_click")


def test_first_skip_and_your_own_goal_make_the_route(editor):
    editor.put_first("tool_ladder_early")
    editor.put_first("black_bear_egg_chains")
    editor.toggle_skip("basic_eggs_to_25")
    gid = editor.add_goal("30 bees on the alt", "mid")
    assert gid == "30_bees_on_the_alt"
    # a label that makes a goal's id again gets its own id
    assert editor.add_goal("25 Bees", "early") != "basic_eggs_to_25"
    editor.first_list.setCurrentRow(1)
    editor.move(-1)
    route = editor.route()
    assert route["base"] == "blue"
    assert route["first"] == ["black_bear_egg_chains", "tool_ladder_early"]
    assert route["skip"] == ["basic_eggs_to_25"]
    assert {"id": gid, "label": "30 bees on the alt", "stage": "mid"} in route["add"]
    early = _shown(editor, 0)
    assert early[0].startswith("★ 1. ") and "Black Bear" in early[0]
    assert any("(skipped)" in t and "25 bees" in t for t in early)
    assert any("30 bees on the alt" in t and "(yours)" in t for t in _shown(editor, 1))
    # skipping a first goal takes it out of first; deleting your goal removes it
    editor.toggle_skip("tool_ladder_early")
    assert editor.first == ["black_bear_egg_chains"]
    editor.delete_goal(gid)
    assert gid not in [g["id"] for g in editor.route()["add"]]


def test_save_writes_the_file_and_picks_it(editor, tmp_path):
    assert editor.save() is False and editor.saved == []      # no name yet
    assert "name" in editor.note.text()
    editor.name.setText("My Blue Route")
    editor.put_first("tool_ladder_early")
    assert editor.save()
    assert editor.saved == ["My Blue Route"]
    path = tmp_path / "config" / "progression" / "my_blue_route.yaml"
    assert prog.load_route("My Blue Route") == {"name": "My Blue Route", "base": "blue",
                                                "first": ["tool_ladder_early"]}
    assert path.is_file() and editor.routes.currentData() == str(path)
    assert "follows your route" in editor.note.text()
    # the bot's plan follows it
    settings = tmp_path / "settings.yaml"
    settings.write_text(yaml.safe_dump({"progression.plan": "My Blue Route"}), encoding="utf-8")
    got = prog.progress(tmp_path, Settings(settings), n=1)
    assert got.next and got.next[0].id == "tool_ladder_early"
    # a new route, then the saved one opened again
    editor.open_route("")
    assert editor.route()["first"] == [] and editor.name.text() == ""
    editor.open_route(path)
    assert editor.first == ["tool_ladder_early"]
    editor.use_researched()
    assert editor.saved[-1] == ""


def test_import_copies_a_shared_route_in_and_export_saves_a_copy(editor, tmp_path):
    shared = tmp_path / "shared.yaml"
    shared.write_text(yaml.safe_dump({"name": "Red rush", "base": "red", "first": ["no_such_goal"],
                                      "skip": [], "add": [{"id": "x", "label": "X"}],
                                      "junk": {"not": "kept"}}), encoding="utf-8")
    assert editor.import_file(shared) == "Red rush"
    assert editor.base == "red" and editor.name.text() == "Red rush"
    copied = prog.load_route("Red rush")
    assert "junk" not in copied and copied["base"] == "red"
    # customise's notes are shown
    assert "no goal 'no_such_goal'" in editor.note.text()
    assert editor.saved == []                                # not used until Save
    # the same name again is not written over
    assert editor.import_file(shared) == "Red rush 2"
    out = tmp_path / "out" / "copy.yaml"
    out.parent.mkdir()
    assert editor.export_file(out)
    assert yaml.safe_load(out.read_text(encoding="utf-8"))["name"] == "Red rush 2"


def test_a_file_that_is_not_a_route_is_said_and_nothing_copied(editor, tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("just: words\n", encoding="utf-8")
    assert editor.import_file(bad) == ""
    assert "not a route file" in editor.note.text()
    broken = tmp_path / "broken.yaml"
    broken.write_text("first: [unclosed\n", encoding="utf-8")
    assert editor.import_file(broken) == ""
    assert not (tmp_path / "config" / "progression").exists()


def _write(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(body) if isinstance(body, dict) else body, encoding="utf-8")


def test_a_goal_priority_that_is_not_a_number_never_stops_the_window(editor, tmp_path,
                                                                     monkeypatch):
    """Review 2026-10-26: `priority: high` raised in refresh's sort -- import
    left the tree half-built, and once picked the window would not start."""
    shared = tmp_path / "shared.yaml"
    _write(shared, {"name": "Prio", "base": "blue",
                    "add": [{"id": "zz", "label": "ZZ", "stage": "early", "priority": "high"},
                            {"id": "yy", "label": "YY", "stage": "early", "priority": True}]})
    assert editor.import_file(shared) == "Prio"
    assert any("ZZ" in t for t in _shown(editor, 0))
    assert all("priority" not in g for g in editor.route()["add"])
    assert editor.save()
    # a hand-written file that still has one: the window is built all the same
    _write(prog.route_path("Prio"), {"name": "Prio", "base": "blue",
                                     "add": [{"id": "zz", "label": "ZZ", "priority": "high"}]})
    from hivemind.gui.panels.route import RouteEditor
    again = RouteEditor({"progression.hive": "blue", "progression.plan": "Prio"})
    assert again.name.text() == "Prio" and again.tree.topLevelItemCount() > 0
    # and a file that breaks the page some other way only gives a note
    real = prog.customise
    monkeypatch.setattr(prog, "customise",
                        lambda data, route: 1 / 0 if route.get("add") else real(data, route))
    broken = RouteEditor({"progression.hive": "blue", "progression.plan": "Prio"})
    assert "could not be shown" in broken.note.text() and broken.opened is None
    again.close()
    broken.close()


def test_save_asks_before_replacing_another_saved_route(editor):
    """Review 2026-10-26: 'alpha' is the same file as 'Alpha'."""
    asked = []
    editor.confirm = lambda title, text: asked.append(text) or False
    editor.name.setText("Alpha")
    editor.put_first("tool_ladder_early")
    assert editor.save() and asked == []
    editor.put_first("black_bear_egg_chains")
    assert editor.save() and asked == []             # the route opened: no question
    editor.open_route("")
    editor.name.setText("alpha")
    assert editor.save() is False and "Alpha" in asked[0]
    assert "Not saved" in editor.note.text()
    assert prog.load_route("Alpha")["first"] == ["tool_ladder_early", "black_bear_egg_chains"]
    editor.confirm = lambda title, text: True
    assert editor.save()
    assert "first" not in prog.load_route("Alpha")


def test_a_lone_id_or_true_is_not_read_letter_by_letter():
    from hivemind.gui.panels.route import clean_route
    got = clean_route({"first": "tool_ladder_early", "skip": [True, "basic_eggs_to_25", 7],
                       "add": "nope"})
    assert got["first"] == ["tool_ladder_early"]
    assert got["skip"] == ["basic_eggs_to_25", "7"] and got["add"] == []
    assert clean_route({"first": {"a": 1}, "skip": True})["first"] == []
    assert clean_route({"skip": True})["skip"] == []


def test_any_route_file_in_the_folder_opens_as_it_is_named(editor, tmp_path):
    folder = prog.route_path("x").parent
    _write(folder / "My Route.yaml", {"base": "blue", "first": ["tool_ladder_early"]})
    _write(folder / "short.yml", {"name": "Short one", "skip": ["basic_eggs_to_25"]})
    editor.fill_routes()
    names = [editor.routes.itemText(k) for k in range(editor.routes.count())]
    assert "My Route" in names and "Short one" in names
    editor.open_route(folder / "My Route.yaml")
    assert editor.first == ["tool_ladder_early"] and editor.name.text() == "My Route"
    assert "No route file" not in editor.note.text()
    editor.open_route(folder / "short.yml")
    assert editor.skip == ["basic_eggs_to_25"]
    editor.open_route(folder / "gone.yaml")
    assert "No route file gone.yaml" in editor.note.text() and editor.opened is None


def test_picking_another_route_asks_about_unsaved_changes(editor):
    editor.name.setText("Kept")
    assert editor.save()
    editor.put_first("tool_ladder_early")             # not saved
    answers = []
    editor.confirm = lambda title, text: answers.append(text) or False
    editor.routes.setCurrentIndex(0)                  # 'A new route'
    editor._route_picked()
    assert answers and editor.first == ["tool_ladder_early"]
    assert editor.routes.currentData() == str(prog.route_path("Kept"))
    editor.confirm = lambda title, text: True
    editor.routes.setCurrentIndex(0)
    editor._route_picked()
    assert editor.first == [] and editor.name.text() == ""
    # nothing changed: no question
    answers.clear()
    editor.confirm = lambda title, text: answers.append(text) or False
    editor.routes.setCurrentIndex(editor.routes.findData(str(prog.route_path("Kept"))))
    editor._route_picked()
    assert answers == [] and editor.name.text() == "Kept"
