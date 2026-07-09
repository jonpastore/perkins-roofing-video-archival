"""F1 authz tests — section-scoped action strings per TRD-F1 §11.

TDD sequence: write red first, then implement in core/authz.py, then green.
"""

import pytest
from core.authz import can


# ---------------------------------------------------------------------------
# §11 normative action list for use across tests
# ---------------------------------------------------------------------------

ALL_SECTION_ACTIONS = [
    "kb_search",
    "kb_ask",
    "kb_faq_read",
    "kb_faq_manage",
    "kb_archive_read",
    "kb_archive_manage",
    "kb_contract_faq_read",
    "marketing_opportunities",
    "marketing_articles",
    "marketing_schedule",
    "marketing_clips",
    "marketing_comments",
    "marketing_email",
    "marketing_video_approval",
    "marketing_status",
    "estimating_view",
    "estimating_manage",
    "quoting_view",
    "quoting_create",
    "quoting_send",
    "quoting_manage_templates",
    "admin_users",
    "admin_config",
    "admin_tenants",
]

# Actions granted to web_admin (per §11)
WEB_ADMIN_ACTIONS = [
    "kb_search",
    "kb_ask",
    "kb_faq_read",
    "kb_faq_manage",
    "kb_archive_read",
    "kb_archive_manage",
    "kb_contract_faq_read",
    "marketing_opportunities",
    "marketing_articles",
    "marketing_schedule",
    "marketing_clips",
    "marketing_comments",
    "marketing_video_approval",
    "marketing_status",
    "estimating_view",
    "estimating_manage",
    "quoting_view",
    "quoting_create",
    "quoting_send",
    "admin_users",
]

# Actions granted to sales (per §11)
SALES_ACTIONS = [
    "kb_search",
    "kb_ask",
    "estimating_view",
    "quoting_view",
    "quoting_create",
    "quoting_send",
]

# Actions NOT granted to sales (boundary check subset)
SALES_DENIED = [
    "kb_faq_manage",
    "kb_faq_read",
    "kb_archive_read",
    "kb_archive_manage",
    "kb_contract_faq_read",
    "marketing_opportunities",
    "marketing_articles",
    "marketing_schedule",
    "marketing_clips",
    "marketing_comments",
    "marketing_email",
    "marketing_video_approval",
    "marketing_status",
    "estimating_manage",
    "quoting_manage_templates",
    "admin_users",
    "admin_config",
    "admin_tenants",
]

# Actions NOT granted to web_admin (boundary check)
WEB_ADMIN_DENIED = [
    "marketing_email",        # email is admin-only
    "quoting_manage_templates",  # admin-only
    "admin_config",           # admin-only
    "admin_tenants",          # platform_admin only
]

# platform_admin actions (per §11)
PLATFORM_ADMIN_ACTIONS = [
    "admin_tenants",
    "admin_users",
]

# platform_admin must NOT get wildcard — specific denials
PLATFORM_ADMIN_DENIED = [
    "kb_search",
    "marketing_articles",
    "quoting_create",
    "estimating_view",
    "admin_config",
]


# ---------------------------------------------------------------------------
# Group 1 — web_admin positive grants
# ---------------------------------------------------------------------------

def test_web_admin_can_kb_search():
    assert can("web_admin", "kb_search") is True


def test_web_admin_can_kb_ask():
    assert can("web_admin", "kb_ask") is True


def test_web_admin_can_kb_faq_read():
    assert can("web_admin", "kb_faq_read") is True


def test_web_admin_can_kb_faq_manage():
    assert can("web_admin", "kb_faq_manage") is True


def test_web_admin_can_kb_archive_read():
    assert can("web_admin", "kb_archive_read") is True


def test_web_admin_can_kb_archive_manage():
    assert can("web_admin", "kb_archive_manage") is True


def test_web_admin_can_kb_contract_faq_read():
    assert can("web_admin", "kb_contract_faq_read") is True


def test_web_admin_can_marketing_opportunities():
    assert can("web_admin", "marketing_opportunities") is True


def test_web_admin_can_marketing_articles():
    assert can("web_admin", "marketing_articles") is True


def test_web_admin_can_marketing_schedule():
    assert can("web_admin", "marketing_schedule") is True


def test_web_admin_can_marketing_clips():
    assert can("web_admin", "marketing_clips") is True


def test_web_admin_can_marketing_comments():
    assert can("web_admin", "marketing_comments") is True


def test_web_admin_can_marketing_video_approval():
    assert can("web_admin", "marketing_video_approval") is True


def test_web_admin_can_marketing_status():
    assert can("web_admin", "marketing_status") is True


def test_web_admin_can_estimating_view():
    assert can("web_admin", "estimating_view") is True


def test_web_admin_can_estimating_manage():
    assert can("web_admin", "estimating_manage") is True


def test_web_admin_can_quoting_view():
    assert can("web_admin", "quoting_view") is True


def test_web_admin_can_quoting_create():
    assert can("web_admin", "quoting_create") is True


def test_web_admin_can_quoting_send():
    assert can("web_admin", "quoting_send") is True


def test_web_admin_can_admin_users():
    assert can("web_admin", "admin_users") is True


# ---------------------------------------------------------------------------
# Group 1 — web_admin boundary denials
# ---------------------------------------------------------------------------

def test_web_admin_cannot_marketing_email():
    """Email compose/send is admin-only; web_admin must be denied."""
    assert can("web_admin", "marketing_email") is False


def test_web_admin_cannot_quoting_manage_templates():
    assert can("web_admin", "quoting_manage_templates") is False


def test_web_admin_cannot_admin_config():
    assert can("web_admin", "admin_config") is False


def test_web_admin_cannot_admin_tenants():
    assert can("web_admin", "admin_tenants") is False


# ---------------------------------------------------------------------------
# Group 1 — sales positive grants
# ---------------------------------------------------------------------------

def test_sales_can_kb_search():
    assert can("sales", "kb_search") is True


def test_sales_can_kb_ask():
    assert can("sales", "kb_ask") is True


def test_sales_can_estimating_view():
    assert can("sales", "estimating_view") is True


def test_sales_can_quoting_view():
    assert can("sales", "quoting_view") is True


def test_sales_can_quoting_create():
    assert can("sales", "quoting_create") is True


def test_sales_can_quoting_send():
    assert can("sales", "quoting_send") is True


# ---------------------------------------------------------------------------
# Group 1 — sales boundary denials
# ---------------------------------------------------------------------------

def test_sales_cannot_kb_faq_manage():
    """sales must not manage FAQ — write-gated."""
    assert can("sales", "kb_faq_manage") is False


def test_sales_cannot_marketing_clips():
    assert can("sales", "marketing_clips") is False


def test_sales_cannot_estimating_manage():
    assert can("sales", "estimating_manage") is False


def test_sales_cannot_admin_users():
    assert can("sales", "admin_users") is False


def test_sales_cannot_admin_tenants():
    assert can("sales", "admin_tenants") is False


@pytest.mark.parametrize("action", SALES_DENIED)
def test_sales_denied_parametrized(action):
    assert can("sales", action) is False, f"sales must not have {action}"


# ---------------------------------------------------------------------------
# Group 1 — admin wildcard covers all new section actions
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("action", ALL_SECTION_ACTIONS)
def test_admin_can_all_section_actions(action):
    """admin '*' wildcard must cover every new action name."""
    assert can("admin", action) is True, f"admin must have {action} via wildcard"


# ---------------------------------------------------------------------------
# Group 1 — platform_admin (two explicit actions, no wildcard)
# ---------------------------------------------------------------------------

def test_platform_admin_can_admin_tenants():
    assert can("platform_admin", "admin_tenants") is True


def test_platform_admin_can_admin_users():
    assert can("platform_admin", "admin_users") is True


@pytest.mark.parametrize("action", PLATFORM_ADMIN_DENIED)
def test_platform_admin_denied_operational_actions(action):
    """platform_admin must not inherit wildcard or operational capabilities."""
    assert can("platform_admin", action) is False, f"platform_admin must not have {action}"


# ---------------------------------------------------------------------------
# Group 1 — unknown role denied everything
# ---------------------------------------------------------------------------

def test_unknown_role_denied_all_section_actions():
    assert can("unknown_role", "kb_search") is False


@pytest.mark.parametrize("action", ALL_SECTION_ACTIONS)
def test_unknown_role_denied_parametrized(action):
    assert can("unknown_role", action) is False


# ---------------------------------------------------------------------------
# Regression — existing actions still work (no breakage)
# ---------------------------------------------------------------------------

def test_existing_web_admin_actions_intact():
    for action in ("search", "ask", "manage_articles", "manage_scheduling", "approve_video",
                   "manage_archive", "view_status", "manage_estimates"):
        assert can("web_admin", action) is True, f"web_admin regression: lost {action}"


def test_existing_sales_actions_intact():
    for action in ("search", "ask", "email_compose", "email_proof", "email_send",
                   "manage_templates", "article_read", "manage_estimates"):
        assert can("sales", action) is True, f"sales regression: lost {action}"


def test_existing_admin_wildcard_intact():
    for action in ("search", "ask", "manage_users", "manage_config", "email_send"):
        assert can("admin", action) is True, f"admin wildcard regression: lost {action}"
