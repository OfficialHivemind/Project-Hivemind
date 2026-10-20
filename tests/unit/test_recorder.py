import numpy as np
from hivemind.telemetry.recorder import Recorder, load


def test_round_trip_is_lossless(tmp_path):
    """HSV bands get sampled from these recordings, so the pixels that come back
    must be bit-identical to the pixels that went in."""
    rng = np.random.default_rng(0)
    frames = [rng.integers(0, 255, (60, 80, 3), dtype=np.uint8) for _ in range(4)]
    with Recorder(tmp_path / "rec", note="test") as r:
        for i, f in enumerate(frames):
            r.add(f, label=f"f{i}", extra_field=i * 2)

    back = list(load(tmp_path / "rec"))
    assert len(back) == 4
    for original, (img, entry) in zip(frames, back):
        assert np.array_equal(original, img), "recording was not lossless"
    assert back[2][1]["label"] == "f2"
    assert back[2][1]["extra_field"] == 4


def test_manifest_records_timing(tmp_path):
    with Recorder(tmp_path / "rec2") as r:
        r.add(np.zeros((10, 10, 3), np.uint8))
        r.add(np.zeros((10, 10, 3), np.uint8))
    import json
    m = json.loads((tmp_path / "rec2" / "manifest.json").read_text())
    assert m["frames"] == 2
    assert m["index"][1]["t"] >= m["index"][0]["t"]
