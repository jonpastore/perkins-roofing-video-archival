from core.authz import can, effective_role

_ADMINS = frozenset({"jon@perkinsroofing.net", "tim@perkinsroofing.net"})


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


def test_default_admin_email_is_admin_regardless_of_claim():
    assert effective_role("jon@perkinsroofing.net", "", _ADMINS) == "admin"
    assert effective_role("TIM@PerkinsRoofing.net", "sales", _ADMINS) == "admin"  # case-insensitive


def test_non_default_admin_keeps_assigned_role():
    assert effective_role("stranger@example.com", "sales", _ADMINS) == "sales"
    assert effective_role("stranger@example.com", "", _ADMINS) == ""
    assert effective_role(None, "sales", _ADMINS) == "sales"
