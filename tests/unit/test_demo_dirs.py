"""A demo never touches the real app's files (the Windows Claude's check of the
UI preview, 2026-10-22: it showed the owner's real server name from settings)."""
import os
import subprocess
import sys
from pathlib import Path

import hivemind

SRC = str(Path(hivemind.__file__).resolve().parents[1])


def _demo_root(tmp_path):
    """Where use_demo_dirs puts a demo under this test's throwaway home.
    WINDOWS (MEASURED 2026-10-26 on the Windows PC): the code is right and the
    old expectation was Linux-only. There the demo is platformdirs'
    %LOCALAPPDATA%/Hivemind Demo (test_installer checks that name), HOME is
    not read, and the space in "Hivemind Demo" broke the old .split() of the
    output. WIN_PD_OVERRIDE_LOCAL_APPDATA (platformdirs 4.13.5, the pinned
    version) points %LOCALAPPDATA% at tmp_path so the run stays off the real one."""
    if os.name == "nt":
        import platformdirs
        return Path(platformdirs.user_data_dir("Hivemind Demo", appauthor=False))
    return tmp_path / ".local/share/hivemind-demo"


def test_a_demo_reads_its_own_settings_and_var(tmp_path, monkeypatch):
    monkeypatch.delenv("HIVEMIND_CONFIG", raising=False)
    monkeypatch.delenv("HIVEMIND_VAR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("WIN_PD_OVERRIDE_LOCAL_APPDATA", str(tmp_path / "AppData" / "Local"))
    from hivemind import datapaths
    real = datapaths.config_dir()          # the real app's folder, under tmp_path
    assert real.is_relative_to(tmp_path)
    real.mkdir(parents=True)
    (real / "settings.yaml").write_text("server.name: the owner's server\n", encoding="utf-8")
    code = ("from hivemind import datapaths; datapaths.use_demo_dirs();"
            "from hivemind.world import settings; from hivemind.datapaths import var, config_dir;"
            "print(settings.CONFIG); print(var('x')); print(config_dir())")
    env = dict(os.environ, PYTHONPATH=SRC)
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True,
                         text=True, check=True).stdout.splitlines()
    demo = _demo_root(tmp_path)
    assert demo.is_relative_to(tmp_path)
    assert out == [str(demo / "config/settings.yaml"), str(demo / "var/x"), str(demo / "config")]
    assert not Path(out[0]).is_relative_to(real)


def test_without_the_override_config_is_the_real_folder(monkeypatch):
    from hivemind import datapaths
    monkeypatch.delenv("HIVEMIND_CONFIG", raising=False)
    assert datapaths.config_dir().name.lower() == "hivemind"
    monkeypatch.setenv("HIVEMIND_CONFIG", "/x/demo")
    assert datapaths.config_dir() == Path("/x/demo")


def test_a_new_demo_starts_from_the_safe_preset(tmp_path, monkeypatch):
    """FOUND 2026-10-26 (the usability review): the demo ran on the schema
    defaults, not the safe first-run settings a real install starts from."""
    from hivemind import datapaths
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("WIN_PD_OVERRIDE_LOCAL_APPDATA", str(tmp_path / "AppData" / "Local"))
    monkeypatch.setattr(datapaths, "VAR_ROOT", datapaths.VAR_ROOT)   # use_demo_dirs sets it
    settings = _demo_root(tmp_path) / "config" / "settings.yaml"
    datapaths.use_demo_dirs({})
    assert settings.read_bytes() == datapaths.data("presets", "safe-first-run.yaml").read_bytes()
    settings.write_text("gather.field: Clover\n", encoding="utf-8")   # the demo's own change
    datapaths.use_demo_dirs({})
    assert settings.read_text(encoding="utf-8") == "gather.field: Clover\n"
