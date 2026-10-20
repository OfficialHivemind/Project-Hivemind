"""The doctor.

Its own failure mode is the interesting one: a diagnostic that crashes on a
broken machine is useless precisely when you need it. So each section is wrapped
and a section that raises becomes a FAIL line rather than a traceback.
"""
from hivemind.cli import doctor


def test_runs_without_raising():
    checks = doctor.run()
    assert checks


def test_every_check_is_well_formed():
    for check in doctor.run():
        assert check.status in (doctor.OK, doctor.WARN, doctor.FAIL)
        assert check.name
        assert check.group


def test_failures_carry_a_fix():
    """A failure with no instruction is a dead end."""
    for check in doctor.run():
        if check.status == doctor.FAIL and check.name != "check itself":
            assert check.fix, f"{check.name} failed with no suggested fix"


def test_failures_carry_a_fix_when_things_are_genuinely_missing(tmp_path,
                                                                monkeypatch):
    """The test above asserts NOTHING on a healthy machine.

    doctor.run() returns 20 checks with 0 FAILs here, so its loop body never
    executes -- which is exactly how four calibration checks shipped with no
    fix= argument at all. This one points the data root at an empty directory
    so the file checks genuinely fail, and only then asserts.
    """
    monkeypatch.setattr(doctor, "data",
                        lambda *parts: tmp_path.joinpath(*parts))
    checks = doctor.calibration()
    failed = [c for c in checks if c.status == doctor.FAIL]
    assert len(failed) >= 5, f"expected missing files to FAIL, got {checks}"
    for check in failed:
        assert check.fix, f"{check.name} failed with no suggested fix"


def test_a_raising_section_becomes_a_finding(monkeypatch):
    def explode():
        raise RuntimeError("no /dev at all")
    # calibration, not environment: Windows runs cli/doctor_win's environment
    # (doctor.sections), and calibration is checked on both
    monkeypatch.setattr(doctor, "calibration", explode)
    checks = doctor.run()
    broken = [c for c in checks if c.name == "check itself"]
    assert broken and broken[0].status == doctor.FAIL
    # and the other sections still ran
    assert len(checks) > 1


def test_exit_code_reflects_failures(monkeypatch, capsys):
    monkeypatch.setattr(doctor, "run",
                        lambda: [doctor.Check("g", "n", doctor.OK)])
    assert doctor.main() == 0
    monkeypatch.setattr(doctor, "run",
                        lambda: [doctor.Check("g", "n", doctor.FAIL, fix="do x")])
    assert doctor.main() == 1


def test_the_panic_key_is_checked_as_a_hard_requirement():
    """Running unattended with no panic key is not a warning-level problem."""
    names = [c.name for c in doctor.safety()]
    assert any("panic key" in n for n in names)
    for check in doctor.safety():
        assert check.status in (doctor.OK, doctor.FAIL)   # never merely a warning


def test_low_memory_and_no_vision_model_say_what_to_do(monkeypatch):
    """U15: a beginner learns about the 6 GB start floor and the missing
    vision model from doctor, not from a refused Start."""
    from hivemind.brain import vlm
    from hivemind.platform import memory
    monkeypatch.setattr(memory, "read", lambda: memory.Memory(2.0, 8.0, 0.0, 0.0))
    low = doctor.memory_check()
    # FAIL, so the doctor never says "Everything is here" to a PC whose Start
    # will be refused (the ux report's #1)
    assert low.status == doctor.FAIL and "Close big programs" in low.fix
    assert "Everything Hivemind needs is here." not in doctor.report([low], "arch")
    monkeypatch.setattr(memory, "read", lambda: memory.Memory(12.0, 16.0, 0.0, 0.0))
    assert doctor.memory_check().status == doctor.OK

    class NoServer:
        enabled, model = True, "qwen2.5vl:7b"
        reason = "no model server at http://127.0.0.1:11434 (refused) — sudo pacman -S x"

        def available(self):
            return False
    monkeypatch.setattr(vlm, "from_settings", lambda: NoServer())
    on_debian = doctor.vision_model_check("debian")
    assert on_debian.status == doctor.WARN
    assert "ollama.com" in on_debian.fix and "pacman" not in on_debian.fix
    on_arch = doctor.vision_model_check("arch").fix
    assert "pacman" in on_arch and on_arch.endswith("ollama pull qwen2.5vl:7b")
    assert "refused" not in on_arch                      # no raw error in the fix


def test_memory_says_needs_and_has_and_report_flags_non_package_fails(monkeypatch):
    from hivemind.platform import memory
    monkeypatch.setattr(memory, "read", lambda: memory.Memory(5.0, 8.0, 0.0, 0.0))
    low = doctor.memory_check()
    assert "needs 6 GB free to start, you have 5.0 GB" in low.fix
    assert "needs 6 GB free, you have 5.0 GB" in memory.check("the game")[1]
    missing = doctor.Check("environment", "Flatpak", doctor.FAIL, key="flatpak")
    text = doctor.report([missing, low], "arch")
    assert "One command" in text and "does not fix every" in text
    assert "does not fix every" not in doctor.report([missing], "arch")


def test_server_check_reads_server_join(monkeypatch):
    """A fresh install (no server.yaml, server.join at its default) joins the
    private server: no "public servers" warning. Only a share-link choice
    with no link warns."""
    from hivemind.world import settings as settings_mod

    def first_line(values):
        class Fake:
            problems = []

            def get(self, key, fallback=None):
                return values.get(key, fallback)
        monkeypatch.setattr(settings_mod, "Settings", Fake)
        return doctor.state()[0]

    fresh = first_line({})
    assert fresh.status == doctor.OK and "public" not in fresh.detail + fresh.fix
    assert first_line({"server.join": "my private server"}).status == doctor.OK
    no_link = first_line({"server.join": "this share link", "server.link": ""})
    assert no_link.status == doctor.WARN and "Share link to join" in no_link.fix
    linked = first_line({"server.join": "this share link",
                         "server.link": "https://www.roblox.com/share?code="
                                        + "0" * 32 + "&type=Server"})
    assert linked.status == doctor.OK


def test_missing_hyprland_on_mint_is_not_called_too_old(monkeypatch):
    monkeypatch.setattr(doctor, "which", lambda name: None)
    missing = {c.name: c for c in doctor.environment("debian", "hyprland")}["Hyprland 0.56+"]
    assert missing.detail == "not installed"
    assert "too old" not in missing.fix and "not ready" in missing.fix
