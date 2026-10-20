"""The new five-tab layout (gui/shell, ROADMAP U18). Offscreen. Nothing here
reads or writes the real ~/.config/hivemind, and the bot is a stand-in: Start
must never launch anything from a test."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

os.environ["HIVEMIND_TELEGRAM_ENV"] = str(Path(tempfile.mkdtemp()) / "telegram.env")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
import yaml  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from hivemind.gui.panels import settings as panel_mod  # noqa: E402
from hivemind.world import settings as schema  # noqa: E402

APP = QApplication.instance() or QApplication([])


class _Launch:
    ok = False

    def describe(self) -> str:
        return "not started (test)"


class FakeBot:
    process = None
    log_path = "nowhere"

    def __init__(self):
        self.starts = 0

    def running(self) -> bool:
        return False

    def start(self):
        self.starts += 1
        return _Launch()

    def describe_state(self) -> str:
        return ""

    def exit_code(self):
        return None


@pytest.fixture
def config(tmp_path, monkeypatch):
    path = tmp_path / "settings.yaml"
    monkeypatch.setattr(panel_mod, "CONFIG", path)
    monkeypatch.setattr(schema, "CONFIG", path)
    monkeypatch.setattr(schema.Settings.__init__, "__defaults__", (path,))
    # the start-on-boot card writes a login entry: never the real one
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    return path


@pytest.fixture
def shell(config):
    from hivemind.gui.bridge import EventBridge
    from hivemind.gui.shell import ShellWindow
    window = ShellWindow(EventBridge(), bot=FakeBot())
    window.sent = []
    window.bridge.send = lambda event: window.sent.append(event) or True
    yield window
    window.close()
    # FREED, NOT JUST CLOSED: nineteen whole windows outgrew the 900M test cap
    from PySide6.QtCore import QEvent
    window.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_it_builds_with_plan_first_and_the_old_tabs_hidden(shell):
    """choose-design 2026-10-26: PLAN, BOOSTING, STATS, SETTINGS; the old
    MACRO and AI PROGRESS tabs are hidden behind Advanced mode, never deleted."""
    shown = [b.text() for b in shell.tab_buttons.values() if not b.isHidden()]
    assert shown == ["PLAN", "BOOSTING", "STATS", "SETTINGS"]
    assert shell.tab_buttons["plan"].isChecked()
    assert shell.tab_stack.count() == 6
    for key in shell.tab_buttons:
        shell._show_tab(key)
        assert shell.tab_buttons[key].isChecked()
    shell.advanced_switch.click()
    assert not shell.tab_buttons["macro"].isHidden() and not shell.tab_buttons["ai"].isHidden()
    shell._show_tab("ai")
    shell.advanced_switch.click()                     # off again: back to Plan
    assert shell.tab_buttons["ai"].isHidden() and shell.tab_buttons["plan"].isChecked()


def test_advanced_mode_reveals_the_full_panels(shell, config):
    menu = shell._menus["settings"]
    labels = [menu.item(i).text() for i in range(menu.count())]
    assert "All settings" in labels and "Log" in labels
    hidden = [menu.item(r).text() for r in range(menu.count()) if menu.isRowHidden(r)]
    assert "All settings" in hidden and "General" not in hidden    # off by default
    shell.advanced_switch.click()
    assert shell.advanced_mode
    assert not any(menu.isRowHidden(r) for r in range(menu.count()))
    assert yaml.safe_load(config.read_text())["gui.mode"] == "advanced"
    shell.advanced_switch.click()
    assert not shell.advanced_mode and menu.isRowHidden(labels.index("Log"))


def test_the_bottom_bar_is_the_windows_own_run_controls(shell):
    assert [b.text() for b in shell.run_buttons] == ["Start", "Pause", "Stop"]
    assert shell.start_button.isEnabled() and not shell.stop_button.isEnabled()
    shell.start_button.click()
    assert shell.bot.starts == 1                     # MainWindow._start, reused
    assert shell.preset.itemText(0) == "Current settings"


def test_save_this_moment_sits_under_the_live_view_and_report_is_in_help(shell):
    """ROADMAP BUG-PACK: the button moved with the live view into Plan."""
    from hivemind.gui.shell import HelpPage
    from hivemind.telemetry.events import Action
    assert shell.moment_row.parentWidget() is shell.live.parentWidget()
    shell.moment_row.button.click()
    assert shell.sent[-1].action == Action.SAVE_MOMENT
    help_page = HelpPage("F12")
    assert help_page.report.button.text() == "Report a problem"
    assert any(title == "Report a problem" for title, _ in help_page.terms)


def test_a_card_saves_like_the_settings_panel(shell, config):
    card = shell._cards["gather.convert_at"][0]
    card.control.setValue(75)
    assert yaml.safe_load(config.read_text())["gather.convert_at"] == 75
    assert any(getattr(e, "name", "") == "setting:gather.convert_at" for e in shell.sent)
    # a change made elsewhere shows on the card, without saving it again
    shell.settings.set_value("gather.chase_tokens", False)
    assert shell._cards["gather.chase_tokens"][0].control.isChecked() is False


def test_only_working_settings_reach_the_simple_tabs(shell):
    assert all(schema.wired(key) for key in shell._cards)


def test_the_layout_setting_picks_the_window(config):
    from hivemind.gui import app
    from hivemind.gui.shell import ShellWindow
    from hivemind.gui.window import MainWindow
    assert app.window_class() is ShellWindow            # 'new' by default (owner, 19 Oct)
    config.write_text(yaml.safe_dump({"gui.layout": "classic"}))
    assert app.window_class() is MainWindow


# ---- round 2: field picker, item picker, search, Discord ------------------------
def test_the_field_picker_writes_the_same_settings(shell, config):
    card = shell._field_card
    assert card is not None and not card.change.isEnabled()      # AI picks by default
    assert card._name.text() == "AI picks"
    shell._cards["gather.auto_field"][0].control.click()          # switch the AI off
    assert card.change.isEnabled()
    card.open_picker()
    zones = [z for z, _ in __import__("hivemind.gui.gameicons", fromlist=["x"]).field_zones()]
    assert zones[0] == "Starter" and "35 Bee" in zones
    card.picker.tiles["Pine Tree"].click()
    saved = yaml.safe_load(config.read_text())
    assert saved["gather.auto_field"] is False and saved["gather.field"] == "Pine Tree"
    assert card._name.text() == "Pine Tree"
    # the classic panel's dropdown shows it too: one setting, two views
    assert shell.settings.values["gather.field"] == "Pine Tree"


def test_the_item_picker_filters():
    from hivemind.gui.shell import ItemPicker
    picker = ItemPicker()
    picker.search.setText("dice")
    assert picker.visible_items() == ["Field Dice", "Smooth Dice", "Loaded Dice"]
    picker.search.setText("royal jelly")
    assert picker.visible_items() == ["Royal Jelly"]
    picker.search.setText("nothing like this")
    assert picker.visible_items() == [] and not picker.empty.isHidden()
    got = []
    picker.picked.connect(got.append)
    picker.search.clear()
    picker.list.itemClicked.emit(picker.list.item(0))
    assert got == ["Glitter"]


def test_boosting_hotbar_page_saves_the_rules(shell, config):
    """$11: Boosting > Hotbar is the rules card, saved through the window's path."""
    assert shell.hotbar_rules.rules == []                       # default: no rules
    shell.hotbar_rules.add()
    saved = yaml.safe_load(config.read_text())["hotbar.rules"]
    assert saved == [{"item": "coconut", **schema.HOTBAR_ENTRY}]
    assert shell.settings.values["hotbar.rules"] == saved


def test_settings_token_priority_page_is_advanced_and_saves(shell, config):
    """ROADMAP T2: Settings > Token priority, after Gather, in Advanced mode,
    saved through the window's path into settings.yaml (never data/)."""
    menu = shell._menus["settings"]
    labels = [menu.item(i).text() for i in range(menu.count())]
    assert labels.index("Token priority") == labels.index("Gather") + 1
    assert menu.isRowHidden(labels.index("Token priority"))      # Advanced only
    shell.token_priority.use_suggestions()
    saved = yaml.safe_load(config.read_text())["gather.token_priority"]
    assert saved and all(r["hive"] == "blue" for r in saved)
    assert shell.settings.values["gather.token_priority"] == saved


def test_the_search_finds_a_setting_and_opens_its_page(shell):
    from hivemind.gui.shell import CommandPalette
    entries = shell.search_index()
    palette = CommandPalette(entries)
    palette.filter("micro-converter")
    target = palette.results.item(0).data(0x0100)                  # Qt.UserRole
    assert palette.results.item(0).data(0x0101).startswith("Convert a full bag")
    shell.go_to(target)
    assert getattr(shell, "search_flash", None) is None     # only the palette's jump lights
    shell.go_to(target, light=True)
    # THE HIT LIGHTS UP for 2.5 s (GUI polish 2026-10-27), over the card itself
    from hivemind.gui.widgets import FLASH_MS
    assert shell.search_flash.parentWidget() is target[3] and FLASH_MS == 2500
    assert shell.search_flash.geometry() == target[3].rect()
    # a simple page first: Settings > Features, not the hidden Macro tab
    assert shell.tab_buttons["settings"].isChecked() and not shell.advanced_mode
    page = shell._stacks["settings"].widget(shell._menus["settings"].currentRow())
    assert any(c.key == "gather.micro_convert" for c in shell._cards["gather.micro_convert"]
               if page.isAncestorOf(c))
    # a page on a hidden tab switches Advanced on and shows the tab
    palette.filter("patterns")
    shell.go_to(palette.results.item(0).data(0x0100))
    assert shell.advanced_mode and shell.tab_buttons["macro"].isChecked()
    shell.set_mode("simple")
    # a setting that lives only in the Advanced panels switches Advanced on
    palette.filter("zoom out while farming")   # gather.camera_zoom_out (plain-words label 2026-10-21)
    shell.go_to(palette.results.item(0).data(0x0100))
    assert shell.advanced_mode and shell.tab_buttons["settings"].isChecked()
    # pages and tabs are found too
    palette.filter("notifications")
    assert palette.results.item(0).data(0x0101) == "Notifications"
    shell.open_search()                     # the real palette's jump: a page lights up
    shell.command_palette.chosen.emit(palette.results.item(0).data(0x0100))
    shell.command_palette.close()
    assert shell.search_flash.parentWidget() is shell._stacks["settings"].currentWidget()


def test_search_finds_how_to_start_safety_and_uninstall_and_short_words_start_words(shell):
    """Usability triage 2026-10-27 #4: "afk", "ban" and "uninstall" found
    nothing, and "ram" found telegram / frames."""
    from hivemind.gui.shell import CommandPalette, matches
    assert matches("ban", "could be banned") and not matches("ban", "urban fields")
    assert not matches("ram", "telegram frames") and matches("ram", "free ram")
    assert matches("legr", "telegram")                     # 4+ letters: anywhere
    palette = CommandPalette(shell.search_index())
    for word, title in (("afk", "How to start"), ("ban", "Is it safe?"),
                        ("uninstall", "Remove it or report a problem"),
                        ("report", "Remove it or report a problem")):
        palette.filter(word)
        titles = [palette.results.item(i).data(0x0101) for i in range(palette.results.count())]
        assert title in titles, (word, titles)
    palette.filter("ram")
    titles = [palette.results.item(i).data(0x0101) or "" for i in range(palette.results.count())]
    assert not any("Telegram" in t for t in titles), titles


def test_the_bar_names_the_plan_and_a_click_opens_macro_gather(shell):
    """Usability triage 2026-10-27 #3/#11: the bar said "Macro" beside the
    Plan tab's "Your own setup", for a Macro tab simple mode hides."""
    assert shell._mode_label.text().startswith("Your own setup · ")
    assert not shell.advanced_mode
    shell._mode_label.click()
    assert shell.advanced_mode and shell.tab_buttons["macro"].isChecked()
    assert shell._menus["macro"].currentItem().text() == "Gather"


def test_hidden_feature_cards_leave_no_hole_in_the_grid(shell):
    """Usability triage 2026-10-27 #8: macro mode hides the AI's field cards
    and Features kept their empty cells."""
    shell.settings.set_value("mode.macro", True)
    shell._show_mode_label()
    rows = shell._menus["settings"]
    page = shell._stacks["settings"].widget(
        [rows.item(r).text() for r in range(rows.count())].index("Features"))
    for cards in page._groups:
        shown = [c for c in cards if not c.isHidden()]
        if not shown:
            continue
        grid = shown[0].parentWidget().layout()
        cells = [grid.getItemPosition(grid.indexOf(c))[:2] for c in shown]
        assert cells == [(i // 2, i % 2) for i in range(len(shown))]


def test_search_words_find_low_cpu_mode_on_the_general_page(shell):
    """ux report #10: 'gpu', 'lag', 'slow pc' found nothing, and Low CPU mode
    was in Advanced only. Its words (world/settings.SEARCH_WORDS) find it on
    the simple General page."""
    entries = shell.search_index()
    for words in ("cpu", "lag", "slow pc", "performance"):
        hits = [e for e in entries if all(w in e[2] for w in words.split())]
        low = [e for e in hits if e[0] == "AI mode"]
        assert low, words
        assert "General" in low[0][1] and "(Advanced)" not in low[0][1], low[0][1]
    assert set(schema.SEARCH_WORDS) <= set(schema.defaults())   # no stale keys
    # ux report 2026-10-27 #4/#23: "gpu" finds the vision model; the words
    # players type find a home. (Low CPU mode, which did not touch the card,
    # is the AI mode now, whose Max/Standard do -- AI-N4.)
    for word, label in (("gpu", "Use the local vision model"),
                        ("afk", "Stop after (hours)"),
                        ("reconnect", "Which server Start joins"),
                        ("ban", "Human-like timing"),
                        ("bundle", "Keep debug frames up to (GB)")):
        assert any(word in e[2] and e[0] == label for e in entries), word


def test_the_discord_field_validates_and_saves(tmp_path, monkeypatch):
    from hivemind.gui.panels import discord
    env = tmp_path / "discord.env"
    monkeypatch.setattr(discord.tg, "DISCORD_ENV", env)
    page = discord.DiscordPage()
    assert not page.test_button.isEnabled()
    for bad in ("https://example.com/api/webhooks/123456/abcdefghijklmnopqrstuvwxyz",
                "http://discord.com/api/webhooks/123456/abcdefghijklmnopqrstuvwxyz",
                "https://discord.com.evil.io/api/webhooks/123456/abcdefghijklmnopqrstu",
                "https://discord.com/api/webhooks/123456/abcdefghijklmnopqrst\nX=1"):
        page.url.setText(bad)
        assert page.save() is False and not env.exists()
    url = "https://discord.com/api/webhooks/1234567890/" + "a1B2_c3-" * 8
    page.url.setText(url)
    page.ping.setText("12ab")
    assert page.save() is False and not env.exists()               # not a user id
    page.ping.setText("123456789012345678")
    assert page.save() is True
    assert env.read_text() == f"DISCORD_WEBHOOK={url}\nDISCORD_PING=123456789012345678\n"
    assert os.name == "nt" or env.stat().st_mode & 0o777 == 0o600   # chmod is a no-op on Windows (MEASURED 2026-10-21: files come out 0o666); %LOCALAPPDATA% is the user's own
    assert page.url.text() == "" and url not in page._detail.text()   # never read back
    assert discord.tg.discord_env()["DISCORD_WEBHOOK"] == url       # what the service reads
    page.ping.setText("")                                         # ping-only change keeps the URL
    assert page.save() and env.read_text() == f"DISCORD_WEBHOOK={url}\n"
    # Send test runs the service's own --discord-test and never shows the URL
    ran = []

    class Done:
        stdout, stderr = "not sent: no valid DISCORD_WEBHOOK\n", f"discord: not sent ({url})\n"

    monkeypatch.setattr(discord.subprocess, "run", lambda cmd, **kw: ran.append(cmd) or Done)
    page._spawn = lambda job: job()
    page.test()
    APP.processEvents()
    assert ran[0][0] == "/usr/bin/python3" and ran[0][-1] == "--discord-test"
    assert url not in page._detail.text() and "<webhook>" in page._detail.text()
    # FREED: left to PySide's exit-time teardown, this page crashed the run
    # after every test had passed (seen alone with -k, and with U12's page)
    from PySide6.QtCore import QEvent
    page.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def test_every_card_on_every_tab_really_saves(shell, config):
    """The owner, 2026-10-19: every option, toggle, setting and button must
    work. Every enabled card is changed once, through its own control, and
    the new value must be in settings.yaml and the bot must have been told."""
    from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QLineEdit, QSpinBox
    checked = 0
    for key, cards in shell._cards.items():
        c = cards[0].control
        if not c.isEnabled():
            continue
        if isinstance(c, QComboBox):
            if c.count() < 2:
                continue
            want = c.itemText((c.currentIndex() + 1) % c.count())
            c.setCurrentText(want)
        elif isinstance(c, (QSpinBox, QDoubleSpinBox)):
            want = c.value() + c.singleStep() if c.value() < c.maximum() else c.value() - c.singleStep()
            c.setValue(want)
            want = c.value()
        elif isinstance(c, QLineEdit):
            want = (c.text() or "x") + "1"
            c.setText(want)
            c.editingFinished.emit()
        else:                                         # the Toggle switch
            want = not c.isChecked()
            c.setChecked(want)
        # A SECRET (server.link) is saved to secrets.env, never settings.yaml
        from hivemind.world.settings import SECRET, read_secrets
        saved = (read_secrets(config).get(key) if key in SECRET
                 else yaml.safe_load(config.read_text()).get(key))
        assert saved == want or str(saved) == str(want), f"{key}: shows {want!r}, saved {saved!r}"
        if not key.startswith("gui."):           # gui.* is the window's own, never sent to the bot
            assert any(getattr(e, "name", "") == f"setting:{key}" for e in shell.sent), f"{key}: bot not told"
        checked += 1
    assert checked >= 20, f"only {checked} cards were checked"


# ---- macro mode (ROADMAP U16): the field list and its editor ---------------------
def _saved(config, key):
    return yaml.safe_load(config.read_text()).get(key)


def test_the_macro_mode_switch_saves_and_tells_the_bot(shell, config):
    card = shell.macro_mode
    assert card.ai.isChecked() and not card.macro.isChecked()        # off by default
    card.macro.click()
    assert _saved(config, "mode.macro") is True
    assert any(getattr(e, "name", "") == "setting:mode.macro" for e in shell.sent)
    shell.settings.set_value("mode.macro", False)                    # from elsewhere
    assert card.ai.isChecked()


def test_the_field_list_adds_edits_reorders_and_deletes(shell, config):
    from hivemind.world.settings import MACRO_ENTRY
    box = shell.macro_list
    assert not box.empty.isHidden() and box.editor.isHidden()        # the empty state
    box.open_picker()
    box.picker.tiles["Pine Tree"].click()                            # "+" then a field
    box.add("Rose")
    assert _saved(config, "macro.fields") == [
        {"field": "Pine Tree", **MACRO_ENTRY}, {"field": "Rose", **MACRO_ENTRY}]
    assert box.selected == 1 and not box.editor.isHidden()
    # the editor writes the chosen card
    box.minutes.setValue(0)
    box.pattern.setCurrentIndex(box.pattern.findData("farm_square"))
    box.convert_at.setValue(75)
    box.back.setCurrentIndex(box.back.findData("respawn"))
    box.sprinklers.setValue(0)
    rose = {"field": "Rose", "minutes": 0, "pattern": "farm_square", "convert_at": 75,
            "return": "respawn", "sprinklers": 0}
    assert _saved(config, "macro.fields")[1] == rose
    assert box.rows[1].summary.text() == ("until full · Square, small (64 studs) · "
                                          "home at 75% · respawn · no sprinkler")
    assert any(getattr(e, "name", "") == "setting:macro.fields" for e in shell.sent)

    def act(row, text):
        next(a for a in box.rows[row].menu.actions() if a.text() == text).trigger()

    act(1, "Move up")
    assert [e["field"] for e in _saved(config, "macro.fields")] == ["Rose", "Pine Tree"]
    assert box.selected == 0 and box._edit_name.text() == "1. Rose"
    act(0, "Copy")
    act(1, "Paste")                                   # Rose's settings, Pine Tree kept
    assert _saved(config, "macro.fields")[1] == {**rose, "field": "Pine Tree"}
    act(1, "Default")
    assert _saved(config, "macro.fields")[1] == {"field": "Pine Tree", **MACRO_ENTRY}
    act(0, "Delete")
    assert _saved(config, "macro.fields") == [{"field": "Pine Tree", **MACRO_ENTRY}]
    assert [a.isEnabled() for a in box.rows[0].menu.actions()
            if a.text().startswith("Move")] == [False, False]
    # Change field on the editor
    box.open_picker(replace=True)
    box.picker.tiles["Clover"].click()
    assert _saved(config, "macro.fields")[0]["field"] == "Clover"
    # what the bot reads back is exactly what was saved (nothing left out)
    assert schema.Settings(config).get("macro.fields") == _saved(config, "macro.fields")
    act(0, "Delete")
    assert _saved(config, "macro.fields") == [] and box.editor.isHidden()


def test_a_list_saved_elsewhere_shows_on_the_cards(shell, config):
    shell.settings.set_value("macro.fields", [{"field": "Bamboo", "minutes": 20, "pattern": "field",
                                               "convert_at": 90, "return": "walk", "sprinklers": 2}])
    assert [r.summary.text() for r in shell.macro_list.rows] == [
        "20:00 · The field's own · home at 90% · walk · 2 sprinklers"]
    shell.settings.set_value("mode.macro", True)
    assert shell._mode_label.text() == "Your own setup · 1 field"     # the Plan radio's name


def test_the_saved_list_is_loaded_when_the_window_opens(config):
    from hivemind.gui.bridge import EventBridge
    from hivemind.gui.shell import ShellWindow
    config.write_text(yaml.safe_dump({"mode.macro": True, "macro.fields": [
        {"field": "Stump"}, {"field": "Nowhere"}]}))
    window = ShellWindow(EventBridge(), bot=FakeBot())
    try:
        # the bad one is SHOWN with its warning, and left out of what the bot
        # uses (render probe, UI panel round 2, 2026-10-22: dropped at load,
        # the warning could never fire)
        assert [r.index for r in window.macro_list.rows] == [0, 1]
        assert "Nowhere" in window.macro_list.warning.text()
        assert [e["field"] for e in window.settings.values["macro.fields"]] == ["Stump"]
        assert window.macro_mode.macro.isChecked()
        assert any("Nowhere" in p for p in window.settings.problems)
    finally:
        window.close()


def test_macro_mode_hides_the_ais_field_cards(shell, config):
    """They do nothing in macro mode, so they are not shown there (19 Oct)."""
    shell.settings.set_value("mode.macro", True)
    shell._show_mode_label()
    assert all(not c.isVisibleTo(shell) for k in shell.AI_FIELD_KEYS for c in shell._cards.get(k, []))
    shell.settings.set_value("mode.macro", False)
    shell._show_mode_label()
    # "Hivemind chooses" IS the AI's pick: its own switch shows only to unpin
    # a field pinned before (UI panel 2026-10-21 item 12)
    assert all(not c.isHidden() for k in shell.AI_FIELD_KEYS if k != "gather.auto_field"
               for c in shell._cards.get(k, []))
    on_gather = [c for c in shell._cards["gather.auto_field"] if shell._gather_page.isAncestorOf(c)]
    elsewhere = [c for c in shell._cards["gather.auto_field"] if c not in on_gather]
    assert on_gather and all(c.isHidden() for c in on_gather)
    assert all(not c.isHidden() for c in elsewhere)        # Features lists every switch
    shell.settings.set_value("gather.auto_field", False)
    assert all(not c.isHidden() for c in shell._cards["gather.auto_field"])
    assert not shell._field_card.isHidden()


def test_a_pill_over_nothing_is_hidden_and_an_empty_list_is_said(shell, config):
    page = shell._gather_page
    shell.settings.set_value("mode.macro", True)
    shell.settings.set_value("macro.fields", [])
    assert shell._mode_label.text() == "Your own setup · No valid fields: add one with +"
    for card in page._groups[1]:
        card.hide()                                  # a group with nothing to show
    page.pills[1].click()
    page.sync_pills()
    assert page.pills[1].isHidden() and not page.pills[0].isHidden()
    assert page.stack.currentIndex() == 0            # moved off the empty group


# ---- the Boosting tab (ROADMAP U19) ------------------------------------------------
def test_the_boosting_tab_shows_each_boosts_timer_live_and_its_cards(shell):
    import time
    from hivemind.telemetry.events import Timer
    now = time.time()
    shell.handle(Timer(id="boost_running", category="boost", name="Boost · pine tree x2",
                       ready_at=now + 300))
    shell.handle(Timer(id="booster:blue_field_booster", category="booster",
                       name="Blue Field Booster", ready_at=now - 5))
    shell.handle(Timer(id="item:glue", category="item", name="Glue", ready_at=now + 90))
    shell.handle(Timer(id="crab", category="boss", name="Coconut Crab", ready_at=now + 90))
    tiles = shell.boost_strip.tiles
    assert tiles["boost_running"].name.text() == "Field boost · pine tree x2"
    assert tiles["boost_running"].left.text().endswith("left")
    assert tiles["booster:blue_field_booster"].left.text() == "ready"
    assert tiles["booster:red_field_booster"].left.text() == "not pressed yet"
    assert "item:glue" in tiles and "crab" not in tiles
    for key in ("boost.keeper", "boost.boosters", "boost.glitter", "boost.dice",
                "boost.item_buffs", "boost.ai"):
        assert key in shell._cards, key


def test_the_boost_ai_page_says_what_is_not_measured(tmp_path):
    import json
    from hivemind.gui.panels.boosting import MeasuredGains
    (tmp_path / "boosts.jsonl").write_text(json.dumps(
        {"at": 1.0, "booster": "field_dice", "field": None}) + "\n")
    page = MeasuredGains(var=tmp_path)
    page.reload()
    assert page.gains == {} and "Pine Tree" in page.not_yet
    assert "0 of 1 rolls" in page.missing.text() and "not measured" in page.missing.text()



def test_the_pattern_studio_feeds_the_macro_pattern_box(shell, config):
    """T17: Macro > Patterns; a pattern saved there is offered (and saved) in
    a field's Pattern box as its routine name, beside settings.yaml."""
    menu = shell._menus["macro"]
    rows = [menu.item(i).text() for i in range(menu.count())]
    assert rows[:2] == ["Gather", "Patterns"]
    studio = shell.pattern_studio
    assert studio.folder == config.parent / "patterns"
    studio.new()
    studio.name.setText("Tight loop")
    studio.name.textEdited.emit("Tight loop")
    assert studio.save()
    box = shell.macro_list
    box.add("Clover")
    index = box.pattern.findData("user_pattern_tight_loop")
    assert index >= 0 and box.pattern.itemText(index) == "Yours: Tight loop"
    box.pattern.setCurrentIndex(index)
    assert _saved(config, "macro.fields")[0]["pattern"] == "user_pattern_tight_loop"
    assert "Yours: tight loop" in box.rows[0].summary.text()
    assert schema.Settings(config).get("macro.fields")[0]["pattern"] == "user_pattern_tight_loop"
    studio.delete()                              # deleted: kept on the card, said
    assert box.pattern.currentText().endswith("(not saved)")


def test_the_features_page_lists_every_feature_with_its_badge(shell, config):
    """U12: Settings > Features, from world/settings.FEATURES, saving through
    the same path as every other card."""
    from hivemind.gui.shell import CardPage
    from hivemind.world.settings import FEATURES
    menu, stack = shell._menus["settings"], shell._stacks["settings"]
    row = [menu.item(i).text() for i in range(menu.count())].index("Features")
    page = stack.widget(row)
    assert isinstance(page, CardPage) and not page.pills          # one page, headings
    assert list(page.where) == [key for _, key, *_ in FEATURES]
    badges = {lab.property("kind") for lab in page.findChildren(QLabel) if lab.objectName() == "Badge"}
    assert badges == {b for *_, b in FEATURES}
    # shown in plain words with a shape (UI panel round 2, 2026-10-22)
    assert "◌ watch only" in {lab.text() for lab in page.findChildren(QLabel)}
    card = page.where["economy.memory_match"][1]
    was = card.control.isChecked()
    card.control.click()
    assert yaml.safe_load(config.read_text())["economy.memory_match"] is (not was)


def test_the_run_state_has_a_shape_and_a_word_not_just_a_colour(shell):
    """UI panel 2026-10-21: the bare dot was red/green only, and red whenever
    the socket was down -- an idle app looked broken to 7 of 8 readers."""
    from types import SimpleNamespace
    from hivemind.gui.shell import run_look
    def st(**kw):
        base = dict(_handed_over=False, _running=False, _paused=False, _connected=False)
        return SimpleNamespace(**{**base, **kw})
    looks = {run_look(st(), False)[:2], run_look(st(_running=True), True)[:2],
             run_look(st(_running=True, _paused=True), True)[:2],
             run_look(st(), True)[:2], run_look(st(), False, exit_code=1)[:2]}
    assert {g for g, _ in looks} == {"■", "▶", "❚❚", "◌", "⚠"}       # five shapes
    assert run_look(st(), False)[1] == "Stopped"                   # idle is not red
    assert run_look(st(), False)[2] != run_look(st(), False, exit_code=1)[2]
    shell._sync_bar()
    assert shell._word.text() == "■  Stopped" and shell._dot.isHidden()
    assert shell._state.text() == "Press Start (F1) to begin."
    shell.status.set_status(running=True, paused=False, note="gathering")
    assert shell._word.text() == "▶  Running" and shell._state.text() == "gathering"
    assert shell._dot.pulsing


def test_a_replay_says_demo_replay_not_running(shell):
    """UI panel round 2 (2026-10-22): a demo replay read as a running bot."""
    shell.set_replay_banner("session.jsonl")
    shell.status.set_status(running=True, paused=False, note="gathering")
    assert shell._word.text() == "◌  Demo replay"
    assert shell._state.text() == "gathering"            # not "running — gathering"
    assert not shell.stop_button.property("primary")
    assert not shell._dot.pulsing


def test_empty_pages_do_not_say_press_start_while_it_runs(shell):
    """UI panel round 2 (2026-10-22): 7 of 8 read "Press Start" under a bar
    that said Running (Live view, Stats graphs)."""
    from hivemind.gui.panels import liveview, graphs
    shell.live._degrade("frame not found: x")
    assert shell.live._hint.text() == liveview.NO_PICTURE
    shell.status.set_status(running=True, paused=False, note="gathering")
    assert shell.live._hint.text() == liveview.NO_PICTURE_RUNNING
    assert shell.stats_graphs.empty.line.text() == graphs.EMPTY_RUNNING
    shell.status.set_status(running=False, paused=False, note="idle")
    assert shell.live._hint.text() == liveview.NO_PICTURE
    assert shell.stats_graphs.empty.line.text() == graphs.EMPTY_IDLE


def test_stop_is_the_highlighted_button_while_it_runs(shell):
    assert shell.start_button.property("primary") and not shell.stop_button.property("primary")
    shell.status.set_status(running=True, paused=False)
    assert shell.stop_button.property("primary") and not shell.start_button.property("primary")
    assert not shell.start_button.isEnabled()


def test_the_bar_does_not_say_idle_twice(shell):
    shell.task_label.setText("idle")
    shell.status.set_status(running=False, paused=False, note="idle")
    assert shell._doing.isHidden()
    shell.task_label.setText("gathering — Pine Tree")
    shell._show_doing()
    assert not shell._doing.isHidden()


def test_a_field_the_bot_would_drop_is_warned_about(shell, config):
    lst = shell.macro_list
    lst.show_fields([{"field": "Pine Tree"}, {"field": "No Such Meadow"}])
    assert not lst.warning.isHidden()
    assert "skips 1" in lst.warning.text() and "No Such Meadow" in lst.warning.text()
    lst.delete(1)
    assert lst.warning.isHidden()


def test_the_share_link_is_dots_until_show_is_held(shell):
    from PySide6.QtWidgets import QLineEdit
    card = shell._cards["server.link"][0]
    assert card.control.echoMode() == QLineEdit.Password
    card.reveal.setChecked(True)
    assert card.control.echoMode() == QLineEdit.Normal and card.reveal.text() == "Hide"
    card.show()
    card.hide()                                    # leaving the page hides it again
    assert card.control.echoMode() == QLineEdit.Password


def test_the_help_page_explains_the_words_and_the_search_finds_them(shell):
    menu = shell._menus["settings"]
    rows = [menu.item(r).text() for r in range(menu.count())]
    assert rows.index("Help") == rows.index("Credits") - 1
    hits = [e for e in shell.search_index() if "gifted" in e[2] and e[1].startswith("Help")]
    assert hits and hits[0][3][0] == "settings"
    page = shell._stacks["settings"].widget(rows.index("Help"))
    words = {w for w, _ in page.terms}
    assert {"Convert", "Studs", "Gifted", "Royal Jelly", "Nectar", "Pollen"} <= words
    labels = [c.findChild(QLabel).text() for c in shell._cards["safety.panic_key"]]
    assert "Emergency stop key" in labels


def test_general_opens_with_the_safety_card(shell):
    text = shell.safety.body.text()
    assert "Never spends Robux" in text and "password" in text and "F3" in text
    assert "Roblox's rules" in text and "own risk" in text
    shell.settings.set_value("safety.panic_key", "F10")
    assert "F10" in shell.safety.body.text()


def test_general_asks_about_updates_once_and_contacts_nothing_until_yes(shell, config):
    """U15f: off by default, the question shows while never chosen, and the
    card follows the setting however it is changed (gui/updater)."""
    card = shell.updates
    card._check_fn = lambda: pytest.fail("contacted GitHub while off")
    assert not card.question.isHidden() and not card.check_button.isEnabled()
    assert card.install_button.isHidden()
    card._check_fn = lambda: (None, "Hivemind 0.1.0 is the newest")
    card._run = lambda work: work()
    shell._cards["gui.check_updates"][0].control.setChecked(True)
    assert _saved(config, "gui.check_updates") is True
    assert card.question.isHidden() and card.check_button.isEnabled()
    card.check_button.click()
    assert "is the newest" in card.line.text()


def test_the_switch_knob_slides_and_pages_crossfade(shell):
    from hivemind.gui.shell import Toggle
    shell.show()
    APP.processEvents()
    switch = shell.advanced_switch
    assert isinstance(switch, Toggle)
    shell._show_tab("settings")
    APP.processEvents()
    switch.setChecked(True)                          # a click's toggled: it glides
    from PySide6.QtCore import QAbstractAnimation
    assert switch._glide.state() == QAbstractAnimation.Running
    switch._glide.setCurrentTime(switch._glide.duration())
    assert switch._glide.now == 1.0
    menu = shell._menus["settings"]
    menu.setCurrentRow(1)
    assert shell._stacks["settings"].currentIndex() == 1     # shown at once, faded over
    covers = [c for c in shell._stacks["settings"].children()
              if type(c).__name__ == "QLabel" and c.pixmap() is not None and not c.pixmap().isNull()]
    assert covers, "no fading picture of the old page"


def test_the_overview_shows_the_latest_decision(shell):
    from hivemind.telemetry.events import Considered, Option
    shell.handle(Considered(question="Convert now?", options=[Option("convert at 90%", 1.0)],
                            chosen="convert at 90%", rationale="It keeps the bag from overflowing."))
    assert shell._thinking.body.text() == "It chose “convert at 90%”."      # one line
    assert "overflowing" in shell._thinking.body.toolTip()                 # the why on hover
    from hivemind.gui.shell import _first_sentence
    assert _first_sentence("Pine Tree next. It pays 12% more.") == "Pine Tree next."
    assert _first_sentence("no stop") == "no stop"


def test_bars_ease_in_the_new_window(shell):
    from hivemind.gui.widgets import Meter, Ring
    assert Meter.ease_ms > 0 and Ring.ease_ms > 0


def test_number_boxes_fit_their_number(shell):
    """Render probe, UI panel round 2 (2026-10-22): 96 px boxes cut 50000000
    and "Stop after (hours)" read "0.00"."""
    box = shell._cards["safety.max_session_h"][0].control
    assert box.decimals() == 1 and box.minimumWidth() >= 130


def test_the_empty_field_list_follows_who_chooses(shell):
    """UI panel round 2 (2026-10-22): "Press +" under "Hivemind chooses"."""
    from hivemind.gui.shell import EMPTY_LIST, EMPTY_LIST_AI
    shell._save_card("mode.macro", False)
    assert shell.macro_list.empty.text() == EMPTY_LIST_AI
    shell._save_card("mode.macro", True)
    assert shell.macro_list.empty.text() == EMPTY_LIST



def test_the_palette_says_ai_not_ai(shell):
    """UI panel round 2 (2026-10-22): .title() showed "Ai Progress"."""
    tabs = {t for t, where, *_ in shell.search_index() if where == "Tab"}
    assert "AI progress" in tabs and "Ai Progress" not in tabs


def test_a_help_dot_shows_its_help_on_a_click():
    """A tester, 2026-10-22: clicking the (?) did nothing."""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication, QToolTip
    from hivemind.gui.shell import HelpDot
    QApplication.instance() or QApplication([])
    dot = HelpDot("?")
    dot.setToolTip("the help text")
    dot.show()
    press = QMouseEvent(QEvent.MouseButtonPress, QPointF(4, 4), QPointF(4, 4),
                        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    dot.mousePressEvent(press)
    assert QToolTip.isVisible() and QToolTip.text() == "the help text"
