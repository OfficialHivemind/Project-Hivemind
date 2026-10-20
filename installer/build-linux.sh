#!/usr/bin/env bash
# Builds installer/build/Hivemind-Setup.exe ON LINUX: the same steps as
# build.ps1, with Wine (from the WineCharm Flatpak) only for Inno Setup's
# compiler, the selftest and the install smoke test. No GitHub needed.
#
#   bash installer/build-linux.sh
#
# Needs: flatpak io.github.fastrizwaan.WineCharm (wine) and com.usebottles.bottles
# (7z), ~/Hivemind/.venv (pip + cv2 for make_icon). Downloads are pinned by
# sha256 like build.ps1. Under Wine the selftest's Qt checks fail (Wine has no
# icuuc.dll, which Windows 10 1903+ ships), so only the other checks gate.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd); ROOT=$(dirname "$HERE")
WORK=${HIVEMIND_WININST:-$HOME/.cache/hivemind-work/wininst}
C=$WORK/cache B=$HERE/build P=$WORK/prefix PY=${PY:-$HOME/Hivemind/.venv/bin/python}
mkdir -p "$C"
fp() { flatpak run --filesystem="$WORK" --filesystem="$ROOT" --env=WINEPREFIX="$P" --env=WINEDEBUG=-all "$@" 2>&1 | grep -v radv || true; }
wine() { fp --command=wine io.github.fastrizwaan.WineCharm "$@"; }

pinned() {  # url sha256 -> path in cache
  local f="$C/$(basename "$1")"
  [ -f "$f" ] || curl -fsSL -o "$f" "$1"
  echo "$2  $f" | sha256sum -c --quiet - || { rm -f "$f"; echo "bad sha256: $1" >&2; exit 1; }
  echo "$f"
}
PYZIP=$(pinned https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip 4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3)
TESS=$(pinned https://github.com/UB-Mannheim/tesseract/releases/download/v5.4.0.20240606/tesseract-ocr-w64-setup-5.4.0.20240606.exe c885fff6998e0608ba4bb8ab51436e1c6775c2bafc2559a19b423e18678b60c9)
AFR=$(pinned https://raw.githubusercontent.com/tesseract-ocr/tessdata/4.1.0/afr.traineddata 5ec41cebed3f4a178ee9d72e1112ac9a4a38a7b0ddcafb1266d55d9ded452ea9)
LIC=$(pinned https://raw.githubusercontent.com/tesseract-ocr/tesseract/5.4.0/LICENSE cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30)
INNO=$(pinned https://github.com/jrsoftware/issrc/releases/download/is-6_7_3/innosetup-6.7.3.exe 9c73c3bae7ed48d44112a0f48e66742c00090bdb5bef71d9d3c056c66e97b732)
[ -f "$P/drive_c/iscc/ISCC.exe" ] || wine "$INNO" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CURRENTUSER '/DIR=C:\iscc'
# The prefix's user folders link to the real ~/Downloads etc.: make them private,
# so the old-copy search below only ever sees the test's own fake kit.
for d in Desktop Documents Downloads Music Pictures Videos; do
  L="$P/drive_c/users/$USER/$d"; if [ -L "$L" ]; then rm "$L"; mkdir "$L"; fi
done

rm -rf "$B"; A=$B/app; mkdir -p "$A/python"
# 1. embeddable Python, same ._pth as build.ps1
"$PY" -c "import zipfile,sys; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" "$PYZIP" "$A/python"
printf 'python312.zip\r\n.\r\nLib\\site-packages\r\n..\\src\r\nimport site\r\n' > "$A/python/python312._pth"
# 2. pinned wheels
"$PY" -m pip install -q --disable-pip-version-check --no-deps --only-binary=:all: --require-hashes \
  --platform win_amd64 --python-version 3.12 --implementation cp \
  --target "$A/python/Lib/site-packages" -r "$HERE/requirements-windows.txt"
rm -rf "$A/python/Lib/site-packages/bin"
# 3. the app (repo layout minus tests/docs/tools/var)
mkdir -p "$A/src" "$A/scripts"
# WHERE THE APP'S CODE COMES FROM: APP_SOURCE, else this checkout. A PREVIEW
# (public) build must use the scrubbed public export (tools/export_public.py),
# never the team tree: MEASURED 2026-10-22, a preview built from the team tree
# carried the owner's paths and notes in 48 files.
SRC="${APP_SOURCE:-$ROOT}"
if [ "${PREVIEW:-}" ] && [ -z "${APP_SOURCE:-}" ]; then
  echo "PREVIEW=1 needs APP_SOURCE=<the public export>: a public build never packages the team tree" >&2; exit 1
fi
cp -r "$SRC/src/hivemind" "$A/src/"; cp "$SRC"/scripts/*.py "$A/scripts/"; cp -r "$SRC/data" "$A/"; cp "$SRC/pyproject.toml" "$A/"
find "$A" -name __pycache__ -type d -prune -exec rm -rf {} +; rm -f "$A"/data/calib/*.local.yaml
# 4. Tesseract, unpacked (not run) with 7z
U=$B/tess-unpacked
fp --command=7z com.usebottles.bottles x -y -bso0 -o"$U" "$TESS" >/dev/null
T=$(find "$U" -name tesseract.exe | head -1); D=$(dirname "$T")
mkdir -p "$A/tesseract/tessdata"
cp "$T" "$D"/*.dll "$A/tesseract/"; cp -r "$D/tessdata/configs" "$A/tesseract/tessdata/"
cp "$AFR" "$A/tesseract/tessdata/afr.traineddata"; cp "$LIC" "$A/tesseract/LICENSE-tesseract.txt"; rm -rf "$U"
# 5. icon + wizard images
"$PY" -B "$HERE/make_icon.py" "$B" >/dev/null; cp "$B/hivemind.ico" "$A/"
# 6. prove it (Qt checks are Wine-only failures, see the header)
VER=$(cd "$A" && wine python/python.exe -B -m hivemind.gui --version | tr -d '\r' | tail -1)
[[ $VER =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "--version gave '$VER'" >&2; exit 1; }
ST=$(cd "$A" && wine python/python.exe -B -m hivemind.gui --selftest); echo "$ST"
for must in "ok    data files" "ok    run_farm imports" "ok    tesseract: afr found"; do
  grep -qF "$must" <<<"$ST" || { echo "selftest missing: $must" >&2; exit 1; }
done
rm -rf "$A/var"
# 7. the installer
(cd "$B" && wine 'C:\iscc\ISCC.exe' /Q "/DAppVersion=$VER" "/DAppDir=Z:$A" "/DImages=Z:$B" "/OZ:$B" "Z:$HERE/hivemind.iss")
if [ "${SPLIT:-}" ]; then   # SPLIT=1: also a 45 MB-parts copy for Telegram, in build/split
  mkdir -p "$B/split"; (cd "$B" && wine 'C:\iscc\ISCC.exe' /Q /DSplit "/DAppVersion=$VER" "/DAppDir=Z:$A" "/DImages=Z:$B" "/OZ:$B/split" "Z:$HERE/hivemind.iss")
  # PARTS.txt, sent FIRST: every part with its size and sha256, so a part lost
  # on the way shows before Setup asks for it (MEASURED 2026-10-22: the 20 Oct
  # split's -3.bin never arrived and Setup stopped at "Please insert Disk 3").
  (cd "$B/split" && { echo "All of these files must be in ONE folder before you run Hivemind-Setup-PARTS.exe:"
     for f in Hivemind-Setup-PARTS.exe Hivemind-Setup-PARTS-*.bin; do printf '%s  %s bytes  %s\n' "$f" "$(stat -c %s "$f")" "$(sha256sum "$f" | cut -c1-64)"; done; } > PARTS.txt)
fi
if [ "${PREVIEW:-}" ]; then # PREVIEW=1: also Hivemind-UI-Preview.exe (the demo-only UI preview, hivemind.iss)
  (cd "$B" && wine 'C:\iscc\ISCC.exe' /Q /DPreview "/DAppVersion=$VER" "/DAppDir=Z:$A" "/DImages=Z:$B" "/OZ:$B" "Z:$HERE/hivemind.iss")
  [ -s "$B/Hivemind-UI-Preview.exe" ] || { echo "ISCC made no Hivemind-UI-Preview.exe" >&2; exit 1; }
fi
[ -s "$B/Hivemind-Setup.exe" ] || { echo "ISCC made no Hivemind-Setup.exe" >&2; exit 1; }
# 8. smoke: an old portable kit to find, silent install, files, uninstall
K="$P/drive_c/users/$USER/Downloads/Hivemind"; rm -rf "$K"
mkdir -p "$K/src/hivemind" "$K/var"; : > "$K/Start Hivemind.bat"; echo learned > "$K/var/old-kit-marker.txt"
rm -rf "$P/drive_c/users/$USER/AppData/Local/Programs/Hivemind"
wine "Z:$B/Hivemind-Setup.exe" /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
I="$P/drive_c/users/$USER/AppData/Local/Programs/Hivemind"
for f in python/pythonw.exe src/hivemind/gui/__main__.py tesseract/tesseract.exe unins000.exe; do
  [ -e "$I/$f" ] || { echo "installed copy has no $f" >&2; exit 1; }
done
[ -f "$I/var/old-kit-marker.txt" ] || { echo "old kit's var not carried over" >&2; exit 1; }
[ -f "$P/drive_c/users/$USER/AppData/Local/Hivemind/settings.yaml" ] || { echo "no first-run settings.yaml" >&2; exit 1; }
wine 'C:\users\'"$USER"'\AppData\Local\Programs\Hivemind\unins000.exe' /VERYSILENT /SUPPRESSMSGBOXES
rm -rf "$K" "$I"
echo "built $B/Hivemind-Setup.exe (Hivemind $VER, $(du -h "$B/Hivemind-Setup.exe" | cut -f1))"
