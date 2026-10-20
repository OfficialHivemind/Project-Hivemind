"""The stream's voice: what it says comes from what the bot did, and how often.

The owner, 2026-09-28: "make it so the AI has a text to speach and says where
its gonna go or what its thinking", "it needs to be more entertaining for
veiwers ... keep them watching and make them subscribe". stream/voice picks
the words, gui/stream_voice says them; no sound is made here -- the player
is a fake that records the commands it was given.
"""
from __future__ import annotations

import random
import subprocess
import time
from types import SimpleNamespace

from hivemind.gui import stream_voice
from hivemind.stream import voice
from hivemind.stream.show import CANNON_WORDS, toast
from hivemind.telemetry.events import Considered, Log, TaskUpdate, Thought


class Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


SETTINGS = {"stream.voice": True, "stream.voice_room": True, "stream.chat_games": True,
            "stream.chat_may_jump": True, "stream.chat_w_rain": True,
            "stream.voice_volume": 80, "stream.voice_name": "joe"}


def announcer(clock, chat=True, **over):
    got = dict(SETTINGS, **over)
    return voice.Announcer(get=got.get, clock=clock, rng=random.Random(4),
                           chat_live=lambda: chat)


def considered(chosen, *labels):
    return Considered(options=[SimpleNamespace(label=l, score=1.0, unit="pollen/s")
                               for l in labels], chosen=chosen)


def drain(a, clock, seconds=120.0, step=1.0):
    said = []
    end = clock.t + seconds
    while clock.t < end:
        line = a.next_line()
        if line:
            said.append(line)
        clock.t += step
    return said


# ---- what it says ---------------------------------------------------------------
def test_the_next_field_is_said_with_the_real_reason():
    clock = Clock()
    a = announcer(clock)
    a.hear(considered("pine_tree", "pine_tree", "bamboo", "clover"))
    line = a.next_line()
    assert "Pine Tree" in line
    assert "the best field on my list right now" in line or line.startswith(("Next stop, Pine Tree!", "Plotting", "Pine Tree, here I come!"))


def test_the_same_field_again_is_not_news():
    clock = Clock()
    a = announcer(clock)
    a.hear(considered("pine_tree", "pine_tree"))
    assert a.next_line()
    clock.t += 30
    a.hear(considered("pine_tree", "pine_tree"))
    assert a.next_line() is None or "Pine Tree" not in a.next_line()


def test_a_convert_toast_is_said_in_words_a_voice_can_say():
    clock = Clock()
    a = announcer(clock)
    a.toasted(toast("convert", "Converted +3.4M", "from the pine tree field"))
    line = a.next_line()
    assert "3.4 million honey" in line, line


def test_the_trip_is_narrated_from_launch_to_landing():
    clock = Clock()
    a = announcer(clock, chat=False, **{"stream.voice_room": False})
    a.hear(considered("bamboo", "bamboo", "pine_tree"))
    a.hear(TaskUpdate(name="travel to the field", status="running", detail="by cannon"))
    a.hear(Thought(topic="journey", text=CANNON_WORDS + " — flying"))
    said = drain(a, clock, 10)
    a.hear(Thought(topic="where", text="I am in the bamboo field (compass)"))
    said += drain(a, clock, 10)
    assert any("Bamboo" in s for s in said), said
    assert any("annon" in s for s in said), said
    assert any(("Bamboo" in s) and s not in said[:1] for s in said[1:]), said


def test_a_token_chase_is_said_and_an_unknown_kind_is_not_named():
    clock = Clock()
    a = announcer(clock)
    a.hear(Log(message="chasing a token at (900, 500), confidence 0.84, up to 4 step(s)",
               source="chase"))
    line = a.next_line()
    assert line and "token" in line.lower() and "unknown" not in line
    clock.t += voice.TOKEN_EVERY_S          # one chase line in TOKEN_EVERY_S
    a.hear(Log(message="chasing a honey token at (900, 500), confidence 0.84", source="chase"))
    assert "honey token" in (a.next_line() or "")


def test_a_boss_a_knockout_and_a_quest_are_all_news():
    clock = Clock()
    a = announcer(clock, **{"stream.voice_room": False})
    a.toasted(toast("threat", "Boss spotted", "Tunnel Bear"))
    assert "Tunnel Bear" in a.next_line()
    clock.t += 10
    a.toasted(toast("death", "Knocked out", "Mantis"))
    assert a.next_line()
    clock.t += 10
    a.toasted(toast("quest", "Quest handed in", "at the brown bear"))
    assert "Brown Bear" in a.next_line()


# ---- how often ---------------------------------------------------------------------
def test_lines_are_spaced_and_old_news_is_dropped():
    clock = Clock()
    a = announcer(clock, **{"stream.voice_room": False})
    a.toasted(toast("convert", "Converted +1M"))
    first = a.next_line()
    a.toasted(toast("convert", "Converted +2M"))
    assert a.next_line() is None, "a second line inside GAP_S"
    clock.t += voice.GAP_S
    assert "2 million" in a.next_line()
    a.hear(TaskUpdate(name="convert", status="running"))       # routine
    clock.t += voice.STALE_S[voice.ROUTINE] + voice.GAP_S + 1
    assert a.next_line() is None, "a routine line said after it went stale"
    assert first


def test_an_event_beats_a_routine_line_waiting():
    clock = Clock()
    a = announcer(clock, **{"stream.voice_room": False})
    a.hear(TaskUpdate(name="convert", status="running"))
    a.toasted(toast("death", "Knocked out"))
    line = a.next_line()
    assert any(w in line for w in ("Knocked", "Down I go", "got me")), line


def test_never_the_same_words_twice_running():
    clock = Clock()
    a = announcer(clock, **{"stream.voice_room": False})
    said = []
    for _ in range(8):
        a.toasted(toast("convert", "Converted +1.5M"))
        said.append(a.next_line())
        clock.t += voice.GAP_S + 1
    spoken = [x for x in said if x]
    assert len(spoken) >= 4, said
    assert all(x != y for x, y in zip(spoken, spoken[1:])), said


# ---- the room ----------------------------------------------------------------------
def test_the_welcome_waits_for_a_quiet_moment_and_then_the_room_is_rationed():
    clock = Clock()
    a = announcer(clock)
    early = drain(a, clock, voice.FIRST_ENGAGE_S - 1)
    assert early == []
    later = drain(a, clock, 40)
    assert later and later[0].startswith("Welcome in"), later
    more = drain(a, clock, voice.ENGAGE_EVERY_S - 60)
    assert more == [], "a second room line before ENGAGE_EVERY_S"


def test_chat_is_only_invited_while_the_stream_reads_chat():
    clock = Clock()
    a = announcer(clock, chat=False)
    said = drain(a, clock, voice.FIRST_ENGAGE_S + 8 * voice.ENGAGE_EVERY_S + 60, step=5.0)
    assert said, "nothing said to the room at all"
    for line in said:
        assert "chat" not in line.lower(), line


def test_the_room_can_be_switched_off():
    clock = Clock()
    a = announcer(clock, **{"stream.voice_room": False})
    assert drain(a, clock, 3 * voice.ENGAGE_EVERY_S, step=5.0) == []


def test_every_room_line_names_a_command_the_stream_really_reads():
    for _, needs, text in voice.ROOM_LINES:
        if "exclamation mark ask" in text:
            assert needs == "stream.chat_ask", text        # stream/ask's own switch
        elif "exclamation mark" in text:
            assert needs == "stream.chat_games", text
        if "jump" in text.lower():
            assert needs == "stream.chat_may_jump"
        if "W rain" in text:
            assert needs == "stream.chat_w_rain"


def test_spoken_amounts():
    assert voice.spoken_amount("Converted +2.55M") == "2.55 million"
    assert voice.spoken_amount("+850K") == "850 thousand"
    assert voice.spoken_amount("New best trip today! +1.2B") == "1.2 billion"


# ---- saying it (no sound: the processes are fakes) ----------------------------------
class FakeProc:
    def __init__(self, cmd, log):
        self.cmd, self.returncode = cmd, 0
        log.append(cmd)

    def communicate(self, data=None, timeout=None):
        self.data = data

    def wait(self, timeout=None):
        return 0

    def terminate(self):
        self.returncode = -15


def _voice(tmp_path, **over):
    piper = tmp_path / "piper"
    piper.write_text("")
    voices = tmp_path / "voices"
    voices.mkdir()
    (voices / stream_voice.VOICE_FILES["kristin"]).write_text("")
    (voices / stream_voice.VOICE_FILES["joe"]).write_text("")
    log = []
    got = dict(SETTINGS, **over)
    v = stream_voice.Voice(get=got.get, popen=lambda cmd, **kw: FakeProc(cmd, log),
                           which=lambda name: name == "pw-play", piper=piper, voices=voices)
    return v, log


def _wait_idle(v, seconds=2.0):
    end = time.monotonic() + seconds
    while v.busy() and time.monotonic() < end:
        time.sleep(0.01)


def test_a_line_is_made_by_piper_and_played_at_the_set_volume(tmp_path):
    v, log = _voice(tmp_path, **{"stream.voice_volume": 55, "stream.voice_name": "kristin"})
    assert v.say("Next stop, Pine Tree!")
    _wait_idle(v)
    assert len(log) == 2, log
    piper, play = log
    assert piper[0].endswith("piper") and "kristin" in piper[piper.index("--model") + 1]
    assert play[:2] == ["pw-play", "--volume=0.55"]
    # its own PipeWire name, which OBS's application capture takes alone
    assert "-P" in play and 'application.name = "Hivemind voice"' in play[play.index("-P") + 1]
    assert v.spoken == 1 and v.failures == 0


def test_nothing_is_said_when_off_or_busy_or_missing(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    v, log = _voice(tmp_path / "a", **{"stream.voice": False})
    assert not v.say("hello")
    v2, _ = _voice(tmp_path / "b")
    v2._busy.set()
    assert not v2.say("hello")
    v3 = stream_voice.Voice(get=SETTINGS.get, piper=tmp_path / "nope")
    assert not v3.say("hello") and "no Piper" in v3.last_error
    assert log == []


def test_a_failing_piper_is_counted_and_never_raised(tmp_path):
    class Broken(FakeProc):
        def communicate(self, data=None, timeout=None):
            raise subprocess.TimeoutExpired(self.cmd, timeout)

        def kill(self):
            pass

    piper = tmp_path / "piper"
    piper.write_text("")
    voices = tmp_path / "voices"
    voices.mkdir()
    (voices / stream_voice.VOICE_FILES["joe"]).write_text("")
    v = stream_voice.Voice(get=SETTINGS.get, popen=lambda cmd, **kw: Broken(cmd, []),
                           which=lambda name: True, piper=piper, voices=voices)
    assert v.say("hello")
    _wait_idle(v)
    assert v.failures == 1 and "TimeoutExpired" in v.last_error and not v.busy()


# ---- what it is thinking: the planner's own reason ------------------------------------
# Real `why`s from run-526 (2026-09-28), clauses joined by ";".
BAMBOO_WHY = ("measured 3,173 pollen/s over 16480s here; 75% of its pollen is a colour "
              "these bees are good at; a quest wants 10 more rhino beetles defeated and "
              "they live here — the bees fight while it gathers; quests first (quests.first)")
RED_WHY = ("measured 1,020 pollen/s over 900s here; 2% of its flowers are red, and the "
           "quests still want 20,500,000 red pollen")


def test_a_quest_is_the_story_it_tells():
    assert voice.because_of(BAMBOO_WHY) == ("A quest wants 10 more rhino beetles defeated, "
                                            "and they live there")


def test_a_field_that_is_barely_red_is_not_picked_for_the_red_quest():
    assert voice.because_of(RED_WHY) == "It made about 1,000 pollen a second last time"
    assert "red pollen" in voice.because_of(RED_WHY.replace("2% of", "64% of"))


def test_the_reason_rides_on_the_next_stop():
    clock = Clock()
    a = announcer(clock)
    a.hear(Considered(options=[SimpleNamespace(label="bamboo", score=1.0, unit="pollen/s")],
                      chosen="bamboo", rationale=BAMBOO_WHY))
    line = a.next_line()
    assert "Bamboo" in line and "rhino beetles" in line, line


def test_the_room_is_only_talked_to_while_the_bot_is_really_playing():
    """ "Nobody is touching the controls" while the owner plays by hand would
    be a lie on his stream."""
    clock = Clock()
    got = dict(SETTINGS)
    a = voice.Announcer(get=got.get, clock=clock, rng=random.Random(1),
                        chat_live=lambda: True, playing=lambda: False)
    assert drain(a, clock, 3 * voice.ENGAGE_EVERY_S, step=5.0) == []


def test_a_kill_the_reward_feed_names_is_cheered():
    clock = Clock()
    a = announcer(clock, **{"stream.voice_room": False})
    a.hear(Log(message="reward feed: a Rhino Beetle was defeated, but the feed has not "
                       "named a field lately — no timer booked", source="feed"))
    assert "Rhino Beetle" in (a.next_line() or "")


def test_the_room_checks_in_on_a_real_quest_step():
    clock = Clock()
    a = announcer(clock, chat=False)
    a.quest_file({"quests": [{"name": "Rhino Rumble", "requirements": [
        "Defeat 16 Rhino Beetles. 11/16"]}]})
    said = drain(a, clock, voice.FIRST_ENGAGE_S + 2 * voice.ENGAGE_EVERY_S + 60, step=5.0)
    quest = [s for s in said if s.startswith("Quest check")]
    assert quest and "Rhino Beetles" in quest[0] and "11 of 16" in quest[0], said


# ---- not over and over (the owner, 2026-10-06 23:05: "its repeating itself") ----
def test_the_same_quest_check_waits_twenty_minutes_but_a_new_count_is_news():
    clock = Clock()
    a = announcer(clock, chat=False, **{"stream.voice_room": False})
    a.quest_file({"quests": [{"name": "Fire Fighter", "requirements": [
        "Defeat 100 Fire Ants. 73/100"]}]})
    said = drain(a, clock, 15 * 60, step=5.0)
    assert sum(s.startswith("Quest check") for s in said) == 1, said
    a.quest_file({"quests": [{"name": "Fire Fighter", "requirements": [
        "Defeat 100 Fire Ants. 74/100"]}]})
    said = drain(a, clock, 5 * 60, step=5.0)
    assert any("74 of 100" in s for s in said), said


def test_a_token_chase_is_said_once_in_five_minutes():
    clock = Clock()
    a = announcer(clock, chat=False, **{"stream.voice_room": False})
    lines = []
    for _ in range(12):                      # a chase every 20 s for 4 minutes
        a.hear(Log(message="chasing a honey token at (900, 500), confidence 0.9",
                   source="chase"))
        lines.append(a.next_line())
        clock.t += 20
    chases = {t.format(kind="honey") for t in voice.SAY["token"]}
    assert sum(1 for x in lines if x in chases) == 1, lines      # the 5th, 10th still are


def test_the_voice_waits_while_an_announcement_plays(tmp_path, monkeypatch):
    lock = tmp_path / "hivemind-announce.lock"
    monkeypatch.setattr(stream_voice, "ANNOUNCE_LOCK", lock)
    v, log = _voice(tmp_path)
    lock.touch()
    assert stream_voice.announcing(lock) and not v.say("Next stop, Pine Tree!")
    assert not stream_voice.announcing(lock, now=time.time() + stream_voice.ANNOUNCE_STALE_S + 1)
    lock.unlink()
    assert v.say("Next stop, Pine Tree!")
    _wait_idle(v)
    assert len(log) == 2
