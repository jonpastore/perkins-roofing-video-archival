"""Deterministic grounding check: does the article name things Tim never said?

Pure string logic, no LLM and no I/O — because the LLM critic demonstrably cannot do this job.
Given 9,389 words of Tim's transcripts, the grounding critic passed an article that instructed
readers to cut 45-degree angles on "Polyblast paper" — a product that appears nowhere in Tim's
vocabulary (he says polyglass, polyflash, polyfresco, polyurethane). A model asked to catch
another model's fabrications returned "clean, stopping".

A substring check cannot be persuaded. It is narrow on purpose: it only judges PROPER NOUNS —
brands, products, standards, codes — because those are the fabrications with consequences on a
licensed roofer's site. Invented adjectives are ugly; an invented product spec or code cite is
a liability.
"""
from __future__ import annotations

import re

# Capitalised tokens that are ordinary English, structural, or our own boilerplate — flagging
# these would be noise, not signal.
_STOPWORDS = {
    "a", "an", "and", "the", "or", "but", "if", "then", "this", "that", "these", "those",
    "for", "of", "to", "in", "on", "at", "by", "with", "from", "as", "is", "are", "was",
    "it", "its", "you", "your", "we", "our", "they", "their", "he", "she", "his", "her",
    "what", "when", "where", "why", "how", "who", "which", "can", "will", "do", "does",
    "not", "no", "yes", "all", "any", "each", "more", "most", "some", "such", "than",
    "table", "contents", "frequently", "asked", "questions", "faq", "conclusion", "summary",
    "introduction", "overview", "step", "steps", "tip", "tips", "guide", "essential", "key",
    "common", "mistakes", "avoid", "understanding", "basics", "practice", "next", "ready",
    "start", "learn", "more", "read", "watch", "video", "youtube", "click", "here",
    "january", "february", "march", "april", "may", "june", "july", "august", "september",
    "october", "november", "december", "monday", "tuesday", "wednesday", "thursday",
    "friday", "saturday", "sunday",
}

# Multi-word proper nouns are matched as a unit first, so "Miami Dade County" is one term
# rather than three. Word chars plus the punctuation real product names use (Polyflash 1C,
# ASTM D226, Ice & Water Shield).
_PROPER_RUN = re.compile(r"\b([A-Z][\w&.-]*(?:\s+(?:[A-Z][\w&.-]*|\d+[A-Z]?))*)\b")
_TAG = re.compile(r"<[^>]+>")
_URL = re.compile(r"https?://\S+")
# Block-level boundaries. Collapsing these to a space welds a heading onto the paragraph under
# it, and the greedy proper-noun run then invents cross-boundary phrases out of thin air —
# "Key Materials Used in Fire and Water Barriers" + "Proper installation..." reported as the
# term "Materials Proper". Every such flag is noise, and noise is what gets a guard ignored.
_BLOCK_END = re.compile(r"</(?:h[1-6]|p|li|div|td|th|blockquote|section)\s*>|<br\s*/?>",
                        re.IGNORECASE)


def _plain(text: str) -> str:
    """Strip HTML and URLs — a brand inside a link href is not a claim about the world."""
    text = _URL.sub(" ", text or "")
    text = _BLOCK_END.sub(". ", text)  # keep the boundary the markup implies
    return _TAG.sub(" ", text)


def _normalise(s: str) -> str:
    """Fold to a comparable form: lowercase, punctuation to SPACE, collapse whitespace.

    Punctuation becomes a space rather than being deleted. Deleting it welded "L-flashing" into
    the token "lflashing", which matches nothing — while Tim plainly says "on all of our L
    flashings". Every fabrication this guard first reported (L-flashing, T-patches, Z-channel,
    T-joint, Miami-Dade) was this bug, not a hallucination. A guard whose false positives look
    exactly like real findings is worse than no guard.
    """
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", (s or "").lower())).strip()


def candidate_terms(content: str) -> set[str]:
    """Proper-noun-ish terms an article asserts. Sentence-initial words are excluded: they are
    capitalised by grammar, not because they name anything."""
    text = _plain(content)
    out: set[str] = set()
    for sentence in re.split(r"(?<=[.!?:;])\s+|\n+", text):
        sentence = sentence.strip()
        if not sentence:
            continue
        for m in _PROPER_RUN.finditer(sentence):
            if m.start() == 0:  # first word of the sentence — capitalisation proves nothing
                continue
            term = m.group(1).strip()
            words = [w for w in term.split() if _normalise(w) not in _STOPWORDS]
            if not words:
                continue
            term = " ".join(words)
            if len(_normalise(term)) < 4:  # too short to be a distinctive name
                continue
            if _normalise(term) in _STOPWORDS:
                continue
            out.add(term)
    return out


def unsourced_terms(content: str, transcript: str, ignore: object = ()) -> list[str]:
    """Terms the article names that do not appear in Tim's transcripts, worst-first.

    A term is sourced if it appears in the transcript, or if every one of its words does — the
    latter covers Tim saying "polyglass" and the writer titling a section "Polyglass Systems".
    Speech transcripts are unpunctuated and inconsistently cased, so matching is normalised.

    `ignore` holds strings that are ours, not claims about the world — chiefly the focus
    keyword, which is derived from the article slug. Flagging "Hurricane Season Roofing
    Preparedness" because Tim never says the word "preparedness" is noise.
    """
    src = _normalise(_plain(transcript))
    if not src:
        return []
    src_words = set(src.split())
    skip = {_normalise(s) for s in ([ignore] if isinstance(ignore, str) else ignore)}
    missing: list[str] = []
    for term in candidate_terms(content):
        norm = _normalise(term)
        if not norm or norm in src or norm in skip:
            continue
        if any(norm in s or s in norm for s in skip if s):
            continue  # a rewording of our own keyword
        if all(w in src_words for w in norm.split()):
            continue  # every component word is Tim's; only the combination is ours
        missing.append(term)
    # Longest first: "Polyblast Paper System" is a more informative report than "Polyblast".
    return sorted(set(missing), key=lambda t: (-len(t), t.lower()))
