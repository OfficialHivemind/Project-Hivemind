"""vision/fieldsense: a look gives no "N% right" from a trust table measured
for a different set of places.

MEASURED 2026-10-21 22:54:54 (var/night/run-1172.log:150): the walk-end frame
of a walk to Pepper said "looks like strawberry (86% of looks like this were
right on unseen nights)": the live classifier knew 22 places, the table in
data/models/fieldsense.json was the 2026-09-26 one for 11. The fixture is
that frame (var/routes/attempt-1172/225453-natro_out_pepper-56-walk-d6.jpg)
at the classifier's own 480x270."""
from pathlib import Path

import cv2
import numpy as np

import hivemind
from hivemind.vision import fieldsense as fs

ROOT = Path(hivemind.__file__).resolve().parents[2]
FRAME = ROOT / "tests" / "fixtures" / "fieldsense" / "pepper-walk-end-1172.jpg"


def sense_with(classes_measured):
    sense = fs.FieldSense(model=fs.MODEL, notes=None, live_dir=None)
    idx = sense.gallery.rows(per_class=20)
    labels = [sense.gallery.labels[i] for i in idx]
    sense.classifier = fs.Classifier.train(fs.unquantise(sense.gallery.codes[idx]), labels)
    taught = sorted(set(labels))
    sense.notes = {"classes": classes_measured(taught)}
    sense.trust = fs.Trust({c: [[None, None, 0.86, 100]] for c in taught})
    return sense


def test_the_pepper_frame_gets_no_number_from_another_classifiers_table():
    frame = cv2.imread(str(FRAME))
    assert frame is not None and frame.shape[:2] == (fs.H, fs.W)
    sense = sense_with(lambda taught: taught[:-1])    # one place learned since
    assert not sense.measured()
    look = sense.look(frame)
    assert look.field is not None and look.sure is None
    assert "were right" not in look.describe()
    assert not look.names(look.field, 0.0) and not look.doubts("pepper", 0.0)


def test_a_measured_classifier_still_reads_its_table():
    sense = sense_with(lambda taught: taught)
    assert sense.measured()
    look = sense.look(cv2.imread(str(FRAME)))
    assert look.sure == 0.86 and "86% of looks like this were right" in look.describe()
    # a walk end is not a gathering frame: no number there (run_farm walk-end lines)
    assert "were right" not in look.describe(trust=False)
    assert "%" not in look.describe(trust=False).split(";")[0]
    assert np.isfinite(look.margin)


def test_the_shipped_model_is_measured_out_of_the_box():
    # the classes the trainer measured (fieldsense.json) are the classes the
    # shipped gallery (fieldsense.npz) teaches, which is what makes
    # `measured()` true before any live learning
    sense = fs.FieldSense(live_dir=None)
    assert sorted(set(sense.gallery.labels)) == sense.notes["classes"]


def test_run_farm_walk_end_lines_give_no_trust_number():
    src = (ROOT / "scripts" / "run_farm.py").read_text(encoding="utf-8")
    assert src.count("the end of the walk to {pretty}: {look.describe(trust=False)}") == 3
    assert "the end of the walk to {pretty}: {look.describe()}" not in src
