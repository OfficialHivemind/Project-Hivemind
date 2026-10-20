"""The alt follows the main into its server (platform/lastserver.FollowUser)."""
from hivemind.platform import lastserver


def test_a_user_id_becomes_robloxs_join_user_link():
    f = lastserver.follow_user(" 1234567890 ")
    assert f.uri() == "roblox://experiences/start?userId=1234567890"
    assert f.private and len(f.digest) == 6 and "1234567890" not in f.digest


def test_anything_but_digits_is_not_followed():
    for text in ("", None, "ExamplePlayer", "12a4"):
        assert lastserver.follow_user(text) is None
