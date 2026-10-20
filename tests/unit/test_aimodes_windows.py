"""platform/hardware reads a Windows adapter's registry size (the Windows review, 27 Oct)."""
import sys
import types

from hivemind.platform import hardware


def test_windows_registry_size_is_read_and_the_biggest_card_wins(monkeypatch, tmp_path):
    vals = {"0000": {"HardwareInformation.MemorySize": (0x7FFFF000).to_bytes(4, "little")},
            "0001": {"HardwareInformation.qwMemorySize": 8 * 1024 ** 3},
            "Configuration": {}}

    class Key:
        def __init__(self, name=None):
            self.name = name
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    fake = types.SimpleNamespace(
        HKEY_LOCAL_MACHINE=object(),
        OpenKey=lambda parent, name: Key(name),
        QueryInfoKey=lambda k: (len(vals), 0, 0),
        EnumKey=lambda k, i: list(vals)[i],
    )

    def query(a, v):
        if v in vals.get(a.name, {}):
            return vals[a.name][v], 3
        raise OSError(v)
    fake.QueryValueEx = query
    monkeypatch.setitem(sys.modules, "winreg", fake)
    monkeypatch.setattr(hardware.shutil, "which", lambda name: None)
    got = hardware.vram_gb(drm=tmp_path)
    assert round(got, 1) == 8.0
    assert sorted(round(x, 1) for x in hardware._vram_windows()) == [2.0, 8.0]


def test_no_winreg_reads_nothing(monkeypatch):
    monkeypatch.setitem(sys.modules, "winreg", None)
    assert list(hardware._vram_windows()) == []
