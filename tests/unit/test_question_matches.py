"""A Yes/No question read through its font's noise (act/inventory
.question_matches). MEASURED 2026-10-06 04:31: "Transform Commander Bee?" was
read 'transforneceommander' and the jelly was answered No."""
from hivemind.act.inventory import question_matches


def test_the_measured_noisy_read_is_the_commanders_question():
    assert question_matches("transforneceommander", "transform commander bee", "Commander Bee")
    assert question_matches("transform commander bee", "transform commander bee", "Commander Bee")


def test_another_bee_a_gifted_one_or_a_longer_question_is_not():
    want, bee = "transform commander bee", "Commander Bee"
    for read in ("transform diamond bee", "transform tabby bee", "transform bear bee",
                 "transform gifted commander bee", "transform commander bee auto jelly",
                 "", "hatch basic egg"):
        assert not question_matches(read, want, bee), read
