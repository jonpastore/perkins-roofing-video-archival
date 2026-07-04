from core.authz import can


def test_admin_can_everything():
    assert can("admin", "manage_templates") is True
    assert can("admin", "anything_at_all") is True


def test_sales_allowed_actions():
    assert can("sales", "search") is True
    assert can("sales", "email_send") is True


def test_sales_denied_admin_actions():
    assert can("sales", "manage_templates") is False


def test_unknown_role_denied():
    assert can("guest", "search") is False
    assert can("", "search") is False
