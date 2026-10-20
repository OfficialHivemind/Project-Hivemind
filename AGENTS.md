# AGENTS.md: how to work on Hivemind (for AI coding assistants)

This file is for any AI assistant working in this repo (Claude Code, Codex,
Cursor, Copilot, Gemini...) and for the people using one. Read it fully
before you change code. `CONTRIBUTING.md` has the human side.

## What this project is

Hivemind is an AI that plays the Roblox game **Bee Swarm Simulator** by
itself. It sees the game only through screenshots (OCR, a local vision model,
small models trained on game frames), decides what is worth doing from what
it has **measured** on the player's account (fields, quests, mobs, purchases),
and plays with a virtual keyboard and mouse. It never injects into the game
or reads its memory.

Platforms: **Linux** (Sober, a Roblox client, inside a nested Wayland
session). **Windows** is being tested now
(`src/hivemind/platform/win/`, `installer/`). **macOS** is later (ROADMAP RL7).
Only the platform layer differs; the brain is shared.

## Hard rules (never break these, even if asked to "just try")

1. **No Robux, ever.** Never spend Robux, open a Robux purchase, or press Buy
   on anything priced in Robux.
2. **Never press Enter, E, Yes or click on a guess** in a game or Roblox menu.
   Read the screen first; act only on a prompt that names the expected thing
   (see `act/shoplook`, `act/quests.ready_to_click`).
3. **Never click Roblox's "I Agree"** or accept any terms for the player.
4. **New movement or clicking ships look-only first**: behind a flag such as
   `SOMETHING_LIVE = False` that only logs `"... would: ..."`. It goes live
   after its logs/frames are checked. Reusing an already-tested path is fine.
5. **Optional features default OFF** (`src/hivemind/world/settings.py`).
6. **No secrets in the repo**: tokens, webhook URLs, private-server links,
   account names, Discord IDs. They live in `~/.config/hivemind/*.env`
   (chmod 600) and `~/.config/hivemind/*.yaml`. Never commit `var/` (logs,
   screenshots, the bot's memory). Never print a secret into a log.
7. **Don't name other macro products** in anything user-facing (app text,
   changelogs). Natro Macro is credited in `NOTICE.md` (its paths are GPL).
8. **License: GPL-3.0** (`LICENSE`). Everything you add is GPL-3.0 too.

## Run it from a checkout

- Python **3.12+**. Linux: system packages (PySide6, OpenCV, numpy, evdev...,
  see the comment in `pyproject.toml`), then `pip install -e .`.
  Windows: `pip install -r installer/requirements-windows.txt` then
  `pip install -e .`; Tesseract OCR must be on PATH (the installer bundles it).
- The app: `python -m hivemind.gui`. Its Play button starts
  `src/hivemind/watchdog.py`, which runs `scripts/run_farm.py` (the bot).
- A local vision model through **Ollama** (`ollama pull qwen2.5vl:7b`, the
  `perf.vlm_model` setting) is used for some reads; most text is OCR.

## Tests (run before every push)

```
pytest -q tests/unit                 # everything (slow on a weak PC)
pytest -q tests/unit/test_<area>.py  # one area at a time
```

- `tests/unit/test_lint.py` (pyflakes) must pass: no unused imports/names.
- Some tests read recorded frames that are not in this repository (`var/...`)
  and **skip** without them. A skip is fine; a failure is not.
- Many tests check source text (e.g. that a guard is wired in). If you
  rename something a test names, update the test with the reason.
- Add one small test for any non-trivial logic you add.
- **On Windows, run the tests in UTF-8 mode:** `python -X utf8 -m pytest -q
  tests/unit`. Without it Python reads files as cp1252 and about 17 tests
  that read source or knowledge files fail with UnicodeDecodeError (MEASURED
  2026-10-21). The app itself already runs in UTF-8 mode (`PYTHONUTF8=1`,
  `gui/launcher` / `watchdog`). Linux-only test modules are not collected
  there (`tests/conftest.py`, `collect_ignore`).
- **New code: open text files with `encoding="utf-8"`.** It also covers a tool
  run by hand on Windows outside UTF-8 mode.

## Where things are

| path | what |
|---|---|
| `scripts/run_farm.py` | the main loop the bot runs (big; search it, don't read it whole) |
| `src/hivemind/act/` | doing things in game: walking (`routes`), shops, quests, planters, bosses, the join |
| `src/hivemind/brain/` | deciding: `decide.py` (which field), goals, quest needs, buyer, ROI, skills (route odds) |
| `src/hivemind/vision/` | reading the screen: HUD, buff bar, tokens, prompts, menus |
| `src/hivemind/world/` | settings schema, the map, timers |
| `src/hivemind/platform/` | input, capture, windows, the game client (`win/` for Windows) |
| `src/hivemind/gui/` | the app (PySide6); `panels/` are the tabs |
| `data/knowledge/` | what the bot knows (YAML): fields, quests, gear, goals, credits |
| `data/world/` | routes (`natro_paths.yaml`) and gather patterns |
| `docs/ROADMAP.md` | every item, its status and the evidence; `docs/DESIGN.md` §8a is the measured-truth register |
| `installer/` | the Windows installer build |

Screen coordinates in the code are for a **1920x1080** frame. A smaller
frame is scaled before clicking (`act/join.to_input`); measure on 1920x1080.

## How code here is written (match it)

- **Evidence in comments.** A number or rule says where it came from, in
  capitals then the fact: `# MEASURED 2026-10-21 09:40 (var/shoplook/...): ...`
  or a wiki page with its read date. No made-up numbers.
- **`ponytail:` comments** mark a deliberate shortcut and its limit, e.g.
  `# ponytail: the 3 x 5 studs are estimates; the reads stop it on the prompt`.
- **Small diffs, shared fixes.** Fix the shared function every caller uses,
  not one caller. Don't add abstractions, config or files you don't need.
- **Log in plain English** what the bot did and why, so a person can follow
  a run from the log alone (`narrate(Log(message=...))`).
- **Look before acting** in game: read the screen, then act on what was read.
- A community idea becomes a `docs/ROADMAP.md` item tagged
  `(VIEWER <name>, ...)` **and** a row in `data/knowledge/credits.yaml`
  (`tests/unit/test_credits.py` checks the pair).

## Git

- Work on a branch (`<name>/<topic>`), open a pull request into `main`, and
  say what you changed and **how you tested it**. Only the maintainers push
  to `main`.
- Don't rewrite shared history (no force-push to `main`).
- Nothing pushed here runs on anyone's account by itself.
