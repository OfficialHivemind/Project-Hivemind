"""AI-N4: Eco / Standard / Max picked from the measured PC (world/aimode)."""
from __future__ import annotations

from hivemind.world import aimode
from hivemind.world.aimode import Hardware
from hivemind.world.settings import migrate

OWNER = Hardware(cpus=16, probe_ms=38.7, ram_total_gb=30.5, ram_free_gb=7.8, vram_gb=15.9)


class S(dict):
    def bool(self, key):
        return bool(self.get(key))


def test_the_pc_it_was_tuned_on_runs_max_which_is_todays_behaviour():
    assert aimode.pick(OWNER)[0] == "max"
    assert aimode.UNMEASURED == "max"


def test_each_rule_picks_its_mode_with_a_reason():
    def mode(**kw):
        return aimode.pick(Hardware(**{**OWNER.__dict__, **kw}))
    assert mode(cpus=4) == ("eco", "it has 4 processor threads, and the game needs them")
    assert mode(probe_ms=2.6 * aimode.REFERENCE_PROBE_MS)[0] == "eco"
    assert mode(probe_ms=2.4 * aimode.REFERENCE_PROBE_MS)[0] == "max"
    assert mode(probe_ms=None)[0] == "max"            # no coin model: no timing rule
    assert mode(ram_total_gb=7.5)[0] == "eco"
    assert mode(ram_total_gb=0.0)[0] == "max"         # unreadable is not small
    assert mode(vram_gb=8.0)[0] == "standard"
    assert "could not be read" in mode(vram_gb=None)[1]
    assert mode(vram_gb=None)[0] == "max"             # unknown keeps perf.vlm as set


def test_the_players_pick_wins_and_auto_reads_the_saved_measurement(tmp_path, monkeypatch):
    path = tmp_path / "hardware.json"
    monkeypatch.setattr(aimode, "HARDWARE", path)
    assert aimode.chosen(S()) == "max"                       # nothing measured yet
    aimode.save(Hardware(cpus=2, probe_ms=120.0, ram_total_gb=8, ram_free_gb=3,
                         vram_gb=None))
    assert aimode.load().cpus == 2
    assert aimode.chosen(S()) == "eco"
    assert aimode.chosen(S({"perf.ai_mode": "max"})) == "max"
    assert aimode.is_eco(S({"perf.ai_mode": "auto"}))
    assert not aimode.vision_model_allowed(S({"perf.ai_mode": "standard"}))
    assert aimode.chosen(object()) == "max"                  # a settings that cannot say
    path.write_text("{not json", encoding="utf-8")
    assert aimode.load() is None


def test_describe_says_what_was_found_and_what_the_mode_does():
    said = aimode.describe(OWNER)
    assert "16 processor threads" in said and "16 GB graphics card" in said
    assert "It can run Max" in said and "vision model" in said
    chose = aimode.describe(OWNER, "eco")
    assert "You chose Eco" in chose and chose.endswith(aimode.EFFECT["eco"] + ".")
    assert "next starts" in aimode.describe(None)


def test_low_cpu_mode_becomes_eco_once():
    on = {"perf.low_power": True}
    assert "low_power_is_eco" in migrate(on)
    assert on["perf.ai_mode"] == "eco" and "perf.low_power" not in on
    off = {"perf.low_power": False}
    migrate(off)
    assert "perf.ai_mode" not in off and "perf.low_power" not in off
    kept = {"perf.low_power": True, "perf.ai_mode": "max"}
    migrate(kept)
    assert kept["perf.ai_mode"] == "max"


def test_only_max_runs_the_vision_model(tmp_path, monkeypatch):
    from hivemind.brain import vlm
    monkeypatch.setattr(aimode, "HARDWARE", tmp_path / "none.json")
    on = vlm.from_settings(S({"perf.vlm": True, "perf.ai_mode": "max"}))
    assert on.enabled
    std = vlm.from_settings(S({"perf.vlm": True, "perf.ai_mode": "standard"}))
    assert not std.enabled and "Standard AI mode" in std.reason
    off = vlm.from_settings(S({"perf.vlm": False, "perf.ai_mode": "max"}))
    assert not off.enabled and off.reason == "turned off in settings"


def test_vram_reads_the_biggest_card(tmp_path, monkeypatch):
    from hivemind.platform import hardware
    for name, size in (("card0", 512 * 2 ** 20), ("card1", 16 * 2 ** 30)):
        (tmp_path / name / "device").mkdir(parents=True)
        (tmp_path / name / "device" / "mem_info_vram_total").write_text(str(size))
    (tmp_path / "card1-DP-1").mkdir()
    monkeypatch.setattr(hardware.shutil, "which", lambda _: None)
    assert hardware.vram_gb(tmp_path) == 16.0
    assert hardware.vram_gb(tmp_path / "nothing") is None


def test_an_nvidia_card_beside_a_built_in_amd_one_is_still_read(tmp_path, monkeypatch):
    import subprocess

    from hivemind.platform import hardware
    (tmp_path / "card0" / "device").mkdir(parents=True)        # the CPU's 0.5 GB amdgpu
    (tmp_path / "card0" / "device" / "mem_info_vram_total").write_text(str(512 * 2 ** 20))
    monkeypatch.setattr(hardware.shutil, "which", lambda _: "/usr/bin/nvidia-smi")
    monkeypatch.setattr(hardware.subprocess, "run", lambda *a, **k:
                        subprocess.CompletedProcess(a, 0, stdout="24564\n"))
    assert round(hardware.vram_gb(tmp_path), 1) == 24.0


def test_the_probe_times_one_thread_and_puts_the_count_back():
    import cv2

    from hivemind.platform import hardware
    from hivemind.vision import coins
    before = cv2.getNumThreads()
    ms = hardware.probe_ms(passes=1)
    assert cv2.getNumThreads() == before
    assert (ms is None) == (coins.model() is None)
    assert ms is None or ms > 0
