"""What to cut for social and what to film next.

Uses the same heat (comments > likes > views) and genre gaps as the topic
graph. No LLM. Callers attach optional edit-plan details per video.
"""
from __future__ import annotations

from core.clip_package import CLIP_MAX_SECS, CLIP_MIN_SECS
from core.edit_plan import EVAL_MAX_SECS, LONG_SECS
from core.topic_graph import classify_label, engagement_score, video_genre

_RANGE = f"{CLIP_MIN_SECS}–{CLIP_MAX_SECS}s"

_ACTION_FORMAT = {
    "post_short": f"Package as a {_RANGE} Short/reel and post",
    "cut_to_short": f"Cut to 1–3 × {_RANGE} Shorts",
    "tighten_or_split": f"Tighten or split, then cut {_RANGE}",
    "chop": f"Chop into standalone clips, then pick the hottest {_RANGE}",
}
_ACTION_EFFORT = {
    "post_short": 10,
    "cut_to_short": 20,
    "tighten_or_split": 35,
    "chop": 50,
}

_QUESTION = ("how ", "what ", "why ", "when ", "does ", "do ", "can ", "is ", "should ")


def social_action(*, duration: float, has_clips: bool, has_social: bool) -> str | None:
    if has_social:
        return None
    dur = float(duration or 0)
    if dur >= EVAL_MAX_SECS:
        return "chop"
    if dur >= LONG_SECS:
        return "tighten_or_split"
    if 45 <= dur <= 180:
        return "post_short"
    if dur > 180:
        return "cut_to_short"
    return None


def _why(action: str, comments: int, duration: float) -> str:
    mins = int(duration // 60)
    if action == "post_short":
        return f"{comments} comments — already short; package as {_RANGE} with town + problem in 3s."
    if action == "cut_to_short":
        return f"{mins} min with audience heat — cut to {_RANGE} for Reels/Shorts."
    if action == "tighten_or_split":
        return f"{mins} min — tighten fluff or split on topic changes before posting."
    return f"{mins} min — chop into standalone clips, then pick the hottest piece."


def rank_cut_for_social(videos: list[dict], *, limit: int = 12) -> list[dict]:
    ranked = []
    for v in videos:
        action = social_action(
            duration=float(v.get("duration") or 0),
            has_clips=bool(v.get("has_clips")),
            has_social=bool(v.get("has_social")),
        )
        if action is None:
            continue
        views = int(v.get("views") or 0)
        likes = int(v.get("likes") or 0)
        comments = int(v.get("comments") or 0)
        heat = engagement_score(views, likes, comments)
        if heat <= 0 and action != "post_short":
            continue
        genre = video_genre(v.get("title") or "")
        ranked.append({
            "id": v.get("id"),
            "title": v.get("title") or v.get("id"),
            "duration": float(v.get("duration") or 0),
            "views": views,
            "likes": likes,
            "comments": comments,
            "heat": round(heat, 3),
            "action": action,
            "why": _why(action, comments, float(v.get("duration") or 0)),
            "genre": genre["label"],
            "genre_id": genre["id"],
            "has_clips": bool(v.get("has_clips")),
        })
    ranked.sort(key=lambda r: (-r["heat"], -r["comments"]))
    return ranked[:limit]


def _is_question(text: str) -> bool:
    t = (text or "").strip().lower()
    if not t:
        return False
    if "?" in t:
        return True
    return t.startswith(_QUESTION)


def rank_film_next(
    genres: list[dict],
    comments: list[dict],
    *,
    limit: int = 8,
) -> list[dict]:
    qs_by_genre: dict[str, list[str]] = {}
    for c in comments:
        text = (c.get("text") or "").strip()
        if not _is_question(text):
            continue
        gid, glabel, pub = classify_label(text)
        if not pub:
            continue
        qs_by_genre.setdefault(gid, []).append(text[:160])

    rows = []
    for g in genres:
        if not g.get("publishable") or g.get("id") == "internal":
            continue
        density = g.get("density") or "balanced"
        grounding = float(g.get("grounding_seconds") or 0)
        if density not in {"empty", "under_served"} and grounding >= 3600:
            continue
        gid = g.get("id") or ""
        questions = qs_by_genre.get(gid, [])[:3]
        if density not in {"empty", "under_served"} and not questions:
            continue
        why = (
            "No footage and no page — film this."
            if density == "empty"
            else "Thin coverage vs the rest of the catalogue — film a new angle."
            if density == "under_served"
            else "Audience is asking this and we barely cover it."
        )
        rows.append({
            "id": gid,
            "label": g.get("label") or gid,
            "density": density,
            "opportunity": float(g.get("opportunity") or 0),
            "grounding_seconds": grounding,
            "n_unpublished": int(g.get("n_unpublished") or 0),
            "why": why,
            "questions": questions,
        })
    rows.sort(key=lambda r: (
        0 if r["density"] == "empty" else 1 if r["density"] == "under_served" else 2,
        -r["opportunity"],
        -len(r["questions"]),
    ))
    return rows[:limit]


def rank_write_next(genres: list[dict], *, limit: int = 12) -> list[dict]:
    rows = []
    for g in genres:
        if not g.get("publishable") or g.get("id") == "internal":
            continue
        for s in g.get("subjects") or []:
            if s.get("covered"):
                continue
            opp = float(s.get("opportunity") or 0)
            if opp <= 0:
                continue
            rows.append({
                "id": s.get("slug") or s.get("label"),
                "label": s.get("label") or "",
                "opportunity": opp,
                "genre": g.get("label") or "",
                "genre_id": g.get("id") or "",
                "yt_comments": int(s.get("yt_comments") or 0),
                "why": "Uncovered topic with demand — write or refresh a page.",
            })
    rows.sort(key=lambda r: (-r["opportunity"], -r["yt_comments"]))
    return rows[:limit]


def _cut_action(row: dict) -> dict:
    action = row.get("action") or "cut_to_short"
    kind = "post" if action == "post_short" else "cut"
    return {
        "kind": kind,
        "id": row.get("id"),
        "title": row.get("title") or row.get("id"),
        "score": float(row.get("heat") or 0),
        "score_kind": "heat",
        "action": action,
        "why": row.get("why") or "",
        "format": _ACTION_FORMAT.get(action, f"Cut to {_RANGE}"),
        "primary": "Publish" if kind == "post" else "Review",
        "effort_min": _ACTION_EFFORT.get(action, 20),
    }


def _film_action(row: dict) -> dict:
    return {
        "kind": "film",
        "id": row.get("id"),
        "title": row.get("label") or row.get("id"),
        "score": float(row.get("opportunity") or 0),
        "score_kind": "opportunity",
        "action": "film_next",
        "why": row.get("why") or "",
        "format": f"Film one {_RANGE} answer",
        "primary": "Film",
        "effort_min": 30,
        "questions": list(row.get("questions") or []),
        "genre_id": row.get("id") or "",
    }


def _write_action(row: dict) -> dict:
    return {
        "kind": "write",
        "id": row.get("id"),
        "title": row.get("label") or row.get("id"),
        "score": float(row.get("opportunity") or 0),
        "score_kind": "opportunity",
        "action": "write",
        "why": row.get("why") or "",
        "format": "Write or refresh the page",
        "primary": "Write",
        "effort_min": 40,
        "genre": row.get("genre") or "",
        "genre_id": row.get("genre_id") or "",
    }


def rank_this_week(
    cuts: list[dict],
    films: list[dict],
    writes: list[dict],
    *,
    limit: int = 5,
    max_cuts: int = 3,
) -> list[dict]:
    """Five actions for this week. Existing high-heat footage ships first."""
    cut_rows = sorted((_cut_action(c) for c in cuts), key=lambda r: -r["score"])
    other = sorted(
        [_film_action(f) for f in films] + [_write_action(w) for w in writes],
        key=lambda r: -r["score"],
    )
    picked = cut_rows[:max_cuts]
    for row in other:
        if len(picked) >= limit:
            break
        picked.append(row)
    if len(picked) < limit:
        picked.extend(cut_rows[max_cuts:limit])
    return picked[:limit]
