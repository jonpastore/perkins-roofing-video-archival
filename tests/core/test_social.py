"""Tests for core/social.py — 100% coverage of the pure module."""
from core.social import SocialPublisher, already_posted, build_caption

# ---------------------------------------------------------------------------
# already_posted
# ---------------------------------------------------------------------------

class _Post:
    def __init__(self, platform, external_id):
        self.platform = platform
        self.external_id = external_id


def test_already_posted_true_when_external_id_present():
    posts = [_Post("instagram", "ig_abc123")]
    assert already_posted(posts, "instagram") is True


def test_already_posted_false_when_external_id_none():
    posts = [_Post("instagram", None)]
    assert already_posted(posts, "instagram") is False


def test_already_posted_false_when_external_id_empty_string():
    posts = [_Post("instagram", "")]
    assert already_posted(posts, "instagram") is False


def test_already_posted_false_when_wrong_platform():
    posts = [_Post("tiktok", "tt_xyz")]
    assert already_posted(posts, "instagram") is False


def test_already_posted_false_when_empty_list():
    assert already_posted([], "instagram") is False


def test_already_posted_true_for_tiktok():
    posts = [_Post("instagram", None), _Post("tiktok", "tt_123")]
    assert already_posted(posts, "tiktok") is True


def test_already_posted_dict_with_external_id():
    posts = [{"platform": "instagram", "external_id": "ig_999"}]
    assert already_posted(posts, "instagram") is True


def test_already_posted_dict_without_external_id():
    posts = [{"platform": "instagram", "external_id": None}]
    assert already_posted(posts, "instagram") is False


def test_already_posted_multiple_platforms_checks_correct_one():
    posts = [
        _Post("instagram", "ig_1"),
        _Post("tiktok", None),
    ]
    assert already_posted(posts, "instagram") is True
    assert already_posted(posts, "tiktok") is False


def test_already_posted_first_match_wins():
    # Two rows for same platform — True as long as at least one has external_id
    posts = [_Post("instagram", None), _Post("instagram", "ig_second")]
    assert already_posted(posts, "instagram") is True


# ---------------------------------------------------------------------------
# build_caption
# ---------------------------------------------------------------------------

def test_build_caption_combines_title_and_tags():
    result = build_caption("Roof Repair Tips", ["roofing", "DIY"])
    assert result == "Roof Repair Tips\n\n#roofing #DIY"


def test_build_caption_tags_without_hash_get_hash_prepended():
    result = build_caption("Title", ["tag1", "tag2"])
    assert "#tag1" in result
    assert "#tag2" in result


def test_build_caption_tags_already_with_hash_not_doubled():
    result = build_caption("Title", ["#existing"])
    assert "##existing" not in result
    assert "#existing" in result


def test_build_caption_empty_tags_returns_title_only():
    result = build_caption("Just a title", [])
    assert result == "Just a title"


def test_build_caption_truncates_at_2200_chars():
    long_title = "A" * 2000
    long_tag = "B" * 300
    result = build_caption(long_title, [long_tag])
    assert len(result) == 2200


def test_build_caption_exactly_2200_chars_not_truncated():
    # title of 2200 chars with no tags — should stay exactly 2200
    title = "X" * 2200
    result = build_caption(title, [])
    assert len(result) == 2200


def test_build_caption_short_stays_intact():
    result = build_caption("Short", ["a", "b", "c"])
    assert len(result) < 2200
    assert result == "Short\n\n#a #b #c"


def test_build_caption_mixed_hash_and_no_hash_tags():
    result = build_caption("Title", ["#already", "nohash"])
    assert "#already" in result
    assert "#nohash" in result
    assert "##already" not in result


# ---------------------------------------------------------------------------
# SocialPublisher Protocol structural check
# ---------------------------------------------------------------------------

def test_social_publisher_is_protocol():
    """SocialPublisher is a runtime-checkable Protocol."""
    class FakePublisher:
        def publish(self, *, video_url, caption, idempotency_key):
            return "fake_id"

    assert isinstance(FakePublisher(), SocialPublisher)


def test_non_publisher_not_instance():
    class NotAPublisher:
        pass

    assert not isinstance(NotAPublisher(), SocialPublisher)
