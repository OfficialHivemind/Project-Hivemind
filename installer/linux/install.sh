#!/usr/bin/env bash
# Hivemind for Linux: per-user install (RL1). No root, ever. Anything that
# needs root (system packages, the input group) is printed as ONE command for
# you to run yourself.
#
#   ./install.sh          install into ~/.local/share/hivemind/app
#   hivemind uninstall    remove it again (keeps settings and what it learned)
#
# NixOS: don't use this. `nix run .` (or `nix profile install .`) in this
# folder; README-LINUX.md says why.
set -euo pipefail
HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
APP="$HOME/.local/share/hivemind/app"

if grep -qi '^ID=nixos' /etc/os-release 2>/dev/null; then
    echo "This is NixOS: install with the flake instead:"
    echo "    nix profile install $HERE      (or try it: nix run $HERE)"
    exit 1
fi

echo "Installing Hivemind into $APP"
mkdir -p "$APP"
# the code; var/ (what it learned) and an existing .venv are never touched
cp -r "$HERE/src" "$HERE/scripts" "$HERE/data" "$HERE/installer" "$HERE/pyproject.toml" "$APP/"

# The system's Python packages (PySide6, OpenCV, pywayland...) are used, not
# pip wheels: --system-site-packages, like the owner's own setup.
python3 -m venv --system-site-packages "$APP/.venv"
# PyYAML is pure Python and often not a system package: pip, no root
"$APP/.venv/bin/python" -c 'import yaml' 2>/dev/null \
    || "$APP/.venv/bin/python" -m pip install -q PyYAML \
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
