from pathlib import Path

PROPOSALS = Path("web/src/pages/Proposals.tsx")


def test_proposals_table_uses_compact_proposal_column_and_wide_customer_address():
    source = PROPOSALS.read_text()

    assert "maxWidth: 1240" in source
    assert "minWidth: 1040" in source
    assert "Customer / Property" in source
    assert ">Title</th>" not in source
    assert "statusCounts" in source
    assert "proposalTotal" in source
    assert "proposalIconButtonStyle" in source
    assert "title=\"Details\"" in source
    assert "title=\"PDF\"" in source
    assert "#{p.id}" in source
    assert "v{p.version_number}" in source
    assert "maxWidth: 300" in source


def test_revision_opens_editable_draft_ui():
    source = PROPOSALS.read_text()

    assert "Create editable revision" in source
    assert "Edit Proposal #" in source
    assert "Save draft" in source
    assert "Edit draft" in source
    assert "handleSaveEditProposal" in source
