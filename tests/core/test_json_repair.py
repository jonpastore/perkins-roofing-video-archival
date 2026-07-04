from core.json_repair import parse_model_json


def test_plain_json():
    assert parse_model_json('{"a": 1}') == {"a": 1}


def test_fenced_json():
    assert parse_model_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_trailing_comma():
    assert parse_model_json('{"a": 1, "b": [2, 3,],}') == {"a": 1, "b": [2, 3]}


def test_prose_around_json():
    assert parse_model_json('Here you go:\n{"title": "Roof"}\nThanks') == {"title": "Roof"}


def test_array_root():
    assert parse_model_json("[1, 2, 3]") == [1, 2, 3]


def test_control_chars_stripped():
    assert parse_model_json('{"a": "x\x07y"}') == {"a": "xy"}


def test_empty_and_garbage():
    assert parse_model_json("") == {}
    assert parse_model_json("no json here") == {}
    assert parse_model_json("{ broken ") == {}
