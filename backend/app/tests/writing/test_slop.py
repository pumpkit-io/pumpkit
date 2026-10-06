"""The machine-written tell detector.

Two things matter here and they pull against each other: the patterns have to
fire on the real output that motivated them, and they have to stay quiet on
ordinary writing. A detector that flags everything gets ignored within a week,
which is worse than not having one.

The positive cases below are taken verbatim from replies this pipeline
produced. The negative cases are from the user's own writing samples, which are
the definition of what must not be flagged.
"""

from app.writing import slop

# The tells, on text that really had them


def test_it_catches_the_correction_pivot_in_its_plain_form():
    assert "correction_pivot" in dict(slop.find("it's not the code, it's the audience"))


def test_it_catches_the_correction_pivot_in_disguise():
    # The disguise is the whole problem: "it's not X, it's Y" was already
    # banned in the prompt, and this is what came out instead.
    disguises = [
        "the interesting part isn't that he built the MVP in 4-5 days",
        "the 4-5 day MVP isn't even the most interesting part",
    ]
    for text in disguises:
        assert "correction_pivot" in dict(slop.find(text)), text


def test_it_catches_the_invented_recurring_opinion():
    assert "invented_stance" in dict(
        slop.find("this is why i keep saying personal brand matters more")
    )


def test_it_catches_startup_commentary_cliches():
    assert "startup_cliche" in dict(slop.find("the unfair advantage was distribution"))


def test_it_catches_the_balanced_list_of_three():
    assert "list_of_three" in dict(
        slop.find("he had demand, a working process and a way to reach people")
    )


def test_it_catches_an_em_dash_and_a_curly_quote():
    assert "em_dash" in dict(slop.find("the tool came later — after the questions"))
    assert "curly_quote" in dict(slop.find("he called it the “secret sauce”"))


def test_it_catches_the_announced_lesson():
    assert "named_lesson" in dict(slop.find("the real lesson here is consistency"))


# Quiet on writing that is fine


def test_it_stays_quiet_on_the_users_own_voice():
    # Straight from writing_samples.py. If the detector fires on the samples,
    # it is measuring the wrong thing.
    samples = [
        "gotcha, yeah non-tech and juniors are screwed. to be really good at "
        "systems design, a solid coding foundation is required.",
        "this was true in 2024. ai is able to build scalable and reliable "
        "software architectures under good guidance.",
        "makes total sense\n\nbest of luck with the new project!",
    ]
    for text in samples:
        assert slop.find(text) == [], text


def test_two_items_are_not_a_triple():
    # The fix for a triple is to cut it to two, so two must not fire.
    assert slop.find("he had demand and a working process") == []


def test_a_plain_question_is_not_a_tell():
    assert slop.find("how much of the 1334/mo came from people who already followed Daniel?") == []
