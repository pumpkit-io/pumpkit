from pumpkit.billing.allowance import COUNT_NOUNS
from pumpkit.billing.models import ALLOWANCE_COUNTS


def test_every_allowance_count_has_a_noun_for_the_user():
    assert set(COUNT_NOUNS) == set(ALLOWANCE_COUNTS)
