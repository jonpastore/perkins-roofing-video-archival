from pathlib import Path

STATUS = Path("web/src/pages/Status.tsx")


def test_dashboard_proposal_funnel_uses_per_status_colors_and_date_range_data():
    source = STATUS.read_text()

    assert "billing.proposal_funnel.draft" in source
    assert "billing.proposal_funnel.sent" in source
    assert "billing.proposal_funnel.accepted" in source
    assert "billing.proposal_funnel.declined" in source
    assert "color:" in source
    assert "funnelData.map((entry)" in source
    assert "<Cell key={entry.name} fill={entry.color}" in source
