import re
from pathlib import Path

PROPOSALS = Path("web/src/pages/Proposals.tsx")
BUILDER = Path("web/src/pages/ProposalBuilder.tsx")


def test_proposals_embeds_new_proposal_builder_in_drawer():
    source = PROPOSALS.read_text()

    assert 'import { ProposalBuilder } from "./ProposalBuilder";' in source
    assert re.search(r"<ProposalBuilder\s+[^>]*embedded", source, re.DOTALL)
    assert "onCreated={handleProposalCreated}" in source
    assert "onCancel={closeCreateDrawer}" in source
    assert 'navigate("proposal-gen")' not in source


def test_proposals_has_legacy_quotes_tab_using_existing_api_helper():
    source = PROPOSALS.read_text()

    assert "Legacy Quotes" in source
    assert "listQuotes" in source
    assert re.search(r"listQuotes\(\{\s*limit:\s*100", source)
    assert "QuoteListItem" in source


def test_proposals_preserves_public_sign_url_helper():
    source = PROPOSALS.read_text()

    assert "function signPublicUrl()" in source
    assert "VITE_SIGN_PUBLIC_URL" in source
    assert "https://sign.perkinsroofing.net" in source
    assert re.search(r"signPublicUrl\(\)\}/p/\$\{p\.accept_token\}", source)


def test_proposal_builder_exposes_embedded_mode_callbacks():
    source = BUILDER.read_text()

    assert "export interface ProposalBuilderProps" in source
    assert "embedded?: boolean" in source
    assert "onCreated?: (result: GenerateProposalResult) => void" in source
    assert "onCancel?: () => void" in source
    assert "prefill?: ProposalBuilderPrefill" in source
    assert re.search(r"export function ProposalBuilder\(\{[^}]*embedded = false", source, re.DOTALL)
    assert "onCreated?.(res)" in source
    assert "{!embedded && <PageTitle>New Proposal</PageTitle>}" in source
