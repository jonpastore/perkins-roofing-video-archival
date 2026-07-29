"""The single-flight guard.

The commit-on-acquire is the whole point: without it the holder sits idle-in-transaction for
the entire job, which (a) blocked a routine ALTER TABLE on 2026-07-29 and queued every reader
behind it, and (b) would now be killed outright by the 5-minute
idle_in_transaction_session_timeout, silently defeating single-flight.
"""
import pytest

from core.single_flight import single_flight


class _FakeSession:
    def __init__(self, acquired=True, dialect="postgresql"):
        self._acquired = acquired
        self.calls: list[str] = []
        self.info: dict = {}
        self.closed = False
        self.bind = type("B", (), {"dialect": type("D", (), {"name": dialect})()})()

    def execute(self, stmt, params=None):
        sql = str(stmt).lower()
        self.calls.append("lock" if "pg_try_advisory_lock" in sql
                          else "unlock" if "pg_advisory_unlock" in sql else "other")
        outer = self

        class _R:
            def scalar(self):
                return outer._acquired
        return _R()

    def commit(self):
        self.calls.append("commit")

    def close(self):
        self.closed = True


def test_lock_is_committed_immediately_so_the_holder_is_not_idle_in_transaction():
    session = _FakeSession()
    with single_flight(lambda: session, 42) as held:
        assert held is True
        # By the time the job body runs, the acquiring transaction must already be closed.
        assert session.calls == ["lock", "commit"], (
            "the holder must not sit idle-in-transaction for the life of the job"
        )
    assert session.calls == ["lock", "commit", "unlock", "commit"]
    assert session.closed is True


def test_a_second_process_is_told_to_skip():
    session = _FakeSession(acquired=False)
    with single_flight(lambda: session, 42) as held:
        assert held is False
    # Never unlock a lock we do not hold — that would release the RUNNING job's lock.
    assert "unlock" not in session.calls
    assert session.closed is True


def test_session_is_closed_even_when_the_job_raises():
    session = _FakeSession()
    with pytest.raises(RuntimeError):
        with single_flight(lambda: session, 42):
            raise RuntimeError("job blew up")
    assert session.calls.count("unlock") == 1, "a crashed job must still release the lock"
    assert session.closed is True


def test_sqlite_is_a_no_op_pass_through():
    """Tests run single-process; the guard exists for prod concurrency only."""
    session = _FakeSession(dialect="sqlite")
    with single_flight(lambda: session, 42) as held:
        assert held is True
    assert session.calls == [], "no advisory-lock SQL on a backend that has none"
    assert session.closed is True
