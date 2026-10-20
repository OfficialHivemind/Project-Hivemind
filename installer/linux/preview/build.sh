#!/usr/bin/env bash
# Build dist/Hivemind-UI-Preview-x86_64.AppImage: ONE file a Linux user
# downloads, marks executable and double-clicks (the owner, 2026-10-22: "make a
# windows and linux installer", "people dont wanna download more than one
# file"). Python 3.12 and the packages in requirements.txt are inside it; it
# opens only the demo (entrypoint.sh). Needs network and python-appimage:
#   python3 -m venv /some/venv && /some/venv/bin/pip install python-appimage
#   PYAPPIMAGE=/some/venv/bin/python-appimage installer/linux/preview/build.sh
set -euo pipefail
HERE="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
PYAPPIMAGE="${PYAPPIMAGE:-python-appimage}"
WORK="${WORK:-$ROOT/installer/build/preview-linux}"     # on disk, not /tmp (RAM)
rm -rf "$WORK"; mkdir -p "$WORK/recipe" "$WORK/app" "$ROOT/dist"

# The app: the SCRUBBED PUBLIC EXPORT's src/ scripts/ data/ (APP_SOURCE, made
# by tools/export_public.py), never the team tree (MEASURED 2026-10-22: built
# from the team tree it carried the owner's paths and notes in 48 files).
[ -n "${APP_SOURCE:-}" ] || { echo "APP_SOURCE=<the public export> is required: the preview is public" >&2; exit 1; }
(cd "$APP_SOURCE" && git ls-files -z src scripts data pyproject.toml \
    | grep -zv -e '^data/knowledge/account[^/]*\.yaml$' -e '\.egg-info/' \
    | xargs -0 cp --parents -t "$WORK/app")
# The same privacy check as installer/linux/build.sh: a finding fails the build.
if grep -rIlE -e '[0-9]{8,10}:AA[A-Za-z0-9_-]{30,}' -e 'privateServerLinkCode=[0-9a-f]{8}' \
        -e 'share\?code=[0-9a-f]{16}' -e 'TELEGRAM_CHAT=-?[0-9]{5,}' "$WORK/app"; then
    echo "privacy check FAILED: the files above look like they hold a secret" >&2; exit 1
fi

cp "$HERE"/requirements.txt "$HERE"/entrypoint.sh "$HERE"/hivemind-ui-preview.desktop \
   "$HERE"/hivemind-ui-preview.appdata.xml "$WORK/recipe/"
cp "$ROOT/data/icon.png" "$WORK/recipe/hivemind-ui-preview.png"
(cd "$WORK" && "$PYAPPIMAGE" -q build app -p 3.12 -n Hivemind-UI-Preview --no-packaging -x app -- recipe)
# Packed here, not by python-appimage: MEASURED 2026-10-22 its own packing step
# made no file and said nothing; appimagetool with --no-appstream works.
TOOL="$(ls -d "$HOME"/.cache/python-appimage/bin/.appimagetool-*.appdir.x86_64 | head -1)/AppRun"
(cd "$WORK" && ARCH=x86_64 "$TOOL" --no-appstream "Hivemind UI Preview-x86_64" \
    "$ROOT/dist/Hivemind-UI-Preview-x86_64.AppImage")
f="$ROOT/dist/Hivemind-UI-Preview-x86_64.AppImage"
echo "$f  $(du -h "$f" | cut -f1)  sha256 $(sha256sum "$f" | cut -c1-64)"
