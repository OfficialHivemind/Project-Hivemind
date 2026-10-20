"""The local vision model client.

The behaviour that matters most is what happens when the model is NOT there.
A plausible sentence about a screen nobody looked at is worse than no answer,
so every failure path has to return None and say why — and the cache has to be
exact, because turning a nondeterministic model into a lookup table is the
property that makes it safe to depend on.

Tested against a stub HTTP server rather than a real model: these are the
client's guarantees, and they have to hold whether or not ollama is installed.
"""
import http.server
import json
import threading

import pytest

from hivemind.brain.vlm import Answer, VisionModel

PNG = b"\x89PNG\r\n\x1a\n" + b"fake image bytes"
OTHER_PNG = b"\x89PNG\r\n\x1a\n" + b"a different screen"


class Stub(http.server.BaseHTTPRequestHandler):
    """Stands in for ollama. Behaviour is set on the class per test."""
    models = [{"name": "qwen2.5vl:7b"}]
    reply = "a dialog that says Join Error"
    calls = 0

    def log_message(self, *_):
        pass

    def _send(self, payload, code=200):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send({"models": type(self).models})

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        self.rfile.read(length)
        type(self).calls += 1
        self._send({"response": type(self).reply})


@pytest.fixture
def server():
    Stub.models = [{"name": "qwen2.5vl:7b"}]
    Stub.reply = "a dialog that says Join Error"
    Stub.calls = 0
    httpd = http.server.HTTPServer(("127.0.0.1", 0), Stub)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


@pytest.fixture(autouse=True)
def _ample_memory(monkeypatch):
    # THE CLIENT'S GUARANTEES, NOT THIS MACHINE'S MEMORY: `ask` first asks
    # `room_to_load`, which reads /proc/meminfo, so with a game open beside
    # the run (2026-10-03, 2.8 GB free) ten of these failed for a reason that
    # was not theirs. The memory rule has its own test below.
    from hivemind.brain import vlm
    from hivemind.platform.memory import Memory
    monkeypatch.setattr(vlm.memory, "read", lambda *a, **k: Memory(
        available_gb=24.0, total_gb=30.0, swap_used_gb=0.0, swap_total_gb=4.0))


@pytest.fixture
def model(server, tmp_path):
    return VisionModel(host=server, cache_dir=tmp_path, timeout=5.0)


def test_a_dropped_model_is_not_loaded_into_a_machine_without_room(server, tmp_path,
                                                                     monkeypatch):
    from hivemind.brain import vlm
    from hivemind.platform.memory import Memory
    tight = Memory(available_gb=2.8, total_gb=30.0, swap_used_gb=4.0, swap_total_gb=4.0)
    monkeypatch.setattr(vlm.memory, "read", lambda *a, **k: tight)
    local = VisionModel(host=server, cache_dir=tmp_path, timeout=5.0)
    monkeypatch.setattr(local, "resident_bytes", lambda: 0)
    assert not local.room_to_load() and "GB free" in local.reason
    assert local.ask(PNG, "what is this?") is None and Stub.calls == 0
    monkeypatch.setattr(local, "resident_bytes", lambda: 5 * 2 ** 30)   # loaded already
    assert local.room_to_load()


# ---- it answers ------------------------------------------------------------

def test_it_answers_a_question_about_an_image(model):
    answer = model.ask(PNG, "what is this?")
    assert isinstance(answer, Answer)
    assert answer.text == "a dialog that says Join Error"
    assert not answer.cached


def test_it_reports_available_when_the_model_is_pulled(model):
    assert model.available()
    assert model.reason == ""


# ---- it never invents ------------------------------------------------------

def test_no_server_means_no_answer_and_a_reason(tmp_path):
    offline = VisionModel(host="http://127.0.0.1:1", cache_dir=tmp_path,
                          timeout=1.0)
    assert offline.ask(PNG, "what is this?") is None
    assert not offline.available()
    assert "ollama" in offline.reason, offline.reason


def test_a_missing_model_is_named_with_the_command_to_fix_it(model):
    Stub.models = [{"name": "llama3:8b"}]
    assert not model.available()
    assert "ollama pull" in model.reason
    assert model.ask(PNG, "what is this?") is None


def test_an_empty_reply_is_not_an_answer(model):
    Stub.reply = "   "
    assert model.ask(PNG, "what is this?") is None
    assert "empty" in model.reason


def test_being_turned_off_is_reported_as_such(tmp_path):
    off = VisionModel(cache_dir=tmp_path, enabled=False)
    assert not off.available()
    assert "settings" in off.reason
    assert off.ask(PNG, "what is this?") is None


# ---- the cache is what makes it dependable ---------------------------------

def test_the_same_screen_and_question_is_answered_from_cache(model):
    first = model.ask(PNG, "what is this?")
    second = model.ask(PNG, "what is this?")
    assert first.text == second.text
    assert not first.cached and second.cached
    assert Stub.calls == 1, "asked the model twice for the same thing"


def test_a_different_screen_is_a_different_question(model):
    model.ask(PNG, "what is this?")
    model.ask(OTHER_PNG, "what is this?")
    assert Stub.calls == 2


def test_a_different_question_is_not_served_from_cache(model):
    model.ask(PNG, "what is this?")
    model.ask(PNG, "how many buttons?")
    assert Stub.calls == 2


def test_a_different_model_invalidates_the_cache(server, tmp_path):
    first = VisionModel(host=server, cache_dir=tmp_path, model="qwen2.5vl:7b")
    first.ask(PNG, "what is this?")
    Stub.models = [{"name": "other"}]
    second = VisionModel(host=server, cache_dir=tmp_path, model="other:7b")
    second.ask(PNG, "what is this?")
    assert Stub.calls == 2, "served one model's answer for another"


def test_the_cache_survives_a_new_client(server, tmp_path):
    VisionModel(host=server, cache_dir=tmp_path).ask(PNG, "what is this?")
    fresh = VisionModel(host=server, cache_dir=tmp_path)
    answer = fresh.ask(PNG, "what is this?")
    assert answer is not None and answer.cached
    assert Stub.calls == 1


def test_a_cached_answer_is_returned_even_with_the_server_down(server, tmp_path):
    """The point of the cache: a screen seen before needs no model at all."""
    VisionModel(host=server, cache_dir=tmp_path).ask(PNG, "what is this?")
    offline = VisionModel(host="http://127.0.0.1:1", cache_dir=tmp_path,
                          timeout=1.0)
    answer = offline.ask(PNG, "what is this?")
    assert answer is not None and answer.cached


def test_an_unwritable_cache_is_not_an_error(server, tmp_path):
    blocked = tmp_path / "file"
    blocked.write_text("not a directory")
    model = VisionModel(host=server, cache_dir=blocked / "under")
    assert model.ask(PNG, "what is this?") is not None


def test_stats_report_how_much_was_free(model):
    assert "not used yet" in model.stats()
    model.ask(PNG, "what is this?")
    model.ask(PNG, "what is this?")
    assert "50% free" in model.stats()


def test_a_real_answer_is_kept_with_its_picture_only_when_the_folder_exists(tmp_path, monkeypatch):
    from hivemind.brain import vlm
    model = vlm.VisionModel(cache_dir=tmp_path / "cache")
    monkeypatch.setattr(vlm, "SAMPLES_DIR", tmp_path / "samples")
    model._keep_sample("abc", b"\x89PNG", "which field?", "Pine Tree")
    assert not (tmp_path / "samples").exists()            # opt-in: no folder, nothing kept
    (tmp_path / "samples").mkdir()
    model._keep_sample("abc", b"\x89PNG", "which field?", "Pine Tree")
    import json
    kept = json.loads((tmp_path / "samples" / "abc.json").read_text())
    assert (tmp_path / "samples" / "abc.png").read_bytes() == b"\x89PNG"
    assert kept["question"] == "which field?" and kept["answer"] == "Pine Tree"
