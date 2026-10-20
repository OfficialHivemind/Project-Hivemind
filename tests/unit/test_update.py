"""U15f's first half (hivemind/update): the newest release with the app's
installer, its checksum from the notes, and a download kept only when it
matches."""
from __future__ import annotations

import hashlib
import io

import pytest

from hivemind import update

SHA = hashlib.sha256(b"installer bytes").hexdigest()


def _release(tag, *, asset=update.WINDOWS_ASSET, draft=False, pre=False, body=None):
    return {"tag_name": tag, "draft": draft, "prerelease": pre,
            "html_url": f"https://example.invalid/{tag}",
            "body": body if body is not None else f"SHA-256: {SHA}  {asset}",
            "assets": [{"name": asset, "size": 15,
                        "browser_download_url": f"https://example.invalid/{tag}/{asset}"}]}


def test_versions_come_out_of_any_tag():
    assert update.parse_version("v0.2.3") == (0, 2, 3)
    assert update.parse_version("hivemind-1.0.0") == (1, 0, 0)
    assert update.parse_version("ui-preview") is None


def test_the_checksum_is_the_one_written_beside_the_file():
    body = f"Windows\nSHA-256: {'a' * 64}  Hivemind-UI-Preview.exe\n{SHA} *Hivemind-Setup.exe"
    assert update.sha256_in_notes(body, "Hivemind-Setup.exe") == SHA
    assert update.sha256_in_notes(body, "Hivemind-UI-Preview.exe") == "a" * 64
    assert update.sha256_in_notes("no checksum here", "Hivemind-Setup.exe") is None


def test_the_ui_preview_and_drafts_are_never_an_update():
    releases = [_release("ui-preview-0.9.0", asset="Hivemind-UI-Preview.exe"),
                _release("v0.5.0", draft=True), _release("v0.2.0"), _release("v0.3.0")]
    assert update.latest(releases).tag == "v0.3.0"


def test_test_builds_count_only_when_asked():
    releases = [_release("v0.2.0"), _release("v0.4.0", pre=True)]
    assert update.latest(releases).tag == "v0.2.0"
    assert update.latest(releases, include_prereleases=True).tag == "v0.4.0"


def test_check_says_newer_or_newest_in_plain_words_and_never_raises():
    win = update.WINDOWS_ASSET
    found, said = update.check("0.1.0", asset=win, releases=[_release("v0.2.0")])
    assert found.tag == "v0.2.0" and said == "Hivemind 0.2.0 is out (you have 0.1.0)"
    found, said = update.check("0.2.0", asset=win, releases=[_release("v0.2.0")])
    assert found is None and "0.2.0 is the newest" in said
    found, said = update.check("0.1.0", asset=win, releases=[])
    assert found is None and "no Hivemind release" in said
    found, said = update.check("0.1.0", asset=win, releases={"message": "rate limited"})
    assert found is None


def test_linux_is_told_only_of_a_linux_package():
    """Usability triage 2026-10-27 #9: a Windows-only release is no update here."""
    linux = update.LINUX_ASSET
    found, _ = update.check("0.1.0", asset=linux, releases=[_release("v0.2.0")])
    assert found is None
    tar = "hivemind-linux-0.3.0.tar.gz"
    found, _ = update.check("0.1.0", asset=linux, releases=[_release("v0.3.0", asset=tar)])
    assert found.tag == "v0.3.0" and found.sha256 == SHA


def test_no_internet_is_said_in_plain_words(monkeypatch):
    import urllib.error

    def offline(timeout=20):
        raise urllib.error.URLError("[Errno -3] Temporary failure in name resolution")
    monkeypatch.setattr(update, "fetch_releases", offline)
    assert update.check("0.1.0") == (None, "could not reach GitHub (no internet?)")


def test_a_download_is_kept_only_when_it_matches(tmp_path):
    rel = update.latest([_release("v0.2.0")])
    got = update.download(rel, tmp_path, opener=lambda url: io.BytesIO(b"installer bytes"))
    assert got.read_bytes() == b"installer bytes" and got.name == update.WINDOWS_ASSET
    bad = update.latest([_release("v0.3.0")])
    with pytest.raises(ValueError, match="not the"):
        update.download(bad, tmp_path / "b", opener=lambda url: io.BytesIO(b"tampered"))
    assert list((tmp_path / "b").iterdir()) == []


def test_no_checksum_no_download(tmp_path):
    rel = update.latest([_release("v0.2.0", body="no checksum")])
    asked = []
    with pytest.raises(ValueError, match="no sha256"):
        update.download(rel, tmp_path, opener=lambda url: asked.append(url))
    assert not asked
