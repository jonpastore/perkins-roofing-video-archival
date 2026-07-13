from pathlib import Path

STATUS = Path("web/src/pages/Status.tsx")
API = Path("web/src/api.ts")


def test_dashboard_proposal_funnel_uses_grouped_time_series_on_selected_bucket():
    source = STATUS.read_text()
    api = API.read_text()

    assert "DashboardProposalFunnelPeriod" in api
    assert "proposal_funnel_over_time" in api
    assert "const funnelTimeData = billing?.proposal_funnel_over_time" in source
    assert "Proposal Funnel Over Time" in source
    assert "same {lastRange?.bucket" in source
    assert 'dataKey="period"' in source
    assert 'dataKey="draft"' in source
    assert 'dataKey="sent"' in source
    assert 'dataKey="accepted"' in source
    assert 'dataKey="declined"' in source
    assert "Sent / Viewed" in source
