

def test_a_fall_the_bot_bought_itself_is_no_question(tmp_path):
    # the 35th hive slot, 209,117,953 honey, is in no price table: without the
    # bot's own record of buying it the fall would be asked about
    import json as _json
    from hivemind.brain import owned as owned_mod
    (tmp_path / "purchases.json").write_text(_json.dumps([
        {"at": 1000.0, "shop": "mountain_top_shop", "item": "Hive Slot",
         "price": 209_117_953, "currency": "Honey", "ok": True},
        {"at": 1000.0, "shop": "ticket_tent", "item": "Festive Bee Egg",
         "price": 500, "currency": "Tickets", "ok": True}]))
    fall = owned_mod.Fall(before_at=900.0, before=430_000_000, after_at=1100.0,
                          after=430_000_000 - 209_117_953)
    assert owned_mod.bot_purchase(tmp_path, fall)["item"] == "Hive Slot"
    # MEASURED 06:01-06:03: the balance fell 24,000 less than the price
    made = owned_mod.Fall(before_at=900.0, before=437_449_487, after_at=1100.0,
                          after=228_355_534)
    assert owned_mod.bot_purchase(tmp_path, made)["item"] == "Hive Slot"
    later = owned_mod.Fall(before_at=5000.0, before=430_000_000, after_at=5100.0,
                           after=430_000_000 - 209_117_953)
    assert owned_mod.bot_purchase(tmp_path, later) is None          # not in its window
    other = owned_mod.Fall(before_at=900.0, before=430_000_000, after_at=1100.0,
                           after=430_000_000 - 150_000_000)
    assert owned_mod.bot_purchase(tmp_path, other) is None          # not its price



def test_gear_the_bot_bought_is_owned_from_then_on(tmp_path):
    # MEASURED 2026-10-07: the Bubble Mask crafted at 02:46 and the plan at
    # 03:09 still "next is the Bubble Mask", buying it again
    import json as _json
    from hivemind.brain import owned as m
    rows = [{"at": 1000.0, "shop": "blue_hq", "item": "Bubble Mask",
             "price": 100_000_000, "currency": "Honey", "ok": False}]
    (tmp_path / "purchases.json").write_text(_json.dumps(rows))
    assert "bubble_mask" not in m.owned("", tmp_path)      # a refused try is not
    rows += [{"at": 2000.0, "shop": "blue_hq", "item": "Bubble Mask",
              "price": 100_000_000, "currency": "Honey", "ok": True},
             {"at": 3000.0, "shop": "mountain_top_shop", "item": "Hive Slot",
              "price": 894_566_712, "ok": True}]
    (tmp_path / "purchases.json").write_text(_json.dumps(rows))
    got = m.owned("Honey Mask", tmp_path)
    assert got["bubble_mask"].how == m.BOUGHT and got["bubble_mask"].at == 2000.0
    assert got["honey_mask"].how == m.CONFIRMED            # their word first
    assert not any(k.startswith("hive_slot") for k in got)  # slots are counted apart
