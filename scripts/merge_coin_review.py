#!/usr/bin/env python3
"""Turn a review's answers into coin labels: scripts/review_coins.py's other half.

    ./scripts/merge_coin_review.py OUT_DIR/review.json [--field NAME]

Each answered candidate becomes a row of data/models/coin_labels.json:
"coin:<kind>" a coin with its box ("from": "review", sure), "no" a
`not_coins` box -- the hard negatives scripts/train_coins.py learns from --
and "skip" nothing. A frame is `partial`: only its candidates were looked at,
so the trainer never takes the rest of it for background. A frame already in
the labels is left alone. Frames outside the checkout are copied into
var/coinreview/ first, so a label's path stays the checkout's own.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hivemind.datapaths import data                             # noqa: E402

LABELS = data("models", "coin_labels.json")
HOME = Path.home() / "Hivemind"


def rows(review: dict, field: str, copy_to: Path) -> list[dict]:
    out = []
    for f in review.get("frames", ()):
        answers = {int(k): str(v).strip().lower() for k, v in (f.get("answers") or {}).items()}
        if not answers:
            continue
        boxes = {int(c["id"]): [int(v) for v in c["box"]] for c in f.get("candidates", ())}
        coins, not_coins = [], []
        for cid, said in sorted(answers.items()):
            if cid not in boxes:
                continue
            if said.startswith("coin"):
                kind = said.split(":", 1)[1].strip() if ":" in said else "unknown"
                coins.append({"box": boxes[cid], "kind": kind or "unknown",
                              "sure": True, "from": "review"})
            elif said == "no":
                not_coins.append({"box": boxes[cid], "from": "review"})
        if not coins and not not_coins:
            continue
        path = Path(f["path"])
        if path.is_absolute():
            copy_to.mkdir(parents=True, exist_ok=True)
            kept = copy_to / f"{f.get('window', 'frame')}__{path.name}"
            shutil.copy2(path, kept)
            path = kept.relative_to(HOME)
        out.append({"path": str(path), "window": f.get("window", ""), "field": field,
                    "partial": True, "coins": coins, "not_coins": not_coins})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("review")
    ap.add_argument("--field", default="live")
    ap.add_argument("--labels", default=str(LABELS))
    args = ap.parse_args(argv)
    review = json.loads(Path(args.review).read_text())
    labels = json.loads(Path(args.labels).read_text())
    have = {f["path"] for f in labels["frames"]}
    new = [r for r in rows(review, args.field, HOME / "var" / "coinreview" / "frames")
           if r["path"] not in have]
    labels["frames"].extend(new)
    Path(args.labels).write_text(json.dumps(labels, indent=1) + "\n")
    print(f"{len(new)} frame(s) added: {sum(len(r['coins']) for r in new)} coin(s), "
          f"{sum(len(r['not_coins']) for r in new)} not-coin box(es)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
