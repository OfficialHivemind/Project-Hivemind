"""The Decision Inbox shows ONE card, the most important, with "+N more"
(the owner's 5th Windows run: seven stacked cards squeezed to blank)."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from hivemind.gui.panels.question import DecisionInbox  # noqa: E402
from hivemind.telemetry.events import Option, Question  # noqa: E402

APP = QApplication.instance() or QApplication([])


def q(qid, expires=0.0):
    return Question(id=qid, question=f"{qid}?", options=[Option("Yes", 1.0)],
                    default="Yes", expires_at=expires)


def visible(inbox):
    return [qid for qid, c in inbox._cards.items() if not c.isHidden()]


def test_one_card_at_a_time_the_most_important_first():
    inbox = DecisionInbox()
    for qid in ("a", "b", "c"):
        inbox.add(q(qid))
    assert visible(inbox) == ["c"] and inbox._more.text().startswith("+2 more")
    inbox.add(q("soon", expires=10 ** 10))       # one that lapses goes first
    assert visible(inbox) == ["soon"] and inbox.pending == 4
    inbox._next()
    assert visible(inbox) == ["c"]
    inbox.remove("c")
    assert len(visible(inbox)) == 1 and inbox._more.text().startswith("+2 more")
    for qid in ("soon", "b", "a"):
        inbox.remove(qid)
    assert inbox.isHidden() and inbox.shown is None


def test_a_single_card_has_no_more_button():
    inbox = DecisionInbox()
    inbox.add(q("only"))
    assert visible(inbox) == ["only"] and inbox._more.isHidden()


def test_a_lapsed_question_stops_offering_its_buttons():
    # UI review 2026-10-21: a timed-out card stayed pinned with live buttons
    import time
    from hivemind.gui.panels.question import QuestionCard
    card = QuestionCard(q("lapsed", expires=time.time() + 3600))
    card.question.expires_at = time.time() - 1
    card._tick()
    assert card._buttons and not any(b.isEnabled() for b in card._buttons)
    assert "Time's up" in card._countdown.text()


def test_a_card_is_one_line_until_opened_and_says_it_in_plain_words():
    # UI panel 2026-10-21 item 4: the card took ~140 px above every tab
    import time
    from hivemind.gui.panels.question import QuestionCard, countdown_text, plain_score
    card = QuestionCard(Question(id="rj", question="Roll Royal Jelly?", default="Roll it",
                                 options=[Option("Roll it", 1.05, unit="x"),
                                          Option("Keep", 1.0, unit="x")],
                                 expires_at=time.time() + 58 * 60 + 30))
    assert card.body.isHidden() and not card._line.isHidden()
    assert card._countdown.text() == "Hivemind picks “Roll it” in 58 min"
    card.toggle.click()
    assert not card.body.isHidden() and card._line.isHidden()
    assert card._buttons[0].text() == "Roll it   (about 5% better)"
    assert plain_score(1.0, "x") == "no change" and plain_score(0.9, "x") == "about 10% worse"
    assert plain_score(431_000, "honey/hr") == "431,000 honey/hr"
    assert countdown_text(30, "Keep") == "Hivemind picks “Keep” in under a minute"
