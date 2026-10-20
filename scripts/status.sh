#!/usr/bin/env bash
# One-line answers to "is it alive, and is it earning?" -- for checking on an
# unattended run without reading four log files.
cd "$(dirname "${BASH_SOURCE[0]}")/.." || exit 1
echo "time      $(date '+%H:%M:%S')"
echo "farm      $(pgrep -c -u "$(id -u)" -f '[r]un_farm.py') running, watchdog $(pgrep -c -u "$(id -u)" -f '[o]vernight.sh')"
echo "attempts  $(grep -c 'starting' var/night/attempts.log 2>/dev/null) started, \
$(grep -c 'exited [^0]' var/night/attempts.log 2>/dev/null) non-zero exits"
./.venv/bin/python scripts/peek_hud.py 2>/dev/null | sed 's/^/hud       /'
echo "cycles    $(cat var/night/earlier/*.log var/night/run-*.log 2>/dev/null | grep -o 'cycle [0-9]*:' | wc -l) logged, \
$(cat var/night/earlier/*.log var/night/run-*.log 2>/dev/null | grep -o 'died:' | wc -l) death lines"
echo "tokens    $(ls var/incidents 2>/dev/null | grep -c token) labelled windows, \
$(du -sh var/incidents 2>/dev/null | cut -f1) on disk"
echo "memory    $(awk '/MemAvailable/ {printf "%.1f GB available", $2/1048576}' /proc/meminfo), \
swap $(free -m | awk '/Swap:/ {printf "%d%%", $3*100/$2}')"
# THE CURRENT RUN ONLY. Grepping every run-*.log mixes in attempts from hours
# ago, which made an old "FAILED: Sober never opened a window" look like it had
# just happened -- twice. `current.log` is the symlink the watchdog repoints at
# each attempt, so this is always the run that is actually going on.
echo "this run:"
tail -n 400 var/night/current.log 2>/dev/null \
  | grep -E "cycle [0-9]+:|died:|FAILED|could not reach|staying up to|unloaded the vision" \
  | tail -4 | sed 's/^ *//'
