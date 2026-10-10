import json
from pathlib import Path

import pytest

from app.publishing.x_length import x_weighted_length

# Shared with frontend/src/lib/xLength.test.ts; the lengths come from twitter-text 3.1.0.
CASES = json.loads((Path(__file__).parent / "x_weighted_length_cases.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=[case["note"] for case in CASES])
def test_a_text_counts_the_way_x_counts_it(case):
    assert x_weighted_length(case["text"]) == case["length"]


def test_a_long_run_of_dotted_labels_is_counted_without_stalling():
    assert x_weighted_length("a." * 12_500) == 25_000
