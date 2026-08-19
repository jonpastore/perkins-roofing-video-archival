"""Topic / FAQ graph: genre taxonomy, coverage, SEO/AIO scores, density.

Pure functions. Callers fetch rows; this module groups and scores them.
Genres are a locked marketing taxonomy — not embedding clusters — so Tim
can see inequality and we stop generating synonym pillars.
"""
from __future__ import annotations

import math
import re
from typing import Iterable

# (id, label, publishable, pattern) — first match wins.
GENRES: tuple[tuple[str, str, bool, str], ...] = (
    ("internal", "Internal / do not publish", False,
     r"\b(franchise|franchising|franchisee|overhead|leadership|"
     r"work[\s-]?in[\s-]?progress|wip accounting|accounting|"
     r"business building|sales techniques?)\b"),
    ("comparisons", "Comparisons", True, r"\bvs\.?\b|\bversus\b"),
    ("windows", "Windows / doors", True,
     r"\b(impact windows?|impact doors?|windows? and doors?|low-?e|"
     r"single-?hung|hurricane shutter)\b"),
    ("weather", "Weather / insurance", True,
     r"\b(hurricane|storm|salt\s?air|saltwater|insurance|wind mitigation|"
     r"el ni[nñ]o|nhc|nws)\b"),
    ("underlayment", "Underlayment", True,
     r"\b(underlayment|tu\+|tu plus|mts\+?|xfr|secondary water barrier|"
     r"vapor barrier)\b"),
    ("flashings", "Flashings / valleys", True,
     r"\b(flashing|valley metal|eave|rake tile|drip metal|termination bar|"
     r"counter flashing|wall flashing)\b"),
    ("vents", "Vents / penetrations", True,
     r"\b(gooseneck|ridge vent|exhaust vent|solar vent|attic breeze|"
     r"roof vent)\b"),
    ("flat", "Flat / TPO / EPDM", True,
     r"\b(flat roof|tpo|epdm|built-?up|modified bitumen|60-?mil)\b"),
    ("tile", "Tile", True,
     r"\b(tile|clay|concrete tile|foam method|s-?tile)\b"),
    ("metal", "Metal", True,
     r"\b(metal|standing seam|snap-?lock|5v|mill finish|stone-?coated|"
     r"aluminum roof|galvalume|24-?gauge)\b"),
    ("shingle", "Shingle", True, r"\b(shingle|three-?tab|architectural shingle)\b"),
    ("code", "Code / HVHZ / HOA", True,
     r"\b(hvhz|hoa|florida (building )?code|miami-?dade|asce|noa|permit|"
     r"wind rating|uplift)\b"),
    ("repair", "Repair / leaks", True,
     r"\b(leak|repair|ponding|drywall|sistering|truss repair)\b"),
    ("cost", "Cost / warranty", True,
     r"\b(cost|price|warranty|warranties|estimate|roi)\b"),
    ("process", "Process / install", True,
     r"\b(install|installation|demolition|walking on|how to|process)\b"),
    ("other", "Other", True, r"."),
)

_ENTITY_RE = re.compile(
    r"\b(polyglass|tu\+|tu plus|mts\+?|xfr|gaf|boral|eagle|mcelroy|"
    r"hvhz|miami-?dade|asce|noa|60-?mil|24-?gauge|martin county|"
    r"palm beach|saltwater)\b",
    re.I,
)

_ALPHA = 1.2


def slugify(text: str, n: int = 80) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:n]


def _norm(text: str) -> str:
    return (text or "").strip().lower()


def genre_catalog() -> list[dict]:
    return [{"id": gid, "label": glabel, "publishable": pub} for gid, glabel, pub, _ in GENRES]


def video_genre(title: str, description: str = "") -> dict:
    gid, glabel, pub = classify_label(f"{title or ''} {description or ''}")
    return {"id": gid, "label": glabel, "publishable": pub}


def classify_label(label: str) -> tuple[str, str, bool]:
    """Return (genre_id, genre_label, publishable). First matching genre wins."""
    blob = _norm(label)
    for gid, glabel, pub, pat in GENRES:
        if re.search(pat, blob, re.I):
            return gid, glabel, pub
    return "other", "Other", True


def article_covered(label: str, cov: dict) -> bool:
    """Covered if keyword, title, slug, or parent pillar already exists."""
    key = _norm(label)
    sl = slugify(label)
    return (
        key in cov["keywords"]
        or key in cov["titles"]
        or sl in cov["slugs"]
        or sl in cov["pillars"]
    )


def coverage_from_articles(rows: Iterable) -> dict:
    """rows: (slug, pillar_slug, title, focus_keyword) or objects with those attrs."""
    slugs: set[str] = set()
    pillars: set[str] = set()
    titles: set[str] = set()
    keywords: set[str] = set()
    for row in rows:
        if hasattr(row, "slug"):
            slug, pillar, title, kw = row.slug, row.pillar_slug, row.title, row.focus_keyword
        else:
            slug = row[0] if row else None
            pillar = row[1] if len(row) > 1 else None
            title = row[2] if len(row) > 2 else None
            kw = row[3] if len(row) > 3 else None
        if slug:
            slugs.add(slug)
        if pillar:
            pillars.add(pillar)
        if title:
            titles.add(_norm(title))
        if kw:
            keywords.add(_norm(kw))
    return {"slugs": slugs, "pillars": pillars, "titles": titles, "keywords": keywords}


def engagement_score(views: float, likes: float, comments: float) -> float:
    """Comments and likes outrank raw views (a 958k / 0-comment video is reach, not intent)."""
    return (
        2.0 * math.log1p(max(0.0, comments))
        + math.log1p(max(0.0, likes))
        + 0.25 * math.log1p(max(0.0, views))
    )


def diversity_weight(published_in_genre: int, alpha: float = _ALPHA) -> float:
    return 1.0 / ((1 + max(0, published_in_genre)) ** alpha)


def aio_boost(label: str) -> float:
    """AIO prefers named entities (product, code, place) over synonym stacks."""
    return 1.0 if _ENTITY_RE.search(label or "") else 0.0


def opportunity(
    *,
    demand: float,
    grounding: float,
    uniqueness: float,
    aio: float,
    diversity: float,
) -> float:
    if uniqueness <= 0:
        return 0.0
    return uniqueness * (0.35 * demand + 0.25 * grounding + 0.20 * aio + 0.20) * diversity


def herfindahl(counts: list[int]) -> float:
    total = sum(counts)
    if total <= 0:
        return 0.0
    return sum((c / total) ** 2 for c in counts)


def shannon_evenness(counts: list[int]) -> float:
    present = [c for c in counts if c > 0]
    if len(present) <= 1:
        return 0.0 if present else 1.0
    total = sum(present)
    entropy = -sum((c / total) * math.log(c / total) for c in present)
    return entropy / math.log(len(present))


def density_flag(
    genre_id: str,
    *,
    n_published: int,
    published_share: float,
    subject_share: float,
) -> str:
    if genre_id == "internal":
        return "internal"
    if n_published == 0:
        return "empty"
    if n_published >= 8 and subject_share > 0 and published_share > 1.5 * subject_share:
        return "over_served"
    if subject_share > 0 and published_share < 0.5 * subject_share:
        return "under_served"
    return "balanced"


def color_for(genre_id: str, *, n_published: int, yt_heat: float, grounding: float) -> str:
    if genre_id == "internal":
        return "amber"
    if n_published == 0 and yt_heat > 0:
        return "green"
    if n_published == 0 and grounding <= 0 and yt_heat <= 0:
        return "red"
    if n_published > 0:
        return "navy"
    return "green"


def _empty_bucket(gid: str, glabel: str, pub: bool) -> dict:
    return {
        "id": gid,
        "label": glabel,
        "publishable": pub,
        "n_subjects": 0,
        "n_variants": 0,
        "n_published": 0,
        "n_unpublished": 0,
        "covered_subjects": 0,
        "yt_views": 0,
        "yt_likes": 0,
        "yt_comments": 0,
        "grounding_seconds": 0.0,
        "opportunity": 0.0,
        "subjects": {},
    }


def _video_key(row: dict) -> str:
    return str(row.get("video_id") or "")


def build_article_graph(
    topics: list[dict],
    articles: list[dict],
    *,
    published: str = "all",
) -> dict:
    """topics: label, video_id, duration, views, likes, comments.
    articles: slug, title, status, role, focus_keyword, pillar_slug.
    published: all | yes | no
    """
    cov = coverage_from_articles(
        (a.get("slug"), a.get("pillar_slug"), a.get("title"), a.get("focus_keyword"))
        for a in articles
    )
    pub_articles = [a for a in articles if (a.get("status") or "") == "published"]

    buckets: dict[str, dict] = {
        gid: _empty_bucket(gid, glabel, pub) for gid, glabel, pub, _ in GENRES
    }

    for t in topics:
        label = (t.get("label") or "").strip()
        if not label:
            continue
        gid, glabel, pub = classify_label(label)
        b = buckets[gid]
        sub_key = slugify(label) or _norm(label)
        sub = b["subjects"].setdefault(sub_key, {
            "label": label,
            "slug": sub_key,
            "variants": set(),
            "video_ids": set(),
            "yt_views": 0,
            "yt_likes": 0,
            "yt_comments": 0,
            "grounding_seconds": 0.0,
            "covered": False,
            "articles": [],
        })
        sub["variants"].add(label)
        vid = _video_key(t)
        if vid and vid not in sub["video_ids"]:
            sub["video_ids"].add(vid)
            sub["yt_views"] += int(t.get("views") or 0)
            sub["yt_likes"] += int(t.get("likes") or 0)
            sub["yt_comments"] += int(t.get("comments") or 0)
            sub["grounding_seconds"] += float(t.get("duration") or 0)
        if article_covered(label, cov):
            sub["covered"] = True

    for a in articles:
        blob = " ".join(
            x for x in (
                a.get("focus_keyword") or "",
                a.get("title") or "",
                (a.get("slug") or "").replace("-", " "),
            ) if x
        )
        gid, _, _ = classify_label(blob)
        sl = a.get("slug") or slugify(a.get("focus_keyword") or a.get("title") or "")
        b = buckets[gid]
        sub = b["subjects"].setdefault(sl, {
            "label": a.get("focus_keyword") or a.get("title") or sl,
            "slug": sl,
            "variants": set(),
            "video_ids": set(),
            "yt_views": 0,
            "yt_likes": 0,
            "yt_comments": 0,
            "grounding_seconds": 0.0,
            "covered": True,
            "articles": [],
        })
        sub["covered"] = True
        if sl:
            sub["articles"].append(a)

    return _finalize(buckets, published, kind="articles", n_items=len(articles),
                     n_published=len(pub_articles))


def build_faq_graph(
    faqs: list[dict],
    unmined: list[dict],
    *,
    published: str = "all",
) -> dict:
    """faqs: question, status, video_id, has_answer, views, likes, comments, duration.
    unmined: question, video_id, views, likes, comments, duration.
    A FAQ is 'published' when it has an answer.
    """
    buckets: dict[str, dict] = {
        gid: _empty_bucket(gid, glabel, pub) for gid, glabel, pub, _ in GENRES
    }

    def _add(question: str, *, answered: bool, row: dict) -> None:
        q = (question or "").strip()
        if not q:
            return
        gid, _, _ = classify_label(q)
        b = buckets[gid]
        key = slugify(q) or _norm(q)
        sub = b["subjects"].setdefault(key, {
            "label": q,
            "slug": key,
            "variants": set(),
            "video_ids": set(),
            "yt_views": 0,
            "yt_likes": 0,
            "yt_comments": 0,
            "grounding_seconds": 0.0,
            "covered": answered,
            "articles": [],
        })
        sub["variants"].add(q)
        if answered:
            sub["covered"] = True
        vid = _video_key(row)
        if vid and vid not in sub["video_ids"]:
            sub["video_ids"].add(vid)
            sub["yt_views"] += int(row.get("views") or 0)
            sub["yt_likes"] += int(row.get("likes") or 0)
            sub["yt_comments"] += int(row.get("comments") or 0)
            sub["grounding_seconds"] += float(row.get("duration") or 0)
        if answered:
            sub["articles"].append({
                "slug": key,
                "title": q,
                "status": "published",
                "role": "faq",
                "focus_keyword": q,
                "pillar_slug": None,
            })

    n_answered = 0
    for f in faqs:
        answered = bool(f.get("has_answer")) or (f.get("status") == "answered")
        if answered:
            n_answered += 1
        _add(f.get("question") or "", answered=answered, row=f)
    for u in unmined:
        _add(u.get("question") or "", answered=False, row=u)

    return _finalize(
        buckets, published, kind="faqs",
        n_items=len(faqs) + len(unmined), n_published=n_answered,
    )


def _finalize(
    buckets: dict[str, dict],
    published: str,
    *,
    kind: str,
    n_items: int,
    n_published: int,
) -> dict:
    pub_counts = []
    subject_counts = []
    for gid, b in buckets.items():
        if not b["publishable"] or gid == "other":
            continue
        n_sub = len(b["subjects"])
        n_pub_sub = sum(1 for s in b["subjects"].values() if s["covered"])
        pub_counts.append(n_pub_sub)
        subject_counts.append(n_sub)

    total_pub = sum(pub_counts) or 1
    total_sub = sum(subject_counts) or 1

    genres_out = []
    flags = []
    for gid, glabel, pub, _ in GENRES:
        b = buckets[gid]
        subjects_raw = list(b["subjects"].values())
        n_pub_sub = sum(1 for s in subjects_raw if s["covered"])
        n_unpub_sub = len(subjects_raw) - n_pub_sub
        if published == "yes":
            subjects_raw = [s for s in subjects_raw if s["covered"]]
        elif published == "no":
            subjects_raw = [s for s in subjects_raw if not s["covered"]]

        yt_views = sum(s["yt_views"] for s in subjects_raw)
        yt_likes = sum(s["yt_likes"] for s in subjects_raw)
        yt_comments = sum(s["yt_comments"] for s in subjects_raw)
        grounding = sum(s["grounding_seconds"] for s in subjects_raw)
        div_w = diversity_weight(n_pub_sub if pub else 99)
        subjects = []
        genre_opp = 0.0
        for s in subjects_raw:
            uniq = 0.0 if s["covered"] else 1.0
            dmd = engagement_score(s["yt_views"], s["yt_likes"], s["yt_comments"])
            ground = math.log1p(s["grounding_seconds"])
            opp = 0.0 if not pub else opportunity(
                demand=dmd, grounding=ground, uniqueness=uniq,
                aio=aio_boost(s["label"]), diversity=div_w,
            )
            genre_opp += opp
            leaf_articles = s["articles"]
            if published == "yes":
                leaf_articles = [a for a in leaf_articles if (a.get("status") or "") == "published"]
            elif published == "no":
                leaf_articles = [a for a in leaf_articles if (a.get("status") or "") != "published"]
            subjects.append({
                "label": s["label"],
                "slug": s["slug"],
                "n_variants": len(s["variants"]) or 1,
                "n_videos": len(s["video_ids"]),
                "yt_views": s["yt_views"],
                "yt_likes": s["yt_likes"],
                "yt_comments": s["yt_comments"],
                "grounding_seconds": round(s["grounding_seconds"], 1),
                "covered": s["covered"],
                "opportunity": round(opp, 4),
                "aio": aio_boost(s["label"]),
                "articles": [
                    {
                        "slug": a.get("slug"),
                        "title": a.get("title"),
                        "status": a.get("status"),
                        "role": a.get("role"),
                    }
                    for a in leaf_articles
                ],
            })
        subjects.sort(key=lambda x: (-x["opportunity"], -x["yt_comments"], x["label"]))

        p_share = n_pub_sub / total_pub
        s_share = (len(b["subjects"]) / total_sub) if b["subjects"] else 0.0
        flag = density_flag(
            gid, n_published=n_pub_sub, published_share=p_share, subject_share=s_share,
        )
        if flag in ("over_served", "under_served", "empty") and pub:
            flags.append({"genre": glabel, "flag": flag})
        color = color_for(
            gid, n_published=n_pub_sub,
            yt_heat=float(yt_likes + yt_comments), grounding=grounding,
        )
        n_variants = sum(len(s["variants"]) or 1 for s in b["subjects"].values())
        if published != "all" and not subjects:
            continue
        genres_out.append({
            "id": gid,
            "label": glabel,
            "publishable": pub,
            "n_subjects": len(subjects),
            "n_variants": n_variants,
            "n_published": n_pub_sub if published != "no" else 0,
            "n_unpublished": n_unpub_sub if published != "yes" else 0,
            "covered_subjects": n_pub_sub,
            "yt_views": yt_views,
            "yt_likes": yt_likes,
            "yt_comments": yt_comments,
            "grounding_seconds": round(grounding, 1),
            "opportunity": round(genre_opp, 4),
            "coverage": round(n_pub_sub / len(b["subjects"]), 3) if b["subjects"] else 0.0,
            "density": flag,
            "color": color,
            "subjects": subjects,
        })

    return {
        "kind": kind,
        "published_filter": published,
        "genres": genres_out,
        "diversity": {
            "herfindahl": round(herfindahl(pub_counts), 4),
            "shannon": round(shannon_evenness(pub_counts), 4),
            "flags": flags,
            "concentrated": herfindahl(pub_counts) >= 0.25,
        },
        "totals": {
            "items": n_items,
            "published": n_published,
            "genres": len(genres_out),
        },
        "legend": {
            "navy": "Published inventory",
            "green": "Audience already watches this — no article/FAQ yet",
            "amber": "Internal / do not publish on the site",
            "red": "No video and no page — Tim brief",
        },
    }


def pick_next_label(
    candidates: list[dict],
    cov: dict,
    published_per_genre: dict[str, int] | None = None,
) -> dict | None:
    """Highest-opportunity uncovered, non-internal candidate.

    candidates: {label, total_seconds, views, likes, comments}
    """
    published_per_genre = published_per_genre or {}
    best = None
    best_score = -1.0
    for c in candidates:
        label = (c.get("label") or "").strip()
        if not label:
            continue
        gid, _, pub = classify_label(label)
        if not pub:
            continue
        if article_covered(label, cov):
            continue
        dmd = engagement_score(
            float(c.get("views") or 0),
            float(c.get("likes") or 0),
            float(c.get("comments") or 0),
        )
        score = opportunity(
            demand=dmd,
            grounding=math.log1p(float(c.get("total_seconds") or 0)),
            uniqueness=1.0,
            aio=aio_boost(label),
            diversity=diversity_weight(published_per_genre.get(gid, 0)),
        )
        if score > best_score:
            best_score = score
            best = {**c, "label": label, "genre": gid, "opportunity": score}
    return best
