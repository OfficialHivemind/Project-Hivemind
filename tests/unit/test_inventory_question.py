"""act/inventory.dialog_question with the Auto-Jelly notice as the box's second line."""
from hivemind.act import inventory as inv


def _ocr(frame, box):
    return '" huie-Jelly ON' if box == inv.DIALOG_TITLE else "Transform Rascal Bee?"


def test_the_question_line_is_read_and_the_notice_kept():
    q = inv.dialog_question(None, _ocr)
    assert q.startswith("transform rascal bee") and "auto" in q


def test_no_yes_while_auto_jelly_is_on():
    q = inv.dialog_question(None, _ocr)
    assert not inv.question_matches(q, "transform rascal bee", "Rascal Bee")


def test_a_one_line_question_reads_the_whole_title():
    def ocr(frame, box):
        assert box == inv.DIALOG_TITLE, "the top line is read only for the notice"
        return "Transform Rascal Bee?"
    q = inv.dialog_question(None, ocr)
    assert q == "transform rascal bee" and inv.question_matches(q, "transform rascal bee", "Rascal Bee")


def test_the_notice_as_the_live_ocr_gave_it():
    ocr = lambda f, box: "huiejelly son" if box == inv.DIALOG_TITLE else "Transform Rascal Bee?"
    q = inv.dialog_question(None, ocr)
    assert q == "transform rascal bee autojelly on"
    assert not inv.question_matches(q, "transform rascal bee", "Rascal Bee")


def test_use_jelly_beans_is_a_plain_question_not_the_auto_jelly_notice():
    """2026-10-13: 'Use Jelly Beans?' was cut to its top line + ' autojelly on'."""
    from hivemind.act import inventory as inv
    ocr = lambda f, box: "Use Jelly Beans?" if box == inv.DIALOG_TITLE else "lo loll daanced"  # noqa: E731
    assert inv.dialog_question(object(), ocr) == "use jelly beans"


def test_an_empty_whole_read_falls_back_to_the_lines_and_keeps_the_notice():
    """audit 2026-10-13 #4: a two-line box read whole as '' (46 jelly rolls refused)."""
    from hivemind.act import inventory as inv
    def ocr_of(whole, top, bottom):
        return lambda f, box: {inv.DIALOG_TITLE: whole, inv.DIALOG_TITLE_TOP: top,
                               inv.DIALOG_TITLE_BOTTOM: bottom}[box]
    assert inv.dialog_question(0, ocr_of("", "Transform Basic Bee?", "(Auto-Jelly is ON)")) \
        == "transform basic bee autojelly on"
    assert inv.dialog_question(0, ocr_of("", 'Add "Purple Point Sticker" to the', "Sticker Stack?")) \
        == "add purple point sticker to the sticker stack"
