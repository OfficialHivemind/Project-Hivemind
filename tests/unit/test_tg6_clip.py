"""TG6: /clip asks the bot for its black-box window (Action.SAVE_MOMENT, a
disk write that presses nothing) and sends the new -manual folder's frames
to Telegram as a video."""
from __future__ import annotations

import importlib.util
import os
import shutil
import tempfile
import time
from pathlib import Path

import pytest

from hivemind.telemetry.events import Action

ROOT = Path(__import__("hivemind").__file__).resolve().parents[2]
os.environ.setdefault("HIVEMIND_TELEGRAM_ENV", str(Path(tempfile.mkdtemp()) / "telegram.env"))
_spec = importlib.util.spec_from_file_location("telegram_alerts_clip",
                                               ROOT / "scripts" / "telegram_alerts.py")
tg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tg)


def _moment(root: Path, name: str, n: int = 3, span: float = 0.2) -> Path:
    d = root / name
    d.mkdir(parents=True)
    for i in range(n):
        (d / f"{i:03d}_t{i * span / (n - 1):+05.1f}s.jpg").write_bytes(b"x")
    (d / "reason.txt").write_text("manual\n")
    return d


def test_clip_is_a_command_in_the_help():
    assert "clip" in tg.COMMANDS and "/clip" in tg.HELP


def test_folder_and_rate(tmp_path):
    assert tg.clip_folder(0, tmp_path) is None
    _moment(tmp_path, "20261102-100000-token")             # not a manual save
    got = _moment(tmp_path, "20261102-100001-manual", n=11, span=1.0)
    assert tg.clip_folder(0, tmp_path) == got
    assert tg.clip_folder(time.time() + 60, tmp_path) is None   # older than asked
    assert tg.clip_fps(got) == pytest.approx(10.0)


def test_clip_sends_the_new_moment_as_a_video(tmp_path, monkeypatch):
    asked, posted = [], []
    folder = _moment(tmp_path, "20261102-100001-manual")
    monkeypatch.setattr(tg.shutil, "which", lambda name: "/bin/" + name)
    monkeypatch.setattr(tg, "bot_socket", lambda cmd, **kw: asked.append(cmd) or [])
    monkeypatch.setattr(tg, "clip_folder", lambda since: folder)
    monkeypatch.setattr(tg, "make_clip", lambda d: d / "clip.mp4")
    monkeypatch.setattr(tg, "post_photo", lambda *a, **kw: posted.append((a, kw)))
    reply = tg.clip_text()
    assert asked[0].action == Action.SAVE_MOMENT
    assert reply.startswith("🐝")
    assert posted[0][0][0] == folder / "clip.mp4"
    assert posted[0][1]["method"] == "sendVideo" and posted[0][1]["field"] == "video"


def test_no_bot_no_clip(monkeypatch):
    monkeypatch.setattr(tg.shutil, "which", lambda name: "/bin/" + name)
    monkeypatch.setattr(tg, "bot_socket", lambda cmd, **kw: None)
    assert "not connected" in tg.clip_text()


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="no ffmpeg")
def test_make_clip_writes_an_mp4(tmp_path):
    cv2 = pytest.importorskip("cv2")
    np = pytest.importorskip("numpy")
    d = tmp_path / "m"
    d.mkdir()
    for i in range(4):
        cv2.imwrite(str(d / f"{i:03d}_t{i * 0.1:+05.1f}s.jpg"),
                    np.full((72, 128, 3), i * 60, np.uint8))
    out = tg.make_clip(d)
    assert out.exists() and out.stat().st_size > 0
