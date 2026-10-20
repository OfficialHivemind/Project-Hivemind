#!/usr/bin/env python3
"""Every look-only flag (`NAME_LIVE = False`) and what the run logs say it
would have done: for the release gate, so a person can promote them one by
one (AGENTS.md rule 4: "It goes live after its logs/frames are checked").

    lookonly_report.py                          print the report
    lookonly_report.py --out docs/pending/lookonly-report.md
    lookonly_report.py --var ~/Hivemind/var --live ~/Hivemind

Per flag: where it is set, the text it logs (the "... would: ..." lines its
comment quotes, and the "would" strings and the flag's own name written
near each mention of it), how many lines of var/night/run-*.log carry that
text since the flag's first commit, the latest few, and what its comment
says must be true to flip it. The verdict column is pre-filled (seen / never
seen / not deployed); the person reading it changes it to "looks wrong"
where it does. Last, the "<who> would:" lines no flag accounts for.
Read-only: it changes no flag and writes only --out.

ponytail: the logged text is found by a window of source lines after each
mention of the flag, so a log line built far from it is missed (the flag
shows "never seen", or its line shows up under the other lines); add its
text to EXTRA when that happens.
"""
from __future__ import annotations

import argparse
import ast
import os
import re
import subprocess
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCAN = ("src", "scripts", "tools")
FLAG = re.compile(r"^\s*([A-Z][A-Z0-9_]*_LIVE)\s*(?::[^=]*)?=\s*False\b\s*(#.*)?$")
CONST = re.compile(r"^[A-Z][A-Z0-9_]* = \S")
LITERAL = re.compile(r"""(?<![\w"'])[rbfRBF]{0,2}(["'])(.+?)(?<!\\)\1""")
WINDOW = 15          # source lines after a mention of the flag
BACK = 5             # and before a read in code (the same statement)
MIN_TEXT = 10        # shorter static text matches too much of a log
OTHER = re.compile(r"\b([A-Za-z][\w-]*(?: [\w-]+){0,2}) would: ")
FLIP_WORDS = re.compile(r"\b(True|flip\w*|promot\w*|until|once|live (after|when|only|half|walk)"
                        r"|goes live|checked|verified|not built)\b", re.I)
# Log text a window cannot find (a line built away from the flag's reads).
EXTRA: dict[str, list[str]] = {
    # the shadow is a word on the "value:" line (run_farm shadow_value)
    "RHO_BALANCE_LIVE": [", trip live)"],
    # its own log and Telegram, not the run log (rollback_watch.step)
    "AUTO_ROLLBACK_LIVE": ["LOOK-ONLY: would roll back to"],
    # boost_ai_look's plan line; ponytail: boost_ai_vetoes' 'look'-mode
    # "boost AI would: use/skip the ..." lines are counted with it
    "MOVES_LIVE": ["boost AI would:"],
    # "planner explore " + "would: draw" are two literals
    "PLANNER_EXPLORE_LIVE": ["planner explore would:"],
}


def flags(root: Path = ROOT) -> list[dict]:
    """[{name, path, line, comment}] for every `NAME_LIVE = False` under SCAN."""
    out = []
    for py in _sources(root):
        lines = py.read_text(encoding="utf-8").splitlines()
        for i, text in enumerate(lines):
            m = FLAG.match(text)
            if not m:
                continue
            # the comment block above it, past its sibling constants
            # (CHAIN_PX = ... between the comment and CHAIN_LIVE) unless the
            # flag has its own inline comment (then the block is a neighbour's)
            block, j, past = [], i - 1, 0
            while j >= 0:
                if lines[j].strip().startswith("#"):
                    block.insert(0, lines[j].strip().lstrip("#").strip())
                elif (not block and not m.group(2) and past < 4 and not text[0].isspace()
                      and (CONST.match(lines[j]) or lines[j][:1].isspace())
                      and not FLAG.match(lines[j])):
                    past += 1               # a sibling constant or its next line
                else:
                    break
                j -= 1
            if m.group(2):
                block.append(m.group(2).lstrip("#").strip())
            if not block:                   # e.g. ARMS_LIVE: said in the module doc
                doc = ast.get_docstring(ast.parse("\n".join(lines))) or ""
                block = [" ".join(p.split()) for p in doc.split("\n\n") if m.group(1) in p]
            out.append({"name": m.group(1), "path": py.relative_to(root).as_posix(),
                        "line": i + 1, "comment": " ".join(block)})
    return out


def _static(literal: str) -> str:
    """The piece of a (maybe f-) string literal outside its {...} that says
    "would", else the longest piece."""
    pieces = re.split(r"\{[^{}]*\}", literal)
    return max(pieces, key=lambda t: ("would" in t, len(t))).strip()


def _quoted(comment: str) -> list[str]:
    """The "... would: ..." lines a comment quotes, cut after "would:" and the
    word after it (the rest is usually a placeholder: "slot N", "...")."""
    out = []
    for q in re.findall(r'"([^"]{0,80}?\bwould\b[^"]{0,80}?)"', comment):
        m = re.match(r"(.*?\bwould:?(?: [\w']+)?)", q)
        out.append((m.group(1) if m else q).strip())
    return out


def texts(name: str, comment: str = "", root: Path = ROOT) -> list[str]:
    """What a flag's look-only half logs: the "would" lines its comment
    quotes, and the static text of string literals after (code: around)
    each mention of `name` (code or comment) that say "would" or name it."""
    word = re.compile(rf"\b{name}\b")
    found: list[str] = [q for q in _quoted(comment) if _usable(q)]
    for py in _sources(root):
        lines = py.read_text(encoding="utf-8").splitlines()
        for i, text in enumerate(lines):
            if not word.search(text) or FLAG.match(text):
                continue
            # a comment points at the code below it; code reads both ways
            before = 0 if text.strip().startswith("#") else BACK
            for near in lines[max(0, i - before): i + WINDOW + 1]:
                if near.strip().startswith(("#", '"""', "'''")):
                    continue
                for m in LITERAL.finditer(near):
                    lit = m.group(2)
                    if "would" not in lit and name not in lit:
                        continue
                    piece = _static(lit)
                    if name in lit and name not in piece:
                        piece = name
                    if _usable(piece) and piece not in found:
                        found.append(piece)
    return found + [t for t in EXTRA.get(name, []) if t not in found]


def _usable(piece: str) -> bool:
    """Says one thing: a flag's name, or words around "would" ("would
    wait" alone, or an identifier, matches too much)."""
    if re.fullmatch(r"[A-Z][A-Z0-9_]*_LIVE", piece):
        return True
    if " " not in piece:
        return False
    return len(piece) >= (2 * MIN_TEXT if piece.startswith("would") else MIN_TEXT)


def _sources(root: Path) -> list[Path]:
    """The .py files under SCAN, this tool left out (its EXTRA names flags)."""
    me = Path(__file__).resolve()
    return sorted(p for d in SCAN for p in (root / d).rglob("*.py") if p.resolve() != me)


def first_commit(name: str, path: str, root: Path = ROOT) -> float | None:
    """Unix time of the first commit that added `name = False` to `path`."""
    got = subprocess.run(["git", "log", "-S", f"{name} = False", "--reverse", "--format=%ct",
                          "--", path], cwd=root, capture_output=True, text=True).stdout.split()
    return float(got[0]) if got else None


def scan(logs: list[Path], wanted: dict[str, tuple[float, list[str]]], keep: int = 3):
    """({name: (count, [latest `keep` (log, snippet)])}, Counter of the other
    "<who> would:" lines) over run logs, each flag's counted only in logs
    written after its time. A snippet starts just before the matched text."""
    got = {n: [0, []] for n in wanted}
    others: Counter = Counter()
    first = min((s for s, _ in wanted.values() if s), default=0)
    for log in logs:
        mtime = log.stat().st_mtime
        if mtime < first:
            continue
        live = [(n, ts) for n, (since, ts) in wanted.items() if ts and mtime >= (since or 0)]
        every = [t for _, ts in wanted.values() for t in ts]
        with open(log, encoding="utf-8", errors="replace") as fh:
            for text in fh:
                if " would" not in text and not any(t in text for _, ts in live for t in ts):
                    continue
                for n, ts in live:
                    hit = next((t for t in ts if t in text), None)
                    if hit is None:
                        continue
                    got[n][0] += 1
                    snip = text[max(0, text.find(hit) - 60):].strip()
                    if got[n][1] and got[n][1][-1][1] == snip:
                        got[n][1][-1] = (log, snip)     # the same words again: keep the latest
                    else:
                        got[n][1] = (got[n][1] + [(log, snip)])[-keep:]
                m = OTHER.search(text)
                if m and not any(t in text for t in every):
                    others[m.group(1)] += 1
    return {n: (c, ex) for n, (c, ex) in got.items()}, others


def flip_rule(comment: str) -> str:
    """The comment's sentences about going live, else the whole comment."""
    said = [s for s in re.split(r"(?<=[.;])\s+", comment) if FLIP_WORDS.search(s)]
    return " ".join(said) or comment or "(no comment found)"


def _cell(text: str, limit: int = 0) -> str:
    text = text.replace("|", "\\|").replace("\n", " ")
    return text[:limit - 1] + "…" if limit and len(text) > limit else text


def report(root: Path, var: Path, live: Path | None) -> str:
    logs = sorted((var / "night").glob("run-*.log"), key=lambda p: p.stat().st_mtime)
    found = flags(root)
    for f in found:
        f["texts"] = texts(f["name"], f["comment"], root)
        f["since"] = first_commit(f["name"], f["path"], root)
        lf = live / f["path"] if live else None
        f["deployed"] = (None if lf is None else
                         lf.exists() and re.search(rf"\b{f['name']}\b", lf.read_text(encoding="utf-8")) is not None)
    seen, others = scan(logs, {f["name"]: (f["since"], f["texts"]) for f in found})
    day = lambda t: time.strftime("%Y-%m-%d", time.localtime(t)) if t else "?"
    out = [
        "# Look-only flags: what each would have done (release gate)",
        "",
        f"Made {time.strftime('%Y-%m-%d %H:%M')} by `tools/lookonly_report.py` from {len(logs)} run logs "
        f"in `{str(var).replace(str(Path.home()), '~')}/night` (newest {day(logs[-1].stat().st_mtime) if logs else '-'}). Re-run it rather than",
        "editing it, except the verdict column. A count is the run-log lines carrying the flag's logged",
        "text, in logs written after the flag's first commit (a commit is not a deploy: \"in live\" says",
        "whether the live install's copy of that file has the flag at all). No flag was changed.",
        "",
        "Verdict: pre-filled `seen` / `never seen` / `not deployed`; a person checks the examples (and",
        "their frames) and writes `looks wrong` where the line says something it shouldn't.",
        "",
        "| flag | where | since | in live | lines | last seen | verdict |",
        "|---|---|---|---|---|---|---|",
    ]
    for f in found:
        count, ex = seen[f["name"]]
        verdict = ("not deployed" if f["deployed"] is False else
                   "seen" if count else "never seen" if f["texts"] else "never seen (logs nothing)")
        last = f"{ex[-1][0].stem} {day(ex[-1][0].stat().st_mtime)}" if ex else "-"
        deployed = {True: "yes", False: "no", None: "?"}[f["deployed"]]
        out.append(f"| `{f['name']}` | `{f['path']}:{f['line']}` | {day(f['since'])} | {deployed} "
                   f"| {count} | {last} | {verdict} |")
    for f in found:
        count, ex = seen[f["name"]]
        out += ["", f"## {f['name']}", "",
                f"- where: `{f['path']}:{f['line']}`",
                "- logs: " + ("; ".join(f"`{_cell(t)}`" for t in f["texts"])
                              or "(no logged text found near its reads)"),
                f"- lines since {day(f['since'])}: {count}"
                + ("; latest:" if ex else "")]
        out += [f"  - {log.stem} ({day(log.stat().st_mtime)}): `{_cell(text, 240).replace('`', chr(39))}`"
                for log, text in reversed(ex)]
        out += [f"- to flip it (its comment): {_cell(flip_rule(f['comment']), 700)}"]
        if f["comment"]:
            out += ["", "<details><summary>its whole comment</summary>", "",
                    _cell(f["comment"]), "", "</details>"]
    out += ["", "## Other look-only lines (no `_LIVE` flag found for them)", "",
            "Lines like `<who> would: ...` in the same logs that no flag above accounts for: shadows",
            "kept on purpose, or a flag whose text this tool missed (add it to EXTRA).", "",
            "| line starts | lines |", "|---|---|"]
    out += [f"| `{_cell(who)} would:` | {n} |" for who, n in others.most_common(25)]
    return "\n".join(out) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--var", type=Path, default=Path(os.path.expanduser("~/Hivemind/var")))
    ap.add_argument("--live", type=Path, default=Path(os.path.expanduser("~/Hivemind")),
                    help="the live install, to say whether each flag is deployed")
    ap.add_argument("--out", type=Path, help="write the report here instead of printing it")
    a = ap.parse_args()
    text = report(ROOT, a.var, a.live if a.live.is_dir() else None)
    if a.out:
        a.out.write_text(text, encoding="utf-8")
    else:
        print(text, end="")


if __name__ == "__main__":
    main()
