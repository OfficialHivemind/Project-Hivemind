"""Eco / Standard / Max: how much of the PC the bot's AI uses (ROADMAP AI-N4).

The setting `perf.ai_mode` is "auto" (the default) or one of MODES. Auto is
what this PC's MEASURED hardware supports: platform/hardware.probe() times the
coin finder and reads the processor, memory and graphics card once a start
(run_farm saves it to var/hardware.json; the doctor measures it again), and
`pick` turns that into a mode with its reason in plain words.

WHAT A MODE CHANGES (the levers the bot really has, measured; nothing else):

  * Screen reading: OpenCV's threads (run_farm). Eco 1, else the bot's 4.
    MEASURED 2026-10-27 (tools/bench_cvthreads.py, 100 incident frames, the
    overlay pass paced like the live one): 4 threads at 216 ms 0.44 cores,
    1 thread at 432 ms 0.15 cores, the same answers.
  * The read rate of the token model in the live view's boxes (the "model
    fps") and the view's own fps (telemetry/liveview): Eco caps the view at
    15 fps and the boxes at one pass per 432 ms (2.3 a second), else the
    player's perf.capture_fps / perf.overlay_ms (216 ms, 4.6 a second).
    The chaser's own looks are not paced: it looks once per step.
  * The model size: the local vision model (brain/vlm, qwen2.5vl:7b) is the
    one big model the bot runs, +6.27 GB of graphics memory MEASURED
    2026-09-20. Only Max uses it (still behind perf.vlm). The token models
    are one size: no int8 or smaller coin network exists, and one would save
    at most ~2 ms a look (docs/pending/inferworker.md, measured 27 Oct).
  * Token weights are NOT per mode: the typed head costs 1.2 ms per 10 crops
    on 1 thread (inferworker.md), about 2% of an Eco look, so a smaller
    token set would save nothing and lose pickups. The player's Token
    priority table applies in every mode.

perf.low_power ("Low CPU mode") was Eco before modes existed; its `true`
becomes `perf.ai_mode: eco` (world/settings MIGRATIONS).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass

from ..datapaths import var

SETTING = "perf.ai_mode"
AUTO = "auto"
MODES = ("eco", "standard", "max")
HARDWARE = var("hardware.json")
# No measurement yet (a GUI opened before the bot ever started, an unreadable
# file): what the bot did before modes existed, which is Max -- 4 threads,
# the player's rates, the vision model as perf.vlm says.
UNMEASURED = "max"

# THE PROBE: the coin finder's stage 1 (HOG, vision/coins.candidates) on a
# fixed 1920x1080 picture on ONE OpenCV thread, median of a few passes.
# MEASURED 2026-10-27 on the owner's PC (8-core Ryzen, nice 19, beside the
# live bot): 38.7 ms (38.0-41.1 over 7) on the synthetic picture against
# 35.0 ms median on 120 real incident frames, so it tracks the real look
# (43.0 ms a whole 1-thread look on the same frames, 16.6 on 4 threads).
REFERENCE_PROBE_MS = 38.7
# ECO WHEN READING IS 2.5x SLOWER THAN THAT. DERIVED, ASSUMED to scale with
# the probe: the live boxes pass is ~84 ms on 4 threads here (run-1259/1260
# "live view:" lines, 78-87 ms); at 2.5x it is ~210 ms, the whole 216 ms
# between passes, so they would run back to back beside the game.
ECO_PROBE_MS = 2.5 * REFERENCE_PROBE_MS
# 4 reading threads on a PC with 4 or fewer would leave the game no core.
ECO_CPUS = 4
# ASSUMED: the game and its compositor settle at 3-4 GB (platform/memory
# GAME_GB, measured); under 8 GB in all, the PC is a small laptop.
ECO_RAM_GB = 8.0
# MAX NEEDS A CARD WITH ROOM FOR THE VISION MODEL BESIDE THE GAME. MEASURED
# 2026-10-27 on the owner's 16 GB card with the model loaded: 9.41 GB used,
# 6.27 of it the model (2026-09-20), so ~3.1 GB is the game and the desktop.
MAX_VRAM_GB = 10.0


@dataclass
class Hardware:
    """One measurement of this PC. None where it could not be read."""
    cpus: int
    probe_ms: float | None
    ram_total_gb: float
    ram_free_gb: float
    vram_gb: float | None


def pick(hw: Hardware) -> tuple[str, str]:
    """(mode, why in plain words) for this PC. RAM decides by its TOTAL: the
    free amount swings by gigabytes as programs open, and the start gate and
    the model drop line (platform/memory) already act on it live."""
    if hw.cpus <= ECO_CPUS:
        return "eco", f"it has {hw.cpus} processor threads, and the game needs them"
    if hw.probe_ms is not None and hw.probe_ms > ECO_PROBE_MS:
        return "eco", (f"screen reading is {hw.probe_ms / REFERENCE_PROBE_MS:.1f}x "
                       "slower than on the PC it was tuned on")
    if 0 < hw.ram_total_gb < ECO_RAM_GB:
        return "eco", f"it has {hw.ram_total_gb:.0f} GB of memory in all"
    if hw.vram_gb is not None and hw.vram_gb < MAX_VRAM_GB:
        return "standard", (f"its graphics card has {hw.vram_gb:.0f} GB; the vision "
                            f"model needs about {MAX_VRAM_GB:.0f} GB beside the game")
    if hw.vram_gb is None:
        return "max", ("its graphics memory could not be read, so the vision "
                       "model is left as you set it")
    return "max", f"its graphics card has {hw.vram_gb:.0f} GB"


def save(hw: Hardware, path=None) -> None:
    path = path or HARDWARE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(hw)), encoding="utf-8")


def load(path=None) -> Hardware | None:
    try:
        return Hardware(**json.loads((path or HARDWARE).read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return None


def chosen(settings, hw: Hardware | None = None) -> str:
    """The mode in force: the player's pick, else what the measured PC
    supports (`hw`, or the last start's var/hardware.json). A settings
    object that cannot say gets UNMEASURED, what the bot did before modes."""
    try:
        value = str(settings.get(SETTING) or AUTO)
    except Exception:
        return UNMEASURED
    if value in MODES:
        return value
    hw = hw or load()
    return pick(hw)[0] if hw else UNMEASURED


def is_eco(settings) -> bool:
    return chosen(settings) == "eco"


def vision_model_allowed(settings) -> bool:
    """Only Max runs the big vision model (still behind perf.vlm)."""
    return chosen(settings) == "max"


EFFECT = {
    "eco": "screen reading on 1 core, the live view at 15 fps with its boxes "
           "2 times a second, no vision model",
    "standard": "screen reading on 4 cores, the live view at your rates, "
                "no vision model",
    "max": "as Standard, plus the vision model on the graphics card "
           "(if 'Use the vision model' is on)",
}


def describe(hw: Hardware | None, setting: str = AUTO) -> str:
    """The plain-words line for Settings, the doctor and the run log."""
    if hw is None:
        head = "This PC is measured when the bot next starts."
        mode = setting if setting in MODES else UNMEASURED
    else:
        mode, why = pick(hw)
        vram = "unknown graphics memory" if hw.vram_gb is None else \
            f"a {hw.vram_gb:.0f} GB graphics card"
        head = (f"This PC: {hw.cpus} processor threads, {hw.ram_total_gb:.0f} GB "
                f"of memory ({hw.ram_free_gb:.0f} GB free), {vram}. It can run "
                f"{mode.capitalize()}: {why}.")
        if setting in MODES and setting != mode:
            head += f" You chose {setting.capitalize()}."
            mode = setting
    return f"{head} {mode.capitalize()} = {EFFECT[mode]}."
