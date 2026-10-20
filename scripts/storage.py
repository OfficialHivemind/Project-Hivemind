#!/usr/bin/env python3
"""What the retention policy WOULD delete from var (telemetry/storage).

  storage.py --dry-run                   at storage.retention_gb from settings
  storage.py --dry-run --budget-gb 40    at another budget

Reads only. Deleting is the bot's, and only with storage.retention_gb on.
"""
from __future__ import annotations

import argparse
import collections
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from hivemind.telemetry import storage  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true", required=True)
    ap.add_argument("--budget-gb", type=float, default=None)
    ap.add_argument("--var", type=pathlib.Path, default=ROOT / "var")
    ap.add_argument("--repo", type=pathlib.Path, default=ROOT,
                    help="whose docs and code protect what they mention")
    args = ap.parse_args()
    budget = args.budget_gb
    if budget is None:
        from hivemind.world.settings import Settings
        budget = float(Settings().get("storage.retention_gb", 0) or 0)
    if budget <= 0:
        print("storage.retention_gb is 0 (off): nothing would go. "
              "Pass --budget-gb to see a budget.")
        return 0
    p = storage.plan(args.var, budget, storage.referenced(args.repo))
    print(f"debug frames: {storage.gb(p.total)} in {args.var} "
          f"({storage.free_gb(args.var):.0f} GB free on the disk)")
    for root, n in sorted(p.by_root.items(), key=lambda kv: -kv[1]):
        print(f"  {root:<17} {storage.gb(n)}")
    gone = collections.Counter(u.root for u in p.doomed)
    print(f"budget {budget:g} GB: would delete {len(p.doomed)} units, "
          f"{storage.gb(p.freed)}, leaving {storage.gb(p.total - p.freed)}; "
          f"{p.protected} protected (newest {storage.KEEP_NEWEST} per folder, "
          f"last hour, {storage.KEEP_MARK} files, named in docs/code)")
    for root, n in gone.most_common():
        print(f"  {root:<17} {n} units")
    if p.doomed:
        print(f"  oldest {p.doomed[0].path}, newest {p.doomed[-1].path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
