"""Tests for core/tc_seed.py — constants only. TDD: written before implementation."""
from core.tc_seed import DRAFT_TC_TEXT, DRAFT_TC_VERSION_TAG


def test_version_tag_is_draft():
    assert DRAFT_TC_VERSION_TAG == "v0.1-DRAFT"


def test_tc_text_is_nonempty():
    assert isinstance(DRAFT_TC_TEXT, str) and len(DRAFT_TC_TEXT) > 0


def test_tc_text_contains_payment_terms():
    assert "PAYMENT TERMS" in DRAFT_TC_TEXT


def test_tc_text_contains_49():
    assert "49" in DRAFT_TC_TEXT


def test_tc_text_is_substantial():
    assert len(DRAFT_TC_TEXT) > 500
