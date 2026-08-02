"""The commit-message parser behind the R6.3 hooks (scripts/task_hooks.py).

Worth testing because it decides whether a task gets CLOSED. A parser that is too eager closes
work that is not done; one that is too shy recreates the failure it exists to fix — six tasks
describing already-shipped work, found 2026-08-02.

Only `parse()` is covered here: it is the pure part. The API calls are one urllib POST each and
are exercised for real by the hooks themselves.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_spec = importlib.util.spec_from_file_location(
    "task_hooks", Path(__file__).parent.parent / "scripts" / "task_hooks.py")
task_hooks = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(task_hooks)
parse = task_hooks.parse


def test_closes_and_verified_are_both_found():
    got = parse("fix(estimator): guard the split\n\nCloses #453\nVerified: pytest -k Split, 19 passed\n")
    assert got["closes"] == [453]
    assert got["verified"].startswith("pytest -k Split")


@pytest.mark.parametrize("word", ["Closes", "closes", "Fixes", "resolves"])
def test_close_synonyms(word):
    assert parse(f"subject\n\n{word} #12\nVerified: ran it\n")["closes"] == [12]


def test_refs_carries_progress_and_never_closes():
    got = parse("subject\n\nRefs #429 60%\n")
    assert got["refs"] == [(429, 60)]
    assert got["closes"] == []


def test_refs_without_a_percentage_is_a_link_not_a_number():
    assert parse("subject\n\nRefs #429\n")["refs"] == [(429, None)]


def test_two_tasks_closed_by_one_commit():
    """The exact shape of 4fd78f7, which fixed #409 and #410 and closed neither."""
    got = parse("fix: #409 test hang + #410 video-id guard\n\nCloses #409\nCloses #410\n"
                "Verified: pytest tests/api/test_topics.py, 36 passed\n")
    assert got["closes"] == [409, 410]


def test_a_task_number_in_the_subject_is_not_an_intent():
    """`fix: #409 test_topics live-LLM hang` names a task and closes nothing — that is how the
    real commit behaved, and the parser must not silently upgrade a mention into a close."""
    got = parse("fix: #409 test_topics live-LLM hang + #410 placeholder guard\n\nbody text\n")
    assert got["closes"] == [] and got["refs"] == []


def test_no_task_opt_out_is_distinguishable_from_forgetting():
    assert parse("chore: typo\n\nNo-Task: docs typo\n")["no_task"] is True
    assert parse("chore: typo\n\nno body\n")["no_task"] is False


def test_comment_lines_are_ignored():
    """git's own commit template is comments; a `# Closes #1` in it must not close task 1."""
    assert parse("subject\n\n# Closes #1\nNo-Task: n/a\n")["closes"] == []
