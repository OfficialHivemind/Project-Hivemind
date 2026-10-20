"""ROADMAP U17b, compare by config, on CLEARLY FAKE data: the setup fingerprint
each trip is tagged with is stable and holds no secret, Stats > Compare groups
the trips by it (the old untagged ones as one group, never guessed), and two
setups get the benchmark's own 95% verdict -- or "too few trips"."""
from __future__ import annotations

import json
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from hivemind.gui.panels import graphs  # noqa: E402
from hivemind.world import settings as st  # noqa: E402
from test_graphs import fake_var  # noqa: E402

APP = QApplication.instance() or QApplication([])
MACRO = {**st.defaults(), "mode.macro": True,
         "macro.fields": [{"field": "Pine Tree", "convert_at": 100}, {"field": "Rose"}],
         "boost.keeper": True, "boost.boosters": True, "boost.glitter": True,
         "boost.item_buffs": True, "boost.dice": False, "boost.ai": "act"}   # U15b: off as shipped


def test_the_fingerprint_is_stable_small_and_has_no_secret(tmp_path):
    fp = st.config_fingerprint(MACRO)
    assert fp["mode"] == "macro" and [e["field"] for e in fp["fields"]] == ["Pine Tree", "Rose"]
    assert fp["boosts"] == ["boosters", "glitter", "item_buffs", "ai"]
    assert st.config_id(fp) == st.config_id(json.loads(json.dumps(fp)))   # same setup, same id
    assert st.config_id(fp) == st.config_id({**fp, "preset": "renamed"})
    assert st.config_id(fp) != st.config_id(st.config_fingerprint({**MACRO, "boost.keeper": False}))
    ai = st.config_fingerprint({**st.defaults(), "stream.youtube_api_key": "SECRET-FAKE"})
    # convert_at's default is 95 since the pro tester, round 1 (19 Oct 2026)
    assert ai == {"mode": "ai", "field": "auto", "convert_at": 95, "boosts": []}
    # a Settings file, and a saved preset with this setup names it
    cfg = tmp_path / "settings.yaml"
    cfg.write_text("gather.auto_field: false\ngather.field: Rose\ngather.convert_at: 80\n")
    (tmp_path / "presets").mkdir()
    (tmp_path / "presets" / "Rose run.yaml").write_text(cfg.read_text())
    (tmp_path / "presets" / "Other.yaml").write_text("gather.convert_at: 50\n")
    tag = st.trip_config(st.Settings(cfg))
    assert tag["config"]["preset"] == "Rose run" and tag["config"]["field"] == "Rose"
    assert "SECRET" not in json.dumps(tag)


def tagged_var(tmp_path, now):
    """fake_var's 3 days: the last day under the macro setup, the day before
    under AI mode, the first day untagged (before tagging)."""
    var = fake_var(tmp_path / "var", now)
    macro, ai = st.trip_config(MACRO), st.trip_config(st.defaults())
    rows = [json.loads(line) for line in (var / "trips.jsonl").read_text().splitlines()]
    for r in rows:
        if r["at"] > now - 86400:
            r.update(macro)
        elif r["at"] > now - 2 * 86400:
            r.update(ai)
    (var / "trips.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    return var, macro["config_id"], ai["config_id"]


def test_setups_group_the_trips_and_get_the_verdict(tmp_path):
    now = time.time()
    var, macro, ai = tagged_var(tmp_path, now)
    data = graphs.load(var, now, work=tmp_path / "nowork")
    groups = graphs.setups(data)
    assert [g[1] for g in groups][-1] == graphs.UNTAGGED          # untagged last
    assert groups[-1][0].startswith("Untagged (before ")
    names = {cid: name for name, cid, _ in groups}
    # Rose's entry takes MACRO_ENTRY's convert_at, 95 since the pro tester's round 1
    assert names[macro] == "Macro: Pine Tree, Rose · convert at 95/100% · boosts"
    assert names[ai] == "AI: auto field · convert at 95%"
    assert sum(n for *_, n in groups) == len(data["trips"])
    c = graphs.compare_setups(data, ai, macro)
    assert c["verdict"]["honey_per_hour"]["verdict"] == "better"   # the fake +30%
    assert c["a"]["summary"]["running_hours"] is None              # not a setup's own
    few = dict(data, units=[u for u in data["units"] if u["config"] != macro]
               + [u for u in data["units"] if u["config"] == macro][:5])
    assert graphs.compare_setups(few, ai, macro)["verdict"]["verdict"] == "too few trips"


def test_the_setups_page_and_the_share_card(tmp_path):
    now = time.time()
    var, macro, ai = tagged_var(tmp_path, now)
    ui = graphs.StatsGraphs(var=var, work=tmp_path / "nowork")
    ui._spawn = lambda job: job()
    ui.refresh()
    ui.set_mode("setups")
    assert ui.side_b.currentText().startswith("Macro: Pine Tree")   # the newest trip's
    assert ui.side_a.currentText().startswith("AI: auto field")
    texts = ui.table_texts()
    assert "better" in texts and not ui.share_button.isHidden()
    assert "Each setup's trips" in ui.compare_note.text()
    ui.side_a.setCurrentIndex(len(ui.setup_list) - 1)                # the untagged ones
    assert "setup is unknown" in ui.compare_note.text()
    assert not ui.share_menu.actions()[0].isEnabled()
    ui.set_mode("periods")
    assert ui.side_a.currentText() in [p[0] for p in ui.periods]
    out = tmp_path / "card.png"
    w = graphs.compare_setups(ui.data, ai, macro)["b"]
    assert graphs.share_card(ui.data["configs"][macro], w["summary"], out)
    assert out.stat().st_size > 5000
