"""Lets the desktop entry run `python -m hivemind.gui`.

`--version` and `--selftest` (hivemind/selftest) answer without opening the
window: the installer's build proves the installed app imports everything."""
import sys

if "--version" in sys.argv[1:] or "--selftest" in sys.argv[1:]:
    from .. import selftest
    if "--version" in sys.argv[1:]:
        print(selftest.version())
        raise SystemExit(0)
    raise SystemExit(selftest.run())

if "--demo" in sys.argv[1:] or any(a == "--replay" or a.startswith("--replay=")
                                   for a in sys.argv[1:]):
    from ..datapaths import use_demo_dirs
    use_demo_dirs()                     # before anything reads settings or var/

from .app import main  # noqa: E402

raise SystemExit(main())
