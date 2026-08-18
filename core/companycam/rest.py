"""CompanyCam endpoint constants — single source, importable INSIDE the jobs container.

`scripts/` is .dockerignore'd (only core/adapters/api/jobs/app ship in the image), so
these live here rather than under scripts/ (mirrors core/knowify/rest.py).
"""
from __future__ import annotations

# Modern public API (developers.companycam.com). Legacy /v2 sunsets 2027-09-01.
# Envelope is {data, errors, meta}; lists paginate with limit/after, not page/per_page.
API = "https://api.companycam.com/public_api/v1"
UA = "PerkinsRoofingPlatform/1.0"


def projects_url() -> str:
    return f"{API}/projects"


def tags_url() -> str:
    """The account's media tags. Used to VALIDATE a configured tag id before filtering on
    it — see adapters.companycam.known_tag_ids."""
    return f"{API}/tags"


def photos_index_url() -> str:
    """ACCOUNT-WIDE photo index. Honours ``?tag_ids[]=`` (verified live 2026-08-12: the whole
    account returns 42 photos for the Projects tag, across 5+ projects, page 2 empty), which is
    what lets the publish-tag pass run in ~2 requests instead of fanning out over 3,684 projects
    — and, critically, run INDEPENDENTLY of the per-project `needs_media` gate."""
    return f"{API}/photos"


def videos_index_url() -> str:
    """ACCOUNT-WIDE video index. Same contract as photos_index_url (10 tagged videos account-wide)."""
    return f"{API}/videos"


def photos_url(project_id: str) -> str:
    return f"{API}/projects/{project_id}/photos"


def photo_url(photo_id: str) -> str:
    return f"{API}/photos/{photo_id}"


def videos_url(project_id: str) -> str:
    """Videos are a separate resource from photos — a project's clips do not come back
    from /photos. Same path on public_api/v1 as on legacy /v2."""
    return f"{API}/projects/{project_id}/videos"
