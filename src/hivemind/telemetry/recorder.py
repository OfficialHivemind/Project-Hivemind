"""Frame recording, so vision work stops needing a live game.

Deliberately NOT a custom binary format: a recording is a directory of numbered
images plus a JSON manifest. You can open it in an image viewer, diff it, delete
a bad frame, or hand one to a person. Every hour spent debugging a bespoke
container is an hour not spent on the actual problem.

Lossless PNG by default. JPEG artifacts shift hue slightly, and these recordings
are exactly what we sample HSV colour bands from -- compressing them would
corrupt the measurement we are making.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np


@dataclass
class Recorder:
    path: Path
    note: str = ""
    lossless: bool = True
    meta: dict = field(default_factory=dict)
    _n: int = 0
    _t0: float = 0.0
    _index: list = field(default_factory=list)

    def __post_init__(self):
        self.path = Path(self.path)
        (self.path / "frames").mkdir(parents=True, exist_ok=True)
        self._t0 = time.monotonic()

    def add(self, frame: np.ndarray, label: str = "", **extra) -> Path:
        ext = "png" if self.lossless else "jpg"
        p = self.path / "frames" / f"{self._n:06d}.{ext}"
        params = [] if self.lossless else [cv2.IMWRITE_JPEG_QUALITY, 95]
        cv2.imwrite(str(p), frame[:, :, :3], params)
        self._index.append({"n": self._n, "file": p.name,
                            "t": round(time.monotonic() - self._t0, 4),
                            "label": label, **extra})
        self._n += 1
        return p

    def close(self) -> dict:
        manifest = {
            "note": self.note,
            "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "frames": self._n,
            "duration_s": round(time.monotonic() - self._t0, 2),
            "lossless": self.lossless,
            **self.meta,
            "index": self._index,
        }
        (self.path / "manifest.json").write_text(json.dumps(manifest, indent=2))
        return manifest

    def __enter__(self): return self
    def __exit__(self, *exc): self.close()


def load(path: str | Path):
    """Replay a recording as (frame, entry) pairs."""
    path = Path(path)
    manifest = json.loads((path / "manifest.json").read_text())
    for entry in manifest["index"]:
        img = cv2.imread(str(path / "frames" / entry["file"]), cv2.IMREAD_COLOR)
        if img is None:
            continue
        yield img, entry
