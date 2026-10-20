# Contributing to Hivemind

Thanks for helping! You don't need to be an expert. Bug reports, ideas,
measurements and small fixes all count.

## Reporting a bug or an idea

Open an issue and pick **Bug report** or **Feature request**. Say what you
expected, what happened, and which build and system you used.

**Never paste** tokens, webhook URLs, private-server links or passwords, and
crop your Roblox username out of screenshots.

## The house rules

These come from [`AGENTS.md`](AGENTS.md), the guide for everyone (and every
AI assistant) working on the code. A pull request that breaks one will not
be merged.

1. **No Robux, ever.** Nothing may spend Robux or open a Robux purchase.
2. **Never press Enter, E or Yes, or click, on a guess.** Read the screen
   first and act only on a prompt that names what you expect.
3. **Never click Roblox's "I Agree"** or accept terms for the player.
4. **New movement or clicking is look-only first**: it logs what it *would*
   do, and goes live only after its logs have been checked.
5. **Optional features are OFF by default.**
6. **No secrets in the repo**: tokens, webhook URLs, private-server links,
   account names, `var/` files.
7. **Don't name other macro products** in anything users see. Natro Macro is
   credited in `NOTICE.md`.
8. **Everything is GPL-3.0**, like the rest of the project.

Hivemind only plays through the screen, keyboard and mouse: no memory
reading, no injection.

## Running the tests

You need Python 3.12 or newer. On Linux:

```sh
make venv
PYTHONPATH=src:. .venv/bin/python -m pytest -q tests/unit
```

On Windows, install the packages with
`pip install -r installer/requirements-windows.txt` and `pip install -e .`,
then run `python -m pytest -q tests/unit`.

Before you open a pull request, run the test file for the part you changed
plus `tests/unit/test_lint.py`.

## Pull requests

- Keep them small and about one thing.
- Say what you changed and **how you tested it**.
- Numbers in the code (speeds, timings, screen positions) are measured. If
  you change one, say how you measured it.
- Plain Python, line length 100, and comments that explain *why*.

By sending a pull request you agree that your work is shared under GPL-3.0.
Please follow the [Code of Conduct](CODE_OF_CONDUCT.md).
