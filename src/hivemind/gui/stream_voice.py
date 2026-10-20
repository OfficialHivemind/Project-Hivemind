"""The stream's voice, spoken: Piper (offline neural text-to-speech) into the
desktop's player, on a thread of its own so the stream never waits for it.

What to say is stream/voice's; this only says it. The audio goes to the
default output, which is where OBS's "Desktop Audio" source listens.

WHAT IS INSTALLED, 2026-09-28, in PIPER_ROOT: the rhasspy/piper 2023.11.14-2 Linux build
(piper_linux_x86_64.tar.gz, 26 MB, github.com/rhasspy/piper/releases), and
two voices from huggingface.co/rhasspy/piper-voices v1.0.0, chosen by
licence because the voice goes out on a stream -- en_US-joe-medium (CC0) and
en_US-kristin-medium (public domain); each voice's MODEL_CARD is beside it.
Ryan and Hi-Fi Captain (CC BY-NC-SA) and Lessac (a research licence) were
left out. The Qt speech plugins on this machine have no engine behind them
(libflite and speech-dispatcher are not installed).

MEASURED on this machine: a 4.0 s line synthesised in 0.11 s (real-time
factor 0.029), 0.26 s for the whole call with the model's load -- so a line
is heard well inside the second after the event it describes.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

PIPER_ROOT = Path.home() / "Applications" / "piper"
PIPER = PIPER_ROOT / "piper" / "piper"
VOICES = PIPER_ROOT / "voices"
VOICE_FILES = {"joe": "en_US-joe-medium.onnx", "kristin": "en_US-kristin-medium.onnx"}
DEFAULT_VOICE = "joe"
# A little brisker than the voice's own pace: a stream voice that drawls
# loses the room (piper's --length_scale; under 1 is faster).
LENGTH_SCALE = 0.92
SYNTH_TIMEOUT_S = 15.0
PLAY_TIMEOUT_S = 30.0



# THE VOICE'S OWN NAME IN PIPEWIRE, so OBS can take the voice and nothing else.
# A stream scene often has Desktop Audio muted -- it carries chat apps and
# the browser -- so a voice played to the desktop never reached the
# stream. With these properties the voice is its own stream, "Hivemind voice"
# (MEASURED 2026-09-28 with pw-dump while pw-play played: application.name and
# media.name "Hivemind voice", media.class Stream/Output/Audio), which OBS's
# "Application Audio Capture (PipeWire)" source (the PipeWireAudioCapture
# plugin, installed) can be pointed at alone.
STREAM_NAME = "Hivemind voice"
PW_PROPERTIES = ('{ application.name = "Hivemind voice" node.name = "hivemind-voice" '
                 'node.description = "Hivemind voice" media.name = "Hivemind voice" }')

# AN ANNOUNCEMENT IS PLAYING (a local announcement tool, not shipped, writes
# this file while it plays and removes it after): the bot's own lines wait, so
# the two never talk over each other (2026-10-06: the owner heard two voices
# overlapping). A file older than ANNOUNCE_STALE_S is a crashed player's.
ANNOUNCE_LOCK = Path(os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()) / "hivemind-announce.lock"
ANNOUNCE_STALE_S = 60.0


def announcing(lock: Path | None = None, now: float | None = None) -> bool:
    lock = ANNOUNCE_LOCK if lock is None else lock
    try:
        age = (time.time() if now is None else now) - lock.stat().st_mtime
    except OSError:
        return False
    return age < ANNOUNCE_STALE_S


class Voice:
    """`say(text)` when not `busy()`; `stop()` on close."""

    def __init__(self, get=lambda key: None, popen=subprocess.Popen, which=shutil.which,
                 piper: Path = PIPER, voices: Path = VOICES):
        self.get = get
        self.popen = popen
        self.which = which
        self.piper = Path(piper)
        self.voices = Path(voices)
        self._busy = threading.Event()
        self._lock = threading.Lock()
        self._player = None
        self._stopped = False
        self.spoken = 0
        self.failures = 0
        self.last_error = ""
        runtime = os.environ.get("XDG_RUNTIME_DIR") or tempfile.gettempdir()
        self._wav = Path(runtime) / "hivemind-voice.wav"

    # ---- what it would use -----------------------------------------------------------
    def model(self) -> Path:
        name = str(self.get("stream.voice_name") or DEFAULT_VOICE)
        return self.voices / VOICE_FILES.get(name, VOICE_FILES[DEFAULT_VOICE])

    def player(self) -> list[str] | None:
        """The command that plays a WAV at the set volume, or None."""
        try:
            volume = max(0, min(100, int(self.get("stream.voice_volume") or 0)))
        except (TypeError, ValueError):
            volume = 80
        if self.which("pw-play"):
            return ["pw-play", f"--volume={volume / 100:.2f}", "-P", PW_PROPERTIES]
        if self.which("paplay"):
            return ["paplay", f"--volume={int(65536 * volume / 100)}",
                    f"--client-name={STREAM_NAME}", f"--stream-name={STREAM_NAME}"]
        return None

    def available(self) -> tuple[bool, str]:
        if not self.piper.is_file():
            return False, f"no Piper at {self.piper}"
        if not self.model().is_file():
            return False, f"no voice model at {self.model()}"
        if self.player() is None:
            return False, "no pw-play or paplay to play it"
        return True, ""

    # ---- saying it ----------------------------------------------------------------------
    def busy(self) -> bool:
        return self._busy.is_set()

    def say(self, text: str) -> bool:
        """Start saying `text` on a thread; False when busy, off or unable."""
        text = " ".join(str(text or "").split())
        if not text or self.busy() or self._stopped or not self.get("stream.voice"):
            return False
        if announcing():
            return False            # one voice at a time: the line waits its turn
        ok, why = self.available()
        if not ok:
            self.last_error = why
            return False
        self._busy.set()
        threading.Thread(target=self._speak, args=(text,), daemon=True,
                         name="stream-voice").start()
        return True

    def _speak(self, text: str) -> None:
        try:
            synth = self.popen([str(self.piper), "--model", str(self.model()),
                                "--length_scale", f"{LENGTH_SCALE}",
                                "--output_file", str(self._wav)],
                               stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL)
            try:
                synth.communicate(text.encode("utf-8"), timeout=SYNTH_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                synth.kill()
                raise
            if synth.returncode != 0:
                raise RuntimeError(f"piper exited {synth.returncode}")
            command = self.player()
            if command is None or self._stopped:
                return
            with self._lock:
                self._player = self.popen(command + [str(self._wav)],
                                          stdout=subprocess.DEVNULL,
                                          stderr=subprocess.DEVNULL)
            try:
                self._player.wait(timeout=PLAY_TIMEOUT_S)
            except subprocess.TimeoutExpired:
                self._player.kill()
                raise
            self.spoken += 1
        except Exception as err:            # the stream must never go down with it
            self.failures += 1
            self.last_error = f"{type(err).__name__}: {err}"
        finally:
            with self._lock:
                self._player = None
            self._busy.clear()

    def stop(self) -> None:
        """Cut the line being said, and say no more."""
        self._stopped = True
        with self._lock:
            player = self._player
        if player is not None:
            try:
                player.terminate()
            except Exception:
                pass
