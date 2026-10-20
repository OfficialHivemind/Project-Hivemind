"""The bot<->GUI socket.

The properties worth testing are the failure modes, not the happy path. A
telemetry link that stalls the agent when nobody is reading it, or that takes
the GUI down when the bot dies, would be worse than having no link at all.
"""
import time

import pytest

from hivemind.ipc.bus import EventClient, EventServer
from hivemind.telemetry.events import Answer, Log, Thought


@pytest.fixture
def sock_path(tmp_path):
    return str(tmp_path / "hm.sock")


def wait_until(predicate, timeout=5.0, interval=0.02):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


def test_event_reaches_the_gui(sock_path):
    got = []
    with EventServer(sock_path) as server:
        client = EventClient(sock_path, on_event=got.append).start()
        assert wait_until(lambda: server.client_count == 1)
        server.send(Thought(text="hello"))
        assert wait_until(lambda: got)
        assert got[0].text == "hello"
        client.stop()


def test_answer_travels_back_to_the_bot(sock_path):
    received = []
    with EventServer(sock_path, on_message=received.append) as server:
        client = EventClient(sock_path).start()
        assert wait_until(lambda: server.client_count == 1)
        assert client.send(Answer(id="q1", choice="yes"))
        assert wait_until(lambda: received)
        assert received[0].id == "q1" and received[0].choice == "yes"
        client.stop()


def test_send_never_blocks_when_nobody_is_listening(sock_path):
    """The agent must not stall because no GUI is attached."""
    with EventServer(sock_path) as server:
        start = time.monotonic()
        for i in range(5000):
            server.send(Log(message=f"line {i}"))
        elapsed = time.monotonic() - start
        assert elapsed < 2.0, f"sending took {elapsed:.2f}s"
        assert server.dropped > 0, "queue should have shed load, not grown"


def test_client_survives_a_bot_that_never_existed(sock_path):
    """Connecting to nothing must not raise; it just stays disconnected."""
    states = []
    client = EventClient(sock_path, on_state=states.append, retry_s=0.05).start()
    time.sleep(0.3)
    assert client.connected is False
    assert client.send(Log(message="x")) is False
    client.stop()


def test_client_reconnects_after_the_bot_restarts(sock_path):
    got = []
    states = []
    client = EventClient(sock_path, on_event=got.append,
                         on_state=states.append, retry_s=0.05).start()
    server = EventServer(sock_path).start()
    assert wait_until(lambda: client.connected)
    server.stop()
    assert wait_until(lambda: not client.connected)

    server2 = EventServer(sock_path).start()
    assert wait_until(lambda: client.connected, timeout=5.0)
    server2.send(Thought(text="back"))
    assert wait_until(lambda: any(getattr(e, "text", "") == "back" for e in got))
    client.stop()
    server2.stop()


def test_refuses_to_clobber_a_live_server(sock_path):
    with EventServer(sock_path):
        with pytest.raises(RuntimeError, match="already listening"):
            EventServer(sock_path).start()


@pytest.mark.skipif(not hasattr(__import__("socket"), "AF_UNIX"),
                    reason="a Unix socket file; Windows uses loopback TCP (test_bus_tcp)")
def test_reclaims_a_stale_socket_file(sock_path):
    """A crashed run leaves the file behind; the next start must still work.

    The crash is simulated with a bare bound-then-closed socket rather than by
    reaching into a running EventServer. Closing a listening socket out from
    under a thread that is blocked in accept() does not release the descriptor
    until that call returns, so the file would still answer connect() for up to
    one accept timeout -- which tests a race, not the behaviour we care about.
    """
    import os
    import socket as _socket
    dead = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
    dead.bind(sock_path)
    dead.listen(1)
    dead.close()
    assert os.path.exists(sock_path), "the stale file is the precondition"

    replacement = EventServer(sock_path).start()
    assert replacement.client_count == 0
    got = []
    client = EventClient(sock_path, on_event=got.append).start()
    assert wait_until(lambda: replacement.client_count == 1)
    client.stop()
    replacement.stop()


def test_malformed_line_does_not_kill_the_reader(sock_path):
    got = []
    with EventServer(sock_path) as server:
        client = EventClient(sock_path, on_event=got.append).start()
        assert wait_until(lambda: server.client_count == 1)
        # push raw rubbish straight past the event layer
        server._q.put("{not json at all")
        server.send(Thought(text="after the rubbish"))
        assert wait_until(lambda: got)
        assert got[0].text == "after the rubbish"
        client.stop()


def test_two_guis_both_receive(sock_path):
    a, b = [], []
    with EventServer(sock_path) as server:
        c1 = EventClient(sock_path, on_event=a.append).start()
        c2 = EventClient(sock_path, on_event=b.append).start()
        assert wait_until(lambda: server.client_count == 2)
        server.send(Thought(text="broadcast"))
        assert wait_until(lambda: a and b)
        c1.stop(); c2.stop()


# ---- a GUI that attaches late must still see the state --------------------
# The owner opened the app mid-run and every panel was empty while the honey
# counter in the same window ticked up: no tab showed anything. Most of what the panels draw arrives ONCE -- quests at startup, the
# field ranking and the plan at the start of a fifteen-minute cycle -- so a
# client that attaches afterwards has nothing to draw.
def test_a_client_that_connects_late_is_given_the_current_state():
    import time
    from hivemind.ipc.bus import EventClient, EventServer
    from hivemind.telemetry.events import FieldStatus, Metric

    path = f"/tmp/hivemind-snap-{time.time_ns()}.sock"
    server = EventServer(path=path).start()
    try:
        server.send(Metric(name="honey", value=29_800_000.0, unit="honey"))
        server.send(FieldStatus(name="pineapple", recommended=True))
        time.sleep(0.2)

        seen = []
        client = EventClient(path, on_event=seen.append).start()
        deadline = time.time() + 3
        while time.time() < deadline and len(seen) < 2:
            time.sleep(0.05)
        client.stop()

        kinds = {getattr(e, "kind", "") for e in seen}
        assert "metric" in kinds, "the header would read blank"
        assert "field" in kinds, "the Fields tab would say 'not visited'"
    finally:
        server.stop()


def test_the_snapshot_keeps_only_the_newest_of_each_row():
    from hivemind.ipc.bus import EventServer
    from hivemind.telemetry.events import Metric

    server = EventServer(path="/tmp/hivemind-unused.sock")
    for value in (1.0, 2.0, 3.0):
        server.send(Metric(name="honey", value=value, unit="honey"))
    assert len(server._latest) == 1, "one metric name, one row"
    assert "3.0" in list(server._latest.values())[0]


def test_frames_are_never_replayed():
    """20 a second, and the live view has its own path."""
    from hivemind.ipc.bus import EventServer
    from hivemind.telemetry.events import Frame

    server = EventServer(path="/tmp/hivemind-unused2.sock")
    server.send(Frame(path="/run/user/1000/hivemind-live.jpg"))
    assert server._latest == {}


def test_only_the_plan_thought_is_replayed_not_the_whole_stream():
    from hivemind.ipc.bus import EventServer
    from hivemind.telemetry.events import Thought

    server = EventServer(path="/tmp/hivemind-unused3.sock")
    server.send(Thought(topic="farm", text="walking"))
    assert server._latest == {}
    server.send(Thought(topic="plan", text="gather in pineapple"))
    assert len(server._latest) == 1
