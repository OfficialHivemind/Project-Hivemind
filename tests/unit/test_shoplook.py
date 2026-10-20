"""Looking at a shop, buying nothing (act/shoplook)."""
from __future__ import annotations

import json
import shutil

import pytest

from hivemind.act import shoplook


class Keys:
    def __init__(self, hold_back=()):
        self.events = []
        self.hold_back = set(hold_back)

    def press(self, *keys):
        if set(keys) & self.hold_back:
            return False
        self.events.append(("down",) + keys)
        return True

    def release(self, *keys):
        self.events.append(("up",) + keys)

    def tap(self, key, *a, **k):
        if key in self.hold_back:
            return False
        self.events.append(("tap", key))
        return True

    def taps(self):
        return [e[1] for e in self.events if e[0] == "tap"]


def script(*reads):
    """read_panel answering `reads` in turn, the last one repeating."""
    seq = list(reads)
    state = {"i": 0}

    def read(_frame):
        i = min(state["i"], len(seq) - 1)
        state["i"] += 1
        return seq[i]
    return read


def run(reads, keys=None, transcribe=None):
    keys = keys or Keys()
    got = shoplook.look(keys, lambda: object(), script(*reads), transcribe,
                        sleep=lambda s: None)
    return got, keys


def test_it_walks_to_the_counter_goes_in_reads_and_comes_out():
    got, keys = run(["fire the red cannon", "", "open shop", "open shop",
                     "E Leave Shop", "E Leave Shop", "open shop"],
                    transcribe=lambda f: "Gold Egg 100 Tickets")
    assert got.ok and got.went_in and got.came_out and not got.trapped
    assert got.steps == 2
    assert keys.taps() == ["e", "e"]                 # one in, one out
    assert got.window == "Gold Egg 100 Tickets"
    # every step it held came up again
    downs = [e for e in keys.events if e[0] == "down"]
    ups = [e for e in keys.events if e[0] == "up"]
    assert len(downs) == len(ups) == 2


def test_no_e_at_the_cannon_or_anything_but_the_exact_prompt():
    got, keys = run(["fire the red cannon"])         # never reads "open shop"
    assert not got.ok and not got.went_in
    assert keys.taps() == []                         # the cannon was not fired
    assert "no \"Open Shop\"" in got.reason


def test_a_window_that_never_says_leave_shop_is_trapped_and_not_pressed_at():
    got, keys = run(["open shop", "open shop", "Close Your Eyes"])
    assert got.trapped and not got.ok
    assert keys.taps() == ["e"]                      # in, and nothing more
    assert "Shop Trap" in got.describe()


def test_an_e_that_opened_nothing_changes_nothing():
    got, keys = run(["open shop", "open shop"])
    assert not got.ok and not got.went_in and not got.trapped
    assert keys.taps() == ["e"]


def test_a_leave_that_does_not_take_is_pressed_again_once_then_trapped():
    got, keys = run(["open shop", "open shop", "leave shop"])
    assert got.trapped and got.went_in and not got.came_out
    assert keys.taps() == ["e", "e", "e"]            # in, then two tries out


def test_the_owners_pause_holds_everything_back():
    got, keys = run(["", "open shop"], keys=Keys(hold_back={"w"}))
    assert not got.ok and keys.taps() == [] and "Pause" in got.reason


def test_the_prompt_reads_with_or_without_its_key_hint():
    assert shoplook.says("E Leave Shop", shoplook.LEAVE)
    assert shoplook.says("  leave   shop ", shoplook.LEAVE)
    assert not shoplook.says("Leave Shop now", shoplook.LEAVE)
    assert not shoplook.says(None, shoplook.OPEN)


def test_a_read_that_fails_after_leaving_is_not_taken_for_out():
    # in, the window, then the model stops answering: never "out", so the
    # caller rejoins instead of resetting with the window open (Shop Trap)
    got, keys = run(["open shop", "open shop", "leave shop", "leave shop", None])
    assert got.went_in and got.trapped and not got.came_out and not got.ok
    assert keys.taps() == ["e", "e"]
    assert "not taken for out" in got.reason


def test_a_raise_inside_is_held_in_here():
    reads = iter(["open shop", "open shop", "leave shop"])

    def read(_frame):
        try:
            return next(reads)
        except StopIteration:
            raise RuntimeError("the model fell over")
    keys = Keys()
    got = shoplook.look(keys, lambda: object(), read, None, sleep=lambda s: None)
    assert got.trapped and not got.ok                 # reported, not raised


def test_the_record_and_when_to_look_again(tmp_path):
    path = tmp_path / "shoplook.json"
    assert shoplook.not_due(path, "ticket_tent", 3600, clock=lambda: 1000.0) == ""
    miss = shoplook.ShopLook(reason="no \"Open Shop\" within 4s")
    shoplook.record(path, miss, shop="ticket_tent", clock=lambda: 1000.0)
    assert "tried" in shoplook.not_due(path, "ticket_tent", 3600, clock=lambda: 1500.0)
    assert shoplook.not_due(path, "ticket_tent", 3600, clock=lambda: 5000.0) == ""
    assert shoplook.not_due(path, "blue_hq", 3600, clock=lambda: 1500.0) == ""
    seen = shoplook.ShopLook(ok=True, went_in=True, came_out=True,
                             window="Gold Egg 100 Tickets", kept=["a.png"])
    shoplook.record(path, seen, shop="ticket_tent", clock=lambda: 6000.0)
    assert "already looked" in shoplook.not_due(path, "ticket_tent", 3600,
                                                clock=lambda: 9e9)
    body = json.loads(path.read_text())
    assert body["looks"][-1]["window"] == "Gold Egg 100 Tickets"
    assert body["looks"][-1]["code"] == shoplook.code()


def test_the_window_words_come_from_tesseract_and_never_raise():
    import numpy as np

    said = iter([b"Gold Egg\n", b" 100  Tickets \n", b"Purchase\n"])

    class Out:
        def __init__(self):
            self.stdout = next(said)
    frame = np.zeros((1080, 1920, 3), np.uint8)
    seen = {}

    def run_(cmd, **kw):
        seen["cmd"] = cmd
        return Out()
    assert shoplook.window_text(frame, run=run_) == "Gold Egg | 100 Tickets | Purchase"
    assert seen["cmd"][0] == "tesseract"
    assert shoplook.window_text(None) == " |  | "

    def broken(cmd, **kw):
        raise OSError("no tesseract")
    assert shoplook.window_text(frame, run=broken) == " |  | "


def test_the_prompt_box_reads_letters_only():
    import numpy as np

    class Out:
        stdout = b"Open Shop |\n"
    frame = np.zeros((1080, 1920, 3), np.uint8)
    assert shoplook.prompt_text(frame, run=lambda c, **k: Out()) == "open shop"
    assert shoplook.prompt_text(None) == ""


def ocr(*reads):
    """A read_prompt answering the reads in turn, the last one repeating; it
    is asked inside the shop only (the approach reads the panel alone)."""
    return script(*reads)


def test_a_red_leave_shop_the_panel_finder_misses_is_read_by_the_box():
    # 06:37 on 2026-10-02, attempt 578: inside the Ticket Tent read_panel
    # said '' (a red prompt over a red wall); the prompt's box said it
    keys = Keys()
    got = shoplook.look(keys, lambda: object(),
                        script("open shop", "open shop", "", "", "open shop"), None,
                        sleep=lambda s: None,
                        read_prompt=ocr("open shop", "leave shop", "leave shop", "open shop"))
    assert got.ok and got.went_in and got.came_out
    assert keys.taps() == ["e", "e"]


def test_an_empty_read_inside_is_never_taken_for_out():
    # the trap this would have walked into: after the E to leave, read_panel
    # says '' while the window is still open and its box says "leave shop"
    keys = Keys()
    got = shoplook.look(keys, lambda: object(),
                        script("open shop", "open shop", ""), None, sleep=lambda s: None,
                        read_prompt=ocr("open shop", "leave shop"))
    assert got.trapped and not got.came_out and not got.ok
    assert keys.taps() == ["e", "e", "e"]            # in, then two tries out


def test_out_needs_the_counter_back():
    # neither reader says anything after the E to leave: not "out"
    keys = Keys()
    got = shoplook.look(keys, lambda: object(),
                        script("open shop", "open shop", "leave shop", "leave shop", ""), None,
                        sleep=lambda s: None, read_prompt=ocr(""))
    assert got.trapped and not got.ok
    assert keys.taps() == ["e", "e"]
    assert "not taken for out" in got.reason


def test_a_read_that_fails_on_the_way_is_not_a_step():
    # 06:09 on 2026-10-02: the model's server recycled mid-approach and the
    # old approach stepped on through None reads, ~180 studs blind
    got, keys = run(["fire the red cannon", None])
    assert not got.ok and not got.went_in and keys.taps() == []
    assert got.steps == 1                            # the one step after a read
    assert "no step was taken blind" in got.reason


def test_a_read_that_comes_back_lets_it_go_on():
    got, keys = run(["fire the red cannon", None, None, "", "open shop",
                     "open shop", "leave shop", "leave shop", "open shop"])
    assert got.ok and got.steps == 2
    assert got.reads[:4] == ["'fire the red cannon'", "<no read>", "''", "'open shop'"]


def test_a_step_covers_the_same_ground_under_a_speed_buff():
    held = []
    keys = Keys()
    got = shoplook.look(keys, lambda: object(), script("", "open shop", "open shop", "leave shop", "leave shop", "open shop"),
                        None, sleep=held.append, speed=lambda: 1.6)
    assert got.ok
    assert abs(held[0] - shoplook.STEP_S / 1.6) < 1e-9    # the one approach step
    # a factor the buff bar cannot mean is ignored
    held.clear()
    shoplook.look(Keys(), lambda: object(), script("", "open shop", "open shop", "leave shop", "leave shop", "open shop"),
                  None, sleep=held.append, speed=lambda: 40.0)
    assert abs(held[0] - shoplook.STEP_S) < 1e-9


class Dropping(Keys):
    """GuardedInput after an owner's Pause: the first E is dropped (stale
    after a wait), the next one goes through."""
    def __init__(self, drops=1):
        super().__init__()
        self.drops = drops

    def tap(self, key, *a, **k):
        if key == "e" and self.drops > 0:
            self.drops -= 1
            return False
        return super().tap(key, *a, **k)


def test_an_e_the_input_dropped_is_looked_at_again_and_pressed_again():
    keys = Dropping(drops=1)
    got = shoplook.look(keys, lambda: object(),
                        script("open shop", "open shop", "open shop", "leave shop",
                               "leave shop", "open shop"),
                        None, sleep=lambda s: None, taken_over=lambda: False)
    assert got.ok and keys.taps() == ["e", "e"]


def test_a_take_over_inside_the_shop_is_his():
    # in, then the owner takes the controls: the E out is held back for him,
    # and the look says trapped (the caller stops; the rejoin clears it)
    class TakenAfterIn(Keys):
        def tap(self, key, *a, **k):
            if key == "e" and self.taps():
                return False
            return super().tap(key, *a, **k)
    keys = TakenAfterIn()
    got = shoplook.look(keys, lambda: object(),
                        script("open shop", "open shop", "leave shop"), None,
                        sleep=lambda s: None, taken_over=lambda: bool(keys.taps()))
    assert got.went_in and got.trapped and not got.ok
    assert keys.taps() == ["e"]
    assert "Take Over" in got.reason
    # and at the counter, before anything opened: nothing pressed, not trapped
    keys2 = Dropping(drops=99)
    got = shoplook.look(keys2, lambda: object(), script("open shop"), None,
                        sleep=lambda s: None, taken_over=lambda: True)
    assert not got.went_in and not got.trapped and keys2.taps() == []
    assert "held the E back" in got.reason


def test_a_stop_ends_the_approach_and_presses_nothing():
    keys = Keys()
    got = shoplook.look(keys, lambda: object(), script("fire the red cannon"),
                        None, sleep=lambda s: None, stopped=lambda: True)
    assert not got.went_in and keys.taps() == [] and got.steps == 0
    assert "stop" in got.reason
    keys = Keys()
    got = shoplook.look(keys, lambda: object(), script("open shop"), None,
                        sleep=lambda s: None, stopped=lambda: True)
    assert not got.went_in and keys.taps() == []


def test_one_look_at_the_counter_after_the_e_is_not_opened_nothing():
    # the window drew late: one look still shows the counter, the next is in
    got, keys = run(["open shop", "open shop", "open shop", "leave shop",
                     "leave shop", "open shop"])
    assert got.ok and got.went_in and keys.taps() == ["e", "e"]


def test_one_look_at_the_counter_after_leaving_is_not_out():
    # a lagged frame shows the counter once, then the window again: in, so
    # the E goes again on a fresh "Leave Shop", and out on two looks in a row
    got, keys = run(["open shop", "open shop", "leave shop", "leave shop",
                     "open shop", "leave shop", "leave shop", "open shop"])
    assert got.ok and keys.taps() == ["e", "e", "e"]


def test_the_e_waits_for_a_fresh_read_of_the_prompt():
    # the counter's prompt is gone by the time the E would go: no E
    got, keys = run(["open shop", ""])
    assert not got.went_in and keys.taps() == []
    assert "no longer read" in got.reason


# ---- the Ticket Tent's doorway, by its carpet ---------------------------------

def carpet_at(x):
    import numpy as np
    frame = np.zeros((1080, 1920, 3), np.uint8)
    if x is not None:
        frame[420:640, x - 60:x + 60] = (0, 210, 250)    # BGR: the carpet's yellow
    return frame


def test_the_steer_edges_toward_the_carpet():
    assert shoplook.ticket_tent_steer(carpet_at(685)) == "wa"    # 11:38's miss
    assert shoplook.ticket_tent_steer(carpet_at(1300)) == "wd"
    assert shoplook.ticket_tent_steer(carpet_at(980)) == "w"
    assert shoplook.ticket_tent_steer(carpet_at(None)) == "w"
    assert shoplook.ticket_tent_steer(None) == "w"


def test_the_approach_presses_what_the_steer_says():
    keys = Keys()
    got = shoplook.look(keys, lambda: carpet_at(685),
                        script("", "", "open shop", "open shop", "leave shop",
                               "leave shop", "open shop"),
                        None, sleep=lambda s: None,
                        steer=shoplook.ticket_tent_steer)
    downs = [e for e in keys.events if e[0] == "down"]
    assert downs and all(e[1:] == ("w", "a") for e in downs)
    assert got.steered == len(downs) == got.steps


# ---- browsing the window: the right arrow, only where it is drawn --------

def _window_frame(button="green"):
    """A 1920x1080 frame with the window's bar as measured 2026-10-02."""
    import cv2
    import numpy as np
    frame = np.full((1080, 1920, 3), 200, np.uint8)
    cv2.rectangle(frame, (761, 847), (1100, 926), (255, 140, 40), -1)          # the blue bar
    colour = (40, 120, 30) if button == "green" else (30, 30, 220)
    cv2.rectangle(frame, (831, 867), (1029, 906), colour, -1)                  # the button
    for tip, base in ((770, 807), (1090, 1054)):                               # the white arrows
        pts = np.array([[tip, 886], [base, 858], [base, 914]], np.int32)
        cv2.fillPoly(frame, [pts], (245, 245, 245))
    return frame


def test_the_arrow_is_seen_only_on_the_window_bar():
    import numpy as np
    frame = _window_frame()
    assert shoplook.arrow_there(frame) and shoplook.arrow_there(frame, shoplook.ARROW_LEFT)
    assert shoplook.arrow_there(_window_frame("red"))          # "Can't afford"
    assert not shoplook.arrow_there(frame, (930, 886))          # the button is no arrow
    assert not shoplook.arrow_there(np.full((1080, 1920, 3), 245, np.uint8))   # white world


def test_browse_reads_round_the_catalogue_once():
    items = ["Photon Bee Egg | 500 Tickets | Buy for 500 Tickets",
             "Festive Bee Egg | 500 Tickets | Buy for 500 Tickets",
             "Gold Egg | 100 Tickets | Buy for 100 Tickets"]
    at, clicks = [0], []

    def click(x, y):
        clicks.append((x, y))
        at[0] = (at[0] + 1) % len(items)
        return True
    seen = shoplook.browse(click, lambda: _window_frame(), lambda f: items[at[0]],
                           sleep=lambda s: None)
    assert seen == items
    assert clicks == [shoplook.ARROW_RIGHT] * 3                 # the third came back round


def test_browse_never_clicks_where_the_arrow_is_not():
    import numpy as np
    clicks = []
    seen = shoplook.browse(lambda x, y: clicks.append((x, y)),
                           lambda: np.full((1080, 1920, 3), 245, np.uint8),
                           lambda f: "Photon Bee Egg | 500 Tickets | Can't afford",
                           sleep=lambda s: None)
    assert seen == ["Photon Bee Egg | 500 Tickets | Can't afford"] and clicks == []


def test_browse_stops_when_the_arrow_changes_nothing():
    clicks = []
    seen = shoplook.browse(lambda x, y: clicks.append((x, y)), lambda: _window_frame(),
                           lambda f: "Photon Bee Egg | 500 Tickets | Can't afford",
                           sleep=lambda s: None)
    assert len(seen) == 1 and len(clicks) == 1


def test_browse_stops_on_a_click_the_input_refused():
    clicks = []

    def refused(x, y):
        clicks.append((x, y))
        return False
    names = iter(["A | 1 Tickets | x", "B | 2 Tickets | y"])
    seen = shoplook.browse(refused, lambda: _window_frame(), lambda f: next(names),
                           sleep=lambda s: None)
    assert seen == ["A | 1 Tickets | x"] and len(clicks) == 1


# ---- buying: the one click on the button, only on an exact read ----------

class _Shop:
    """A window that browses by the right arrow and sells on the button."""
    def __init__(self, items, tickets=507, button="green"):
        self.items, self.at, self.tickets, self.button = list(items), 0, tickets, button
        self.clicks = []

    def click(self, x, y):
        self.clicks.append((x, y))
        if (x, y) == shoplook.ARROW_RIGHT:
            self.at = (self.at + 1) % len(self.items)
        else:                                   # the button
            name, price, _b = [p.strip() for p in self.items[self.at].split("|")]
            self.tickets -= shoplook._number(price)
            self.items[self.at] = f"{name} | {price} | Owned"
        return True

    def frame(self):
        return _window_frame(self.button)

    def read(self, frame):
        return self.items[self.at]

    def button_clicks(self):
        return [c for c in self.clicks if c != shoplook.ARROW_RIGHT]


TENT = ["Photon Bee Egg | 500 Tickets | Buy for 500 Tickets",
        "Festive Bee Egg | 500 Tickets | Buy for 500 Tickets",
        "Gold Egg | 100 Tickets | Buy for 100 Tickets"]


def _buy(shop, want="Festive Bee Egg", most=500, currency="Tickets"):
    return shoplook.buy(shop.click, shop.frame, shop.read, want, currency=currency,
                        most=most, sleep=lambda s: None, counted=lambda: shop.tickets)


def test_it_browses_to_the_item_and_buys_it_once():
    shop = _Shop(TENT)
    got = _buy(shop)
    assert got.ok and got.price == 500 and "fell 507 -> 7" in got.reason
    assert shop.button_clicks() == [((826 + 1034) // 2, (862 + 912) // 2)]
    assert shop.items[1].endswith("Owned")


def test_robux_is_never_bought():
    shop = _Shop(["Some Pass | 99 Robux | Buy for 99 Robux"])
    got = _buy(shop, want="Some Pass", most=10**9, currency="Robux")
    assert not got.ok and "Robux" in got.reason and shop.button_clicks() == []


def test_over_the_allowance_or_unaffordable_is_not_bought():
    shop = _Shop(TENT)
    assert not _buy(shop, most=400).ok and shop.button_clicks() == []
    shop = _Shop(["Festive Bee Egg | 500 Tickets | Can't afford"], button="red")
    got = _buy(shop)
    assert not got.ok and "does not offer" in got.reason and shop.button_clicks() == []


def test_a_red_button_or_a_missing_item_is_not_pressed():
    shop = _Shop(TENT, button="red")
    assert not _buy(shop).ok and shop.button_clicks() == []
    shop = _Shop(TENT)
    got = _buy(shop, want="Star Treat")
    assert not got.ok and "not found" in got.reason and shop.button_clicks() == []
    assert len(shop.clicks) == 3                     # round once, no more


def test_a_bare_purchase_button_is_taken_with_the_price_line():
    shop = _Shop(["Hive Slot | 209,117,953 Honey | Purchase"])
    shop.tickets = 250_000_000                       # honey, here
    got = _buy(shop, want="Hive Slot", most=209_117_953, currency="Honey")
    assert got.ok and got.price == 209_117_953
    for button in ("Purchased", "Purchase for 999 Honey"):
        shop = _Shop([f"Hive Slot | 209,117,953 Honey | {button}"])
        assert not _buy(shop, want="Hive Slot", most=10**9, currency="Honey").ok
        assert shop.button_clicks() == []


def test_a_windows_red_close_square_is_found_by_its_colours():
    import cv2
    from pathlib import Path
    fix = Path(__file__).resolve().parents[1] / "fixtures"
    blender = cv2.imread(str(fix / "shoplook/wiki-blender-window.png"))      # the wiki's picture
    x, y = shoplook.find_close_x(blender)
    assert 20 <= x <= 60 and 15 <= y <= 55
    assert shoplook.find_close_x(_window_frame()) is None                    # the shop's bar is no close
    assert shoplook.find_close_x(cv2.imread(str(fix / "inventory/use-glitter-dialog.png"))) is None


def test_an_owned_items_dimmed_button_is_still_the_window():
    # MEASURED 2026-10-03 05:14: the Mountain Top Shop's browse stopped at the
    # Beekeeper's Boots, whose button is the teal "Equipped" -- three items in,
    # the Hive Slot never reached. The bar is there and its arrows clickable;
    # the button is no buy button, so `buy` could never press it.
    from pathlib import Path

    import cv2
    fix = Path(__file__).resolve().parents[1] / "fixtures" / "shoplook"
    owned = cv2.imread(str(fix / "mts-equipped.jpg"))
    assert shoplook.bar_there(owned)
    assert shoplook.arrow_there(owned) and shoplook.arrow_there(owned, shoplook.ARROW_LEFT)
    assert not shoplook._button_green(owned)
    for_sale = cv2.imread(str(fix / "mts-buy.jpg"))       # Spark Staff, "Buy for 60,000,000"
    assert shoplook.bar_there(for_sale) and shoplook._button_green(for_sale)


def test_a_price_reads_whichever_way_its_commas_come_out():
    # the window draws "60,000,000"; tesseract read its commas as "." or ","
    # (MEASURED 2026-10-03 on the Mountain Top Shop's prices)
    assert shoplook._number("60.000.000 Honey") == 60_000_000
    assert shoplook._number("20,000.000 Honey") == 20_000_000
    # MEASURED 2026-10-06 00:37: a comma read as a space on the Hive Slot's button
    assert shoplook._number("Buy for 508,855 908 Honey") == 508_855_908
    assert shoplook._number("Buy for 209,117,953 Honey") == 209_117_953
    assert shoplook._number("Buy for 500 Tickets") == 500
    assert shoplook._number("1.5M Honey") == 1            # no decimal grows into a price
    assert shoplook._number("Equipped") is None


def test_browse_says_whether_it_came_round():
    items = iter(["A | 1 Honey | Buy for 1 Honey", "B | 2 Honey | Buy for 2 Honey",
                  "A | 1 Honey | Buy for 1 Honey"])
    why = {}
    seen = shoplook.browse(lambda x, y: None, lambda: _window_frame(), lambda f: next(items),
                           sleep=lambda s: None, why=why)
    assert len(seen) == 2 and why["stopped"] == shoplook.BROWSE_CAME_ROUND
    import numpy as np
    why = {}
    shoplook.browse(lambda x, y: None, lambda: np.full((1080, 1920, 3), 200, np.uint8),
                    lambda f: "A | 1 Honey | Buy for 1 Honey", sleep=lambda s: None, why=why)
    assert why["stopped"].startswith("no arrow seen")


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="no tesseract here")
def test_a_two_line_button_reads_as_one():
    # "Buy for 60,000,000" over "Honey": noise as one line, the price as a block
    from pathlib import Path

    import cv2
    frame = cv2.imread(str(Path(__file__).resolve().parents[1] / "fixtures" / "shoplook" / "mts-buy.jpg"))
    name, price, button = [p.strip() for p in shoplook.window_text(frame).split("|")]
    assert name == "Spark Staff"
    assert shoplook._number(price) == shoplook._number(button) == 60_000_000
    assert button.lower().startswith("buy for")


def test_a_done_look_outlives_the_pruning(tmp_path, monkeypatch):
    # MEASURED 2026-10-03 05:34: with 20 looks kept, the night's surveys
    # pushed the Ticket Tent's first look out of the file and it was walked
    # again; the slot survey holding the Mountain Top Shop's way in was next
    monkeypatch.setattr(shoplook, "LOOKS_KEPT", 10)
    path = tmp_path / "shoplook.json"
    shoplook.record(path, shoplook.ShopLook(ok=True, reads=["l11-w: 'Open Shop'"]),
                    shop="mountain_top_survey_slot", clock=lambda: 1.0)
    for i in range(30):
        shoplook.record(path, shoplook.ShopLook(ok=False, reason="x"),
                        shop=f"other_{i % 3}", clock=lambda: 2.0 + i)
    looks = json.loads(path.read_text())["looks"]
    assert len(looks) == 11 and looks[0]["shop"] == "mountain_top_survey_slot"
    assert shoplook.not_due(path, "mountain_top_survey_slot", 3600, clock=lambda: 99.0
                            ).startswith("already looked at")


def test_the_buttons_exact_price_stands_over_a_misread_price_line():
    # MEASURED 2026-10-06 04:55: slot 39's window, its price line misread in the
    # last digit -- and the purchase was refused
    shop = _Shop(["Hive Slot | 676,212.641 Honey | Buy for 676,212,647 Honey"],
                 tickets=800_000_000)
    got = _buy(shop, want="Hive Slot", most=676_212_647, currency="Honey")
    assert got.ok, got.reason
    assert len(shop.button_clicks()) == 1
    # a price line ten times off is a digit dropped somewhere: still refused
    shop = _Shop(["Hive Slot | 67,621,264 Honey | Buy for 676,212,647 Honey"],
                 tickets=800_000_000)
    got = _buy(shop, want="Hive Slot", most=676_212_647, currency="Honey")
    assert not got.ok and shop.button_clicks() == []


def test_a_craft_item_button_is_taken_with_the_price_line_when_green():
    # MEASURED 2026-10-07 02:15 at the Blue HQ: 'Bubble Mask | 100.000.000 Honey | Craft Item'
    items = ["Bubble Wand | 3,500.000 Honey | Equip",
             "Bubble Mask | 100.000.000 Honey | Craft Item"]
    shop = _Shop(items, tickets=680_000_000)
    got = _buy(shop, want="Bubble Mask", most=100_000_000, currency="Honey")
    assert got.ok and got.price == 100_000_000 and len(shop.button_clicks()) == 1
    shop = _Shop(items, tickets=680_000_000, button="red")      # a material short
    got = _buy(shop, want="Bubble Mask", most=100_000_000, currency="Honey")
    assert not got.ok and shop.button_clicks() == []


def test_a_survey_whose_walk_there_missed_waits_an_hour_not_six(tmp_path):
    # MEASURED 2026-10-21 11:52: the route to the start missed, only "arrived" was read
    path = tmp_path / "looks.json"
    shoplook.record(path, shoplook.ShopLook(ok=False, reason="ledge", reads=["arrived: ''"]),
                    shop="pro_shop_survey_door_jump", clock=lambda: 0.0)
    shoplook.record(path, shoplook.ShopLook(ok=False, reason="walked all"),
                    shop="jelly_roll", clock=lambda: 0.0)
    six_h, later = 6 * 3600.0, shoplook.VIA_MISS_RETRY_SECONDS + 1
    assert shoplook.not_due(path, "pro_shop_survey_door_jump", six_h, clock=lambda: later) == ""
    assert "tried" in shoplook.not_due(path, "jelly_roll", six_h, clock=lambda: later)
