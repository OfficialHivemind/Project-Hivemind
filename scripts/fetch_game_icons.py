#!/usr/bin/env python3
"""Fetch the field and item icons the GUI's cards and pickers show from the
Bee Swarm Simulator fan wiki into data/game_icons/{fields,items}/<slug>.png
(96 x 96, transparency kept), and list each file's source in
data/game_icons/SOURCES.md. The same approach as scripts/fetch_bee_faces.py
(its get / urls / square are reused).

The icons are Onett's game art, hosted by the fan wiki: fine for the owner's
own use; ask before any public release. Re-runnable (fetches only the
missing files; delete one to refresh it); image files only.

    ~/Hivemind/.venv/bin/python scripts/fetch_game_icons.py
"""
import pathlib
import sys
import time

import cv2

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from fetch_bee_faces import get, square, urls          # noqa: E402
from hivemind.gui.gameicons import ITEMS, field_zones, slug  # noqa: E402

OUT = ROOT / "data" / "game_icons"
# the wiki's file names tried per name, in order
NAMES = {"fields": ("{n} Field Icon.png", "{n} Patch Icon.png", "{n} Forest Icon.png"),
         "items": ("{n}.png", "{n} Icon.png")}


def main() -> int:
    wanted = {"fields": [f for _, fs in field_zones() for f in fs], "items": list(ITEMS)}
    lines = ["# Game icons: sources", "",
             "Fetched by `scripts/fetch_game_icons.py` from the Bee Swarm Simulator fan wiki",
             "(bee-swarm-simulator.fandom.com). The art is Onett's (the game's); the wiki",
             "hosts it, its text under CC BY-SA unless noted. The game art itself belongs",
             "to Onett; it is included only so the bot can recognise the game's screen and",
             "is not covered by this project's licence.", ""]
    missing = []
    for kind, names in wanted.items():
        (OUT / kind).mkdir(parents=True, exist_ok=True)
        found, todo = {}, list(names)
        for pattern in NAMES[kind]:
            if not todo:
                break
            titles = {f"File:{pattern.format(n=n)}": n for n in todo}
            for title, url in urls(list(titles)).items():
                if titles.get(title) in todo:
                    found[titles[title]] = url
                    todo.remove(titles[title])
        lines += [f"## {kind}", ""]
        for name in names:
            url = found.get(name)
            try:
                if url is None:
                    raise LookupError("no file on the wiki")
                path = OUT / kind / f"{slug(name)}.png"
                if not path.exists():               # a re-run fetches only the missing
                    cv2.imwrite(str(path), square(get(url)))
                    time.sleep(1)
                lines.append(f"- `{kind}/{slug(name)}.png`: {url}")
            except Exception as e:                  # one bad file never stops the rest
                print(f"{kind}/{name}: {e}")
                missing.append(f"{kind}/{name}")
        lines.append("")
    if missing:
        lines += ["Not fetched (a grey placeholder is drawn): " + ", ".join(missing)]
    (OUT / "SOURCES.md").write_text("\n".join(lines) + "\n")
    print(f"missing: {', '.join(missing) or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
