#!/usr/bin/env bash
# RL1b prototype: the compositor INSIDE Sober's own Flatpak runtime
# (org.gnome.Platform//51: its glibc, its Mesa from the GL extension), with
# only the libs that runtime lacks shipped beside it -- and the bot's own
# classes driving it from the HOST through a socket in a shared directory.
# This is the bundle shape of docs/pending/universal-linux.md section 6.
#
#   probe_flatpak.sh DIR [labwc|cage]
#
# DIR as filled by fetch_compositor.sh; DIR/xlib = the libs the runtime lacks
# (libseat, libdisplay-info, libinput, libxcb-errors, liblua5.4, libmtdev,
# libwacom: copied from this Arch host for the prototype). Never starts Sober.
set -euo pipefail
DIR=$(realpath "${1:?usage: probe_flatpak.sh DIR [labwc|cage]}")
COMP=${2:-labwc}
HERE=$(dirname "$(realpath "$0")")
RUN="$DIR/run-$COMP-flatpak"; RT="$DIR/rt"
rm -rf "$RUN" "$RT"; mkdir -p "$RUN/labwc" "$RT"; chmod 700 "$RT"
cat > "$RUN/labwc/rc.xml" <<'XML'
<labwc_config><windowRules>
  <windowRule identifier="*" matchOnce="true"><action name="ToggleFullscreen"/></windowRule>
</windowRules></labwc_config>
XML
NODE=$(python3 -c "import sys; sys.path.insert(0,'$HERE/../../src'); from hivemind.platform.session import render_node; print(render_node() or '')")
if [ "$COMP" = cage ]; then CMD=("$DIR/root/usr/bin/cage" -- sleep 45)
else CMD=("$DIR/root/usr/bin/labwc" -C "$RUN/labwc" -S "sleep 45"); fi

systemd-run --user --scope -q -p MemoryMax=1500M nice -n 19 timeout 60 \
  flatpak run --device=dri --filesystem="$DIR" --command="${CMD[0]}" \
    --env=LD_LIBRARY_PATH="$DIR/root/usr/lib:$DIR/xlib" --env=XDG_RUNTIME_DIR="$RT" \
    --env=WLR_BACKENDS=headless --env=WLR_RENDER_DRM_DEVICE="$NODE" \
    org.gnome.Platform//51 "${CMD[@]:1}" > "$RUN/compositor.log" 2>&1 &
for _ in $(seq 50); do [ -S "$RT/wayland-0" ] && break; sleep 0.2; done

# the host side: the bot's view of it
export XDG_RUNTIME_DIR="$RT" WAYLAND_DISPLAY=wayland-0 QT_QPA_PLATFORM=wayland
export LD_LIBRARY_PATH="$DIR/root/usr/lib"
"$DIR/root/usr/bin/wlr-randr" --output HEADLESS-1 --custom-mode 1920x1080
PROBE_WINDOWED=$([ "$COMP" = labwc ] && echo 1 || true) \
  nice -n 19 python3 "$HERE/probe.py" window "$RUN/window.log" > "$RUN/window.out" 2>&1 & W=$!
sleep 3
nice -n 19 python3 "$HERE/probe.py" drive "$RUN/window.log" | tee "$RUN/drive.log" || true
kill $W 2>/dev/null || true
grep -m1 "GL renderer" "$RUN/compositor.log" | cut -c1-120 || true
wait   # the compositor ends with its 45 s startup command
