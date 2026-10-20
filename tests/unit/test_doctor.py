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
    monkeypatch.setattr(doctor, "environment", explode)
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
