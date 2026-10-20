"""The app's words name the buttons and the panic key as they really are.

A review of the Linux first-run check found it said "before Play will work"
(no button says Play: they say Start) and "The panic key is F12" whatever
`safety.panic_key` was set to. The words now say Start and read the setting.
"""
from hivemind.cli import doctor
from hivemind.gui import launcher
from hivemind.gui.app import first_run_check
from hivemind.world import settings as settings_mod
from hivemind.world.settings import panic_key_name


class Broken:
    def get(self, key):
        raise OSError("unreadable")


def test_panic_key_name_reads_the_setting_and_falls_back_to_f12():
    assert panic_key_name({"safety.panic_key": "F9"}) == "F9"
    assert panic_key_name({"safety.panic_key": "  Pause "}) == "Pause"
    assert panic_key_name({"safety.panic_key": ""}) == "F12"
    assert panic_key_name({}) == "F12"
    assert panic_key_name(Broken()) == "F12"          # never raises


def test_the_default_panic_key_is_still_f12():
    assert settings_mod.defaults()["safety.panic_key"] == "F12"


def test_first_run_text_says_start_and_the_configured_key(tmp_path):
    marker = tmp_path / "first-run-passed"
    bad = [doctor.Check("environment", "Flatpak", doctor.FAIL, fix="sudo apt install flatpak")]
    text = first_run_check(marker=marker, run=lambda: bad,
                           settings={"safety.panic_key": "F9"})
    assert "before Start will work" in text and "Play" not in text
    text = first_run_check(marker=marker, run=lambda: [doctor.Check("g", "n", doctor.OK)],
                           settings={"safety.panic_key": "F9"})
    assert "The panic key is F9." in text and "F12" not in text and "Play" not in text


def test_first_run_text_reads_the_settings_file_when_none_is_given(tmp_path, monkeypatch):
    class Fake:
        def get(self, key):
            return {"safety.panic_key": "F8"}.get(key)
    monkeypatch.setattr(settings_mod, "Settings", Fake)
    text = first_run_check(marker=tmp_path / "m", run=lambda: [doctor.Check("g", "n", doctor.OK)])
    assert "The panic key is F8." in text


def test_the_launchers_kill_message_names_the_configured_key(monkeypatch):
    class Fake:
        def get(self, key):
            return {"safety.panic_key": "F7"}.get(key)
    monkeypatch.setattr(settings_mod, "Settings", Fake)
    assert launcher._panic_key() == "F7"
    source = open(launcher.__file__, encoding="utf-8").read()
    assert "panic key (F12)" not in source and "key (F12)" not in source
