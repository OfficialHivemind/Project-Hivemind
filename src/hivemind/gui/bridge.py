"""Getting events from a socket thread onto Qt's event loop, safely.

`EventClient` delivers on its own reader thread. Touching a widget from there
would be a use-after-free waiting to happen -- Qt objects belong to the thread
that made them. So the bridge is a QObject whose only job is to re-emit each
event as a Qt signal, and Qt's queued connections move it to the GUI thread.

It also provides a replay source. The GUI can then be built and demonstrated
with no bot and no game running at all, which is how this was developed: a file
of recorded event lines plays back through exactly the same signals the live
socket uses, so there is no "demo mode" code path that could rot separately.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from ..ipc.bus import EventClient
from ..telemetry.events import Event, from_json


class EventBridge(QObject):
    """Turns socket-thread callbacks into Qt signals on the GUI thread."""

    event_received = Signal(object)
    connection_changed = Signal(bool)

    def __init__(self, socket_path: str | None = None, parent=None):
        super().__init__(parent)
        self._client: EventClient | None = None
        self._socket_path = socket_path
        self._replay_stop = threading.Event()

    # ---- live ------------------------------------------------------------
    def connect_to_bot(self) -> None:
        from ..ipc.bus import DEFAULT_SOCKET
        path = self._socket_path or DEFAULT_SOCKET
        self._client = EventClient(
            path,
            on_event=self.event_received.emit,
            on_state=self.connection_changed.emit,
        ).start()

    def send(self, event: Event) -> bool:
        return bool(self._client and self._client.send(event))

    # ---- replay ----------------------------------------------------------
    def replay(self, path: str | Path, speed: float = 1.0,
               loop: bool = False) -> None:
        """Play a recorded .jsonl of events through the same signals.

        Timing comes from each event's own `at` field, so a replay looks like
        the session did rather than arriving all at once. `speed` scales it;
        gaps longer than two seconds are clamped, because nobody wants to watch
        a faithful reproduction of the bot waiting for a planter.
        """
        self._replay_stop.clear()
        threading.Thread(target=self._replay_loop,
                         args=(Path(path), speed, loop), daemon=True).start()

    def _replay_loop(self, path: Path, speed: float, loop: bool) -> None:
        while not self._replay_stop.is_set():
            previous: float | None = None
            self.connection_changed.emit(True)
            for line in path.read_text().splitlines():
                if self._replay_stop.is_set():
                    return
                event = from_json(line)
                if event is None:
                    continue
                if previous is not None:
                    gap = min(max(event.at - previous, 0.0), 2.0) / max(speed, 0.01)
                    time.sleep(gap)
                previous = event.at
                self.event_received.emit(event)
            if not loop:
                return

    def stop(self) -> None:
        self._replay_stop.set()
        if self._client:
            self._client.stop()
