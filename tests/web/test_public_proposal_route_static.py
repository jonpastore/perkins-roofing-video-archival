from pathlib import Path

APP = Path("web/src/App.tsx")


def test_public_proposal_route_bypasses_login():
    source = APP.read_text()

    assert "ProposalAcceptRoute" in source
    assert "isPublicProposalRoute" in source
    assert "if (isPublicProposalRoute) return <ProposalAcceptRoute />" in source
    assert "Sales and Marketing Platform" in source
    assert "Video Content Console" not in source
