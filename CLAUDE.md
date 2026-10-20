# CLAUDE.md

Read `AGENTS.md` first: it is this repo's guide for every AI assistant
(the hard rules, how to run and test, where things are, how code is written
here).

@AGENTS.md

Claude-specific:
- Search `scripts/run_farm.py` (tens of thousands of lines) with grep; read only the part you need.
- Before an edit that changes in-game movement or clicks, check rule 4 in AGENTS.md (look-only first).
- Run the one test file for the area you touched, plus `tests/unit/test_lint.py`, before saying you are done.
