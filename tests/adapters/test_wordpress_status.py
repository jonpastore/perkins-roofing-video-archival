"""WP status normalisation — our Article.status vocabulary is not WordPress's."""
import pytest

from adapters.wordpress import _wp_status


@pytest.mark.parametrize(("ours", "wp"), [
    ("published", "publish"),   # the exact 400 jobs/reprocess_articles.py used to hit
    ("scheduled", "future"),
    ("draft", "draft"),
    ("publish", "publish"),     # already-valid WP values pass through unchanged
    ("future", "future"),
    ("pending", "pending"),
    ("private", "private"),
])
def test_maps_our_vocabulary_onto_wordpress(ours, wp):
    assert _wp_status(ours) == wp


def test_none_and_empty_default_to_draft():
    assert _wp_status(None) == "draft"
    assert _wp_status("") == "draft"


def test_unknown_status_raises_rather_than_shipping_a_400():
    with pytest.raises(ValueError, match="not a WordPress post status"):
        _wp_status("archived")
