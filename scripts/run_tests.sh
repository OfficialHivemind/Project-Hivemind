#!/usr/bin/env bash
# Run the test suite so that it can only ever kill itself.
#
# MEASURED, 2026-09-20: `pytest tests -q` froze the desktop and died on exit
# 137 while the owner was playing. Two separate things go wrong in that story
# and this script fixes both:
#
#   the FREEZE is swap thrash. Once the working set exceeds RAM the kernel
#   pages the desktop out to a 4 GB swap file on disk, and everything --
#   compositor, game, input -- stalls behind disk I/O long before anything is
#   killed. `MemorySwapMax=0` denies the scope swap entirely, so the run hits
#   its ceiling and dies instead of dragging the machine through treacle.
#
#   the KILL was the system-wide OOM killer, which picks a victim by badness
#   score across the whole machine -- and a Roblox client or an agent is a far
#   fatter target than pytest. `MemoryMax` inside a cgroup makes the kernel
#   kill something INSIDE the scope, so the blast radius is the test run.
#
# Verified present on this machine: cgroup v2 (`stat -fc %T /sys/fs/cgroup` ->
# cgroup2fs) and a working `systemd-run --user --scope`.
set -uo pipefail

cd "$(dirname "$0")/.."

LIMIT="${HIVEMIND_TEST_MEMMAX:-4G}"
PY="./.venv/bin/python"

if [[ ! -x "$PY" ]]; then
    echo "no venv at $PY — run 'make venv' first" >&2
    exit 2
fi

run() { "$PY" -m pytest "$@"; }

if ! command -v systemd-run >/dev/null 2>&1; then
    # Say so rather than silently running unprotected: the whole point of this
    # script is the cap, and a run without one is a different, riskier thing.
    echo "WARNING: systemd-run not found — running WITHOUT a memory cap." >&2
    echo "         A runaway here can freeze the desktop. Ctrl-C now if that matters." >&2
    sleep 3
    run "$@"
    exit $?
fi

echo "running the suite capped at $LIMIT, swap denied (override: HIVEMIND_TEST_MEMMAX)"
systemd-run --user --scope --quiet --collect \
    -p MemoryMax="$LIMIT" -p MemorySwapMax=0 \
    -- "$PY" -m pytest "$@"
status=$?

# 137 = SIGKILL. Inside this scope that means the cap did its job, which is a
# different diagnosis from "a test failed" and deserves a different message.
if [[ $status -eq 137 ]]; then
    echo >&2
    echo "the run exceeded $LIMIT and was killed INSIDE its own cgroup." >&2
    echo "the desktop was never at risk. Raise it with HIVEMIND_TEST_MEMMAX=6G," >&2
    echo "or find the test that grew: scripts/run_tests.sh -q --durations=0" >&2
fi
exit $status
