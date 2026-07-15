"""Behavioral validation for the audit trail's pure logic.

Redaction gets the most attention here on purpose: an audit log is long-lived, widely read,
and the last place a credential should ever land.
"""
from core.audit import action_for, entity_from, is_secretish, redact, template_path

# ── redaction: deny by default ────────────────────────────────────────────────

def test_secrets_are_never_stored():
    out = redact({"password": "hunter2", "api_key": "sk-live-123", "token": "eyJhbG",
                  "authorization": "Bearer x", "wp_app_pwd": "abcd efgh"})
    assert "hunter2" not in str(out)
    assert "sk-live-123" not in str(out)
    assert "eyJhbG" not in str(out)
    assert "abcd efgh" not in str(out)
    assert all(v == "[redacted]" for v in out.values())


def test_unknown_fields_are_dropped_not_stored():
    # Deny-by-default: a new field on a request body must not silently start being persisted.
    out = redact({"customer_note": "call me on 555-0100", "id": 7})
    assert out["customer_note"] == "[omitted]"
    assert out["id"] == 7


def test_known_safe_fields_are_kept():
    out = redact({"slug": "wall-flashings", "status": "published", "count": 3})
    assert out == {"slug": "wall-flashings", "status": "published", "count": 3}


def test_secretish_name_beats_the_safe_list():
    # "key" is secretish; even though short ids are useful, a field named *_key never lands.
    assert is_secretish("stripe_key") and is_secretish("Session-Cookie")
    assert redact({"private_id": "x"})["private_id"] == "[redacted]"


def test_nested_secrets_are_redacted():
    out = redact({"id": 1, "name": "n", "email": "a@b.c"})
    assert out["email"] == "a@b.c"
    deep = redact({"id": 1, "status": {"password": "p", "slug": "s"}})
    assert deep["status"]["password"] == "[redacted]"


def test_long_values_are_truncated():
    out = redact({"title": "x" * 500})
    assert len(out["title"]) < 260 and out["title"].endswith("…")


def test_payload_is_bounded():
    out = redact({f"slug{i}": i for i in range(200)})
    assert len(out) <= 41  # 40 keys + the truncation marker
    assert "[truncated]" in out


def test_redact_survives_odd_input():
    assert redact(None) is None
    assert redact(5) == 5
    assert redact(["a", "b"]) == ["a", "b"]


# ── action naming (from FastAPI's matched route template) ─────────────────────

def test_action_names_the_thing_that_happened():
    assert action_for("POST", "/articles") == "article.create"
    assert action_for("DELETE", "/articles/{slug}") == "article.delete"
    assert action_for("PATCH", "/customers/{id}") == "customer.update"


def test_trailing_literal_beats_the_http_method():
    # "proposal.sign" is what you grep for at 2am, not "proposal.create".
    assert action_for("POST", "/proposals/{proposal_id}/sign") == "proposal.sign"
    assert action_for("POST", "/articles/{slug}/fix-seo") == "article.fix-seo"


def test_ids_never_leak_into_action_names():
    # Otherwise "what happened to proposals" needs a LIKE scan instead of an index hit.
    a = action_for("POST", "/proposals/{proposal_id}/sign")
    assert "{" not in a and a == "proposal.sign"


def test_entity_uses_the_frameworks_parsed_params_not_a_guess():
    # A guess cannot tell the slug "wall-flashings" from a sub-resource — it got that wrong.
    assert entity_from("/articles/{slug}", {"slug": "wall-flashings"}) == \
        ("article", "wall-flashings")
    assert entity_from("/proposals/{proposal_id}/sign", {"proposal_id": 12}) == ("proposal", "12")
    assert entity_from("/articles", {}) == ("article", None)


def test_template_path_is_only_a_fallback_for_unmatched_paths():
    assert template_path("/proposals/12/sign") == "/proposals/{id}/sign"
    assert template_path("/health") == "/health"

