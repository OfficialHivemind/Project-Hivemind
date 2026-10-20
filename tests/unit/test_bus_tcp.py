"""RL6 phase 3: the bot<->GUI link over loopback TCP with a token (Windows
has no AF_UNIX). Run here on Linux with the TCP switch on: real sockets on
127.0.0.1, nothing else. Linux itself keeps its unix socket (test_bus)."""
import os
import socket
import stat
import time

import pytest

from hivemind.ipc import bus
from hivemind.telemetry.events import Answer, Thought


def wait_until(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


@pytest.fixture
def endpoint(monkeypatch, tmp_path):
    monkeypatch.setattr(bus, "TCP", True)
    monkeypatch.setattr(bus, "TOKEN_WAIT_S", 0.5)
    return str(tmp_path / "hivemind.endpoint")


def test_the_endpoint_names_a_loopback_port_and_a_token_only_we_can_read(endpoint):
    with bus.EventServer(endpoint) as server:
        port, token = bus.read_endpoint(endpoint)
        assert server._sock.getsockname() == ("127.0.0.1", port) and len(token) == 32
        # chmod is a no-op on Windows (MEASURED 2026-10-21: files come out 0o666); %LOCALAPPDATA% is the user's own
        assert os.name == "nt" or stat.S_IMODE(os.stat(endpoint).st_mode) == 0o600
    assert not os.path.exists(endpoint)                 # removed on stop


def test_both_ways_with_the_token(endpoint):
    received, got = [], []
    with bus.EventServer(endpoint, on_message=received.append) as server:
        server.send(Thought(text="the plan", topic="plan"))     # replayed to a newcomer
        client = bus.EventClient(endpoint, on_event=got.append, retry_s=0.05).start()
        assert wait_until(lambda: server.client_count == 1)
        assert wait_until(lambda: got) and got[0].text == "the plan"
        assert client.send(Answer(id="q1", choice="yes"))
        assert wait_until(lambda: received) and received[0].id == "q1"
        client.stop()


def test_a_wrong_token_is_told_nothing_and_heard_not_at_all(endpoint):
    received = []
    with bus.EventServer(endpoint, on_message=received.append) as server:
        server.send(Thought(text="secret plan", topic="plan"))
        port, _ = bus.read_endpoint(endpoint)
        s = socket.create_connection(("127.0.0.1", port), timeout=3)
        s.sendall(b"not-the-token\n" + Answer(id="q9", choice="yes").to_json().encode() + b"\n")
        assert s.recv(4096) == b""                      # closed, no snapshot
        s.close()
        silent = socket.create_connection(("127.0.0.1", port), timeout=3)
        assert silent.recv(4096) == b""                 # said nothing in time: closed
        silent.close()
        time.sleep(0.1)
        assert received == [] and server.client_count == 0


def test_a_second_server_on_a_live_endpoint_refuses(endpoint):
    with bus.EventServer(endpoint):
        with pytest.raises(RuntimeError, match="already listening"):
            bus.EventServer(endpoint).start()


def test_a_stale_endpoint_is_replaced(endpoint):
    with open(endpoint, "w") as fh:
        fh.write("1 deadbeef\n")                         # port 1: nobody there
    with bus.EventServer(endpoint):
        assert bus.read_endpoint(endpoint)[0] != 1


def test_a_one_shot_client_says_the_token_too(endpoint):
    """scripts/telegram_alerts' bot_socket goes through bus.connect."""
    with bus.EventServer(endpoint) as server:
        with bus.connect(endpoint) as s:
            assert wait_until(lambda: server.client_count == 1)
            assert s.family == socket.AF_INET
    with pytest.raises(OSError):
        bus.connect(endpoint)                           # nobody listening: the file is gone
