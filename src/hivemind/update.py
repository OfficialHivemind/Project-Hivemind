"""U15f, AUTO UPDATE, first half (a community idea, 23 Oct): is there a newer
Hivemind on the public repo's Releases, and download its installer checked
against the sha256 its release notes give.

THIS HALF NEVER RUNS ANYTHING and nothing calls it on its own yet. The second
half (the GUI's "a newer version is out" line, the first-run question, the
off-by-default setting, running the installer only while the bot is stopped)
builds on it. It contacts GitHub only when called (AGENTS rule 5: optional
features default off).

A release counts only when it carries the asked-for file, so the UI Preview
release (Hivemind-UI-Preview.exe) is never taken for an update of the app.
No checksum in the notes for that file = nothing is downloaded.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import urllib.error
import urllib.request
from fnmatch import fnmatchcase
from dataclasses import dataclass
from pathlib import Path

from . import datapaths, selftest

RELEASES = "https://api.github.com/repos/OfficialHivemind/Project-Hivemind/releases"
PAGE = "https://github.com/OfficialHivemind/Project-Hivemind/releases"
# The installer's name (installer/hivemind.iss OutputBaseFilename).
WINDOWS_ASSET = "Hivemind-Setup.exe"
# The Linux test package (installer/linux/build.sh: hivemind-linux-<version>.tar.gz).
# A Linux copy is told only about a release that carries it, never about a
# Windows-only one (usability triage 2026-10-27 #9).
LINUX_ASSET = "hivemind-linux-*.tar.gz"
# ponytail: macOS looks for the Linux package until RL7 ships its own
ASSET = WINDOWS_ASSET if sys.platform == "win32" else LINUX_ASSET
CHUNK = 1 << 20


@dataclass
class Release:
    tag: str
    version: tuple[int, ...]
    url: str              # the asset's download link
    size: int
    sha256: str | None    # from the release notes; None = not given
    prerelease: bool
    page: str


def parse_version(text) -> tuple[int, ...] | None:
    """(major, minor, patch) from "0.1.0", "v0.2.3" or "hivemind-1.0.0"; None
    when there is no x.y.z in it."""
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", str(text or ""))
    return tuple(int(g) for g in m.groups()) if m else None


def sha256_in_notes(body, asset: str) -> str | None:
    """The 64-hex checksum written beside `asset` in the release notes
    ("SHA-256: <hex>  Hivemind-Setup.exe", the sha256sum layout)."""
    m = re.search(r"\b([0-9a-fA-F]{64})\b[ \t*]+" + re.escape(asset) + r"\b", str(body or ""))
    return m.group(1).lower() if m else None


def latest(releases: list, asset: str = WINDOWS_ASSET, *,
           include_prereleases: bool = False) -> Release | None:
    """The newest non-draft release that carries `asset` (a file name, or a
    glob like LINUX_ASSET) and has a version."""
    best = None
    for r in releases or []:
        if not isinstance(r, dict) or r.get("draft"):
            continue
        if r.get("prerelease") and not include_prereleases:
            continue
        version = parse_version(r.get("tag_name"))
        file = next((a for a in r.get("assets") or []
                     if isinstance(a, dict) and fnmatchcase(str(a.get("name") or ""), asset)), None)
        if version is None or file is None:
            continue
        if best is None or version > best.version:
            best = Release(tag=str(r.get("tag_name")), version=version,
                           url=str(file.get("browser_download_url") or ""),
                           size=int(file.get("size") or 0),
                           sha256=sha256_in_notes(r.get("body"), str(file.get("name"))),
                           prerelease=bool(r.get("prerelease")),
                           page=str(r.get("html_url") or PAGE))
    return best


def fetch_releases(timeout: float = 20) -> list:
    """The public repo's releases from GitHub's API (no login)."""
    req = urllib.request.Request(RELEASES, headers={
        "Accept": "application/vnd.github+json", "User-Agent": "Hivemind update check"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def check(installed: str | None = None, *, asset: str = ASSET,
          include_prereleases: bool = False, releases=None) -> tuple[Release | None, str]:
    """(the newer release or None, a line in plain words). Never raises."""
    have = parse_version(installed if installed is not None else selftest.version())
    try:
        found = latest(fetch_releases() if releases is None else releases, asset,
                       include_prereleases=include_prereleases)
    except urllib.error.HTTPError as exc:      # GitHub answered, with an error
        return None, f"could not check for updates (GitHub said {exc.code})"
    except OSError:                            # URLError, a timeout: no answer at all
        return None, "could not reach GitHub (no internet?)"
    except Exception as exc:
        return None, f"could not check for updates ({exc})"
    if found is None:
        return None, "no Hivemind release to update to yet"
    if have is not None and found.version <= have:
        return None, f"Hivemind {'.'.join(map(str, have))} is the newest"
    return found, (f"Hivemind {'.'.join(map(str, found.version))} is out"
                   + (f" (you have {'.'.join(map(str, have))})" if have else ""))


def download(release: Release, dest_dir: Path | None = None, *, opener=None) -> Path:
    """The installer, saved and checked against the notes' sha256. Raises
    ValueError (and keeps nothing) when the notes give no checksum or the file
    does not match it."""
    if not release.sha256:
        raise ValueError(f"the {release.tag} release notes give no sha256 for the "
                         f"installer, so it is not downloaded")
    dest_dir = Path(dest_dir) if dest_dir is not None else datapaths.var("updates")
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = release.url.rsplit("/", 1)[-1] or WINDOWS_ASSET
    final, part = dest_dir / name, dest_dir / (name + ".part")
    digest = hashlib.sha256()
    open_url = opener or (lambda url: urllib.request.urlopen(
        urllib.request.Request(url, headers={"User-Agent": "Hivemind update"}), timeout=60))
    try:
        with open_url(release.url) as resp, open(part, "wb") as out:
            while chunk := resp.read(CHUNK):
                digest.update(chunk)
                out.write(chunk)
        if digest.hexdigest() != release.sha256:
            raise ValueError(f"the download's sha256 is {digest.hexdigest()}, not the "
                             f"{release.sha256} the release notes give; deleted")
        part.replace(final)
        return final
    finally:
        part.unlink(missing_ok=True)
