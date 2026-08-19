from core.user_nav import empty_nav, nav_saved, sanitize_nav


def test_empty_and_junk_become_defaults():
    expected = {"pins": [], "sections": [], "collapsed": False}
    assert sanitize_nav(None) == expected
    assert sanitize_nav("nope") == expected
    assert sanitize_nav([]) == expected
    assert sanitize_nav({}) == expected
    assert empty_nav() == expected


def test_keeps_valid_pins_sections_and_collapsed():
    got = sanitize_nav({
        "pins": ["search-ask", "clip-studio"],
        "sections": ["Knowledge Base", "Admin"],
        "collapsed": True,
        "extra": "drop-me",
    })
    assert got == {
        "pins": ["search-ask", "clip-studio"],
        "sections": ["Knowledge Base", "Admin"],
        "collapsed": True,
    }


def test_drops_invalid_pins_and_dedupes():
    got = sanitize_nav({
        "pins": [
            "search-ask",
            "search-ask",
            "Search-Ask",
            "no spaces",
            "../etc",
            "<script>",
            "",
            "a" * 50,
            12,
            None,
            "logs",
        ],
    })
    assert got["pins"] == ["search-ask", "logs"]


def test_caps_list_lengths():
    pins = [f"tab-{i}" for i in range(80)]
    sections = [f"Section {i}" for i in range(20)]
    got = sanitize_nav({"pins": pins, "sections": sections})
    assert len(got["pins"]) == 40
    assert got["pins"][0] == "tab-0"
    assert got["pins"][-1] == "tab-39"
    assert len(got["sections"]) == 8


def test_nav_saved_only_after_keys_written():
    assert nav_saved(None) is False
    assert nav_saved({}) is False
    assert nav_saved({"pins": []}) is True
    assert nav_saved({"sections": ["Admin"], "collapsed": False}) is True


def test_collapsed_truthy_forms():
    assert sanitize_nav({"collapsed": True})["collapsed"] is True
    assert sanitize_nav({"collapsed": 1})["collapsed"] is True
    assert sanitize_nav({"collapsed": "1"})["collapsed"] is True
    assert sanitize_nav({"collapsed": "true"})["collapsed"] is True
    assert sanitize_nav({"collapsed": False})["collapsed"] is False
    assert sanitize_nav({"collapsed": 0})["collapsed"] is False
    assert sanitize_nav({"collapsed": "0"})["collapsed"] is False
    assert sanitize_nav({"collapsed": "yes"})["collapsed"] is False
