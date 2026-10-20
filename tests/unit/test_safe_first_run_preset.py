"""The installer's first-run settings (data/presets/safe-first-run.yaml, RL6i)
load with no problems and keeps the first run to one safe field."""
from pathlib import Path

from hivemind.world.settings import Settings, defaults

PRESET = Path(__import__("hivemind").__file__).resolve().parents[2] / "data/presets/safe-first-run.yaml"


def test_preset_loads_clean_and_safe():
    s = Settings(PRESET)
    assert s.problems == []
    import yaml
    assert set(yaml.safe_load(PRESET.read_text())) <= set(defaults())   # no typos
    assert s.bool("mode.macro") and [e["field"] for e in s["macro.fields"]] == ["Sunflower"]
    # 95, not 100: the pro tester, round 1 (19 Oct 2026) -- convert at 95% or
    # higher, so no time is lost gathering with a full bag
    assert s["macro.fields"][0]["convert_at"] == 95 and s.int("gather.convert_at") == 95
    assert s["server.join"] == "this share link" and s.bool("guard.enabled")
    for key in ("quests.enabled", "economy.buy", "economy.planters", "economy.shop_look",
                "economy.dispensers", "economy.sticker_tickets", "combat.bosses",
                "combat.mobs", "telegram.alerts", "gui.start_on_boot", "perf.vlm"):
        assert s.bool(key) is False, key


def test_preset_keeps_the_disk_small():
    s = Settings(PRESET)
    assert s.bool("learn.token_school") is False and s.int("storage.retention_gb") == 5
