from pathlib import Path
import re


def test_proposal_builder_customer_load_caps_limit_to_backend_maximum():
    """New Proposal must override the shared customer helper default.

    GET /quoting/customers has a backend cap of limit <= 200. The shared
    listQuotingCustomers() helper is used elsewhere, so the ProposalBuilder
    call path must pass its own safe cap.
    """
    source = Path("web/src/pages/ProposalBuilder.tsx").read_text()

    assert re.search(r"listQuotingCustomers\(\{\s*limit:\s*200\s*}\)", source)
