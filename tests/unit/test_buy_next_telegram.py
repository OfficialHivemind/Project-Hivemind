"""G8: "What should I buy next?" on Telegram -- /buy answers with brain/buyer's
own list (next_text), reads only, and a broken plan never kills the poller."""
from __future__ import annotations

import importlib.util
import os
import tempfile
import time
from pathlib import Path

from hivemind.brain import buyer
from hivemind.brain import goals as g

ROOT = Path(__import__("hivemind").__file__).resolve().parents[2]
os.environ.setdefault("HIVEMIND_TELEGRAM_ENV", str(Path(tempfile.mkdtemp()) / "telegram.env"))
_spec = importlib.util.spec_from_file_location("telegram_alerts_buy",
                                               ROOT / "scripts" / "telegram_alerts.py")
tg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tg)


def slot():
    return g.Row(key="hive_slot_35", label="Hive Slot (bee 35)", shop="mountain_top_shop",
                 shop_label="Mountain Top Shop", cost=200_000_000, state=g.READY)


def test_next_pick_first_with_its_reason_and_the_honey(tmp_path):
    text = buyer.next_text(tmp_path, plan=g.Plan(rows=[slot()], honey=300_000_000,
                                                  honey_from="the HUD"))
    lines = text.splitlines()
    assert lines[0].startswith("Buy next: Hive Slot (bee 35) at the Mountain Top Shop")
    assert "200,000,000 honey" in lines[0]
    assert lines[-1].startswith("Honey 300,000,000 (the HUD)")


def test_unread_honey_and_empty_plan_say_so(tmp_path):
    assert "not read yet" in buyer.next_text(tmp_path, plan=g.Plan(rows=[slot()]))
    assert buyer.next_text(tmp_path, plan=g.Plan(rows=[])).startswith("Nothing to buy")


def test_buy_is_a_command_and_routes_to_the_buyer(tmp_path, monkeypatch):
    monkeypatch.setattr(tg, "SETTINGS", tmp_path / "settings.yaml")
    tg.SETTINGS.write_text("telegram.commands: true\n")
    assert tg.command_in({"text": "/buy"}) == "buy"
    sent = []
    monkeypatch.setattr(tg, "send", lambda text, keep=True: sent.append(text))
    monkeypatch.setattr(tg, "buy_text", lambda: "Buy next: X")
    assert tg.run_command("buy", {"text": "/buy", "date": time.time()}) == "Buy next: X"

    # /buy runs on the venv in a child (this service's python has no PyYAML,
    # MEASURED 2 Nov); a failing child is reported, never raised
    import subprocess
    from types import SimpleNamespace
    monkeypatch.undo()                       # the real buy_text again
    monkeypatch.setattr(tg, "SETTINGS", tmp_path / "settings.yaml")
    monkeypatch.setattr(tg, "send", lambda text, keep=True: sent.append(text))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(
        returncode=1, stdout="", stderr="ValueError: bad goals file"))
    assert "bad goals file" in tg.run_command("buy", {"text": "/buy", "date": time.time()})
    assert len(sent) == 2
