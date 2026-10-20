"""2 Nov, All-Whitey Then: 'Collect 10,000,000 White Pollen from the Cactus
Field. 497,038/10,000,000' was swallowed by the finished 600M white step."""
from hivemind.brain import questneeds


def test_a_colour_word_does_not_hide_the_field():
    needs = questneeds.from_lines([
        "Collect 600,000,000 White Pollen. Complete!",
        "Collect 10,000,000 White Pollen from the Cactus Field. 497,038/10,000,000",
    ])
    cactus = needs.fields["cactus"]
    assert cactus.target == 10_000_000 and cactus.remaining == 10_000_000 - 497_038
    assert needs.pollen["white"].target == 600_000_000      # the plain step is unchanged


def test_plain_field_lines_still_read():
    needs = questneeds.from_lines(["Collect 25,000,000 Pollen from the Rose Field. Complete!"])
    assert needs.fields["rose"].remaining == 0
