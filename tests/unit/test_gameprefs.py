"""The game's own settings (platform/gameprefs), on a copy of the owner's
Sober file (MEASURED 2026-10-26; only the item's referent id scrubbed)."""
from __future__ import annotations

import shutil
from pathlib import Path

from hivemind.cli import doctor
from hivemind.platform import gameprefs

import hivemind

# through the package: the deploy gate runs a copy of this file from the live tree
FIXTURE = (Path(hivemind.__file__).resolve().parents[2] / "tests" / "fixtures" / "gameprefs"
           / "GlobalBasicSettings_13.xml")


def _copy(tmp_path, **changes) -> Path:
    path = tmp_path / FIXTURE.name
    shutil.copy(FIXTURE, path)
    text = path.read_text(encoding="utf-8")
    for name, value in changes.items():
        old = gameprefs.read(path)[name]
        text = text.replace(f'name="{name}">{old}<', f'name="{name}">{value}<')
    path.write_text(text, encoding="utf-8")
    return path


def test_the_owners_measured_file_has_nothing_wrong():
    values = gameprefs.read(FIXTURE)
    assert values["ControlMode"] == "1" and values["FramerateCap"] == "240"
    assert set(gameprefs.RULES) <= set(values)       # every rule is in a real file
    assert gameprefs.problems(values) == []


def test_each_wrong_setting_is_named_with_its_fix(tmp_path):
    path = _copy(tmp_path, ControlMode="0", ComputerCameraMovementMode="2",
                 ComputerMovementMode="2", PreferredTextSize="3", FramerateCap="30",
                 SavedQualityLevel="0", PerformanceStatsVisible="true")
    found = {name: (wrong, breaks) for name, wrong, _, breaks in
             gameprefs.problems(gameprefs.read(path))}
    assert found["ControlMode"] == ("Shift Lock Switch is off", True)
    assert found["ComputerCameraMovementMode"] == ("Camera Mode is Follow", True)
    assert found["ComputerMovementMode"][1] is True
    assert found["PreferredTextSize"] == ("Text Size is Larger", False)
    assert found["FramerateCap"] == ("Maximum Frame Rate is 30", False)
    assert found["SavedQualityLevel"] == ("Graphics Quality is Automatic", False)
    assert "PerformanceStatsVisible" in found and len(found) == 7
    before = path.read_text(encoding="utf-8")
    lines = gameprefs.start_lines(False, path, running=lambda: False)
    assert lines[0].startswith("BREAKS THE BOT: Shift Lock Switch is off -- in Roblox's Settings")
    assert path.read_text(encoding="utf-8") == before                               # fix off: untouched
    assert len(list(tmp_path.iterdir())) == 1                                        # and no backup


def test_no_cap_is_fine():
    assert gameprefs.problems({"FramerateCap": "-1"}) == []
    assert gameprefs.problems({"FramerateCap": "0"}) == []


def test_the_fix_writes_only_with_the_game_closed_and_keeps_a_backup(tmp_path):
    path = _copy(tmp_path, ControlMode="0", FramerateCap="30")
    before = path.read_text(encoding="utf-8")
    assert "game is open" in gameprefs.fix(path, running=lambda: True)
    assert path.read_text(encoding="utf-8") == before
    lines = gameprefs.start_lines(True, path, running=lambda: False)
    assert lines[0] == next(l for l in lines if l.startswith("fixing them: set ControlMode 1"))
    # the cap is never written, so it is still named after the fix
    assert lines[1:] == [l for l in lines[1:] if "Maximum Frame Rate is 30" in l]
    after = path.read_text(encoding="utf-8")
    assert after == before.replace('"ControlMode">0<', '"ControlMode">1<')   # one value, nothing else
    backups = [p for p in tmp_path.iterdir() if ".hivemind-" in p.name]
    assert len(backups) == 1 and backups[0].read_text(encoding="utf-8") == before
    assert gameprefs.settings_file(tmp_path) == path           # the backup is not taken for it


def test_unsure_whether_the_game_runs_counts_as_running(monkeypatch):
    from hivemind.platform import startfails
    monkeypatch.setattr(gameprefs, "WINDOWS", False)
    for out, running in [("(nothing, exit 0)", False), ("(could not run: x)", True),
                         ("(nothing, exit 1)", True), ("1\t2\torg.kde.konsole\tx", False),
                         ("1\t2\torg.vinegarhq.Sober\tx", True)]:
        monkeypatch.setattr(startfails, "flatpak_instances", lambda o=out: o)
        assert gameprefs.game_running() is running, out


def test_newest_numbered_file_wins(tmp_path):
    for n in (9, 13, 10):
        (tmp_path / f"GlobalBasicSettings_{n}.xml").write_text("", encoding="utf-8")
    assert gameprefs.settings_file(tmp_path).name == "GlobalBasicSettings_13.xml"
    assert gameprefs.settings_file(tmp_path / "none") is None


def test_doctor_names_a_breaking_setting_as_a_fail(tmp_path, monkeypatch):
    path = _copy(tmp_path, ControlMode="0")
    monkeypatch.setattr(gameprefs, "settings_file", lambda: path)
    [check] = doctor.game_settings()
    assert (check.status, check.detail) == (doctor.FAIL, "Shift Lock Switch is off")
    assert "Shift Lock Switch On" in check.fix
    monkeypatch.setattr(gameprefs, "settings_file", lambda: None)
    assert doctor.game_settings()[0].status == doctor.WARN


def test_roblox_studio_s_settings_file_is_never_taken(tmp_path):
    """MEASURED 2026-10-27 on Windows: GlobalBasicSettings_13.xml sits beside
    GlobalBasicSettings_13_Studio.xml, and the old glob judged Studio's."""
    from hivemind.platform import gameprefs
    for name in ("GlobalBasicSettings_13.xml", "GlobalBasicSettings_13_Studio.xml",
                 "GlobalBasicSettings_9.xml"):
        (tmp_path / name).write_text("<roblox/>", encoding="utf-8")
    assert gameprefs.settings_file(tmp_path).name == "GlobalBasicSettings_13.xml"
    (tmp_path / "GlobalBasicSettings_13.xml").unlink()
    assert gameprefs.settings_file(tmp_path).name == "GlobalBasicSettings_9.xml"
