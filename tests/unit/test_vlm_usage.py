"""ROADMAP S12: what the vision model is asked for, by whom, how often."""
import json
import time

from hivemind.brain import vlm


def _asker(model):
    return model.ask(b"not-a-png", "what?", context=None)


def test_each_question_is_logged_by_its_caller_and_summed(tmp_path):
    model = vlm.VisionModel(cache_dir=tmp_path, enabled=False)
    model._write_cache(model._key(b"not-a-png", "what?"), "a bee")
    assert _asker(model).cached
    assert _asker(model).cached
    row = json.loads((tmp_path / vlm.USAGE_FILE).read_text().splitlines()[0])
    assert row["by"] == "test_vlm_usage._asker" and row["cached"] is True
    # an old line and a torn last line are left out
    with open(tmp_path / vlm.USAGE_FILE, "a") as f:
        f.write(json.dumps({"at": time.time() - 30 * 86400, "by": "old.f",
                            "s": 9, "cached": False}) + "\n")
        f.write('{"at": 1')
    said = vlm.usage(tmp_path)
    assert "test_vlm_usage._asker 2 (2 cached, 0 s)" in said
    assert "old.f" not in said


def test_no_file_says_none(tmp_path):
    assert "no questions" in vlm.usage(tmp_path)
