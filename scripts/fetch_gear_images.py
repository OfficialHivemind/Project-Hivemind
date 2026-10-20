#!/usr/bin/env python3
"""Fetch every priced gear item's picture (brain/owned.prices(): goals.yaml,
progression.yaml tools.known, gear_prices.yaml) from the Bee Swarm Simulator
Fandom wiki into data/knowledge/gear/wiki/<key>.png (128 x 128, transparency
kept) for the Gear plan page, and list each file's source in SOURCES.md
beside them. The same approach as scripts/fetch_game_icons.py (fetch_bee_faces'
get / urls / square are reused).

Per item: the wiki file "<Label>.png", then "<Label> Icon.png", then the
item page's own infobox image (api.php prop=pageimages). The hive-slot ladder
is not gear and is skipped. Re-runnable: only missing files are fetched
(delete one to refresh it); a missing image never breaks the app (the page
draws the item's initials).

    ~/Hivemind/.venv/bin/python scripts/fetch_gear_images.py
"""
import json
import pathlib
import sys
import time
import urllib.parse

import cv2

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import fetch_bee_faces                                   # noqa: E402
from fetch_bee_faces import API, get, square, urls       # noqa: E402
from hivemind.brain.owned import prices                  # noqa: E402

OUT = ROOT / "data" / "knowledge" / "gear" / "wiki"
fetch_bee_faces.SIZE = 128                               # square() reads it per call
# the wiki's own spelling where the price table's label differs
TITLES = {"electro_magnet": "Electro-Magnet", "super_scooper": "Super-Scooper"}
CREDIT = "Bee Swarm Simulator Fandom wiki, CC BY-SA 3.0; game art (c) Onett"


def wanted() -> dict:
    """{key: label}: every priced item but the hive slots."""
    return {k: TITLES.get(k, i.label) for k, i in prices().items() if i.slot != "hive"}


def page_images(labels: list[str]) -> dict:
    """{label: infobox image url} from each item page (redirects followed)."""
    q = urllib.parse.urlencode({"action": "query", "titles": "|".join(labels),
                                "prop": "pageimages", "piprop": "original",
                                "redirects": 1, "format": "json"})
    body = json.loads(get(f"{API}?{q}"))["query"]
    back = {}
    for step in body.get("normalized", []) + body.get("redirects", []):
        back[step["to"]] = back.get(step["from"], step["from"])
    return {back.get(p["title"], p["title"]): p["original"]["source"]
            for p in body.get("pages", {}).values() if p.get("original")}


def decode(raw: bytes) -> bytes:
    """PNG bytes; a GIF (some infobox images are) is read by OpenCV's video
    reader, first frame."""
    if not raw[:6].startswith(b"GIF"):
        return raw
    tmp = OUT / ".frame.gif"
    tmp.write_bytes(raw)
    ok, frame = cv2.VideoCapture(str(tmp)).read()
    tmp.unlink()
    if not ok:
        raise ValueError("unreadable GIF")
    return cv2.imencode(".png", frame)[1].tobytes()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    items = wanted()
    found, todo = {}, dict(items)
    for pattern in ("File:{l}.png", "File:{l} Icon.png"):
        for chunk in range(0, len(todo), 40):
            part = list(todo.items())[chunk:chunk + 40]
            titles = {pattern.format(l=label): key for key, label in part}
            for title, url in urls(list(titles)).items():
                if title in titles:
                    found[titles[title]] = url
        todo = {k: v for k, v in todo.items() if k not in found}
    labels = list(todo.values())
    for chunk in range(0, len(labels), 40):
        for label, url in page_images(labels[chunk:chunk + 40]).items():
            key = next((k for k, v in todo.items() if v == label), None)
            if key:
                found[key] = url
    lines = ["# Gear pictures: sources", "",
             "Fetched by `scripts/fetch_gear_images.py` from the Bee Swarm Simulator Fandom",
             f"wiki (bee-swarm-simulator.fandom.com). {CREDIT}.", ""]
    missing = []
    for key in sorted(items):
        path, url = OUT / f"{key}.png", found.get(key)
        try:
            if url is None:
                raise LookupError("no image on the wiki")
            if not path.exists():                  # a re-run fetches only the missing
                img = square(decode(get(url)))
                cv2.imwrite(str(path), img, [cv2.IMWRITE_PNG_COMPRESSION, 9])
                time.sleep(0.5)
            lines.append(f"- `{key}.png` ({items[key]}): {url}")
        except Exception as e:                     # one bad file never stops the rest
            print(f"{key}: {e}")
            missing.append(key)
    if missing:
        lines += ["", "Not fetched (the page draws the item's initials): " + ", ".join(missing)]
    (OUT / "SOURCES.md").write_text("\n".join(lines) + "\n")
    print(f"{len(items) - len(missing)} of {len(items)} images; missing: {', '.join(missing) or 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
