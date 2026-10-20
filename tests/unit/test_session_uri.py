import pytest
from hivemind.platform.session import bss_uri, parse_private_link


@pytest.mark.parametrize("value,expected", [
    ("AbC123xyz", ("legacy", "AbC123xyz")),
    ("https://www.roblox.com/games/1537690962/Bee-Swarm?privateServerLinkCode=AbC123xyz",
     ("legacy", "AbC123xyz")),
    ("https://roblox.com/games/1537690962/X?privateServerLinkCode=AbC123xyz&foo=1",
     ("legacy", "AbC123xyz")),
    # the current share format (Roblox changed this in Oct 2023)
    ("https://www.roblox.com/share?code=0123456789abcdef0123456789abcdef&type=Server",
     ("share", "0123456789abcdef0123456789abcdef")),
    ("https://www.roblox.com/share?type=Server&code=abcdef0123456789abcdef0123456789",
     ("share", "abcdef0123456789abcdef0123456789")),
    ("0123456789abcdef0123456789abcdef", ("share", "0123456789abcdef0123456789abcdef")),
    (None, None),
    ("", None),
])
def test_accepts_code_or_share_url(value, expected):
    assert parse_private_link(value) == expected


def test_share_link_becomes_a_navigation_deeplink():
    """The share format drops the game id, so it cannot become a PlaceLauncher
    URL - it goes to Sober as a roblox:// share_links deeplink instead."""
    uri = bss_uri("https://www.roblox.com/share?code=0123456789abcdef0123456789abcdef&type=Server")
    assert uri == ("roblox://navigation/share_links?type=Server"
                   "&code=0123456789abcdef0123456789abcdef")


def test_url_without_code_is_a_clear_error():
    with pytest.raises(ValueError, match="private-server code"):
        parse_private_link("https://www.roblox.com/games/1537690962/Bee-Swarm")


def test_public_and_legacy_private_uris_differ_correctly():
    assert "RequestGame" in bss_uri() or "RequestGame" in bss_uri().replace("%3D", "=")
    priv = bss_uri("AbC123xyz")
    from urllib.parse import unquote
    inner = unquote(priv.split("placelauncherurl:")[1])
    assert "RequestPrivateGame" in inner
    assert "linkCode=AbC123xyz" in inner
    assert "placeId=1537690962" in inner
