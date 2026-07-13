from decimal import Decimal

import pytest

from core.discounts import resolve_discounts


def test_resolve_amount_discount_backward_compatible():
    items = resolve_discounts([{"description": "Referral", "amount": "500.00"}], Decimal("10000.00"))
    assert items == [{"description": "Referral", "amount": "500.00", "discount_type": "amount", "value": "500.00"}]


def test_resolve_percent_discount_against_base():
    items = resolve_discounts(
        [{"description": "Veteran", "discount_type": "percent", "value": "10"}],
        Decimal("12345.67"),
    )
    assert items[0]["description"] == "Veteran"
    assert items[0]["discount_type"] == "percent"
    assert items[0]["value"] == "10"
    assert items[0]["amount"] == "1234.57"


def test_percent_alias_field_supported():
    items = resolve_discounts([{"description": "Promo", "percent": "2.5"}], Decimal("1000.00"))
    assert items[0]["amount"] == "25.00"


@pytest.mark.parametrize("bad", ["-1", "101"])
def test_percent_must_be_between_0_and_100(bad):
    with pytest.raises(ValueError):
        resolve_discounts([{"description": "Bad", "discount_type": "percent", "value": bad}], Decimal("1000"))


def test_amount_cannot_be_negative():
    with pytest.raises(ValueError):
        resolve_discounts([{"description": "Bad", "amount": "-1"}], Decimal("1000"))
