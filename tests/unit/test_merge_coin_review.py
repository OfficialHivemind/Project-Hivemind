"""scripts/merge_coin_review.py: a review's answers become coin labels."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location("merge_coin_review",
                                                  ROOT / "scripts/merge_coin_review.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_answers_become_coins_and_hard_negatives_and_nothing_twice(tmp_path):
    m = _load()
    review = {"frames": [
        {"path": "var/incidents/x/045.jpg", "window": "x",
         "candidates": [{"id": 0, "box": [1, 2, 3, 4], "p": 0.99},
                        {"id": 1, "box": [5, 6, 7, 8], "p": 0.4},
                        {"id": 2, "box": [9, 9, 9, 9], "p": 0.1}],
         "answers": {"0": "coin:honey", "1": "no", "2": "skip"}},
        {"path": "var/incidents/x/100.jpg", "window": "x",
         "candidates": [{"id": 0, "box": [1, 1, 2, 2], "p": 0.9}], "answers": {}}]}
    (tmp_path / "review.json").write_text(json.dumps(review))
    labels = tmp_path / "labels.json"
    labels.write_text(json.dumps({"note": "", "frames": []}))
    argv = [str(tmp_path / "review.json"), "--field", "pine_tree", "--labels", str(labels)]
    assert m.main(argv) == 0
    rows = json.loads(labels.read_text())["frames"]
    assert len(rows) == 1 and rows[0]["partial"] and rows[0]["field"] == "pine_tree"
    assert rows[0]["coins"] == [{"box": [1, 2, 3, 4], "kind": "honey", "sure": True, "from": "review"}]
    assert rows[0]["not_coins"] == [{"box": [5, 6, 7, 8], "from": "review"}]
    assert m.main(argv) == 0                                   # merged again: nothing new
    assert len(json.loads(labels.read_text())["frames"]) == 1
