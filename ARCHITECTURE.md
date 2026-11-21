# Architecture

This document describes the `functionz` database layer and records the
decisions made while migrating the project from SQLAlchemy 1.4 to 2.0.

## Repository layout (relevant parts)

```
babyagi/
  __init__.py                 Flask app wiring and the global Functionz instance
  functionz/
    core/                     Functionz facade, registration and execution
    db/
      base_db.py              BaseDB abstract interface
      models.py               SQLAlchemy ORM models + secret-key encryption
      local_db.py             LocalDB: engine, sessions, query helpers
      db_router.py            DBRouter: public database API used by callers
    packs/                    Built-in function packs (registered at import)
tests/
  test_db_layer.py            DBRouter/LocalDB behaviour pins
  test_db_router.py           Additional DBRouter behaviour pins
  test_functionz_integration.py  End-to-end registration/execution tests
  test_acceptance.py          Guards for the migration acceptance criteria
check.sh                      Install requirements and run the suite
```

## Database layer

- **`base_db.py`** defines `BaseDB`, the abstract interface for function,
  import, log and secret-key operations.
- **`models.py`** is the ORM layer. `Base` is a `DeclarativeBase` subclass.
  It defines `Function`, `FunctionVersion`, `Import`, `Log` and `SecretKey`,
  the two association tables (`function_dependency`,
  `function_version_imports`), and Fernet-based encryption of secret values.
  `FunctionVersion.created_date` stores a naive UTC timestamp.
- **`local_db.py`** owns the `Engine` and a `scoped_session` wrapped
  `sessionmaker`. `LocalDB.session_scope()` is the transaction boundary:
  it commits on success, rolls back on `SQLAlchemyError`, and always removes
  the scoped session. All reads use SQLAlchemy 2.0 `select()` statements
  executed through `session.scalars()`; joined eager loads against
  collections call `.unique()` where deduplication is required.
- **`db_router.py`** is the public API (`DBRouter`) used by the rest of the
  application. It opens a `session_scope()` per operation and converts ORM
  rows into plain dictionaries, so callers never see live ORM objects and no
  session leaks across the API boundary.

## SQLAlchemy 2.0 decisions

- `requirements.txt` requires `sqlalchemy>=2.0,<3`. `setup.py` derives its
  install requirements from that file; `pyproject.toml` does not declare
  SQLAlchemy.
- No legacy APIs remain under `babyagi/`:
  - no `session.query()` — use `select()` with `session.scalars()` /
    `session.execute()`;
  - no `engine.execute()` — use `engine.begin()` with `connection.execute()`;
  - no `declarative_base()` from `sqlalchemy.ext.declarative` — use
    `DeclarativeBase` (core models) or `registry(...).generate_base()`
    (dynamic pack tables).
- Raw SQL is always wrapped in `text()`.
- No autocommit and no bound metadata; transactions are explicit through
  `session_scope()` or `engine.begin()`.
- ORM collections loaded with joined eager loading use `.unique()` so row
  deduplication matches the previous behaviour.
- Behaviour is intentionally unchanged; only SQLAlchemy usage moved to the
  2.0 API.

## Tests and checks

```bash
pip install -q -r requirements.txt pytest
SQLALCHEMY_WARN_20=1 python -m pytest -q tests/
```

`./check.sh` runs the same install followed by the stricter
`SQLALCHEMY_WARN_20=1 python -W error::DeprecationWarning -m pytest -q tests/`.

`tests/test_acceptance.py` asserts the two static acceptance criteria (the
2.x pin and the absence of legacy APIs); the behaviour tests cover the third
criterion (registering, reading and updating functions against a temporary
SQLite database).
