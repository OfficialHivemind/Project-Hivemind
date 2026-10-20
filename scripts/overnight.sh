#!/usr/bin/env bash
# Keep the farm running unattended, all night, and survive its own crashes.
#
# WHY THIS EXISTS. The owner went to bed with "dont crash it again just keep it
# cool". A single `python scripts/run_farm.py` ends the night the first time
# anything raises -- and on 2026-09-20 two separate NameErrors did exactly that
# inside the first second. This restarts the farm instead of ending the night,
# and writes one numbered log per attempt so a crash can still be read
# afterwards rather than being scrolled away by the next attempt.
#
# WHAT IT NEVER DOES. It never kills Sober and it never pattern-matches on
# "roblox" or "sober" anywhere. The only process it manages is the python child
# it started itself, by PID. The owner plays on this machine and his own game
# session must survive anything this script does. Cleaning up a leftover nested
# compositor is `Session.clear_stale()`'s job inside the run, and that matches
# only a Hyprland started with our own config path.
#
#   ./scripts/overnight.sh [args passed straight to run_farm.py]
#   touch var/night/STOP      # finish the current attempt, then stop
#   kill -TERM $(cat var/night/watchdog.pid)   # stop now: the trap touches
#                             # STOP and asks the farm to stop, which releases
#                             # every key. This is what the GUI's Stop does.
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1
NIGHT="$ROOT/var/night"
mkdir -p "$NIGHT"

STOP="$NIGHT/STOP"
LEDGER="$NIGHT/attempts.log"
PY="$ROOT/.venv/bin/python"
# WHO IS RUNNING THE FARM, for the GUI's Start and Stop. The owner wants to
# start and stop the bot from the window when nobody is at a terminal
# ("make it so start and stop works for when ur gone"), and the window must
# never search for processes by name (gui/launcher). So this script writes
# its own pid here and removes it on the way out; a stale file names a dead
# pid and is ignored. Two watchdogs would be two farm loops fighting for the
# keyboard, so a live pid here refuses a second start.
PIDFILE="$NIGHT/watchdog.pid"
FARM_PIDFILE="$NIGHT/run_farm.pid"
# THE PID AND WHEN IT STARTED (DESIGN 8du). A live pid is not proof: pids wrap
# here in about two days, and a stale file naming a reused pid refused every
# start for good. Field 22 of /proc/PID/stat is the start time; the text after
# the last ") " begins at field 3, so it is the 20th there. Believed only if it
# is still this script (by name: `cd scripts && ./overnight.sh` runs as
# `bash ./overnight.sh`), started then -- the same test gui/launcher applies.
#
# THE START TIME HAS A FILE OF ITS OWN. The pidfile stays one bare number:
# `kill -TERM $(cat var/night/watchdog.pid)` above is how a terminal stops
# this, and with "pid start" in it that line would also SIGTERM the start
# time as if it were a pid -- clock ticks since boot, which stay below
# pid_max (4194304) for the first 11.6 hours after a boot. And a window
# still running older code reads the pidfile as one integer; two numbers
# there made it say nothing was running. Written before the pid, so the
# pair is never new pid with an old start.
STARTFILE="$NIGHT/watchdog.start"
started_at() { sed 's/.*) //' "/proc/$1/stat" 2>/dev/null | cut -d' ' -f20; }
if [ -f "$PIDFILE" ]; then
  read -r old_pid _ < "$PIDFILE"
  old_start=$(cat "$STARTFILE" 2>/dev/null)
  if [ -n "${old_pid:-}" ] && [ "$old_pid" != "$$" ] \
      && tr '\0' ' ' < "/proc/$old_pid/cmdline" 2>/dev/null | grep -qF "overnight.sh" \
      && { [ -z "${old_start:-}" ] || [ "$(started_at "$old_pid")" = "$old_start" ]; }; then
    echo "[overnight] another watchdog (pid $old_pid) is running; not starting a second" | tee -a "$LEDGER" >&2
    exit 1
  fi
fi
started_at $$ > "$STARTFILE"
echo $$ > "$PIDFILE"

# ONE SESSION, COUNTED FROM HERE (DESIGN 8du). safety.max_session_h used to be
# measured from each run_farm's own start, and an attempt lasts minutes, so the
# limit never came. Exported once; every attempt inherits it. A caller that
# already set it (a restart that should keep the night's count) wins.
export HIVEMIND_SESSION_STARTED="${HIVEMIND_SESSION_STARTED:-$(date +%s)}"

# A SLEEP THE STOP SIGNAL CAN CUT SHORT (DESIGN 8du). bash runs a trap only
# once the foreground command ends, so a TERM during `sleep 180` waited out the
# whole 180 s while the GUI's Stop sat in its 25 s grace and then SIGKILLed the
# group. `wait` returns as soon as a trap fires; the sleep it leaves behind
# exits on its own.
nap() { sleep "$1" & wait $!; }

# A restart that needs the whole game relaunched costs ~45 s of joining, so
# retrying instantly just burns attempts against whatever is actually wrong.
# Short gap normally; a long one once a run dies quickly three times in a row,
# because three fast deaths mean the fault is not transient.
GAP=20
LONG_GAP=180
FAST=45          # a run that lasted less than this counts as a fast death

# CONTINUE THE NUMBERING RATHER THAN RESTARTING IT. A fresh watchdog used to
# begin again at run-001.log and APPEND to it, so one file held attempts from
# different nights and anything tailing it re-read hours-old lines as though
# they were happening now -- including, once, a "FAILED: Sober never opened a
# window" from a run that had ended long before. Each attempt gets its own file.
attempt=0
# ANY WIDTH: the count passed 999 on 2026-10-14, and a three-digit glob found
# 999, so the next watchdog began at 1000 and appended to that afternoon's
# run-1000/1001 logs (the very mix-up this loop exists to prevent).
for existing in "$NIGHT"/run-[0-9]*.log; do
  [ -e "$existing" ] || continue
  n=$(basename "$existing" .log); n=${n#run-}
  n=$((10#$n))
  [ "$n" -gt "$attempt" ] && attempt=$n
done
fast_deaths=0

# Whether the caller asked for a finite number of cycles. See the exit-0 rule.
BOUNDED=no
for arg in "$@"; do
  case "$arg" in --cycles|--cycles=*) BOUNDED=yes ;; esac
done

child=""

# Stopping is asked for, never forced. run_farm handles SIGTERM by finishing
# the current step and releasing every key -- killing it outright could leave
# a key held down in the owner's game, which is the one failure this project
# refuses to ship.
on_signal() {
  echo "[overnight] signalled; asking the run to stop" >> "$LEDGER"
  touch "$STOP"
  [ -n "$child" ] && kill -TERM "$child" 2>/dev/null
}
trap on_signal INT TERM

while [ ! -e "$STOP" ]; do
  attempt=$((attempt + 1))
  log="$NIGHT/run-$(printf '%03d' "$attempt").log"
  ln -sfn "$log" "$NIGHT/current.log"
  start=$(date +%s)
  echo "[overnight] attempt $attempt starting $(date '+%F %T') -> $log" >> "$LEDGER"

  # NOT BESIDE THE OWNER'S OWN GAME (platform/gameguard, roadmap A14): the PC
  # froze twice that way (a big game running beside the bot).
  # THE OWNER PRESSES PLAY HIMSELF after his game: so a game found here STOPS
  # the watchdog (STOP set) instead of starting the bot once the game ends.
  game=$("$PY" -c 'import sys; sys.path.insert(0, "src")
from hivemind.platform import gameguard
from hivemind.world.settings import Settings
print(gameguard.check(Settings()) or "")' 2>> "$LEDGER")
  if [ -n "$game" ]; then
    echo "[overnight] game guard: you're playing $game — stopping (STOP set); press Play after your game" >> "$LEDGER"
    touch "$STOP"
    break
  fi

  # DO NOT START INTO A FULL MACHINE. The owner: "make sure my kernal doesnt
  # terminate u again". The OOM killer has already ended two runs, and a run
  # launched with no headroom is a run that dies at the first VLM question.
  # Wait for room rather than adding another 2 GB to a machine that has none.
  # Ask the SAME question the run itself asks, rather than inventing a second
  # threshold. An earlier version here allowed 3.5 GB while `memory.check`
  # wanted more, so the watchdog cheerfully launched a run that refused to
  # start and exited 2 in under a second. One definition of "enough memory",
  # and it lives in the library.
  waited=0
  while [ "$waited" -lt 300 ]; do
    # FREE OUR OWN WEIGHTS BEFORE ASKING WHETHER THERE IS ROOM. Without this
    # the gate deadlocks: the vision model holds about 8.7 GB, only run_farm
    # unloads it, and the gate runs first -- so the watchdog waits forever for
    # memory that only the thing it will not start would release. MEASURED on
    # 2026-09-20: llama-server at 8,661,392 KB RSS, keep-alive four minutes,
    # and the farm sat in "waiting for memory" behind it.
    if "$PY" -c 'import sys; sys.path.insert(0, "src")
from hivemind.brain.vlm import from_settings
from hivemind.platform import memory, session
from_settings().unload()
kept = session.kept_session("var/night/session.json", session.Session().config_path) is not None
ok, note = memory.check("the game", kept=kept)
print(note)
sys.exit(0 if ok else 1)' >> "$LEDGER" 2>&1; then
      break
    fi
    echo "[overnight] waiting for memory" >> "$LEDGER"
    nap 15
    waited=$((waited + 15))
    [ -e "$STOP" ] && break
  done

  # A STOP ASKED FOR DURING THE MEMORY GATE OR THE GAP used to launch one
  # more attempt anyway, because the loop only looked at the file at its
  # top -- and that attempt then ran to its own end. The window's Stop
  # touches the file, so it is checked again right before launching.
  [ -e "$STOP" ] && break

  # THE RUN IS TOLD ITS OWN NUMBER, rather than reading it off current.log,
  # which outlives the watchdog: a hand run after the night was filed as
  # attempt 406 (run_farm.this_attempt, DESIGN 8ds).
  HIVEMIND_ATTEMPT="$attempt" "$PY" scripts/run_farm.py "$@" >> "$log" 2>&1 &
  child=$!
  echo "$child" > "$FARM_PIDFILE"
  # MAKE THE FARM THE PREFERRED VICTIM. If the kernel has to kill something,
  # it should be this -- the watchdog restarts it in twenty seconds. Killing
  # the session that is supervising it, or the owner's own game, loses the
  # night. Raising our own child's score needs no privilege; lowering anyone
  # else's would, and nothing here touches another process.
  # The alt's bot (HIVEMIND_ROLE=alt, tools/alt) goes before the main's.
  adj=400; [ "${HIVEMIND_ROLE:-}" = alt ] && adj=900
  echo "$adj" > "/proc/$child/oom_score_adj" 2>/dev/null || true
  # `wait` returns early when a trap fires, so wait again until the child is
  # really gone; otherwise the ledger records the signal instead of the run.
  wait "$child"; code=$?
  while kill -0 "$child" 2>/dev/null; do wait "$child"; code=$?; done
  child=""
  rm -f "$FARM_PIDFILE"

  end=$(date +%s)
  lasted=$((end - start))
  echo "[overnight] attempt $attempt exited $code after ${lasted}s" >> "$LEDGER"

  # Keep the morning report current between attempts. The owner is asleep and
  # will not read a log directory; this is the one page that says what the
  # night actually did. Regenerated here rather than on a timer so it always
  # reflects a completed attempt.
  "$PY" scripts/night_report.py --write > /dev/null 2>&1 || true

  # EXIT 0 IS NOT NECESSARILY "DONE", and treating it as such ended the first
  # night after eleven minutes. run_farm returns 0 when it gives up as well as
  # when it finishes -- on 2026-09-20 it stopped itself with "3 cycles in a row
  # measured nothing ... this needs a human" and exited 0, so the watchdog
  # congratulated it and went home. When no cycle count was asked for, the run
  # is meant to last until morning, so ANY exit is something to recover from.
  # An explicit --cycles N is a request that can genuinely complete.
  if [ "$code" -eq 0 ] && [ "$BOUNDED" = "yes" ]; then
    echo "[overnight] finished the cycles it was asked for" >> "$LEDGER"
    break
  fi
  # 3 IS brain/alive.SessionCap.EXIT_FINISHED: safety.max_session_h is used up,
  # which is the owner's "stop after", not a failure to recover from.
  if [ "$code" -eq 3 ]; then
    echo "[overnight] the session limit (safety.max_session_h) is reached — not relaunching" >> "$LEDGER"
    break
  fi
  # 4 is run_farm's SHELL_LOCKED_EXIT: another run_farm, started outside this
  # watchdog, holds var/night/farm.lock. Retried like any other exit.
  if [ "$code" -eq 4 ]; then
    echo "[overnight] another run_farm holds var/night/farm.lock — retrying after the gap" >> "$LEDGER"
  fi
  # 5 is run_farm's GAME_GUARD_EXIT: a game of the owner's started after the
  # gate above looked. The gate waits for it before the next attempt.
  if [ "$code" -eq 5 ]; then
    echo "[overnight] the owner is playing a game — stopping (STOP set); press Play after your game" >> "$LEDGER"
    touch "$STOP"
  fi
  if [ "$code" -eq 0 ]; then
    echo "[overnight] exited 0 but no cycle limit was set — restarting" >> "$LEDGER"
  fi

  if [ "$lasted" -lt "$FAST" ]; then
    fast_deaths=$((fast_deaths + 1))
  else
    fast_deaths=0
  fi

  [ -e "$STOP" ] && break

  if [ "$fast_deaths" -ge 3 ]; then
    echo "[overnight] 3 fast deaths in a row; waiting ${LONG_GAP}s" >> "$LEDGER"
    nap "$LONG_GAP"
    fast_deaths=0
  else
    nap "$GAP"
  fi
done

rm -f "$PIDFILE" "$STARTFILE" "$FARM_PIDFILE"
echo "[overnight] finished $(date '+%F %T') after $attempt attempt(s)" >> "$LEDGER"
