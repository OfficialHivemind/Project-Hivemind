"""DECIDED, NOT ASKED. The owner, 2026-10-26: the bot asked far too
many questions. What the bot can tell from its own evidence
it decides, says (log + Telegram) and offers one Undo; nothing is asked."""
import importlib.util
import json
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import hivemind  # noqa: E402
from hivemind.brain import goals as goals_plan  # noqa: E402
from hivemind.brain import owned as owned_mod  # noqa: E402
from hivemind.telemetry.events import GOT_IT, UNDO, Option, Question  # noqa: E402

NOW = 10_000.0


def judge(tmp_path, amount, plan=None):
    buyer = owned_mod.Purchases(tmp_path, clock=lambda: NOW)
    fall = owned_mod.Fall(before_at=1000.0, before=900_000_000, after_at=2000.0,
                          after=900_000_000 - amount)
    with owned_mod._locked(tmp_path) as state:
        return buyer._judge(state, fall, plan, None)


def plan_of(*keys):
    return goals_plan.Plan(rows=[goals_plan.Row(key=k, label=k, cost=1) for k in keys])


def questions(events):
    return [e for e in events if isinstance(e, Question)]


def test_an_exact_fall_is_decided_with_an_undo_card(tmp_path):
    line = judge(tmp_path, 75_000_000)
    assert line.startswith("decided: the Honeycomb Belt counts as yours (inferred)")
    assert "/undo" in line
    body = owned_mod.load_state(tmp_path)["items"]["honeycomb_belt"]
    assert (body["state"], body["label"], body["decided_at"]) == (
        owned_mod.INFERRED, "Honeycomb Belt", NOW)
    events = []
    owned_mod.Purchases(tmp_path, emit=events.append, clock=lambda: NOW).cards()
    [card] = questions(events)
    assert card.decided and card.question == "Counted the Honeycomb Belt as bought"
    assert [o.label for o in card.options] == [GOT_IT, UNDO]
    assert card.expires_at == NOW + owned_mod.DECIDED_SHOW_S
    # a day later it is not sent again, and comes down
    events.clear()
    late = NOW + owned_mod.DECIDED_SHOW_S + 1
    owned_mod.Purchases(tmp_path, emit=events.append, clock=lambda: late).cards()
    assert not questions(events) and [e.value for e in events] == ["withdrawn"]


def test_undo_takes_it_back_and_got_it_keeps_it(tmp_path):
    judge(tmp_path, 75_000_000)
    assert owned_mod.record_answer(tmp_path, "owned:honeycomb_belt", UNDO) is None
    assert owned_mod.load_state(tmp_path)["items"]["honeycomb_belt"]["state"] == owned_mod.REJECTED
    assert "honeycomb_belt" not in owned_mod.owned("", tmp_path)
    assert owned_mod.card_key("owned:honeycomb_belt", GOT_IT) == "honeycomb_belt"


def test_an_undone_item_is_not_decided_again(tmp_path):
    judge(tmp_path, 75_000_000)
    owned_mod.record_answer(tmp_path, "owned:honeycomb_belt", UNDO)
    buyer = owned_mod.Purchases(tmp_path, clock=lambda: NOW)
    fall = owned_mod.Fall(before_at=5000.0, before=800_000_000, after_at=6000.0,
                          after=725_000_000)
    with owned_mod._locked(tmp_path) as state:
        line = buyer._judge(state, fall, None, None)
    assert "you undid the Honeycomb Belt before, so it counts as no gear" in line
    assert owned_mod.load_state(tmp_path)["items"]["honeycomb_belt"]["state"] == owned_mod.REJECTED


def test_the_bots_own_memory_match_game_is_no_purchase(tmp_path):
    # MEASURED 13 Oct 04:22 (run-946) and 16 Oct 11:42 (run-1031): Mega games
    # "inferred" as a Parachute and a Belt Bag; the owner said No each time
    (tmp_path / "memorymatch.json").write_text(json.dumps({"tries": [
        {"at": 1500.0, "kind": "mega", "result": "played", "pressed": True},
        {"at": 1600.0, "kind": "normal", "result": "walk", "pressed": False}]}))
    line = judge(tmp_path, 424_642)
    assert "the bot's own purchase of the mega Memory Match game" in line
    assert "belt_bag" not in owned_mod.load_state(tmp_path).get("items", {})
    assert "bot's own" not in judge(tmp_path / "x", 424_642)   # no game: the Belt Bag


def test_a_tie_with_one_on_the_goal_list_is_that_one(tmp_path):
    # 100,000,000: the Honey, Bubble and Fire Mask alike; a blue plan wants one
    line = judge(tmp_path, 100_000_000, plan_of("bubble_mask", "glider"))
    assert line.startswith("decided: the Bubble Mask counts as yours")
    assert "the only one of them on your goal list" in line


def test_a_fall_nothing_explains_is_said_and_checked_never_asked(tmp_path):
    line = judge(tmp_path, 100_000_000)                      # a tie, none wanted
    assert line.startswith("decided: counted as no gear")
    assert "shop windows" in line and "?" not in line.split("—")[0]
    drop = owned_mod.load_state(tmp_path)["drops"][0]
    assert drop["asked"] and not drop.get("answered")       # open: the shop look checks it
    events = []
    owned_mod.Purchases(tmp_path, emit=events.append, clock=lambda: NOW).cards()
    assert not questions(events)
    assert [(e.name, e.value) for e in events] == [(f"drop:{drop['id']}", "withdrawn")]


def test_a_ready_goal_is_said_not_asked(tmp_path):
    said, events = [], []
    watch = goals_plan.Watch(tmp_path, emit=events.append, say=said.append,
                             clock=lambda: NOW)
    row = goals_plan.Row(key="parachute", label="Parachute", shop_label="Noob Shop",
                         cost=500_000, state=goals_plan.READY)
    plan = goals_plan.Plan(rows=[row], honey=1_000_000)
    for _ in range(goals_plan.ASK_AFTER_READINGS + 2):
        watch._judge(plan)
    assert not questions(events)
    assert len(said) == 1 and said[0].startswith("goals: Ready to buy the Parachute")
    # still open, so brain/sight's shop look checks it
    assert "parachute" in json.loads((tmp_path / "goals.json").read_text())["asked"]


def test_a_slot_no_window_showed_is_decided_once_ever(tmp_path):
    from hivemind.brain import progression as prog
    card = Question(id="progression:slot:boots", question="Which boots do you wear?",
                    default=prog.NONE_YET,
                    options=[Option("Beekeeper's Boots", 1.0), Option(prog.NONE_YET, 0.0)])
    plan = goals_plan.Plan(progress=prog.Progress(questions=[card]))
    said, events = [], []
    goals_plan.Watch(tmp_path, emit=events.append, say=said.append)._progression_cards(plan)
    assert not events
    assert said == ["progression: decided: no shop window showed your boots yet, so the "
                    "plan assumes none of the Beekeeper's Boots yet (nothing is bought on "
                    "it); the bot looks at their shop windows on its next visits. Have one? "
                    "Add it in Settings > Goals > Gear you already own"]
    # the next process says nothing, and takes down a card an older version sent
    said.clear()
    goals_plan.Watch(tmp_path, emit=events.append, say=said.append)._progression_cards(plan)
    assert not said and [(e.name, e.value) for e in events] == [
        ("progression:slot:boots", "withdrawn")]


def test_a_decided_card_does_not_wait_for_him():
    import time
    from PySide6.QtWidgets import QApplication
    from hivemind.gui.panels.question import DecisionInbox
    QApplication.instance() or QApplication([])
    inbox = DecisionInbox()
    inbox.add(Question(id="owned:glider", question="Counted the Glider as bought",
                       decided=True, default=GOT_IT, expires_at=time.time() + 3600,
                       options=[Option(GOT_IT, 5e6, unit="honey"), Option(UNDO, 0.0, unit="honey")]))
    card = inbox._cards["owned:glider"]
    assert inbox.pending == 0 and not inbox.isHidden()
    assert [b.text() for b in card._buttons] == [GOT_IT, UNDO]
    assert card.toggle.text().startswith("Details") and card._countdown.text() == ""
    card.question.expires_at = time.time() - 1
    card._tick()
    assert card.isHidden()


def test_telegram_undo_sends_the_newest_decision(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location(
        "telegram_alerts_undo",
        Path(hivemind.__file__).resolve().parents[2] / "scripts" / "telegram_alerts.py")
    tg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tg)
    sent = []
    monkeypatch.setattr(tg, "bot_socket", lambda command=None, read_s=0.0:
                        sent.append(command) or [])
    assert tg.undo_last(tmp_path).startswith("Nothing to undo")
    (tmp_path / "owned.json").write_text(json.dumps({"items": {
        "glider": {"state": "inferred", "decided_at": 5.0, "label": "Glider"},
        "scythe": {"state": "inferred", "decided_at": 9.0, "label": "Scythe"},
        "spark_staff": {"state": "rejected", "decided_at": 99.0}}}))
    assert tg.undo_last(tmp_path).startswith("Undone: the Scythe")
    assert (sent[0].kind, sent[0].id, sent[0].choice) == ("answer", "owned:scythe", UNDO)
    monkeypatch.setattr(tg, "bot_socket", lambda command=None, read_s=0.0: None)
    assert "not running" in tg.undo_last(tmp_path)
    assert "undo" in tg.COMMANDS and "/undo" in tg.HELP
