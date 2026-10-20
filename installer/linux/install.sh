#!/usr/bin/env bash
# Hivemind for Linux: per-user install (RL1). No root, ever. Anything that
# needs root (system packages, the input group) is printed as ONE command for
# you to run yourself.
#
#   ./install.sh          install into ~/.local/share/hivemind/app
#   ./install.sh --force  install on Ubuntu/Mint/Debian anyway (your own Hyprland 0.56+)
#   hivemind uninstall    remove it again (keeps settings and what it learned)
#
# NixOS: don't use this. `nix run .` (or `nix profile install .`) in this
# folder; README-LINUX.md says why.
set -euo pipefail
HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
APP="$HOME/.local/share/hivemind/app"
OS_RELEASE="${HIVEMIND_OS_RELEASE:-/etc/os-release}"   # tests point this elsewhere

if grep -qi '^ID=nixos' "$OS_RELEASE" 2>/dev/null; then
    echo "This is NixOS: install with the flake instead:"
    echo "    nix profile install $HERE      (or try it: nix run $HERE)"
    exit 1
fi
# UBUNTU, MINT, DEBIAN, POP!_OS: no Hyprland 0.56+ in their repositories, so
# the doctor could never pass (cli/doctor fix_for "hyprland"); stop BEFORE
# copying anything. Stock Debian/Ubuntu also lack python3-venv (ASSUMED, not
# seen on a test PC), which made the venv step below crash.
if grep -qiE '^(ID|ID_LIKE)=.*(debian|ubuntu)' "$OS_RELEASE" 2>/dev/null \
        && [ "${1:-}" != --force ]; then
    echo "This looks like Ubuntu, Linux Mint, Debian or Pop!_OS."
    echo "Hivemind does not work on these yet: they do not have Hyprland 0.56 or newer."
    echo "Nothing was installed."
    echo "README-LINUX.md (\"Ubuntu, Mint and Debian\") says what you can do instead."
    echo "Already built Hyprland 0.56+ yourself? Then run:  ./install.sh --force"
    exit 1
fi

echo "Installing Hivemind into $APP"
mkdir -p "$APP"
# the code; var/ (what it learned) and an existing .venv are never touched
cp -r "$HERE/src" "$HERE/scripts" "$HERE/data" "$HERE/installer" "$HERE/pyproject.toml" "$APP/"

# The system's Python packages (PySide6, OpenCV, pywayland...) are used, not
# pip wheels: --system-site-packages, like the owner's own setup.
python3 -m venv --system-site-packages "$APP/.venv" || {
    echo "Could not set up Python for Hivemind. On Ubuntu, Mint or Debian run:" >&2
    echo "    sudo apt install python3-venv     then run ./install.sh again" >&2
    exit 1; }
# PyYAML is pure Python and often not a system package: pip, no root
"$APP/.venv/bin/python" -c 'import yaml' 2>/dev/null \
    || "$APP/.venv/bin/python" -m pip install -q --disable-pip-version-check PyYAML \
    || echo "(could not pip install PyYAML; the check below names the package)"

mkdir -p "$HOME/.local/bin" "$HOME/.local/share/applications" \
         "$HOME/.local/share/icons/hicolor/512x512/apps"
ln -sfn "$APP/installer/linux/hivemind" "$HOME/.local/bin/hivemind"
cp "$HERE/data/icon.png" "$HOME/.local/share/icons/hicolor/512x512/apps/hivemind.png"
sed "s|^Exec=hivemind|Exec=$HOME/.local/bin/hivemind|; s|^Exec=sh -c \"hivemind|Exec=sh -c \"$HOME/.local/bin/hivemind|" \
    "$HERE/installer/linux/hivemind.desktop" > "$HOME/.local/share/applications/hivemind.desktop"
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true

echo
echo "Checking this PC:"
"$HOME/.local/bin/hivemind" doctor || true
echo
echo "Installed. Open Hivemind from your app menu, or run: hivemind"
case ":$PATH:" in *":$HOME/.local/bin:"*) ;; *)
    echo "(~/.local/bin is not on your PATH: use $HOME/.local/bin/hivemind)" ;; esac
