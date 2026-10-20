#!/usr/bin/env bash
# RL1b prototype: run a fetched wlroots compositor HEADLESS (no window on any
# desktop, no seat, no root) in a private XDG_RUNTIME_DIR, and drive it with
# tools/universal/probe.py. Never starts Sober.
#
#   probe_headless.sh DIR cage|labwc [headless|x11|wayland]
#
#   headless  the compositor renders into its own headless output
#   x11       proves the X11 backend with no X server on the desktop: a
#             headless cage hosts a non-rootless Xwayland, and the compositor
#             under test opens its output as a window on THAT X server
#   wayland   the same with a Wayland host: a window of a headless cage,
#             never of the desktop
#
# Memory-capped, niced, time-limited; everything it starts dies with it.
set -euo pipefail
DIR=$(realpath "${1:?usage: probe_headless.sh DIR cage|labwc [headless|x11|wayland]}")
COMP=${2:-cage}
MODE=${3:-headless}
HERE=$(dirname "$(realpath "$0")")
RUN="$DIR/run-$COMP-$MODE"
RT="$DIR/rt"     # short: a socket path must fit in 108 bytes
rm -rf "$RUN" "$RT"; mkdir -p "$RUN" "$RT"; chmod 700 "$RT"
REAL_RT=${XDG_RUNTIME_DIR:-/run/user/$(id -u)}
export XDG_RUNTIME_DIR="$RT" LD_LIBRARY_PATH="$DIR/root/usr/lib"
unset WAYLAND_DISPLAY DISPLAY HYPRLAND_INSTANCE_SIGNATURE
export WLR_LIBINPUT_NO_DEVICES=1 QT_QPA_PLATFORM=wayland
# the GPU with the most VRAM (session.render_node's rule), not the iGPU
NODE=$(python3 -c "import sys; sys.path.insert(0,'$HERE/../../src'); from hivemind.platform.session import render_node; print(render_node() or '')")
[ -n "$NODE" ] && export WLR_RENDER_DRM_DEVICE="$NODE"
BIN="$DIR/root/usr/bin"

# what runs INSIDE the compositor under test
inner() {
  cat > "$RUN/inner.sh" <<EOF
set -x
"$BIN/wlr-randr" --output \$("$BIN/wlr-randr" | head -1 | cut -d' ' -f1) --custom-mode 1920x1080 || true
"$BIN/wlr-randr" | head -4
wayland-info > "$RUN/wayland-info.txt" 2>&1
python3 "$HERE/probe.py" window "$RUN/window.log" & W=\$!
sleep 3
python3 "$HERE/probe.py" drive "$RUN/window.log"; RC=\$?
kill \$W; exit \$RC
EOF
  echo "sh $RUN/inner.sh"
}

start() {   # start <compositor> <command...> : the compositor under test
  local c=$1; shift
  if [ "$c" = cage ]; then "$BIN/cage" -- "$@"
  else
    # labwc: the game's window made fullscreen by a window rule on map (what
    # Session.fullscreen_focused does with hyprctl today); the probe window
    # opens WINDOWED here, so a 1920x1080 click report proves the rule
    mkdir -p "$RUN/labwc"
    cat > "$RUN/labwc/rc.xml" <<'XML'
<labwc_config>
  <windowRules>
    <windowRule identifier="*" matchOnce="true"><action name="ToggleFullscreen"/></windowRule>
  </windowRules>
</labwc_config>
XML
    PROBE_WINDOWED=1 "$BIN/labwc" -C "$RUN/labwc" -S "$*"
  fi
}

# systemd finds the user bus through the REAL runtime dir; the compositor gets the private one
cap() { XDG_RUNTIME_DIR=$REAL_RT systemd-run --user --scope -q -p MemoryMax=1500M \
          nice -n 19 timeout 60 env XDG_RUNTIME_DIR="$RT" "$@"; }

if [ "$MODE" = headless ]; then
  WLR_BACKENDS=headless cap bash -c "$(declare -f start); BIN='$BIN' RUN='$RUN' start $COMP $(inner)" \
    > "$RUN/compositor.log" 2>&1 || true
elif [ "$MODE" = wayland ]; then
  # outer: a headless cage; the compositor under test is a window of it
  cat > "$RUN/wl.sh" <<EOF
export WLR_BACKENDS=wayland
$(declare -f start)
BIN='$BIN' RUN='$RUN' start $COMP $(inner) > "$RUN/compositor.log" 2>&1
EOF
  WLR_BACKENDS=headless cap "$BIN/cage" -- bash "$RUN/wl.sh" > "$RUN/outer.log" 2>&1 || true
else
  # outer: a headless cage whose only client is a 1920x1080 Xwayland; the
  # compositor under test then runs on WLR_BACKENDS=x11 against that :N
  cat > "$RUN/x11.sh" <<EOF
Xwayland :87 -geometry 1920x1080 -noreset & X=\$!
sleep 2
export DISPLAY=:87 WLR_BACKENDS=x11
unset WAYLAND_DISPLAY
$(declare -f start)
BIN='$BIN' RUN='$RUN' start $COMP $(inner) > "$RUN/compositor.log" 2>&1
RC=\$?; kill \$X; exit \$RC
EOF
  WLR_BACKENDS=headless cap "$BIN/cage" -- bash "$RUN/x11.sh" > "$RUN/outer.log" 2>&1 || true
fi
grep -E "^(protocols|frame|capture|after|PROBE|  )|HEADLESS|X11-|custom-mode|Failed|error" "$RUN"/*.log "$RUN/compositor.log" 2>/dev/null | sort -u | head -40
echo "--- globals the bot needs:"
grep -oE "'(zwp_virtual_keyboard_manager_v1|zwlr_virtual_pointer_manager_v1|zwlr_screencopy_manager_v1|ext_image_copy_capture_manager_v1|zwp_pointer_constraints_v1|zwp_relative_pointer_manager_v1|xdg_wm_base|xwayland_shell_v1|zwp_linux_dmabuf_v1)'" "$RUN/wayland-info.txt" | sort -u | tr '\n' ' '; echo
