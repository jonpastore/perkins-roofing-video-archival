"""Proposal fairness/security review — pass, issues, and fail-safe."""
from core.proposal_review import review_proposal


def test_clean_proposal_passes():
    r = review_proposal("scope + fair terms", chat_fn=lambda p, want_json=True: {"pass": True, "issues": []})
    assert r == {"pass": True, "issues": []}


def test_flags_issues():
    issues = [{"severity": "high", "category": "contradiction", "detail": "deposit differs", "location": "T&C"}]
    r = review_proposal("bad", chat_fn=lambda p, want_json=True: {"pass": False, "issues": issues})
    assert r["pass"] is False and r["issues"] == issues


def test_llm_error_is_failsafe_not_a_pass():
    def _boom(p, want_json=True):
        raise RuntimeError("vertex down")
    r = review_proposal("x", chat_fn=_boom)
    assert r["pass"] is False and r["issues"][0]["category"] == "review_error"


def test_unparseable_result_is_failsafe():
    r = review_proposal("x", chat_fn=lambda p, want_json=True: "not a dict")
    assert r["pass"] is False and r["issues"][0]["category"] == "review_error"


def test_proposal_text_injected():
    captured = {}
    def _cap(p, want_json=True):
        captured["p"] = p
        return {"pass": True, "issues": []}
    review_proposal("UNIQUE-MARKER-123", chat_fn=_cap)
    assert "UNIQUE-MARKER-123" in captured["p"]
