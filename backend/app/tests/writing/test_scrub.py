"""The deterministic clean-up between the draft and the rewrite.

Every case is one character and the one string it must become, plus the
negatives: text a person typed must come out exactly as it went in.
"""

import pytest

from app.writing import slop
from app.writing.scrub import scrub

# Em and en dashes


def test_a_spaced_em_dash_becomes_a_hyphen():
    assert scrub("the tool came later — after the questions") == (
        "the tool came later - after the questions"
    )


def test_an_unspaced_em_dash_between_words_gets_spaces():
    assert scrub("the tool came later—after the questions") == (
        "the tool came later - after the questions"
    )


def test_an_em_dash_spaced_on_one_side_only_gets_the_missing_space():
    assert scrub("later— after") == "later - after"
    assert scrub("later —after") == "later - after"


def test_every_em_dash_in_a_post_is_replaced():
    assert scrub("one—two — three—four") == "one - two - three - four"


def test_an_em_dash_at_the_end_of_a_line_gets_no_trailing_space():
    assert scrub("wait—\nthen") == "wait -\nthen"


def test_an_em_dash_next_to_numbers_is_spaced_too():
    assert scrub("4—5 days") == "4 - 5 days"


def test_an_en_dash_becomes_a_hyphen_with_its_spacing_untouched():
    assert scrub("later – after") == "later - after"
    assert scrub("4–5 days") == "4-5 days"
    assert scrub("one–two — three—four") == "one-two - three - four"


# Quotes and apostrophes


def test_a_curly_apostrophe_becomes_a_straight_one():
    assert scrub("it’s what didn’t ship") == "it's what didn't ship"


def test_curly_single_quotes_become_straight_ones():
    assert scrub("he called it ‘done’") == "he called it 'done'"


def test_curly_double_quotes_become_straight_ones():
    assert scrub("the “secret sauce”") == 'the "secret sauce"'


def test_mixed_straight_and_curly_quotes_end_up_all_straight():
    assert scrub('"one" and “two”') == '"one" and "two"'


# Ellipsis, arrows, bullets, multiplication sign


def test_the_ellipsis_character_becomes_three_dots():
    assert scrub("and then…") == "and then..."


def test_right_arrows_become_a_typed_arrow():
    assert scrub("Step 1 → Step 2") == "Step 1 -> Step 2"
    assert scrub("idea ⇒ product") == "idea -> product"


def test_a_left_arrow_becomes_a_typed_arrow():
    assert scrub("Step 2 ← Step 1") == "Step 2 <- Step 1"


def test_up_and_down_arrows_are_left_alone():
    # No typed equivalent anyone uses; the slop check is where they would be judged.
    assert scrub("revenue ↑ churn ↓") == "revenue ↑ churn ↓"


def test_a_typed_bullet_becomes_a_hyphen():
    assert scrub("• ship\n• learn") == "- ship\n- learn"


def test_the_multiplication_sign_becomes_an_x():
    assert scrub("3× growth, 10×") == "3x growth, 10x"


# Invisible characters


def test_a_non_breaking_space_becomes_an_ordinary_space():
    # Not deleted: it sits between two words, and deleting it joins them.
    assert scrub("10 km") == "10 km"


@pytest.mark.parametrize("char", ["​", "‌", "‍", "﻿"])
def test_zero_width_characters_are_removed(char):
    assert scrub(f"{char}ship{char} it{char}") == "ship it"


# What must not change


@pytest.mark.parametrize(
    "text",
    [
        "",
        "shipped it in 4-5 days, no team, no funding",
        "it's what we didn't build that mattered",
        'he said "ship it" and left',
        "and then... nothing",
        "a -> b, c <- d",
        "- one\n- two",
        "3x growth - which nobody expected",
        "naïve café, 50€, 🚀",
    ],
)
def test_text_a_person_typed_comes_through_unchanged(text):
    assert scrub(text) == text


def test_scrubbing_twice_changes_nothing_more():
    once = scrub("one—two–x “three” … → • 3×  ​")
    assert scrub(once) == once


def test_the_scrubbed_text_trips_none_of_the_character_tells():
    names = dict(slop.find(scrub("it’s later—after the “questions”…")))
    assert "em_dash" not in names
    assert "curly_quote" not in names
