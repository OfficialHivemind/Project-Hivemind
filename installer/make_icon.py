"""Make the installer's images from data/icon.png (RL6i): build/hivemind.ico
(the app, shortcuts and Setup icon) and the two wizard bitmaps Inno Setup
shows. OpenCV only, which the app already needs, so the build adds nothing.

    python installer/make_icon.py [out_dir]       (default: installer/build)

The .ico holds one PNG per size (Windows Vista and later read PNG entries),
so every size is the real logo scaled down, not one image stretched.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "icon.png"
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)
PANEL = (28, 25, 23)          # BGR: the window's dark background, behind the logo


def ico(image: np.ndarray, sizes=SIZES) -> bytes:
    """An ICO file of PNG entries, one per size."""
    blobs = []
    for s in sizes:
        small = cv2.resize(image, (s, s), interpolation=cv2.INTER_AREA)
        ok, png = cv2.imencode(".png", small)
        assert ok
        blobs.append(png.tobytes())
    head = struct.pack("<HHH", 0, 1, len(sizes))
    offset = 6 + 16 * len(sizes)
    entries = b""
    for s, blob in zip(sizes, blobs):
        entries += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(blob), offset)
        offset += len(blob)
    return head + entries + b"".join(blobs)


def panel(image: np.ndarray, width: int, height: int, logo: int) -> np.ndarray:
    """The logo centred on the dark background, alpha blended, 24-bit."""
    out = np.zeros((height, width, 3), np.uint8)
    out[:] = PANEL
    small = cv2.resize(image, (logo, logo), interpolation=cv2.INTER_AREA).astype(np.float32)
    alpha = small[:, :, 3:4] / 255.0
    y, x = (height - logo) // 2, (width - logo) // 2
    spot = out[y:y + logo, x:x + logo].astype(np.float32)
    out[y:y + logo, x:x + logo] = (small[:, :, :3] * alpha + spot * (1 - alpha)).astype(np.uint8)
    return out


def main(out_dir: Path) -> None:
    image = cv2.imread(str(SOURCE), cv2.IMREAD_UNCHANGED)
    if image is None or image.ndim != 3 or image.shape[2] != 4:
        raise SystemExit(f"{SOURCE} is not a BGRA image")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "hivemind.ico").write_bytes(ico(image))
    # Inno Setup 6's sizes at 100% and 200% DPI: the welcome/finish side panel
    # (164x314) and the small top-right image (55x58, square here).
    cv2.imwrite(str(out_dir / "wizard-large-100.bmp"), panel(image, 164, 314, 132))
    cv2.imwrite(str(out_dir / "wizard-large-200.bmp"), panel(image, 328, 628, 264))
    cv2.imwrite(str(out_dir / "wizard-small-100.bmp"), panel(image, 58, 58, 54))
    cv2.imwrite(str(out_dir / "wizard-small-200.bmp"), panel(image, 116, 116, 108))
    print(f"wrote {out_dir}/hivemind.ico and the wizard images")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent / "build")
