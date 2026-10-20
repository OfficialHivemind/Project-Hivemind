"""A honey-fall card offers "I rolled Royal Jelly" (the owner's usual spend), and
that answer marks no gear owned (brain/owned)."""
from hivemind.brain import owned


def test_jelly_answer_owns_nothing():
    assert owned.card_key("drop:123", owned.SPENT_ON_JELLY) is None
    assert owned.card_key("drop:123", owned.NONE_OF_THESE) is None


def test_the_option_is_on_the_card():
    src = open(owned.__file__).read()
    assert "Option(label=SPENT_ON_JELLY" in src
