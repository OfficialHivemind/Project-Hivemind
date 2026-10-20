"""ROADMAP M11: which server Start joins, its fallbacks, the drawer row picked
by name, and the owner's server switch during Take Over."""
from __future__ import annotations

from pathlib import Path

import numpy as np

import hivemind
from hivemind.act import join
from hivemind.platform import clientlog, lastserver
from hivemind.platform.clientlog import ClientLog, await_switch, moved_servers

ROOT = Path(hivemind.__file__).resolve().parents[2]
FAKE = "https://www.roblox.com/share?code=" + "ab" * 16 + "&type=Server"
NEVER = lambda s: False                       # noqa: E731


# ---- the target ------------------------------------------------------------
def test_default_is_his_own_server():
    t = lastserver.target(None)
    assert t.server is None and t.name == ""
    assert lastserver.target("my private server").server is None


def test_a_share_link_rides_the_launch_and_is_never_said():
    t = lastserver.target("this share link", FAKE, failed=NEVER)
    assert isinstance(t.server, lastserver.ShareLink)
    assert "ab" * 16 not in t.said and "share?code" not in t.said
    assert t.server.digest in t.said


def test_a_bad_or_failed_link_falls_back_and_says_why():
    t = lastserver.target("this share link", "not a link")
    assert t.server is None and "no share-link code" in t.said
    t = lastserver.target("this share link", FAKE, "Mama's server", failed=lambda s: True)
    assert t.server is None and t.name == "Mama's server" and "last time" in t.said


def test_a_named_server_needs_a_name():
    assert lastserver.target("a named server", name="  someone's   server ").name \
        == "someone's server"
    t = lastserver.target("a named server", name="")
    assert t.name == "" and "empty" in t.said


def test_follow_me():
    public = lastserver.LastServer(job="00000000-0000-0000-0000-000000000000",
                                   request="RequestGame", at=0.0, log="x.log")
    private = lastserver.LastServer(job=public.job, request="RequestPrivateGame",
                                    at=0.0, log="x.log")
    assert lastserver.target("follow me", last=lambda: public, failed=NEVER).server is public
    assert lastserver.target("follow me", last=lambda: private).server is None
    assert lastserver.target("follow me", last=lambda: None).server is None
    assert public.job not in lastserver.target("follow me", last=lambda: public,
                                               failed=NEVER).said


def test_the_choices_are_the_settings_choices():
    from hivemind.world.settings import SECRET, SECTIONS
    entry = {e[0]: e for _, es in SECTIONS for e in es}["server.join"]
    assert entry[5] == lastserver.JOIN_CHOICES and entry[3] == lastserver.MY_SERVER
    assert "server.link" in SECRET


# ---- the drawer row by name ------------------------------------------------
def drawer(*buttons):
    """A drawer frame: the dark header and blue Joins at (x, y)."""
    f = np.full((1080, 1920, 3), 250, np.uint8)
    f[0:44, 960:] = 20
    for x, y in buttons:
        f[y:y + 32, x:x + 63] = (255, 120, 60)          # BGR roblox blue, S high
    return f


def fake_ocr(rows):
    """Reads the name of every row whose Join's centre line is in the box,
    as long as the box is left of that Join (the name is, MEASURED)."""
    def ocr(frame, box):
        x0, y0, x1, y1 = box
        return " ".join(t for (x, y), t in rows.items() if y0 <= y + 16 < y1 and x1 <= x)
    return ocr


def test_the_named_row_is_found_and_its_neighbour_is_not_borrowed():
    rows = {(1841, 213): "ExampleHost's Server", (1841, 277): "someone’s server"}
    f = drawer(*rows)
    hit, text, why = join.find_named_button(f, "Someone's Server", fake_ocr(rows))
    assert hit is not None and abs(hit.cy - 293) < 3, why
    hit, _, why = join.find_named_button(f, "nobody's server", fake_ocr(rows))
    assert hit is None and "no row reads" in why


def test_two_matching_rows_are_never_clicked():
    rows = {(1841, 213): "mama server", (1841, 277): "mama server"}
    hit, _, why = join.find_named_button(drawer(*rows), "mama", fake_ocr(rows))
    assert hit is None and "none is clicked" in why


def test_look_only_and_not_found_click_his_own():
    rows = {(1841, 213): "ExampleHost's Server", (1841, 277): "someone's server"}
    f = drawer(*rows)
    own = join.find_primary_button(f)
    said = []
    assert join.chosen_button(f, "someone's server", own, said.append,
                              ocr=fake_ocr(rows), live=False) is own
    assert "would join row 'someone's server'" in said[-1]
    assert join.chosen_button(f, "zzz", own, said.append, ocr=fake_ocr(rows),
                              live=True) is own
    live = join.chosen_button(f, "someone's server", own, said.append,
                              ocr=fake_ocr(rows), live=True)
    assert live is not own and abs(live.cy - 293) < 3
    assert join.JOIN_CHOSEN_LIVE is False


def test_the_real_drawer_reads_his_row_by_name():
    """MEASURED: tesseract on the real drawer (their own server alone)."""
    import shutil
    import cv2
    import pytest
    path = ROOT / "tests/fixtures/screens/servers_drawer_private.png"
    if not path.exists() or shutil.which("tesseract") is None:
        pytest.skip("the drawer fixture or tesseract is not here")
    from hivemind.act.shoplook import _ocr_line
    ocr = lambda f, box: _ocr_line(f, box, psm=6)     # noqa: E731
    f = cv2.imread(str(path))
    # the row's own words, read off the frame, so no account name is written here
    (button,) = join.find_primary_buttons(f)
    own = " ".join(ocr(f, join.row_box(button)).split())
    hit, text, _ = join.find_named_button(f, own, ocr)
    assert hit is not None and "server" in text.lower()
    assert join.find_named_button(f, "someone's server", ocr)[0] is None
    assert join.find_named_button(f, "Create a private server", ocr)[0] is None


# ---- the take-over server switch -------------------------------------------
JOB_A = "11111111-2222-3333-4444-555555555555"
JOB_B = "66666666-7777-8888-9999-aaaaaaaaaaaa"


def line(stamp, channel, text):
    return f"2026-10-16T{stamp}Z,1.0,abcd,6 [{channel}] {text}\n"


RUN_1034 = [   # its shape, in UTC; the reader keeps no id or address
    line("10:11:40.000", "FLog::Output", f"! Joining game '{JOB_A}' place 1537690962 at 10.0.0.1|1"),
    line("10:11:40.200", "FLog::Network", "Replicator created: 0x1"),
    line("10:12:40.000", "FLog::Output", "onSessionHeartbeat"),
    line("10:13:00.000", "FLog::Network", "leaveUGCGameInternal"),
    line("10:13:00.010", "FLog::Network", "Time to disconnect replication data: 0.01"),
    line("10:13:00.020", "FLog::Network", "Sending disconnect with reason: 285"),
    line("10:13:00.040", "FLog::Network",
         "Disconnected from server for reason: left (DisconnectClientInitiated)"),
]
JOIN_B = line("10:13:14.000", "FLog::Output", f"! Joining game '{JOB_B}' place 1537690962 at 10.0.0.2|1")


def test_run_1034_reads_as_a_server_switch(tmp_path):
    log = tmp_path / "sober.log"
    log.write_text("".join(RUN_1034))
    lost = []
    reader = ClientLog(log, on_lost=lost.append)
    reader.poll()
    reader.poll()                    # the ending is said one poll later
    assert len(lost) == 1 and reader.reason == "285"
    ended = lost[0]
    with log.open("a") as fh:
        fh.write(JOIN_B)
    reader.poll()
    assert moved_servers(ended, reader.joined)
    assert reader.joined.at - ended.at == 14.0
    assert JOB_B not in reader.joined.detail
    assert reader.ended is None                 # the new session is not "ended"


def test_no_join_in_the_window_is_the_client_leaving():
    ended = clientlog.ClientEvent("leave", 1000.0)
    now = [1000.0]

    def sleep(s):
        now[0] += s
    assert await_switch(ended, lambda: None, window=30, clock=lambda: now[0],
                        sleep=sleep) is None
    assert now[0] > 1030
    late = clientlog.ClientEvent("join", 1000.0 + 31)
    assert not moved_servers(ended, late, window=30)
    before = clientlog.ClientEvent("join", 990.0)          # the old session's join
    assert not moved_servers(ended, before)


def test_a_join_inside_the_window_returns_it():
    ended = clientlog.ClientEvent("leave", 1000.0)
    joined = clientlog.ClientEvent("join", 1014.0, "place 1537690962 server #abc123")
    seq = iter([None, None, joined])
    now = [1000.0]
    got = await_switch(ended, lambda: next(seq), clock=lambda: now[0],
                       sleep=lambda s: now.__setitem__(0, now[0] + s))
    assert got is joined


def test_run_farm_defers_the_stop_only_during_a_handover():
    body = (ROOT / "scripts" / "run_farm.py").read_text()
    lost = body[body.index("def client_lost"):body.index("def stop_for_loss")]
    assert "controls.handed_over" in lost and "await_switch" in lost
    assert "stop_for_loss(ended)" in lost


def test_the_long_private_link_joins_by_link_code():
    from hivemind.platform import lastserver
    s = lastserver.share_link("https://www.roblox.com/games/1537690962/Bee-Swarm-Simulator"
                              "?privateServerLinkCode=12345678901234567890")
    assert s is not None and s.kind == "link"
    assert s.uri() == "roblox://placeId=1537690962&linkCode=12345678901234567890"
    fake = lastserver.share_link("https://www.roblox.com/share?code=" + "ab" * 16 + "&type=Server")
    assert fake.kind == "share" and "share_links" in fake.uri()
