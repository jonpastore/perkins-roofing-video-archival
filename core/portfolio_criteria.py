"""THE project-page checklist — one gate, enforced before publish (pure, no I/O).

Mirrors core.article_criteria: one list of named criteria, each with a severity, so "is this
publishable?" has exactly one answer and the API cannot drift from the UI.

WHY A GATE AND NOT A SCORE. The score (core.portfolio_media.score_project) answers "how good
is this page"; that is advice. This module answers "may it go out at all", which is a different
question with legal and privacy consequences:

  * ``blocker`` — publishing would disclose PII or breach a client permission. Refuses.
  * ``major``   — the page would embarrass us (no images, duplicate alt text, no scope). Refuses
                  too, because a thin project page is worse than none: it competes with the
                  nine existing ones and dilutes the site.
  * ``minor``   — advisory only, never refuses.

The PII criteria exist because the exposure is measured, not imagined: every CompanyCam project
carries a street address, half the project names ARE customer names, and one scope line held a
street address one curation click from a public page (see core.pii).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from core.photo_privacy import unsanitized_media
from core.pii import find_pii, person_name_risk

BLOCKING = ("blocker", "major")

_IMG_ALT_RE = re.compile(r'<img[^>]*\balt="([^"]*)"', re.I)
# Jon, 2026-08-11, answering Wendy's 10-20 range: 20 is the HARD MAX, 1 is the hard floor.
# The floor is deliberately permissive — a real project with one good photo should publish rather
# than be blocked — while the ceiling is Wendy's rule and is enforced strictly. Her stated 10 is
# an editorial target, not a gate; gating on it would have blocked Building 77 (9 tagged photos),
# the very fixture chosen to demo this.
_MIN_IMAGES = 1
_MAX_IMAGES = 20
_MIN_WORDS = 120


@dataclass(frozen=True)
class Criterion:
    key: str
    label: str
    ok: bool
    severity: str
    detail: str = ""
    evidence: tuple = field(default=())

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "label": self.label, "ok": self.ok,
                "severity": self.severity, "detail": self.detail,
                "evidence": list(self.evidence)}


def _plain(html: str) -> str:
    return re.sub(r"<[^>]+>", " ", html or "")


def check_project(
    *,
    title: str,
    city: str | None,
    meta: str,
    content_html: str,
    selections: Iterable[dict],
    scope_lines: Iterable[str] = (),
    jsonld: Iterable[dict] = (),
    permissions: dict[str, bool] | None = None,
) -> list[Criterion]:
    """Every criterion, in the order a reviewer cares about: privacy, permission, then quality."""
    perms = permissions or {}
    sels = list(selections)
    scope = list(scope_lines)
    nodes = list(jsonld)
    photos = [s for s in sels if s.get("kind") == "photo"]
    videos = [s for s in sels if s.get("kind") == "video"]
    text = _plain(content_html)
    out: list[Criterion] = []

    def add(key, label, ok, severity, detail="", evidence=()):
        out.append(Criterion(key, label, bool(ok), severity, detail, tuple(evidence)))

    # ── Privacy — blockers ────────────────────────────────────────────────
    # Body, meta, alt text and the schema are checked TOGETHER: an address removed from the
    # prose but left in an image alt or a JSON-LD caption is still published.
    surfaces = {
        "body": text,
        "meta": meta or "",
        "title": title or "",
        "alt text": " ".join(_IMG_ALT_RE.findall(content_html or "")),
        "schema": " ".join(
            str(v) for node in nodes for v in node.values() if isinstance(v, (str, int, float))
        ),
        "scope": " ".join(scope),
    }
    leaks = [f"{where}: {f.kind} {f.text!r}"
             for where, value in surfaces.items() for f in find_pii(value)]
    add("no_pii", "No address, unit, postcode, phone, email or GPS anywhere on the page",
        not leaks, "blocker",
        f"{len(leaks)} disclosure(s)" if leaks else "", leaks[:8])

    add("title_not_a_person", "Title is a property or organisation, not a customer's name",
        not person_name_risk(title, city), "blocker",
        "rename the project — it reads as an individual" if person_name_risk(title, city) else "")

    # CompanyCam burns the capture GPS into the pixels, which no text check can see (see
    # core/photo_privacy). Requiring every file to be WP-hosted means requiring it to have come
    # through the sanitizer — a question with a reliable answer, unlike "is there a stamp in it".
    # Covers <video> and its poster as well: those frames carry the same stamp, and there is no
    # video sanitizer yet, so this blocks video until one exists rather than shipping it stamped.
    unsanitized = unsanitized_media(content_html)
    add("media_sanitized", "Every image and video is WP-hosted, so the capture stamp was stripped",
        not unsanitized, "blocker",
        f"{len(unsanitized)} file(s) still on a third-party CDN" if unsanitized else "",
        unsanitized[:8])

    # ── Client permission — blockers ──────────────────────────────────────
    add("permission_property", "Client cleared naming the property",
        bool(perms.get("permission_property")), "blocker")
    add("permission_photos", "Client cleared using photos",
        bool(perms.get("permission_photos")) or not photos, "blocker",
        "" if perms.get("permission_photos") or not photos else f"{len(photos)} image(s) selected")
    add("permission_video", "Client cleared using video",
        bool(perms.get("permission_video")) or not videos, "blocker",
        "" if perms.get("permission_video") or not videos else f"{len(videos)} video(s) selected")

    # ── Quality — majors ──────────────────────────────────────────────────
    alts = [a.strip().lower() for a in _IMG_ALT_RE.findall(content_html or "")]
    add("gallery_size", f"At least {_MIN_IMAGES} curated image(s)", len(photos) >= _MIN_IMAGES,
        "major", f"{len(photos)} selected")
    add("gallery_max", f"No more than {_MAX_IMAGES} curated images", len(photos) <= _MAX_IMAGES,
        "major", f"{len(photos)} selected, max {_MAX_IMAGES}")
    add("alt_present", "Every image has alt text", all(alts) and len(alts) == len(photos),
        "major", f"{sum(1 for a in alts if not a)} missing")
    add("alt_unique", "No alt text reused between images",
        len(set(alts)) == len(alts) if alts else True, "major",
        f"{len(alts) - len(set(alts))} duplicate(s)")
    words = len(text.split())
    add("body_length", f"Write-up over {_MIN_WORDS} words", words > _MIN_WORDS, "major",
        f"{words} words")
    add("has_scope", "Scope of work stated", bool(scope), "major",
        "no contract scope matched — the page is generic" if not scope else f"{len(scope)} lines")

    # ── Advisory — minors ─────────────────────────────────────────────────
    types = {n.get("@type") for n in nodes}
    add("schema_present", "JSON-LD built (FAQPage / ImageObject / VideoObject)", bool(types),
        "minor", ", ".join(sorted(t for t in types if t)))
    add("schema_scoped", "No schema type Rank Math already owns",
        not (types - {"FAQPage", "ImageObject", "VideoObject"}), "minor",
        f"stray: {sorted(types - {'FAQPage', 'ImageObject', 'VideoObject'})}"
        if types - {"FAQPage", "ImageObject", "VideoObject"} else "")
    add("has_video", "Project video included", bool(videos), "minor")
    return out


def failing(criteria: Iterable[Criterion]) -> list[Criterion]:
    """Criteria that must be fixed before publish (blocker + major)."""
    return [c for c in criteria if not c.ok and c.severity in BLOCKING]


def blockers(criteria: Iterable[Criterion]) -> list[Criterion]:
    return [c for c in criteria if not c.ok and c.severity == "blocker"]


def publishable(criteria: Iterable[Criterion]) -> bool:
    return not failing(criteria)


def summary(criteria: Iterable[Criterion]) -> dict[str, Any]:
    items = list(criteria)
    return {
        "publishable": publishable(items),
        "blockers": [c.to_dict() for c in blockers(items)],
        "failing": [c.to_dict() for c in failing(items)],
        "criteria": [c.to_dict() for c in items],
    }
