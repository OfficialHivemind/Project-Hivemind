"""O3: every Linux pip dependency in pyproject is pinned to one exact version
in installer/requirements-linux.txt, and both venv builders use that file."""
from __future__ import annotations

import re
import tomllib
from pathlib import Path

ROOT = Path(__import__("hivemind").__file__).resolve().parents[2]
PINS = ROOT / "installer/requirements-linux.txt"


def _name(req: str) -> str:
    return re.split(r"[<>=!~;\s\[]", req, maxsplit=1)[0].lower().replace("_", "-")


def test_every_linux_dependency_is_pinned_exactly():
    deps = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["dependencies"]
    linux = {_name(d) for d in deps if "win32" not in d}
    pins = set()
    for line in PINS.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            assert re.fullmatch(r"[A-Za-z0-9_.-]+==[0-9][0-9A-Za-z.]*", line), line
            pins.add(_name(line))
    assert linux and linux <= pins, linux - pins


def test_venv_builders_use_the_pins():
    assert "-c installer/requirements-linux.txt" in (ROOT / "Makefile").read_text()
    assert "requirements-linux.txt" in (ROOT / "installer/linux/install.sh").read_text()
