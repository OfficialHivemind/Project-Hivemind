## What this changes

<!-- One or two sentences, in plain words. -->

Fixes #<!-- the issue number, if there is one -->

## How I tested it

<!-- The tests you ran, and for anything that plays the game, what you saw on a real run. -->

- [ ] The test file for the part I changed passes, and so does `tests/unit/test_lint.py`
      (`PYTHONPATH=src:. python -m pytest -q tests/unit/test_<area>.py tests/unit/test_lint.py`)
- [ ] I added a small test for any new logic
- [ ] New movement or clicking is look-only first (it logs "would ..." and does nothing yet)
- [ ] New optional features are OFF by default
- [ ] No secrets, account names, personal paths or `var/` files in the diff
- [ ] No Robux, no memory reading, no injection
- [ ] User-facing text names no other macro products

## Anything else

<!-- Screenshots (username cropped out), measurements, open questions. -->
