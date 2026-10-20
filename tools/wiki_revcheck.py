#!/usr/bin/env python3
"""K12, knowledge kept current: which wiki pages changed since we cited them.

Every wiki fact in data/knowledge and src/hivemind is cited with the page's
revision id ("wiki/Black_Bear (api.php rev 448714", "BSS Wiki: Amulet (rev
448314", "Commando_Chick rev 448352", "Module:RQValue (revid 446090)"). This
tool collects those (page, revid) pairs, asks the wiki's api.php for each
page's CURRENT revid and prints every page that moved on since, with the
file:line that cites it. Run it after a BSS update; a CHANGED page is a page
to re-read, not a proof the fact changed (most edits are typo fixes).

    wiki_revcheck.py            check every cited page (one request per 50)
    wiki_revcheck.py --list     only list the citations found, no network

Read-only: it never edits a citation. Exit 1 when a page changed.
ponytail: citations written in a shape the patterns below miss ("Polar Bear
rev 447913", "Module:RandomBias (445165)") are not checked; add a pattern
when one matters.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from hivemind import datapaths  # noqa: E402

API = "https://bee-swarm-simulator.fandom.com/api.php"
# THE CITATION SHAPES IN USE (grep of data/ and src/, 2026-11-02).
PATTERNS = [
    re.compile(r"fandom\.com/wiki/(\S+) \([^)]*?\brev (\d{5,})"),          # source: URL (api.php rev N
    re.compile(r"BSS Wiki: (.+?) \(rev (\d{5,})"),                          # title: 'BSS Wiki: X (rev N'
    re.compile(r"\b([A-Z][\w']*_[\w'/]+)(?: page)? \(?rev (\d{5,})"),       # Commando_Chick rev N
    re.compile(r"\b((?:Module:)?[A-Z][\w/]*(?: [\w/]+)*) \(revid (\d{5,})\)"),  # Module:X Y/data (revid N)
]


def title(raw: str) -> str:
    return urllib.parse.unquote(raw).replace("_", " ").strip()


def citations(text: str):
    """[(page title, cited revid, line no)] in one file's text."""
    out = []
    for no, line in enumerate(text.splitlines(), 1):
        seen = set()
        for pat in PATTERNS:
            for m in pat.finditer(line):
                key = (title(m.group(1)), int(m.group(2)))
                if key not in seen:
                    seen.add(key)
                    out.append((*key, no))
    return out


def scan():
    """{page: [(cited revid, 'file:line')]} over data/knowledge and the package."""
    pkg = Path(datapaths.__file__).resolve().parent
    files = sorted((datapaths.DATA_ROOT / "knowledge").rglob("*.yaml")) + sorted(pkg.rglob("*.py"))
    found = defaultdict(list)
    for path in files:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for page, rev, no in citations(text):
            try:
                where = path.relative_to(ROOT)
            except ValueError:
                where = path
            found[page].append((rev, f"{where}:{no}"))
    return found


def current_revids(pages, fetch=None):
    """{page: (revid, timestamp) or None if missing}, asked 50 titles a request."""
    fetch = fetch or _fetch
    out = {}
    pages = sorted(pages)
    for i in range(0, len(pages), 50):
        chunk = pages[i:i + 50]
        q = fetch(chunk)["query"]
        back = {n["to"]: n["from"] for n in q.get("normalized", [])}
        for p in q.get("pages", []):
            name = back.get(p["title"], p["title"])
            revs = p.get("revisions") or []
            out[name] = (revs[0]["revid"], revs[0].get("timestamp", "")) if revs else None
    return out


def _fetch(titles):
    url = API + "?" + urllib.parse.urlencode({
        "action": "query", "prop": "revisions", "rvprop": "ids|timestamp",
        "titles": "|".join(titles), "format": "json", "formatversion": "2"})
    req = urllib.request.Request(url, headers={"User-Agent": "Hivemind wiki_revcheck"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def diff(found, now):
    """Report lines: CHANGED / MISSING per cited page, oldest cite first."""
    lines = []
    for page in sorted(found):
        cur = now.get(page)
        if cur is None:
            lines.append(f"MISSING {page}: not on the wiki now (cited at {found[page][0][1]})")
            continue
        by_rev = defaultdict(list)
        for rev, where in found[page]:
            by_rev[rev].append(where)
        for rev in sorted(by_rev):
            if rev != cur[0]:
                at = by_rev[rev]
                more = f" +{len(at) - 1} more" if len(at) > 1 else ""
                lines.append(f"CHANGED {page}: cited rev {rev} ({at[0]}{more}), "
                             f"now rev {cur[0]} ({cur[1]})")
    return lines


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--list", action="store_true", help="only list the citations, no network")
    args = ap.parse_args(argv)
    found = scan()
    if args.list:
        for page in sorted(found):
            for rev, where in sorted(found[page]):
                print(f"{page}\trev {rev}\t{where}")
        return 0
    report = diff(found, current_revids(found))
    print("\n".join(report) or f"all {len(found)} cited pages are at their cited revision")
    return 1 if report else 0


if __name__ == "__main__":
    sys.exit(main())
