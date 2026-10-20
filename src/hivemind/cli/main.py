"""`hivemind <command>`, the installed entry point (pyproject [project.scripts]).

WHY THIS FILE EXISTS (DESIGN 8du). pyproject.toml has always named
`hivemind.cli.main:main`, the venv's `.venv/bin/hivemind` was generated from it,
and `make check` runs `python -m hivemind.cli.main doctor` -- and the module was
never written, so all three ended in ModuleNotFoundError. Adding it here makes
the already-installed command work without a reinstall.

One command, because there is one: `doctor`. The GUI starts with
`python -m hivemind.gui.app` and the bot with `scripts/overnight.sh`; neither is
offered here, so nothing listed can fail to exist.
"""
from __future__ import annotations

import sys

COMMANDS = {"doctor": "check every dependency, protocol and calibration file"}


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    command = args[0] if args else "doctor"
    if command == "doctor":
        from .doctor import main as doctor
        return doctor(args[1:])
    print("usage: hivemind [command]\n")
    for name, what in COMMANDS.items():
        print(f"  {name:10s} {what}")
    return 0 if command in ("-h", "--help", "help") else 2


if __name__ == "__main__":
    raise SystemExit(main())
