"""A demo never touches the real app's files (the Windows Claude's check of the
UI preview, 2026-10-22: it showed the owner's real server name from settings)."""
import os
import subprocess
import sys
from pathlib import Path

import hivemind

SRC = str(Path(hivemind.__file__).resolve().parents[1])


def test_a_demo_reads_its_own_settings_and_var(tmp_path):
    real = tmp_path / ".config" / "hivemind"
    real.mkdir(parents=True)
    (real / "settings.yaml").write_text("server.name: the owner's server\n", encoding="utf-8")
    code = ("from hivemind import datapaths; datapaths.use_demo_dirs();"
            "from hivemind.world import settings; from hivemind.datapaths import var, config_dir;"
            "print(settings.CONFIG); print(var('x')); print(config_dir())")
    env = {k: v for k, v in os.environ.items() if k not in ("HIVEMIND_CONFIG", "HIVEMIND_VAR")}
    env.update(HOME=str(tmp_path), PYTHONPATH=SRC)
    out = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True,
                         text=True, check=True).stdout.split()
    demo = tmp_path / ".local/share/hivemind-demo"
    assert out == [str(demo / "config/settings.yaml"), str(demo / "var/x"), str(demo / "config")]
    assert not out[0].startswith(str(real))


def test_without_the_override_config_is_the_real_folder(monkeypatch):
    from hivemind import datapaths
    monkeypatch.delenv("HIVEMIND_CONFIG", raising=False)
    assert datapaths.config_dir().name.lower() == "hivemind"
    monkeypatch.setenv("HIVEMIND_CONFIG", "/x/demo")
    assert datapaths.config_dir() == Path("/x/demo")
