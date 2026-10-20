"""Every buff-bar icon named, with the share of it left: a small learned reader.

vision/buffs reads the bar with one template per icon, and has templates for
Haste, Melody and the bear morphs only. Everything else on the bar -- Baby
Love, Focus, Tabby Love, the boosts, the extracts -- is invisible to the bot,
so a rule like "Melody above 30%" or "Focus at 10 stacks" cannot be written.
This module names EVERY slot (`Model.classes`) and reads how far its square
has drained, as a share of the icon (`Icon.left`, 0..1) and, for a class
whose drain rate was measured on our own frames, in seconds (`Icon.seconds`).
The stack count comes from vision/buffs' digit reader, which already reads
any icon's count.

HOW FAR IT HAS DRAINED is read by RULE once the network has named the icon:
every icon's coloured square empties from the top as Haste's does (vision/
buffs DRAIN_*), so each class keeps its square's colour and where a full
icon shows it (`Model.fills`, `masks`), and the drain line is the highest
row from which every row below still shows it (`fill_line`); a bear morph's
is buffs.bear_drain_line. MEASURED 2026-10-27 over 78,004 saved route
frames: tracked over consecutive frames this line falls at 1.89 rows/s for
Haste (1,426 tracks, IQR 1.85-1.92 -- the hand clock's 1.895), 1.88 for
Focus (20 s), 1.26 for Melody and 1.18 for Baby Love (30-32 s), 1.27-1.34
for every bear (the hand clock's 1.28). The network's own share-left output
is the fallback for a class with no readable square; it is 2-7 rows off on
held-out nights, the rule a fraction of a row (docs/pending/ai-bufficons.md).

THE NETWORK is vision/coinnet's shape (3x3 conv 16/32/64, 64 hidden) on the
38 px slot shrunk to 32 px, with one output per class plus one more: the
logit of the share left. About 90k weights in data/models/bufficons.npz.
How it was labelled (our templates at high scores, k-means clusters named
once by eye, and each icon tracked over consecutive frames so its drain line
only falls), trained and measured against the template reader on held-out
nights: scripts/bufficons_data.py, scripts/train_bufficons.py and
docs/pending/ai-bufficons.md.

OFF UNLESS SWITCHED ON (setting `gather.buff_icons`). Look-only: nothing
walks or presses differently on it; the farm reports what it reads and logs
how long each buff was up per trip (brain/reflect.buff_effect). A missing or
broken model file means `read` returns None and `error()` says why.
"""
from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from ..datapaths import data
from . import buffs, coinnet

MODEL = data("models", "bufficons.npz")
SETTING = "gather.buff_icons"
SIZE = 32                      # the slot (buffs.ICON = 38 px) shrunk for coinnet's 3 pools

_lock = threading.Lock()
_model = None
_error = ""
_on = False


@dataclass(frozen=True)
class Icon:
    slot: int
    name: str
    p: float                   # the class probability
    left: float                # share of the square still full, 0..1
    seconds: float | None      # left / the class's measured drain rate; None: no rate
    stacks: int | None         # the count written on it (vision/buffs.stacks)
    # The rule cannot see above its mask's top row, so a read AT that row
    # means "this much or more". MEASURED 2026-10-27 (review, unseen
    # attempts): Baby Love's heart hides rows 0-10, so a full one reads
    # 71% for its first ~9 s; Puppy Love tops out at 76%, Enzymes at 45%.
    at_least: bool = False


@dataclass(frozen=True)
class Bar:
    icons: tuple

    def get(self, name: str) -> Icon | None:
        """The named icon with the most left (two Hastes: the surge drains first)."""
        hits = [i for i in self.icons if i.name == name]
        return max(hits, key=lambda i: i.left) if hits else None

    def percent(self, name: str) -> float | None:
        """How much of `name` is left, 0..100 (Melody/Baby Love gates); None: not up."""
        i = self.get(name)
        return None if i is None else round(100.0 * i.left, 1)

    def stacks(self, name: str) -> int | None:
        """Its stack count (Focus x10 gates): 1 when up with no count drawn; None: not up."""
        i = self.get(name)
        if i is None:
            return None
        return i.stacks if i.stacks is not None else 1

    def names(self) -> list[str]:
        return [i.name for i in self.icons]

    def describe(self) -> str:
        if not self.icons:
            return "nothing on the buff bar"
        return "; ".join(
            f"{i.name}" + (f" x{i.stacks}" if i.stacks else "")
            + f" {'>=' if i.at_least else ''}{100 * i.left:.0f}%"
            + (f" (~{i.seconds:.0f}s)" if i.seconds is not None else "") for i in self.icons)


# A pixel within FILL_TOL (BGR distance) of the class's fill counts as fill;
# a row of the mask is still full when FILL_ROW_SHARE of it is.
FILL_TOL = 38.0
FILL_ROW_SHARE = 0.5
# Classes whose empty-square claims are dropped (Model.read, the measurement there).
NO_EMPTY = frozenset({"melody"})


def fill_line(crop, fill, mask) -> int:
    """The drain line by rule: the highest row from which every masked row
    below still shows the fill (buffs.ICON for an empty square)."""
    near = np.linalg.norm(crop[..., :3].astype(np.float32) - fill, axis=-1) < FILL_TOL
    line = buffs.ICON
    for r in range(buffs.ICON - 1, -1, -1):
        if not mask[r].any():
            continue
        if near[r][mask[r]].mean() < FILL_ROW_SHARE:
            break
        line = r
    return line


class Model:
    def __init__(self, params: dict, classes, tau: float, rates: dict,
                 fills: dict | None = None, masks: dict | None = None):
        self.params = {k: np.asarray(v, np.float32) for k, v in params.items()}
        self.classes = [str(c) for c in classes]
        self.tau = float(tau)
        self.rates = {str(k): float(v) for k, v in rates.items()}   # rows a second
        self.fills = {str(k): np.asarray(v, np.float32) for k, v in (fills or {}).items()}
        self.masks = {str(k): np.asarray(v, bool) for k, v in (masks or {}).items()}

    @classmethod
    def load(cls, path: Path = MODEL) -> "Model":
        with np.load(path, allow_pickle=False) as z:
            named = [str(c) for c in z["fill_names"]] if "fill_names" in z else []
            return cls({k: z[k] for k in coinnet.PARAM_NAMES}, list(z["classes"]),
                       float(z["tau"]), json.loads(str(z["rates"])),
                       {c: z["fills"][j] for j, c in enumerate(named)},
                       {c: z["masks"][j] for j, c in enumerate(named)})

    def save(self, path: Path, **notes) -> None:
        named = sorted(self.fills)
        np.savez_compressed(
            path, classes=np.array(self.classes), tau=np.float32(self.tau),
            rates=np.array(json.dumps(self.rates)), fill_names=np.array(named, dtype=str),
            fills=np.array([self.fills[c] for c in named], np.float32).reshape(-1, 3),
            masks=np.array([self.masks[c] for c in named], bool).reshape(-1, buffs.ICON, buffs.ICON),
            **self.params, **notes)

    def left_of(self, crop, name: str, head: float) -> float:
        """Share of the square left: by rule where the class has one, else `head`."""
        line = None
        if name.startswith("bear_"):
            line = buffs.bear_drain_line(np.ascontiguousarray(crop[..., :3]), name[5:])
        elif name in self.masks:
            line = fill_line(crop, self.fills[name], self.masks[name])
        return head if line is None else (buffs.ICON - line) / buffs.ICON

    def top_share(self, name: str) -> float | None:
        """The most the rule can read for `name` (its mask's top row); None: no mask."""
        rows = np.flatnonzero(self.masks[name].any(1)) if name in self.masks else ()
        return (buffs.ICON - int(rows[0])) / buffs.ICON if len(rows) else None

    def predict(self, crops: np.ndarray):
        """(class probabilities N x K, share left N) for N 38x38 BGR uint8 slots."""
        x = prepare(crops)
        z = coinnet.logits(self.params, x)
        k = len(self.classes)
        c = z[:, :k] - z[:, :k].max(1, keepdims=True)
        p = np.exp(c)
        p /= p.sum(1, keepdims=True)
        left = 1.0 / (1.0 + np.exp(-np.clip(z[:, k], -30, 30)))
        return p, left

    def read(self, frame) -> Bar:
        bar = buffs.slots(frame)
        if not bar:
            return Bar(icons=())
        crops = np.stack(bar)
        p, left = self.predict(crops)
        icons = []
        for s, (row, lf) in enumerate(zip(p, left)):
            j = int(row.argmax())
            name = self.classes[j]
            if name == "background" or row[j] < self.tau:
                continue
            rate = self.rates.get(name)
            share = float(self.left_of(bar[s], name, float(lf)))
            top = self.top_share(name)
            # A MELODY WITH NO FILL LEFT IS NOT CALLED UP. MEASURED 2026-10-27
            # (review: 13,162 frames of test-night attempts never extracted,
            # graded by eye): Melody claims with no white showing were 26 of
            # 40 scenery or bear faces, against 2 of 48 above 0%; the true ones
            # are expiring anyway. Auto labels: P 0.857 -> 0.897, R 0.994 ->
            # 0.959. Not for every class: Moon and Purple Bulb read 0% on most
            # true icons (recall 1.00 -> 0.41 / 0.72), Focus loses 0.08 recall.
            if name in NO_EMPTY and share <= 0.0:
                continue
            rows_left = share * buffs.ICON
            icons.append(Icon(slot=s, name=name, p=float(row[j]), left=share,
                              seconds=rows_left / rate if rate else None,
                              stacks=buffs.stacks(bar[s]),
                              at_least=top is not None and share >= top - 1e-9))
        return Bar(icons=tuple(icons))


def prepare(crops: np.ndarray) -> np.ndarray:
    """N x 38 x 38 x 3 uint8 -> N x 32 x 32 x 3 float32 in 0..1."""
    out = np.empty((len(crops), SIZE, SIZE, 3), np.float32)
    for n, c in enumerate(crops):
        out[n] = cv2.resize(np.ascontiguousarray(c[..., :3]), (SIZE, SIZE),
                            interpolation=cv2.INTER_AREA)
    return out / 255.0


def switch(on: bool) -> None:
    """The setting's value; run_farm sets it each time it reads settings."""
    global _on
    _on = bool(on)


def model() -> Model | None:
    """The model while switched on and loadable, else None."""
    global _model, _error
    if not _on:
        return None
    if _model is None and not _error:
        with _lock:
            if _model is None and not _error:
                try:
                    _model = Model.load(MODEL)
                except (OSError, KeyError, ValueError) as err:
                    _error = f"no buff-icon model ({MODEL.name}): {err}"
    return _model


def read(frame) -> Bar | None:
    """The whole bar named, or None while off, unloadable or with no frame."""
    global _error
    m = model()
    if m is None or frame is None:
        return None
    # LOOK-ONLY MEANS IT CANNOT HURT THE WALK: run_farm reads this inside
    # movespeed_factor, where a raise would turn Haste's factor into 1.0
    # (routes._speed_factor) or crash the caller that has no try.
    try:
        return m.read(frame)
    except Exception as err:          # noqa: BLE001
        _error = f"buff-icon read failed: {err!r}"
        return None


def error() -> str:
    return _error
