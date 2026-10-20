"""XKB keymap delivered to the compositor over a memfd.

The virtual-keyboard protocol requires a keymap before any key event. We compile
one from xkbcommon rather than shipping a literal, so it always matches the
system's XKB version.
"""
from __future__ import annotations

import os

from xkbcommon import xkb

XKB_KEYMAP_FORMAT_TEXT_V1 = 1


def build_keymap_fd(layout: str = "us") -> tuple[int, int]:
    """Return (fd, size) of a sealed memfd holding a text XKB keymap."""
    ctx = xkb.Context()
    keymap = ctx.keymap_new_from_names(layout=layout)
    data = keymap.get_as_string().encode()

    fd = os.memfd_create("hivemind-keymap", os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
    os.write(fd, data)
    # The compositor mmaps this; it must stay readable for the object's lifetime.
    return fd, len(data)
