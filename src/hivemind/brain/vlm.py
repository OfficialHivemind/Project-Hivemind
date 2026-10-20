"""The local vision model: asking a question about what is on screen.

WHAT IT IS FOR, AND WHAT IT IS NOT FOR

Classical CV does the work that happens every frame: HUD digits in 0.3 ms,
tokens by HSV, screens by structure. A 7B model cannot run at 30 fps and does
not need to. This is for the handful of questions that are *rare, awkward and
open-ended*, where a template would have to be written in advance for something
nobody has seen yet:

    an unknown dialog        "what does this box say, and what are its buttons?"
    a quest board            "list the objectives and their progress"
    being stuck              "what is in front of the character?"
    a new field              "is this open ground or a wall?"

All four share a shape: they happen occasionally, a wrong answer is recoverable,
and writing a template first is impossible because the whole point is that the
screen is unfamiliar.

IT NEVER INVENTS AN ANSWER

`ask()` returns None when the model is unavailable, times out, or replies with
something unusable. It does not fall back to a guess, and callers must handle
None -- because the alternative is a plausible sentence about a screen nobody
looked at, which is worse than no answer at all. `available()` and `reason`
say what is wrong in words a user can act on.

IT GETS CHEAPER AND MORE DETERMINISTIC WITH USE

Every answer is cached against a hash of the exact image region plus the exact
question. Bee Swarm's dialogs are static images, so the second time the bot
meets one the answer is a dictionary lookup: free, instant, and identical. A
model that is nondeterministic on first sight becomes a lookup table over time,
which is the property that makes it safe to depend on at all.

WHY OLLAMA OVER A PYTHON RUNTIME

It is packaged for Arch (`extra/ollama-vulkan`), it keeps the model resident
between calls, and it runs as a separate process -- so a model that wedges or
runs out of VRAM cannot take the bot down with it. Vulkan rather than ROCm
because Vulkan was the supported path on the test PC's GPU.
Talking to it is plain HTTP, so nothing here needs a heavyweight dependency.
"""
from __future__ import annotations

import base64
import hashlib
import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from ..datapaths import var
from ..platform.current import memory
from ..world import aimode

DEFAULT_HOST = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen2.5vl:7b"
CACHE_DIR = var("vlm_cache")
# EVERY REAL ANSWER KEPT WITH ITS PICTURE AND QUESTION, for training a small
# model from the big one later (research 2026-10-21: 143,964 cached answers,
# none usable, the cache keeps the text under a hash only). Written only when
# the folder exists, so an install opts in by making it (it may be a link to
# another drive); a call costs seconds, so the rate stays small.
SAMPLES_DIR = var("vlm_samples")

# A vision model on a 7B checkpoint answers in single-digit seconds. Past this
# something is wrong -- the model is swapping, or the request is queued behind
# another -- and the bot should get on with its life rather than block.
DEFAULT_TIMEOUT = 45.0
# How long to wait when merely asking whether the server is up.
PROBE_TIMEOUT = 2.0

# How long ollama keeps the weights resident after an answer.
#
# MEASURED THE HARD WAY: the Linux OOM killer terminated the agent twice while
# a live game test was running. This machine has 30 GB, and the peak stack is
# Sober (Roblox) plus a nested compositor plus the desktop app plus a 6 GB
# model -- with 2.9 of 4 GB of swap already consumed. Ollama's own default
# keeps a model resident for five minutes after the last request, which is
# exactly long enough to still be holding it when the game loads.
#
# 30s is long enough that a burst of questions about one screen reuses the
# loaded weights, and short enough that the model is gone before a game test
# starts. `unload()` makes it immediate when we know we are done.
# MEASURED 2026-09-20 on the test PC (a 16 GB GPU), because the
# original 30 s was chosen when the model was believed to cost system memory:
#
#     system RAM   9,808 -> 10,103 MB   (+295 MB)
#     VRAM          1.64 -> 7.91 GB     (+6.27 GB)
#     ollama ps     qwen2.5vl:7b  100% GPU
#
# The weights live in VRAM. They cost about 300 MB of system RAM, so the model
# was never a candidate for the OOM kills, and dropping it every 30 seconds
# bought almost nothing while paying a ~20 s reload for the next question.
#
# What unloading DOES free is VRAM, which the game also wants -- so
# `unload()` still exists and is still called before a launch. It is just no
# longer something to do between two questions asked a minute apart.
DEFAULT_KEEP_ALIVE = "10m"

# WHO THE MODEL IS, and it is prepended to every question unless a caller
# turns it off. The owner asked for this directly: the AI should know its only
# task is to play Bee Swarm.
#
# MEASURED difference it makes: asked "what do you see" on a real gameplay
# frame with no context, the reply was "a screenshot from a video game...
# possibly a beekeeping simulation" -- accurate, and no use to anything.
TASK = (
    "You are the eyes of an autonomous bot whose only job is to play the "
    "Roblox game Bee Swarm Simulator on its owner's behalf. Every image you "
    "are shown is a screenshot of that game, captured live while the bot is "
    "playing. Your answers are used to decide what the bot does next and to "
    "diagnose it when it goes wrong, so be concrete and specific about what "
    "is actually visible. If you cannot tell, say so plainly rather than "
    "guessing — a wrong answer is worse than no answer here."
)

# MEASURED on this machine, same question and same frame, model already
# resident on the GPU:
#
#     1920x1080   1,838 KB   3.7 s
#     1280x720      922 KB   1.6 s
#     960x540       585 KB   1.6 s
#     640x360       291 KB   1.6 s
#
# Full resolution costs over two seconds and buys nothing -- the 640-wide
# answer was the most detailed of the four ("a hexagonal platform... blue
# flowers with yellow centers"). Anything at or below the cap is left exactly
# as it is, so small crops -- a prompt panel is 352x58 -- keep every pixel,
# which is what reading text off them depends on.
MAX_WIDTH = 1280


def _learned_context() -> str:
    """What this bot has worked out by playing, appended to every question.

    THIS IS WHAT MAKES IT A SPECIALIST RATHER THAN A GENERAL MODEL BEING
    ASKED ABOUT A GAME. The owner: an AI dedicated to Bee Swarm alone, which
    knows everything about it and keeps growing that knowledge.

    qwen2.5vl:7b has vague second-hand knowledge of Bee Swarm -- asked what it
    saw on a real frame with no context it offered "possibly a beekeeping
    simulation". What it does not have is anything about THIS account, THIS
    client or what this bot has already discovered: that a free pad reads
    "Claim Hive", that the shop is not a destination, that dying empties the
    backpack. Those came from playing, and now they travel with every
    question.

    It never raises and never blocks a question: a knowledge base that can
    break vision is worse than one that is briefly out of date.
    """
    try:
        from .knowledge import for_playing
        briefing = for_playing()
    except Exception:
        return ""
    return f"\n\n{briefing}" if briefing else ""


def _shrink(image_png: bytes) -> bytes:
    """Downscale an oversized frame. Returns the original on any failure."""
    try:
        import cv2
        import numpy as np
        buf = np.frombuffer(image_png, dtype=np.uint8)
        img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
        if img is None or img.shape[1] <= MAX_WIDTH:
            return image_png
        scale = MAX_WIDTH / float(img.shape[1])
        small = cv2.resize(img, None, fx=scale, fy=scale,
                           interpolation=cv2.INTER_AREA)
        ok, out = cv2.imencode(".png", small)
        return out.tobytes() if ok else image_png
    except Exception:
        return image_png


@dataclass(frozen=True)
class Answer:
    """What the model said, and how much it cost to find out."""
    text: str
    model: str
    seconds: float
    cached: bool

    def describe(self) -> str:
        how = "cached" if self.cached else f"{self.seconds:.1f}s"
        return f"{self.text}  [{self.model}, {how}]"


class VisionModel:
    """A local vision-language model, or an honest report of its absence."""

    def __init__(self, host: str = DEFAULT_HOST, model: str = DEFAULT_MODEL,
                 cache_dir: Path | str = CACHE_DIR,
                 timeout: float = DEFAULT_TIMEOUT, enabled: bool = True,
                 keep_alive: str = DEFAULT_KEEP_ALIVE):
        self.host = host.rstrip("/")
        self.model = model
        self.cache_dir = Path(cache_dir)
        self.timeout = timeout
        self.enabled = enabled
        self.keep_alive = keep_alive
        self.reason = "" if enabled else "turned off in settings"
        self.calls = 0
        self.cache_hits = 0

    # ---- availability -----------------------------------------------------
    def available(self) -> bool:
        """Is the server up with our model loaded? Sets `reason` if not.

        Deliberately cheap and deliberately not cached: the server can be
        started or stopped while the bot runs, and a stale "unavailable" would
        keep a working model switched off for the rest of the session.
        """
        if not self.enabled:
            self.reason = "turned off in settings"
            return False
        try:
            with urllib.request.urlopen(f"{self.host}/api/tags",
                                        timeout=PROBE_TIMEOUT) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            self.reason = (f"no model server at {self.host} ({exc.reason}) — "
                           "sudo pacman -S ollama-vulkan && "
                           "sudo systemctl enable --now ollama")
            return False
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self.reason = f"model server gave an unusable reply: {exc}"
            return False

        names = [entry.get("name", "") for entry in body.get("models", [])]
        if not any(name.startswith(self.model.split(":")[0]) for name in names):
            self.reason = (f"{self.model} is not pulled yet — "
                           f"ollama pull {self.model}"
                           + (f"  (installed: {', '.join(names)})" if names else ""))
            return False
        self.reason = ""
        return True

    # ---- asking -----------------------------------------------------------
    def ask(self, image_png: bytes, question: str,
            use_cache: bool = True, context: str | None = TASK,
            essential: bool = False) -> Answer | None:
        """Ask about an image. None means no answer, never a guess.

        `image_png` is encoded bytes rather than an array on purpose: the cache
        key must be the EXACT bytes the model saw, so the same screen gives the
        same key, and callers crop to the region that matters before encoding.

        `context` tells the model what it is looking at and what it is for.
        Without it the answers are generic -- asked "what do you see" on a real
        frame it replied "a screenshot from a video game... possibly a
        beekeeping simulation", which is true and useless. Pass None to ask a
        bare question.
        """
        image_png = _shrink(image_png)
        if context:
            question = f"{context}{_learned_context()}\n\n{question}"
        key = self._key(image_png, question)
        if use_cache:
            hit = self._read_cache(key)
            if hit is not None:
                self.cache_hits += 1
                return Answer(hit, self.model, 0.0, cached=True)

        if not self.available():
            return None
        if not self.room_to_load(essential=essential):
            return None

        payload = json.dumps({
            "model": self.model,
            "prompt": question,
            "images": [base64.b64encode(image_png).decode("ascii")],
            "stream": False,
            "keep_alive": self.keep_alive,
            # Deterministic decoding. The whole value of the cache is that the
            # same screen gives the same answer; sampling would undermine it
            # before the cache ever got the chance to.
            "options": {"temperature": 0.0, "seed": 7},
        }).encode("utf-8")

        started = time.monotonic()
        try:
            request = urllib.request.Request(
                f"{self.host}/api/generate", data=payload,
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            self.reason = f"the model did not answer: {exc.reason}"
            return None
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self.reason = f"unusable reply from the model: {exc}"
            return None

        text = str(body.get("response", "")).strip()
        if not text:
            self.reason = "the model returned an empty answer"
            return None

        self.calls += 1
        elapsed = time.monotonic() - started
        if use_cache:
            self._write_cache(key, text)
        self._keep_sample(key, image_png, question, text)
        return Answer(text, self.model, elapsed, cached=False)

    def unload(self) -> bool:
        """Ask ollama to drop the weights NOW, and say whether it worked.

        Called before anything heavy starts -- a game launch, a long capture
        run. Six gigabytes is the difference between a test that finishes and
        one the OOM killer ends, and this machine has already lost two agents
        that way.

        A zero `keep_alive` on an empty prompt is ollama's documented way to
        evict a model without generating anything.

        NOT WHEN THIS BOT HAS IT TURNED OFF (`perf.vlm`): the server is the
        machine's, and the alt's bot (tools/alt), which runs without it, would
        otherwise drop the main's weights at every start and memory check --
        a ~20 s reload in the middle of the main's play.
        """
        if not self.enabled:
            return False
        payload = json.dumps({"model": self.model, "prompt": "",
                              "keep_alive": 0}).encode("utf-8")
        try:
            request = urllib.request.Request(
                f"{self.host}/api/generate", data=payload,
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(request, timeout=PROBE_TIMEOUT * 5):
                return True
        except (urllib.error.URLError, OSError, ValueError):
            return False        # nothing loaded, or no server: either is fine

    def room_to_load(self, essential: bool = False) -> bool:
        """Would asking now load the weights into a machine without room?

        A question to a dropped model reloads it. The reload costs about
        platform/memory.MODEL_LOAD_COST_GB of system memory, and every image
        asked after it adds about a tenth of a gigabyte until the model is
        dropped again (MEASURED, see platform/memory). Before this, run_farm
        dropped the model below its floor and the very next feed read loaded
        it straight back -- run-452.log shows the drop every three minutes.
        An answer that has to wait for room is a missed feed line; memory
        taken from the owner's game is a crash.

        Only a LOCAL server is checked: this machine's memory says nothing
        about another's. Loaded already: nothing to add, so always yes.
        """
        if not self.host.startswith(("http://127.0.0.1", "http://localhost")):
            return True
        need = memory.ESSENTIAL_LOAD_GB if essential else memory.MODEL_LOAD_GB
        now = memory.read()
        if now.total_gb == 0.0 or now.available_gb >= need:
            return True
        if self.resident_bytes() > 0:
            return True
        self.reason = (f"not loading the vision model: {now.available_gb:.1f} "
                       f"GB free and loading it needs {need:.1f} GB — another "
                       f"program is using the memory; it loads once there is "
                       f"room")
        return False

    def resident_bytes(self) -> int:
        """How much the server currently has loaded. 0 when nothing is."""
        try:
            with urllib.request.urlopen(f"{self.host}/api/ps",
                                        timeout=PROBE_TIMEOUT) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, ValueError,
                json.JSONDecodeError):
            return 0
        return sum(int(m.get("size", 0)) for m in body.get("models", []))

    # ---- the cache --------------------------------------------------------
    def _key(self, image_png: bytes, question: str) -> str:
        digest = hashlib.sha256()
        digest.update(image_png)
        digest.update(b"\x00")
        digest.update(question.encode("utf-8"))
        digest.update(b"\x00")
        digest.update(self.model.encode("utf-8"))   # a new model, a new answer
        return digest.hexdigest()

    def _path(self, key: str) -> Path:
        # two-level fan-out, so a long session does not put ten thousand files
        # in one directory
        return self.cache_dir / key[:2] / f"{key}.txt"

    def _read_cache(self, key: str) -> str | None:
        try:
            return self._path(key).read_text(encoding="utf-8")
        except OSError:
            return None

    def _write_cache(self, key: str, text: str) -> None:
        path = self._path(key)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        except OSError:
            pass            # a cache that cannot be written is not an error

    def _keep_sample(self, key: str, image_png: bytes, question: str, text: str) -> None:
        """SAMPLES_DIR/<key>.png + .json (question, answer, model), when it exists."""
        if not SAMPLES_DIR.is_dir():
            return
        try:
            (SAMPLES_DIR / f"{key}.png").write_bytes(image_png)
            (SAMPLES_DIR / f"{key}.json").write_text(json.dumps(
                {"question": question, "answer": text, "model": self.model,
                 "at": time.time()}), encoding="utf-8")
        except OSError:
            pass            # a sample that cannot be written is not an error

    def stats(self) -> str:
        total = self.calls + self.cache_hits
        if not total:
            return "not used yet"
        share = self.cache_hits / total
        return (f"{total} questions, {self.cache_hits} from cache "
                f"({share:.0%} free)")


def from_settings(settings=None) -> VisionModel:
    """Build a client configured the way the user asked for it.

    This is what makes the `perf.vlm` toggle real rather than decorative. It
    was shipped as a control wired to nothing, which is exactly the thing the
    owner asked not to happen; the settings test now fails if it ever becomes
    ornamental again.
    """
    if settings is None:
        from ..world.settings import Settings
        settings = Settings()
    # ONLY THE MAX AI MODE RUNS IT (world/aimode, ROADMAP AI-N4): it is the
    # one big model, +6.27 GB of graphics memory (measured above).
    on = bool(settings.bool("perf.vlm"))
    allowed = aimode.vision_model_allowed(settings)
    model = VisionModel(
        model=str(settings.get("perf.vlm_model", DEFAULT_MODEL)),
        enabled=on and allowed)
    if on and not allowed:
        model.reason = (f"not used in the {aimode.chosen(settings).capitalize()} "
                        "AI mode (Settings > General)")
    return model
