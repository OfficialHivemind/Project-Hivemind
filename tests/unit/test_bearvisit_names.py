"""A giver's prompt named whole, or run together when a read split its words
(act/bearvisit.names_giver). MEASURED 2026-10-06 02:43 at the Mother Bear:
the floating numbers over the prompt read it as 'ta lkitê m other bear'."""
from hivemind.act.bearvisit import names_giver


def test_a_prompt_whose_words_were_split_still_names_the_giver():
    assert names_giver("mother_bear", "Talk to Mother Bear")
    assert names_giver("mother_bear", "ta lkitê m other bear")
    assert not names_giver("mother_bear", "ta k t cï m o fr mer bear")


def test_a_dispenser_still_names_no_bee():
    assert not names_giver("honey_bee", "Use the Honey Dispenser")
    assert names_giver("honey_bee", "Talk to Honey Bee")
    assert not names_giver("brown_bear", "Talk to Black Bear")
