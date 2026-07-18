"""CompanyCam endpoint constants — single source, importable INSIDE the jobs container.

`scripts/` is .dockerignore'd (only core/adapters/api/jobs/app ship in the image), so
these live here rather than under scripts/ (mirrors core/knowify/rest.py).
"""
from __future__ import annotations

API = "https://api.companycam.com/v2"
UA = "PerkinsRoofingPlatform/1.0"


def projects_url() -> str:
    return f"{API}/projects"


def photos_url(project_id: str) -> str:
    return f"{API}/projects/{project_id}/photos"


def photo_url(photo_id: str) -> str:
    return f"{API}/photos/{photo_id}"
