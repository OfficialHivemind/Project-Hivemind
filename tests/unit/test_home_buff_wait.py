"""W5: a walk home's buff wait lasts until the bar is clear (act/routes HOME_BUFF_REARM)."""
from hivemind.act import routes
from hivemind.act.routes import home_buff_wait_s


def test_ab_waits_the_cap_in_odd_hours_and_the_read_seconds_in_even(monkeypatch):
    monkeypatch.setattr(routes, "HOME_BUFF_REARM", "ab")
    assert home_buff_wait_s(16.0, 32.0, hour=3) == 32.0      # attempt 943's 03:23
    assert home_buff_wait_s(16.0, 32.0, hour=2) == 17.0      # today's left + 1
    assert home_buff_wait_s(None, 32.0, hour=2) == 32.0      # time unknown: the cap


def test_pinned_on_and_off(monkeypatch):
    monkeypatch.setattr(routes, "HOME_BUFF_REARM", "on")
    assert home_buff_wait_s(5.0, 32.0, hour=2) == 32.0
    monkeypatch.setattr(routes, "HOME_BUFF_REARM", "off")
    assert home_buff_wait_s(5.0, 32.0, hour=3) == 6.0
    assert home_buff_wait_s(40.0, 32.0, hour=3) == 32.0      # never past the cap
