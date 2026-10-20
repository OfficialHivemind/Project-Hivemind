#!/usr/bin/env bash
# One line per interesting event across every attempt, appended to
# var/night/events.log -- so a check-in reads the digest instead of grepping
# six run logs. Started alongside the watchdog; harmless if run twice
# (duplicate lines are deduplicated by the marker file per log).
set -u
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$ROOT/var/night/events.log"
PATTERN='join: Bee Swarm|FAILED|in game after|hive: slot|farming |to [a-z_]+: |at the red cannon|never stood at the red cannon|cannon-hop|buff bar:|school:|token brain: (chase|switched)|this is the row|end of the hive row|stepping back|on our own pad|blocked|cycle [0-9]+:|died:|rejoin|measured the hive slot|learned slot|Traceback'
declare -A SEEN
while true; do
  for log in "$ROOT"/var/night/run-*.log; do
    [ -f "$log" ] || continue
    name=$(basename "$log" .log)
    from=${SEEN[$name]:-0}
    total=$(wc -l < "$log")
    if [ "$total" -gt "$from" ]; then
      tail -n +$((from + 1)) "$log" | grep -nE "$PATTERN" | sed "s|^|${name#run-} |" >> "$OUT"
      SEEN[$name]=$total
    fi
  done
  sleep 20
done
