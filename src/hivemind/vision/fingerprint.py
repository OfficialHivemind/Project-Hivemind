"""AI-N9: a picture-fingerprint lookup table in front of a one-line OCR.

`cached(ocr)` wraps an `ocr(frame, box) -> str` reader (act/shoplook's
`_ocr_line`, what act/inventory reads row titles with) so the SAME PIXELS are
read once: the crop's exact bytes (plus its shape) are hashed, and a crop seen
before returns the text it read last time without starting tesseract again.

EXACT, NOT NEAR. A near-match hash (dHash and friends) would let
"Red Extract" answer for "Blue Extract" -- one word apart on the same panel --
so only a byte-identical crop hits. That makes the table lossless: tesseract
is deterministic on identical input, so a hit returns what the miss would have
read. Its ceiling is a background that moves under the words (a hit then
simply never happens and every read is a plain OCR, as before).

Never stored: an empty read ("" is also what a timeout or a missing binary
returns, act/shoplook), so a failure is retried next time, not remembered.

ESTIMATED gain, NOT MEASURED: a tesseract run per row title against a dict
lookup; the hit rate on live inventory pages is unknown until P1 counts it --
`stats()` gives the hits and misses for that.
"""
from __future__ import annotations

import hashlib
from collections import OrderedDict

# HOW MANY PICTURES ARE KEPT. Inventory titles are short crops (a few KB
# each); a few hundred cover every item row with room to spare. Oldest first
# out. ponytail: in-memory only, a JSON table on disk if cross-session hits matter.
MOST = 512


def key(frame, box) -> str | None:
    """The fingerprint of `frame`'s `box` (x0, y0, x1, y1): sha1 over the
    crop's shape and bytes, or None when there is no crop to read."""
    if frame is None or getattr(frame, "size", 0) == 0:
        return None
    x0, y0, x1, y1 = box
    crop = frame[y0:y1, x0:x1]
    if crop.size == 0:
        return None
    h = hashlib.sha1(repr((crop.shape, str(crop.dtype))).encode())
    h.update(crop.tobytes())          # tobytes copies a slice into C order
    return h.hexdigest()


class Table:
    """One reader's lookup table: fingerprint -> the text it read."""

    def __init__(self, ocr, most: int = MOST):
        self.ocr = ocr
        self.most = most
        self.seen: OrderedDict[str, str] = OrderedDict()
        self.hits = 0
        self.misses = 0

    def __call__(self, frame, box, *args, **kwargs) -> str:
        if args or kwargs:                 # another psm or run: not this table's reading
            return self.ocr(frame, box, *args, **kwargs)
        k = key(frame, box)
        if k is not None and k in self.seen:
            self.hits += 1
            self.seen.move_to_end(k)
            return self.seen[k]
        self.misses += 1
        text = self.ocr(frame, box)
        if k is not None and text:
            self.seen[k] = text
            if len(self.seen) > self.most:
                self.seen.popitem(last=False)
        return text

    def stats(self) -> dict:
        return {"hits": self.hits, "misses": self.misses, "kept": len(self.seen)}


_TABLES: dict = {}


def cached(ocr) -> Table:
    """The one table for `ocr` (one per reader, kept for the process), so
    every inventory open shares what the last one read."""
    table = _TABLES.get(ocr)
    if table is None:
        table = _TABLES[ocr] = Table(ocr)
    return table
