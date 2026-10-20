#!/usr/bin/env bash
# Build the Linux test package (RL1): dist/hivemind-linux-<version>.tar.gz.
# Only git-tracked files of the app go in -- never var/ (runtime state), never
# the owner's account files (data/knowledge/account*.yaml), no tests or tools,
# and of docs only the tester guide and the safety page (docs/TESTING.md,
# docs/SECURITY.md: README-LINUX.md links them) -- then a privacy check fails
# the build on anything that looks like a secret.
set -euo pipefail
ROOT="$(cd "$(dirname "$(readlink -f "$0")")/../.." && pwd)"
# WHERE THE CODE COMES FROM: APP_SOURCE (a git tree), else this checkout. A
# package for testers is built from the scrubbed public export
# (tools/export_public.py <out>; APP_SOURCE=<out>), like installer/build-linux.sh:
# MEASURED 2026-10-22, a build from the team tree carried the owner's paths and
# notes in 48 files. The tarball still lands in this checkout's dist/.
cd "${APP_SOURCE:-$ROOT}"
VERSION="$(sed -n 's/^version = "\(.*\)"/\1/p' pyproject.toml)"
NAME="hivemind-linux-$VERSION"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/$NAME" "$ROOT/dist"

git ls-files -z src scripts data pyproject.toml flake.nix installer/linux \
        docs/TESTING.md docs/SECURITY.md \
    | grep -zv -e '^data/knowledge/account[^/]*\.yaml$' -e '\.egg-info/' \
    | xargs -0 cp --parents -t "$STAGE/$NAME"
cp installer/linux/install.sh installer/linux/README-LINUX.md "$STAGE/$NAME/"

# PRIVACY: nothing that looks like a token, a private-server code or a home
# directory. A finding fails the build; it is not a warning.
if grep -rIlE -e '[0-9]{8,10}:AA[A-Za-z0-9_-]{30,}' -e 'privateServerLinkCode=[0-9a-f]{8}' \
        -e 'share\?code=[0-9a-f]{16}' -e 'TELEGRAM_CHAT=-?[0-9]{5,}' \
        "$STAGE/$NAME"; then
    echo "privacy check FAILED: the files above look like they hold a secret" >&2
    exit 1
fi
[ -z "$(find "$STAGE/$NAME" -path '*/var/*' -o -name 'account*.yaml' -path '*knowledge*' -o -name '*.env')" ] \
    || { echo "privacy check FAILED: var/, account or .env files staged" >&2; exit 1; }

OUT="$ROOT/dist/$NAME.tar.gz"
tar -C "$STAGE" -czf "$OUT" "$NAME"
echo "$OUT  $(stat -c %s "$OUT") bytes  $(tar -tzf "$OUT" | grep -vc '/$') files  sha256 $(sha256sum "$OUT" | cut -c1-64)"
