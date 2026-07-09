from core.authz import can, effective_role

_ADMINS = frozenset({"jon@perkinsroofing.net", "tim@perkinsroofing.net"})


def test_admin_can_everything():
    assert can("admin", "manage_templates") is True
    assert can("admin", "anything_at_all") is True


def test_sales_allowed_actions():
    assert can("sales", "search") is True
    assert can("sales", "email_send") is True


def test_sales_denied_admin_actions():
    assert can("sales", "manage_users") is False


def test_unknown_role_denied():
    assert can("guest", "search") is False
    assert can("", "search") is False


def test_web_admin_manages_content_not_email_or_admin():
    for a in ("search", "ask", "manage_articles", "manage_scheduling", "approve_video", "view_status"):
        assert can("web_admin", a) is True, a
    for a in ("email_send", "manage_templates", "manage_users", "manage_config"):
        assert can("web_admin", a) is False, a


def test_sales_has_email_templates_not_admin():
    assert can("sales", "manage_templates") is True
    assert can("sales", "email_send") is True
    for a in ("manage_users", "manage_config", "approve_video", "manage_articles"):
        assert can("sales", a) is False, a


def test_only_admin_manages_users_and_config():
    assert can("admin", "manage_users") is True and can("admin", "manage_config") is True
    for r in ("web_admin", "sales", "guest"):
        assert can(r, "manage_users") is False and can(r, "manage_config") is False


def test_default_admin_email_is_admin_when_verified():
    assert effective_role("jon@perkinsroofing.net", "", _ADMINS, email_verified=True) == "admin"
    # case-insensitive
    assert effective_role("TIM@PerkinsRoofing.net", "sales", _ADMINS, email_verified=True) == "admin"


def test_default_admin_email_NOT_elevated_when_unverified():
    # security: an unverified email must never be promoted to admin (self-registration guard)
    assert effective_role("jon@perkinsroofing.net", "", _ADMINS, email_verified=False) == ""
    assert effective_role("jon@perkinsroofing.net", "sales", _ADMINS) == "sales"   # default is unverified
    # an explicit custom-claim role is still honored regardless of verification
    assert effective_role("jon@perkinsroofing.net", "web_admin", _ADMINS, email_verified=False) == "web_admin"


def test_non_default_admin_keeps_assigned_role():
    assert effective_role("stranger@example.com", "sales", _ADMINS, email_verified=True) == "sales"
    assert effective_role("stranger@example.com", "", _ADMINS, email_verified=True) == ""
    assert effective_role(None, "sales", _ADMINS, email_verified=True) == "sales"


# ---------------------------------------------------------------------------
# F3 quoting actions
# ---------------------------------------------------------------------------

def test_admin_can_all_quoting_actions():
    for action in ("quoting_view", "quoting_create", "quoting_send",
                   "quoting_manage_templates", "quoting_manage_settings"):
        assert can("admin", action) is True, action


def test_web_admin_can_all_quoting_actions():
    for action in ("quoting_view", "quoting_create", "quoting_send",
                   "quoting_manage_templates", "quoting_manage_settings"):
        assert can("web_admin", action) is True, action


def test_sales_can_quoting_view_create_send_but_not_manage():
    assert can("sales", "quoting_view") is True
    assert can("sales", "quoting_create") is True
    assert can("sales", "quoting_send") is True
    assert can("sales", "quoting_manage_templates") is False
    assert can("sales", "quoting_manage_settings") is False


# ---------------------------------------------------------------------------
# F4 effective_role DB path
# ---------------------------------------------------------------------------

def test_effective_role_db_path_elevates_admin():
    from unittest.mock import MagicMock
    mock_db = MagicMock()
    mock_db.execute.return_value.fetchone.return_value = (1,)
    result = effective_role("admin@example.com", "sales", tenant_id=1,
                            db_session=mock_db, email_verified=True)
    assert result == "admin"
    mock_db.execute.assert_called_once()


def test_effective_role_db_path_no_row_keeps_role():
    from unittest.mock import MagicMock
    mock_db = MagicMock()
    mock_db.execute.return_value.fetchone.return_value = None
    result = effective_role("stranger@example.com", "sales", tenant_id=1,
                            db_session=mock_db, email_verified=True)
    assert result == "sales"


def test_effective_role_db_path_exception_falls_through():
    from unittest.mock import MagicMock
    mock_db = MagicMock()
    mock_db.execute.side_effect = Exception("table missing")
    result = effective_role("admin@example.com", "sales", tenant_id=1,
                            db_session=mock_db, email_verified=True)
    # Should fall through to config fallback, not raise
    assert result in ("admin", "sales")
