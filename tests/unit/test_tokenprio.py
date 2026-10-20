"""ROADMAP T2 custom token priorities: the setting's checks
(world/settings.token_priority), the bot side (vision/tokens Kinds.use_own,
brain/tokenbrain own_of / off_of) and the Settings > Token priority table
(gui/panels/tokenprio), offscreen."""
from __future__ import annotations

import os
from types import SimpleNamespace as S

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from hivemind.brain import tokenbrain  # noqa: E402
from hivemind.brain.tokenbrain import TokenBrain  # noqa: E402
from hivemind.datapaths import data  # noqa: E402
from hivemind.gui.panels import tokenprio  # noqa: E402
from hivemind.vision import tokens  # noqa: E402
from hivemind.world import settings as schema  # noqa: E402

APP = QApplication.instance() or QApplication([])
ROWS = tokenprio._table_file()


def row(kind="honey", weight=10, hive="blue", off=False):
    return {"hive": hive, "kind": kind, "weight": weight, "off": off}


# ---- the setting ---------------------------------------------------------------
def test_default_is_no_rows_and_bad_rows_are_dropped_and_said():
    assert schema.defaults()["gather.token_priority"] == []
    got, why = schema.token_priority([
        row(), {"hive": "blue", "kind": "haste", "weight": 90},     # off defaults False
        row(hive="green"), row(kind="Haste!"), row(weight=-1), row(weight=True),
        row(weight=1001), row(off="yes"), {**row(), "colour": 1}, "honey",
        row(weight=20)])                                            # replaces the first
    assert got == [row(weight=20), row("haste", 90)]
    assert len(why) == 8 and all("left out" in w for w in why)
    assert schema.token_priority({"blue": {}})[0] == []


# ---- the bot side --------------------------------------------------------------
def kinds(rows=(), hive="blue"):
    k = tokens.Kinds(ROWS, hive=hive)
    k.use_own(list(rows))
    return k


def test_kinds_take_only_this_hives_rows_and_a_quest_still_wins():
    k = kinds([row("haste", 200), row("honey", 5, off=True), row("haste", 1, hive="red")])
    assert k.own_weight("haste") == 200.0 and k.is_off("honey")
    assert k.own_weight("focus") is None and not k.is_off("focus")
    assert "YOUR token table for the blue hive" in k.describe()
    k.want(["honey", "haste"])
    # a quest's kinds still go first: above the table's top weight (200 > 100)
    assert k.own_weight("haste") == k.own_weight("honey") == 201.0 and not k.is_off("honey")
    k = kinds([row("haste", 40)])
    k.want(["honey"])
    assert k.own_weight("honey") == tokens.QUEST_WEIGHT == tokenbrain.WEIGHT_BY_PRIORITY[tokens.QUEST_PRIORITY]
    assert kinds().own_weight("haste") is None


def test_a_quest_kind_beats_a_table_weight_above_the_quest_rank():
    k = kinds([row("haste", 900), row("honey", 5)])
    k.want(["honey"])
    seen = [track(1, "honey", 1100), track(2, "haste", 1100)]
    d = brain(k).decide(seen, (960, 500), (960, 500), 10.0)
    assert d.target.kind == "honey"


def test_the_nearest_pick_skips_off_kinds_and_follows_the_table():
    k = kinds()
    near = S(x=980, y=680, confidence=0.9, kind="haste")
    far = S(x=1500, y=680, confidence=0.9, kind="honey")
    k.classify = lambda s: s.kind
    assert tokens.nearest([near, far], 1920, 1080, prefer=k) is near    # haste ranks first
    k.use_own([row("honey", 90), row("haste", 50)])
    assert tokens.nearest([near, far], 1920, 1080, prefer=k) is far     # the table's order
    k.use_own([row("honey", 90, off=True), row("haste", 50, off=True)])
    assert tokens.nearest([near, far], 1920, 1080, prefer=k) is None    # Off: never walked to


def track(id, kind, x, y=500):
    return S(id=id, kind=kind, x=x, y=y, matches=3, unseen_for=lambda now: 0.0,
             age=lambda now: 0.5)


def brain(k):
    return TokenBrain(priority_of=k.priority, life_of=k.life_s, weight_of=k.weight,
                      preempt_of=k.preempt_px, own_of=k.own_weight, off_of=k.is_off)


def test_no_rows_decide_exactly_as_before_and_rows_change_the_pick():
    seen = [track(1, "honey", 1100), track(2, "haste", 1400), track(3, "unknown", 700)]
    old = TokenBrain(priority_of=kinds().priority, life_of=kinds().life_s,
                     weight_of=kinds().weight, preempt_of=kinds().preempt_px)
    a = old.decide(seen, (960, 500), (960, 500), 10.0)
    b = brain(kinds()).decide(seen, (960, 500), (960, 500), 10.0)
    assert [(c.track_id, c.score) for c in a.ranked] == [(c.track_id, c.score) for c in b.ranked]
    mine = brain(kinds([row("haste", 400), row("unknown", 0, off=True)]))
    d = mine.decide(seen, (960, 500), (960, 500), 10.0)
    assert d.action == "chase" and d.target.kind == "haste"
    assert d.target.trace["base"] == 400.0
    gated = next(c for c in d.ranked if c.kind == "unknown")
    assert gated.gated == "turned off in your token priorities" and gated.score == 0.0


# ---- the table -----------------------------------------------------------------
def test_the_table_starts_from_the_bots_own_numbers_and_the_hive_seeds():
    table = {e["kind"]: e for e in tokenprio.entries(ROWS, ["item_treat"], [], "blue")}
    k = kinds()
    plain = TokenBrain(priority_of=k.priority, weight_of=k.weight)
    for kind, e in table.items():
        assert e["weight"] == round(plain.base_for(kind)) and not e["off"]
    assert {"unknown", "item_treat", "tabby_love"} <= set(table)
    # the blue seeds (tokens.yaml, assumed): honey's weight_by_hive 0, token
    # link's priority_by_hive 3 through the ordering
    assert table["honey"]["suggested"] == 0 and table["honey"]["seeded"]
    assert table["token_link"]["suggested"] > table["token_link"]["builtin"]
    assert not table["tabby_love"]["seeded"]
    assert not any(e["seeded"] for e in tokenprio.entries(ROWS, [], [], "red"))


def test_the_panel_saves_moves_resets_and_never_touches_the_other_hive():
    saved = []
    other = row("honey", 7, hive="red")
    p = tokenprio.TokenPriority({"progression.hive": "blue",
                                 "gather.token_priority": [other]},
                                lambda k, v: saved.append((k, v)))
    assert p.current_hive() == "blue" and not p.is_custom()
    assert p.table.rowCount() == len(p.shown) >= len(ROWS)
    second = p.shown[1]["kind"]
    p.move(-1, second)                                   # up one place
    key, value = saved[-1]
    assert key == "gather.token_priority" and other in value
    assert p.shown[0]["kind"] == second and p.is_custom()
    assert len([r for r in value if r["hive"] == "blue"]) == len(p.shown)
    p.use_suggestions()
    assert {e["kind"]: e["weight"] for e in p.shown}["honey"] == 0
    # Off ticked in the table: saved after the edit returns
    n = next(i for i, e in enumerate(p.shown) if e["kind"] == "haste")
    p.table.item(n, 2).setCheckState(Qt.Checked)
    APP.processEvents()
    assert any(r["kind"] == "haste" and r["off"] for r in saved[-1][1])
    p.reset_hive()
    assert saved[-1][1] == [other] and not p.is_custom()
    p.show_rows([row("haste", 999)])
    assert p.shown[0]["kind"] == "haste" and p.is_custom()


def test_every_wiki_icon_named_in_the_table_exists():
    for kind, r in ROWS.items():
        if r.get("icon"):
            assert data("knowledge", "tokens", "wiki", r["icon"]).exists(), kind
