"""Meta-test: every Pydantic str field in api/routes that maps to a length-bounded
DB column must carry max_length <= that column's length.

Why: the test suite runs on SQLite, which IGNORES VARCHAR(n) limits — oversized
input passes every endpoint test, then 500s on prod Postgres ("value too long for
type character varying(N)"). That exact bug shipped (property state="Florida",
fixed in 16a662b). Pydantic max_length turns it into a clean 422 on both DBs.

This test introspects ALL route modules so any future schema/column drift fails
here instead of in prod. Matching heuristic: a schema field is tied to a bounded
column when (a) a table whose ORM class is referenced by that route module has a
column of the same name, and (b) that column is a bounded String. Response-only
models (serialization out, not input validation) go in ALLOW.
"""
import importlib
import inspect
import pkgutil

from pydantic import BaseModel
from sqlalchemy import String

import api.routes as routes_pkg
from app import models

# "module.Class.field" entries exempt from the rule (response models etc.).
ALLOW = {
    "api.routes.pricing_configs.ConfigResponse.config_hash",  # response model — output, not input
    # ContactCreate/Update.name writes contacts.name (255); the heuristic cross-matches
    # branches.name (100) because customers.py references Branch for validation only.
    "api.routes.customers.ContactCreate.name",
    "api.routes.customers.ContactUpdate.name",
}


def _bounded_columns() -> dict[str, list[tuple[str, int]]]:
    out: dict[str, list[tuple[str, int]]] = {}
    for table in models.Base.metadata.tables.values():
        for col in table.columns:
            if isinstance(col.type, String) and col.type.length:
                out.setdefault(col.name, []).append((table.name, col.type.length))
    return out


def test_route_schemas_bound_string_fields():
    bounded = _bounded_columns()
    model_tables = {
        name: obj.__tablename__
        for name, obj in vars(models).items()
        if isinstance(obj, type) and hasattr(obj, "__tablename__")
    }

    failures = []
    for modinfo in pkgutil.iter_modules(routes_pkg.__path__):
        modname = f"api.routes.{modinfo.name}"
        mod = importlib.import_module(modname)
        src = inspect.getsource(mod)
        touched = {tbl for cls, tbl in model_tables.items() if cls in src}
        for objname, obj in vars(mod).items():
            if not (
                isinstance(obj, type)
                and issubclass(obj, BaseModel)
                and obj is not BaseModel
                and obj.__module__ == modname
            ):
                continue
            for fname, finfo in obj.model_fields.items():
                if fname not in bounded or "str" not in str(finfo.annotation):
                    continue
                candidates = [(t, length) for t, length in bounded[fname] if t in touched]
                if not candidates:
                    continue
                if f"{modname}.{objname}.{fname}" in ALLOW:
                    continue
                strictest = min(length for _, length in candidates)
                maxlen = next(
                    (m.max_length for m in finfo.metadata if hasattr(m, "max_length")), None
                )
                if maxlen is None:
                    failures.append(
                        f"{modname}.{objname}.{fname}: no max_length "
                        f"(DB bounds it at {strictest}: {candidates})"
                    )
                elif maxlen > strictest:
                    failures.append(
                        f"{modname}.{objname}.{fname}: max_length={maxlen} exceeds "
                        f"DB column limit {strictest} ({candidates})"
                    )

    assert not failures, (
        "Schema fields missing/exceeding max_length for bounded DB columns "
        "(oversized input will 500 on prod Postgres — SQLite tests can't catch it):\n"
        + "\n".join(failures)
    )
