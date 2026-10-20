#!/usr/bin/env python3
"""Fetch each bee type's icon from the Bee Swarm Simulator fan wiki into
data/bee_faces/<type>.png (96 x 96, transparency kept) for the GUI's Hive
Planner, and list each file's source in data/bee_faces/SOURCES.md.

The icons are Onett's game art, hosted by the fan wiki: fine for the owner's
own use; ask before any public release. Re-runnable; image files only.

    ./scripts/fetch_bee_faces.py
"""
import json
import pathlib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import cv2
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hivemind.vision.beemenu import types   # noqa: E402

API = "https://bee-swarm-simulator.fandom.com/api.php"
UA = "Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0"
OUT = ROOT / "data" / "bee_faces"
SIZE = 96
# the wiki's file names tried per bee, in order ("Bubble Bee.png" first)
NAMES = ("{label}.png", "{label}.webp", "{label} Icon.png")


def get(url: str, tries: int = 4) -> bytes:
    """The bytes at url; the CDN answers 403 to a burst, so wait and retry."""
    for n in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code not in (403, 429) or n == tries - 1:
                raise
            time.sleep(5 * (n + 1))


def urls(titles: list[str]) -> dict:
    """{'File:X.png': image url} for the titles the wiki has."""
    q = urllib.parse.urlencode({"action": "query", "titles": "|".join(titles),
                                "prop": "imageinfo", "iiprop": "url", "format": "json"})
    body = json.loads(get(f"{API}?{q}"))["query"]
    back = {n["to"]: n["from"] for n in body.get("normalized", [])}
    return {back.get(p["title"], p["title"]): p["imageinfo"][0]["url"]
            for p in body.get("pages", {}).values() if p.get("imageinfo")}


def square(png: bytes) -> np.ndarray:
    """The icon fitted into SIZE x SIZE, centred on a transparent square."""
    im = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_UNCHANGED)
    if im.ndim == 2:
        im = cv2.cvtColor(im, cv2.COLOR_GRAY2BGRA)
    elif im.shape[2] == 3:
        im = cv2.cvtColor(im, cv2.COLOR_BGR2BGRA)
    h, w = im.shape[:2]
    k = SIZE / max(h, w)
    im = cv2.resize(im, (max(1, round(w * k)), max(1, round(h * k))), interpolation=cv2.INTER_AREA)
    out = np.zeros((SIZE, SIZE, 4), np.uint8)
    y, x = (SIZE - im.shape[0]) // 2, (SIZE - im.shape[1]) // 2
    out[y:y + im.shape[0], x:x + im.shape[1]] = im
    return out


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    labels = {k: str(v.get("label") or f"{k.title()} Bee") for k, v in types().items()}
    found, missing = {}, []
    todo = dict(labels)
    for pattern in NAMES:
        if not todo:
            break
        titles = {f"File:{pattern.format(label=lab)}": k for k, lab in todo.items()}
        for title, url in urls(list(titles)).items():
            if titles.get(title) in todo:
                found[titles[title]] = url
                todo.pop(titles[title])
    for key, url in sorted(found.items()):
        try:
            cv2.imwrite(str(OUT / f"{key}.png"), square(get(url)))
            time.sleep(1)
        except Exception as e:                       # one bad file never stops the rest
            print(f"{key}: {e}")
            found.pop(key)
    missing = sorted(set(labels) - set(found))
    lines = ["# Bee faces: sources", "",
             "Fetched by `scripts/fetch_bee_faces.py` from the Bee Swarm Simulator fan wiki",
             "(bee-swarm-simulator.fandom.com). The art is Onett's (the game's); the wiki",
             "hosts it. The game art belongs to Onett; it is included only so the bot can",
             "recognise the game's screen and is not covered by this project's licence.", ""]
    lines += [f"- `{k}.png`: {found[k]}" for k in sorted(found)]
    if missing:
        lines += ["", "No image found: " + ", ".join(missing)]
    (OUT / "SOURCES.md").write_text("\n".join(lines) + "\n")
    print(f"{len(found)} of {len(labels)} faces; missing: {', '.join(missing) or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
