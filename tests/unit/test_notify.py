"""Telling the owner on his desktop (platform/notify)."""
from hivemind.platform import notify


def test_each_reason_is_said_once_per_interval(monkeypatch):
    monkeypatch.setattr(notify, "_last", {})
    sent, now = [], [1000.0]

    def run(argv, **kw):
        sent.append(argv)
    assert notify.owner_alert("T", "B", key="agreements", clock=lambda: now[0], run=run)
    assert not notify.owner_alert("T", "B", key="agreements", clock=lambda: now[0], run=run)
    now[0] += notify.ALERT_EVERY_S + 1
    assert notify.owner_alert("T", "B", key="agreements", clock=lambda: now[0], run=run)
    assert len(sent) == 2 and sent[0][0] == "notify-send" and sent[0][-2:] == ["T", "B"]


def test_a_failed_notify_never_raises(monkeypatch):
    monkeypatch.setattr(notify, "_last", {})

    def run(argv, **kw):
        raise OSError("no notify-send")
    assert notify.owner_alert("T", "B", run=run) is False
