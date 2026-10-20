"""AI-N9: vision/fingerprint -- the same title pixels are read by OCR once."""
import numpy as np

from hivemind.vision import fingerprint


def _reader(answers):
    calls = []

    def ocr(frame, box):
        calls.append(box)
        return answers.pop(0) if answers else ""
    return ocr, calls


def test_same_pixels_read_once_and_a_change_reads_again():
    page = np.zeros((40, 100, 3), np.uint8)
    page[5:15, 10:60] = 200
    ocr, calls = _reader(["royal jelly", "red extract"])
    table = fingerprint.Table(ocr)
    box = (0, 0, 80, 20)
    assert table(page, box) == "royal jelly"
    assert table(page.copy(), box) == "royal jelly"       # same bytes: no OCR
    assert len(calls) == 1
    other = page.copy()
    other[10, 30] = 199                                   # ONE pixel: a miss
    assert table(other, box) == "red extract"
    assert len(calls) == 2
    assert table.stats() == {"hits": 1, "misses": 2, "kept": 2}


def test_empty_read_is_never_kept_and_no_crop_has_no_key():
    page = np.full((20, 20, 3), 7, np.uint8)
    ocr, _calls = _reader(["", "glitter"])
    table = fingerprint.Table(ocr)
    assert table(page, (0, 0, 20, 20)) == ""
    assert table(page, (0, 0, 20, 20)) == "glitter"       # retried, not remembered
    assert fingerprint.key(page, (0, 0, 0, 0)) is None
    assert fingerprint.key(None, (0, 0, 5, 5)) is None


def test_oldest_dropped_and_one_table_per_reader():
    ocr, _calls = _reader([str(i) for i in range(10)])
    table = fingerprint.Table(ocr, most=2)
    for v in range(3):
        table(np.full((4, 4, 3), v, np.uint8), (0, 0, 4, 4))
    assert len(table.seen) == 2
    assert fingerprint.cached(ocr) is fingerprint.cached(ocr)


def test_inventory_wraps_its_default_reader():
    import inspect
    from hivemind.act import inventory
    assert inspect.getsource(inventory).count("fingerprint.cached(shoplook._ocr_line)") == 3
