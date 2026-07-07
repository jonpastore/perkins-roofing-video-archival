"""Test isolation: bind app.models to a fresh temp SQLite DB before any test imports it.

Without this, the first test to import app.models (e.g. via api.app) binds the module-global
engine to the real app/dev.db (an old POC DB missing newer columns like archive_uri), which
then leaks into every other test. Setting DB_URL here — before collection imports anything —
guarantees a clean, current-schema database for the whole suite.
"""
import os
import tempfile

_tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp.close()
os.environ["DB_URL"] = f"sqlite:///{_tmp.name}"


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_auth_verifier():
    """Reset the injected auth verifier after every test so a file that sets it can't leak
    into another (a hidden ordering dependency the audit flagged)."""
    yield
    try:
        from api.auth import set_verifier
        set_verifier(None)
    except Exception:
        pass
