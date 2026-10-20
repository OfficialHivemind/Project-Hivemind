"""brain/sight: CHECK, DON'T ASK (ROADMAP G13). What a shop's window showed
owned answers the gear questions before they are asked."""
import json
import shutil
from pathlib import Path

import pytest
import yaml

import hivemind
from hivemind.act import shoplook
from hivemind.brain import goals as goals_plan
from hivemind.brain import owned as owned_mod
from hivemind.brain import progression as prog
from hivemind.brain import sight
from hivemind.world.settings import Settings

# found from the code under test, so the deploy gate's run from the live tree
# finds the frames beside it
FIX = Path(hivemind.__file__).resolve().parents[2] / "tests" / "fixtures" / "sight"


def look(at, *windows, shop="mountain_top_catalogue", frames=True):
    return {"at": at, "shop": shop, "window": "", "catalogue": list(windows),
            "kept": [f"/v/shoplook/x-mts-browse-{i:02d}.jpg" for i in range(len(windows))]
            if frames else []}


def test_the_buttons_seen_in_saved_windows():
    # every wording var/shoplook.json holds (2026-10-03 .. 10-15), and Owned
    assert sight.button_state("Edguipped") == (sight.OWNED, True)
    assert sight.button_state("Equipped") == (sight.OWNED, True)
    for owned in ("Edguip", "Eguiph", "Equip"):
        assert sight.button_state(owned) == (sight.OWNED, False), owned
    assert sight.button_state("Purchased") == (sight.OWNED, False)
    assert sight.button_state("Owned") == (sight.OWNED, False)
    for price in ("Buy for 60,000,000 Honey", "Can't afford", "Can't affded", "Can't gfford",
                  "Craft Item", "Purchase", "Buy for 1 Tikket"):
        assert sight.button_state(price)[0] == sight.NOT_OWNED, price
    assert sight.button_state("") == ("", False)
    assert sight.button_state("——")[0] == ""


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="no tesseract")
def test_reads_from_real_frames(tmp_path):
    import cv2
    frames = {name: cv2.imread(str(FIX / f"{name}.jpg"))
              for name in ("mts-boots-equipped", "mts-mask-equip", "mts-spark-staff-buy-for",
                           "tent-festive-purchased")}
    text = {k: shoplook.window_text(f) for k, f in frames.items()}
    entry = {"at": 1000.0, "shop": "mountain_top_catalogue", "window": "",
             "catalogue": [text["mts-boots-equipped"], text["mts-mask-equip"],
                           text["mts-spark-staff-buy-for"]],
             "kept": [str(FIX / f"{k}.jpg").replace(k, f"{k}-browse-{i:02d}")
                      for i, k in enumerate(("mts-boots-equipped", "mts-mask-equip",
                                             "mts-spark-staff-buy-for"))]}
    got = dict(sight.reads_of(entry, owned_mod.prices()))
    assert got["beekeepers_boots"]["state"] == sight.OWNED and got["beekeepers_boots"]["worn"]
    assert got["beekeepers_boots"]["frame"].endswith("mts-boots-equipped-browse-00.jpg")
    assert got["beekeepers_mask"]["state"] == sight.OWNED and not got["beekeepers_mask"]["worn"]
    assert got["spark_staff"]["state"] == sight.NOT_OWNED
    # "Purchased" reads owned; an egg is no gear of the price table, so not kept
    assert sight.button_state(text["tent-festive-purchased"].split("|")[2])[0] == sight.OWNED
    assert sight.reads_of({"window": text["tent-festive-purchased"]}, owned_mod.prices()) == []


def test_a_look_is_recorded_with_its_frame_and_only_by_its_own_name(tmp_path):
    got = shoplook.ShopLook(ok=True, catalogue=[
        "Beekeeper's Boots | 15.000.000 Honey | Edguipped",
        "Beekeeper Boot | 15.000.000 Honey | Edguipped",       # a clipped name: nobody's
        "Spark Staff | 60.000.000 Honey | Buy for 60,000,000 Honey"],
        kept=["/v/20261003-055044-window.png", "/v/a-mts-browse-00.jpg",
              "/v/a-mts-browse-01.jpg", "/v/a-mts-browse-02.jpg"])
    shoplook.record(tmp_path / "shoplook.json", got, shop="mountain_top_catalogue",
                    clock=lambda: 5000.0)
    body = json.loads((tmp_path / sight.SIGHT_FILE).read_text())
    assert set(body["items"]) == {"beekeepers_boots", "spark_staff"} and body["backfill"]
    boots = body["items"]["beekeepers_boots"][sight.OWNED]
    assert boots["at"] == 5000.0 and boots["frame"] == "/v/a-mts-browse-00.jpg" and boots["worn"]
    assert body["items"]["spark_staff"][sight.NOT_OWNED]["frame"] == "/v/a-mts-browse-02.jpg"
    line = sight.checked_line("Beekeeper's Boots", boots)
    assert line.startswith("checked: Beekeeper's Boots shows Equipped at the mountain top shop")
    assert "a-mts-browse-00.jpg" in line and line.endswith("-- not asking")
    # what they own, by sight
    assert owned_mod.owned("", tmp_path)["beekeepers_boots"].how == owned_mod.SEEN
    assert "spark_staff" not in owned_mod.owned("", tmp_path)


def test_looks_saved_before_the_file_count_without_writing(tmp_path):
    (tmp_path / "shoplook.json").write_text(json.dumps({"looks": [
        look(1000.0, "Glider | 5,000.000 Honey | Edguipped")]}))
    assert "glider" in sight.seen_owned(tmp_path)
    assert not (tmp_path / sight.SIGHT_FILE).exists()            # read-only


def _boots_progress(tmp_path):
    (tmp_path / "bees.json").write_text(json.dumps({"total": 41, "bees": {}}))
    path = tmp_path / "settings.yaml"
    path.write_text(yaml.safe_dump({"goals.owned": "Porcelain Dipper, Bubble Mask, "
                                                   "Porcelain Port-O-Hive"}))
    acct = prog.account_from_files(tmp_path, Settings(path))
    nxt = prog.next_goals(acct, 3, prog.load("blue"))
    checked: list = []
    cards = prog.questions(acct, prog.load("blue"), nxt, tmp_path, checked)
    return {c.id: c for c in cards}, checked


def test_a_slot_question_is_checked_first(tmp_path):
    cards, checked = _boots_progress(tmp_path)
    boots = cards["progression:slot:boots"]
    assert "Not checked yet" in boots.context and "Beekeeper's Boots" in boots.context
    assert checked == []
    # a price seen: still asked, and the card says what was checked and when
    (tmp_path / "shoplook.json").write_text(json.dumps({"looks": [
        look(1000.0, "Beekeeper's Boots | 15.000.000 Honey | Buy for 15,000,000 Honey")]}))
    cards, checked = _boots_progress(tmp_path)
    assert "Checked: a shop window showed the Beekeeper's Boots with a price" \
        in cards["progression:slot:boots"].context
    # the worn boots seen Equipped: the slot is answered, not asked
    (tmp_path / "shoplook.json").write_text(json.dumps({"looks": [
        look(1000.0, "Beekeeper's Boots | 15.000.000 Honey | Buy for 15,000,000 Honey"),
        look(2000.0, "Beekeeper's Boots | 15.000.000 Honey | Edguipped")]}))
    cards, checked = _boots_progress(tmp_path)
    assert "progression:slot:boots" not in cards
    acct = prog.account_from_files(tmp_path, Settings(tmp_path / "settings.yaml"))
    line = prog.slot_checked(acct, prog.load("blue"), "boots")
    assert line.startswith("progression: Which boots do you wear? -- checked: Beekeeper's "
                           "Boots shows Equipped at the mountain top shop")
    # the card already in the inbox is taken down, and the log says what was seen
    events, said = [], []
    watch = goals_plan.Watch(tmp_path, emit=events.append, say=said.append,
                             settings_factory=lambda: Settings(tmp_path / "settings.yaml"))
    watch.asked = {"progression:slot:boots": {"at": 1.0}}
    watch._progression_cards(goals_plan.Plan(progress=prog.Progress(
        hive="blue", questions=[], account=acct)))
    assert [(e.name, e.value) for e in events] == [("progression:slot:boots", "withdrawn")]
    assert said == [line]
    # their own word answers it: nothing to say about sight
    (tmp_path / "settings.yaml").write_text(yaml.safe_dump({"goals.owned": "Hiking Boots"}))
    acct = prog.account_from_files(tmp_path, Settings(tmp_path / "settings.yaml"))
    assert prog.slot_checked(acct, prog.load("blue"), "boots") == ""


def test_an_inferred_purchase_seen_owned_is_not_asked(tmp_path):
    # decided_at: a decided card is up for a day (tests/unit/test_no_questions.py)
    import time
    (tmp_path / "owned.json").write_text(json.dumps({"items": {"bubble_mask": {
        "state": owned_mod.INFERRED, "at": 1.0, "why": "a fall", "honey": 100_000_000,
        "decided_at": time.time()}}}))
    events, said = [], []
    buyer = owned_mod.Purchases(tmp_path, emit=events.append, say=said.append)
    buyer.cards()
    card = next(e for e in events if getattr(e, "id", "") == "owned:bubble_mask")
    assert "Not checked yet" in card.context
    (tmp_path / "shoplook.json").write_text(json.dumps({"looks": [
        look(3000.0, "Bubble Mask | 100,000,000 Honey | Equipped", shop="blue_hq_buy:bubble_mask:1")]}))
    events.clear()
    buyer.cards()
    assert [getattr(e, "value", None) for e in events] == ["withdrawn"]
    assert any(s.startswith("owned: checked: Bubble Mask shows Equipped at the blue hq")
               for s in said)
    assert owned_mod.owned("", tmp_path)["bubble_mask"].how == owned_mod.SEEN


def _drop(tmp_path, could):
    (tmp_path / "owned.json").write_text(json.dumps({"drops": [{
        "id": "2000", "before_at": 1000.0, "before": 500_000_000, "after_at": 2000.0,
        "after": 400_000_000, "amount": 100_000_000, "stopped": True,
        "explains": could, "asked": True, "could_be": could}]}))


def test_a_fall_card_is_checked_first(tmp_path):
    could = ["bubble_mask", "fire_mask"]
    # nothing seen: no card since 2026-10-26 (decided, not asked), still open
    _drop(tmp_path, could)
    events, said = [], []
    owned_mod.Purchases(tmp_path, emit=events.append, say=said.append).cards()
    assert not any(getattr(e, "kind", "") == "question" for e in events)
    assert not owned_mod.load_state(tmp_path)["drops"][0].get("answered")
    # one of them seen owned after the fall began: that is the answer
    (tmp_path / "shoplook.json").write_text(json.dumps({"looks": [
        look(3000.0, "Bubble Mask | 100,000,000 Honey | Equip", shop="blue_hq")]}))
    events.clear()
    owned_mod.Purchases(tmp_path, emit=events.append, say=said.append).cards()
    assert not any(getattr(e, "kind", "") == "question" for e in events)
    drop = owned_mod.load_state(tmp_path)["drops"][0]
    assert drop["answered"].startswith(owned_mod.BOUGHT_THE + "Bubble Mask (checked:")
    assert any("not asking" in s for s in said)


def test_a_fall_card_none_of_whose_answers_can_be_is_settled(tmp_path):
    _drop(tmp_path, ["bubble_mask", "fire_mask"])
    (tmp_path / "shoplook.json").write_text(json.dumps({"looks": [
        look(500.0, "Bubble Mask | 100,000,000 Honey | Equip", shop="blue_hq"),     # before
        look(2500.0, "Fire Mask | 100,000,000 Honey | Craft Item", shop="red_hq")]})) # after
    events = []
    owned_mod.Purchases(tmp_path, emit=events.append).cards()
    assert not any(getattr(e, "kind", "") == "question" for e in events)
    assert owned_mod.load_state(tmp_path)["drops"][0]["answered"].startswith(owned_mod.NONE_OF_THESE)


def test_a_goal_card_says_what_was_checked():
    row = goals_plan.Row(key="spark_staff", label="Spark Staff", shop_label="Mountain Top Shop",
                         cost=60_000_000, state=goals_plan.READY,
                         checked="Checked: a shop window showed the Spark Staff with a price")
    card = goals_plan.question(row, goals_plan.Plan())
    assert card.context.endswith("Checked: a shop window showed the Spark Staff with a price")


def test_the_shop_errand(tmp_path):
    routed = {"mountain_top_shop"}
    # an open card's items: the Bubble Mask's shop has no route, the Boots' has
    wanted = ["bubble_mask", "beekeepers_boots", "beekeepers_mask"]
    check = sight.errand(tmp_path, wanted, routed, clock=lambda: 10_000.0)
    assert (check.key, check.shop) == ("beekeepers_boots", "mountain_top_shop")
    assert sight.errand(tmp_path, ["bubble_mask"], routed) is None        # no route
    assert sight.errand(tmp_path, [], routed) is None                      # nothing open
    # once a day per item: one visit reads the whole catalogue, so both wait
    sight.errand_started(tmp_path, check, wanted, clock=lambda: 10_000.0)
    assert sight.errand(tmp_path, wanted, routed, clock=lambda: 10_000.0 + 3600) is None
    later = 10_000.0 + sight.CHECK_EVERY_S + 1
    assert sight.errand(tmp_path, wanted, routed, clock=lambda: later).key == "beekeepers_boots"
    # seen owned: never looked for again
    (tmp_path / "shoplook.json").write_text(json.dumps({"looks": [
        look(20_000.0, "Beekeeper's Boots | 15.000.000 Honey | Edguipped")]}))
    assert sight.errand(tmp_path, wanted, routed, clock=lambda: later).key == "beekeepers_mask"


def test_open_items_are_the_unanswered_cards(tmp_path):
    from hivemind.telemetry.events import Option, Question
    card = Question(id="progression:slot:boots", question="Which boots do you wear?",
                    options=[Option("Beekeeper's Boots", 1.0), Option(prog.NONE_YET, 0.0)])
    plan = goals_plan.Plan(progress=prog.Progress(questions=[card]))
    (tmp_path / "owned.json").write_text(json.dumps({
        "items": {"glider": {"state": owned_mod.INFERRED}, "spark_staff": {"state": "rejected"}},
        "drops": [{"asked": True, "could_be": ["fire_mask"]},
                  {"asked": True, "answered": "x", "could_be": ["scythe"]}]}))
    (tmp_path / "goals.json").write_text(json.dumps({"asked": {
        "honey_mask": {"at": 1}, "diamond_mask": {"at": 1, "answered": "Not yet"},
        "progression:slot:boots": {"at": 1}}}))
    got = sight.open_items(tmp_path, plan, "Glider")
    assert set(got) == {"beekeepers_boots", "fire_mask", "honey_mask"}
