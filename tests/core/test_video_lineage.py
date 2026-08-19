from types import SimpleNamespace

from core.video_lineage import (
    attach_derived_urls,
    derived_ids_from_db,
    derived_video_ids,
    ids_from_urls,
    parent_index_from_db,
    stamp_longform_source,
    youtube_id_from_url,
)


def test_stamp_longform_only_on_uncut_fifteen_plus():
    short = SimpleNamespace(duration=400, longform_reprocessed_at=None, longform_note=None)
    assert stamp_longform_source(short) is False
    long = SimpleNamespace(duration=1200, longform_reprocessed_at=None, longform_note=None)
    assert stamp_longform_source(long) is True
    assert long.longform_reprocessed_at is not None
    assert long.longform_note == "clip_studio"
    assert stamp_longform_source(long) is False
    assert stamp_longform_source(None) is False


def test_parses_watch_share_and_raw_ids():
    assert youtube_id_from_url("https://youtu.be/abcdefghijk") == "abcdefghijk"
    assert youtube_id_from_url("https://www.youtube.com/watch?v=abcdefghijk") == "abcdefghijk"
    assert youtube_id_from_url("https://www.youtube.com/shorts/abcdefghijk") == "abcdefghijk"
    assert youtube_id_from_url("abcdefghijk") == "abcdefghijk"
    assert youtube_id_from_url("not-a-url") is None
    assert youtube_id_from_url("") is None


def test_ids_from_urls_dedupes_and_skips_junk():
    assert ids_from_urls([
        "https://youtu.be/abcdefghijk",
        "abcdefghijk",
        "nope",
        "https://youtu.be/lmnopqrstuv",
    ]) == ["abcdefghijk", "lmnopqrstuv"]


def test_derived_set_includes_parented_rows_and_listed_urls():
    videos = [
        SimpleNamespace(id="LONGVIDEO01", parent_video_id=None,
                        derived_urls=["https://youtu.be/CLIPVIDEO01"]),
        SimpleNamespace(id="CLIPVIDEO01", parent_video_id="LONGVIDEO01", derived_urls=[]),
        SimpleNamespace(id="OTHERVIDEO1", parent_video_id=None, derived_urls=[]),
    ]
    assert derived_video_ids(videos) == {"CLIPVIDEO01"}


def test_attach_derived_urls_stamps_existing_children():
    parent = SimpleNamespace(id="LONGVIDEO01", derived_urls=None)
    child = SimpleNamespace(id="CLIPVIDEO01", parent_video_id=None)
    store = {"CLIPVIDEO01": child}

    class _DB:
        def get(self, _model, key):
            return store.get(key)

    attached = attach_derived_urls(parent, ["https://youtu.be/CLIPVIDEO01"], _DB())
    assert attached == ["CLIPVIDEO01"]
    assert child.parent_video_id == "LONGVIDEO01"
    assert parent.derived_urls == ["https://youtu.be/CLIPVIDEO01"]


def test_attach_skips_self_blank_and_missing_child():
    parent = SimpleNamespace(id="LONGVIDEO01", derived_urls=["https://youtu.be/CLIPVIDEO01"])

    class _DB:
        def get(self, _model, key):
            return None

    attached = attach_derived_urls(
        parent,
        ["", "LONGVIDEO01", "https://youtu.be/CLIPVIDEO01", "https://youtu.be/NEWCLIP0001"],
        _DB(),
    )
    assert attached == []
    assert "NEWCLIP0001" in "".join(parent.derived_urls)


class _Q:
    def __init__(self, rows):
        self._rows = rows
    def filter(self, *a, **k):
        return self
    def all(self):
        return self._rows


class _Sess:
    def __init__(self, rows):
        self._rows = rows
    def query(self, *cols):
        return _Q(self._rows)


def test_derived_ids_and_parent_index_from_db():
    rows_full = [
        ("LONGVIDEO01", None, ["https://youtu.be/CLIPVIDEO01"]),
        ("CLIPVIDEO01", "LONGVIDEO01", []),
    ]
    assert derived_ids_from_db(_Sess(rows_full)) == {"CLIPVIDEO01"}
    assert parent_index_from_db(_Sess([
        ("LONGVIDEO01", ["https://youtu.be/CLIPVIDEO01"]),
        ("LONGVIDEO01", ["LONGVIDEO01"]),
    ])) == {"CLIPVIDEO01": "LONGVIDEO01"}
