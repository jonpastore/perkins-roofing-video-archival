from core.enumerate import is_short, to_video_rows


def test_is_short_by_url():
    assert is_short(600, "https://www.youtube.com/shorts/abc") is True


def test_is_short_by_duration():
    assert is_short(45) is True
    assert is_short(60) is True


def test_not_short_when_long():
    assert is_short(600, "https://youtu.be/x") is False


def test_not_short_when_duration_unknown():
    assert is_short(None) is False


def test_to_video_rows_maps_and_classifies():
    rows = to_video_rows([
        {"id": "v1", "title": "Long one", "duration": 600, "url": "https://youtu.be/v1"},
        {"id": "v2", "title": "Short one", "duration": 30, "url": "https://www.youtube.com/shorts/v2"},
    ])
    assert rows[0] == {"id": "v1", "title": "Long one", "duration": 600,
                       "url": "https://youtu.be/v1", "is_short": False}
    assert rows[1]["is_short"] is True


def test_to_video_rows_skips_entries_without_id():
    rows = to_video_rows([{"title": "no id"}, {"id": "v3", "duration": 10}])
    assert len(rows) == 1
    assert rows[0]["id"] == "v3"


def test_to_video_rows_defaults_missing_url():
    rows = to_video_rows([{"id": "v4", "duration": 100}])
    assert rows[0]["url"] == "https://youtu.be/v4"
