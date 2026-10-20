"""Hivemind. On Windows the installed app's bundled tools go on PATH first
(datapaths.use_bundled_tesseract says why)."""
import os

if os.name == "nt":                                  # pragma: no cover (Windows)
    from .datapaths import use_bundled_tesseract
    use_bundled_tesseract()
