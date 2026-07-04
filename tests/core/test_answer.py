from core.answer import build_answer_prompt, should_abstain


def test_abstains_below_threshold():
    assert should_abstain(0.5, 0.71) is True


def test_no_abstain_at_or_above_threshold():
    assert should_abstain(0.71, 0.71) is False
    assert should_abstain(0.9, 0.71) is False


def test_no_hits_abstains():
    assert should_abstain(0.0, 0.71) is True


def test_build_answer_prompt_includes_question_and_sources():
    p = build_answer_prompt(
        "why does my roof leak",
        contexts=[("https://youtu.be/v1?t=10", "flashing fails first")],
        key_points=[("https://youtu.be/v1?t=5", "check the flashing")],
    )
    assert "QUESTION: why does my roof leak" in p
    assert "flashing fails first" in p
    assert "(key point, source https://youtu.be/v1?t=5) check the flashing" in p


def test_key_points_truncated_to_20():
    kp = [(f"l{i}", f"point{i}") for i in range(30)]
    p = build_answer_prompt("q", contexts=[], key_points=kp)
    assert "point19" in p
    assert "point20" not in p
