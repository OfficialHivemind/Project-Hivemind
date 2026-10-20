#!/usr/bin/env bash
# RL1b prototype: unpack cage + labwc + wlroots 0.20 (+ wlr-randr) from Arch's
# signed-repo packages into DIR, no root, no pacman. Only the libs this machine
# lacked are fetched; a real bundle adds every non-glibc lib (see
# docs/pending/universal-linux.md section 6).
#   tools/universal/fetch_compositor.sh DIR
set -euo pipefail
DIR=${1:?usage: fetch_compositor.sh DIR}
MIRROR=${MIRROR:-https://geo.mirror.pkgbuild.com/extra/os/x86_64}
PKGS=(cage-0.3.1-1 wlroots0.20-0.20.2-1 libliftoff-0.5.0-1 labwc-0.20.2-1
      libsfdo-0.1.4-1 wlr-randr-0.5.0-1)
mkdir -p "$DIR/pkgs" "$DIR/root"
for p in "${PKGS[@]}"; do
  f="$DIR/pkgs/$p-x86_64.pkg.tar.zst"
  [ -s "$f" ] || curl -sfL -o "$f" "$MIRROR/$p-x86_64.pkg.tar.zst"
  tar -C "$DIR/root" -xf "$f" 2>/dev/null
done
ls "$DIR/root/usr/bin"
