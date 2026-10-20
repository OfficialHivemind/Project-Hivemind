"""V3: the stream overlay keeps up with new features.

Every Log source and Thought topic the bot emits has a stream category (or is
quiet on purpose), and every task the farm loop names has an overlay label --
so a new feature cannot reach the broadcast tagged FARM or as a raw task name.
"""
import ast
from pathlib import Path

import hivemind
from hivemind.stream import show

SRC = Path(hivemind.__file__).resolve().parent
FILES = sorted(SRC.rglob("*.py")) + [SRC.parents[1] / "scripts" / "run_farm.py"]


def _calls(name: str, keyword: str, files=FILES) -> dict[str, str]:
    """Constant `keyword=` values of every `name(...)` call, to a file using it."""
    found = {}
    for path in files:
        if not path.exists():
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            called = getattr(node.func, "id", getattr(node.func, "attr", ""))
            if called != name:
                continue
            for kw in node.keywords:
                if kw.arg == keyword and isinstance(kw.value, ast.Constant):
                    found.setdefault(kw.value.value, path.name)
    return found


def test_every_log_source_has_a_stream_category():
    known = set(show.SOURCE_CATEGORY) | show.QUIET_SOURCES
    missing = {s: f for s, f in _calls("Log", "source").items() if s not in known}
    assert not missing, f"add these to stream/show SOURCE_CATEGORY: {missing}"


def test_every_thought_topic_has_a_stream_category():
    known = set(show.TOPIC_CATEGORY) | show.QUIET_TOPICS
    missing = {t: f for t, f in _calls("Thought", "topic").items() if t not in known}
    assert not missing, f"add these to stream/show TOPIC_CATEGORY: {missing}"


def test_every_category_has_a_tag_on_the_overlay():
    from hivemind.gui.stream import CATEGORY
    used = set(show.SOURCE_CATEGORY.values()) | set(show.TOPIC_CATEGORY.values())
    assert used <= set(CATEGORY), used - set(CATEGORY)


def test_every_farm_task_has_an_overlay_label():
    from hivemind.gui.stream import ACTIVITY
    farm = [SRC / "brain" / "farm.py"]
    names = set(_calls("TaskUpdate", "name", farm))
    # the walking legs pass their task name as _leg's first argument
    for node in ast.walk(ast.parse(farm[0].read_text(encoding="utf-8"))):
        if (isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "_leg"
                and node.args and isinstance(node.args[0], ast.Constant)):
            names.add(node.args[0].value)
    assert {"gather", "convert", "return to the hive"} <= names
    assert names <= set(ACTIVITY), names - set(ACTIVITY)
