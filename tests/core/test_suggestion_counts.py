from core.suggestion_counts import compute_suggestion_counts, to_question


def test_to_question_empty():
    assert to_question("", "") == ""


def test_to_question_already_question():
    assert to_question("Need a permit?", "") == "Need a permit?"


def test_to_question_capitalizes():
    assert to_question("need a permit", "") == "Need a permit?"
    assert to_question("", "storm damage") == "Storm damage?"


class _Q:
    def __init__(self, rows=None):
        self._rows = rows or []

    def filter(self, *a, **k):
        return self

    def distinct(self):
        return self

    def all(self):
        return self._rows

    def count(self):
        return len(self._rows)


class _Node:
    def __init__(self, label, video_id="v1"):
        self.label = label
        self.video_id = video_id
        self.start = 1
        self.detail = ""


def test_compute_skips_blank_topic_labels():
    class _Db:
        def query(self, *cols):
            model = cols[0]
            name = getattr(model, "__name__", str(getattr(model, "class_", model)))
            if name == "GraphNode":
                return _Q([_Node(""), _Node("Flat roof")])
            return _Q([])

    out = compute_suggestion_counts(_Db())
    assert out["article_topics"] == 1
