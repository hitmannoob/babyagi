"""Transaction-boundary tests for ``LocalDB.session_scope``.

The SQLAlchemy 2.0 migration moved the database layer onto explicit
transactions: ``session_scope()`` commits on success and rolls back when a
``SQLAlchemyError`` escapes the block. These tests pin that behaviour against
a temporary SQLite file so a future change cannot silently start relying on
implicit/autocommit semantics.
"""

import datetime

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from babyagi.functionz.db.db_router import DBRouter
from babyagi.functionz.db.local_db import LocalDB
from babyagi.functionz.db.models import Import


@pytest.fixture()
def db_url(tmp_path):
    return f"sqlite:///{tmp_path / 'transactions.db'}"


def _add_import(db, name, source="test"):
    with db.session_scope() as session:
        session.add(Import(name=name, source=source))


def test_session_scope_commits_on_success(db_url):
    first = LocalDB(db_path=db_url)
    _add_import(first, "committed")

    second = LocalDB(db_path=db_url)
    with second.session_scope() as session:
        stored = session.scalars(select(Import).filter_by(name="committed")).one()
        stored_name, stored_source = stored.name, stored.source

    assert stored_name == "committed"
    assert stored_source == "test"


def test_session_scope_rolls_back_on_sqlalchemy_error(db_url):
    db = LocalDB(db_path=db_url)

    with pytest.raises(SQLAlchemyError):
        with db.session_scope() as session:
            session.add(Import(name="rolled-back", source="test"))
            session.add(Import(name="also-rolled-back", source="test"))
            session.flush()
            session.execute(text("INSERT INTO table_that_does_not_exist (x) VALUES (1)"))

    with db.session_scope() as session:
        assert session.scalars(select(Import).filter_by(name="rolled-back")).first() is None
        assert session.scalars(select(Import).filter_by(name="also-rolled-back")).first() is None


def test_session_scope_does_not_commit_when_other_error_propagates(db_url):
    db = LocalDB(db_path=db_url)

    with pytest.raises(ValueError):
        with db.session_scope() as session:
            session.add(Import(name="not-committed", source="test"))
            session.flush()
            raise ValueError("boom")

    with db.session_scope() as session:
        assert session.scalars(select(Import).filter_by(name="not-committed")).first() is None


def test_committed_function_data_survives_a_fresh_engine(db_url):
    """A new engine/session sees everything committed by the previous one."""
    now = datetime.datetime(2024, 1, 1, 12, 0, 0)

    first = DBRouter(db_path=db_url)
    first.add_function("base", "def base():\n    return 1\n")
    first.add_function(
        "greet",
        "def greet(name):\n    return 'hi ' + name\n",
        metadata={"description": "greets"},
        dependencies=["base"],
        triggers=["downstream"],
        input_parameters=[{"name": "name", "type": "str"}],
        output_parameters=[{"name": "result", "type": "str"}],
        imports=["os"],
    )
    first.add_function("counter", "count = 1\n")
    first.update_function("counter", code="count = 2\n")
    first.add_secret_key("api_key", "super-secret")
    log_id = first.add_log(
        "greet",
        "ran",
        now,
        params={"name": "world"},
        output="hello world",
        time_spent=0.25,
    )

    second = DBRouter(db_path=db_url)

    greet = second.get_function("greet")
    assert greet["version"] == 1
    assert greet["code"] == "def greet(name):\n    return 'hi ' + name\n"
    assert greet["metadata"] == {"description": "greets"}
    assert greet["dependencies"] == ["base"]
    assert greet["triggers"] == ["downstream"]
    assert greet["imports"] == ["os"]
    assert greet["input_parameters"] == [{"name": "name", "type": "str"}]
    assert greet["output_parameters"] == [{"name": "result", "type": "str"}]
    assert datetime.datetime.fromisoformat(greet["created_date"])

    counter = second.get_function("counter")
    assert counter["version"] == 2
    assert counter["code"] == "count = 2\n"
    versions = sorted(
        second.get_function_versions("counter"), key=lambda v: v["version"]
    )
    assert [v["version"] for v in versions] == [1, 2]
    assert versions[0]["code"] == "count = 1\n"
    assert versions[0]["is_active"] is False
    assert versions[1]["code"] == "count = 2\n"
    assert versions[1]["is_active"] is True

    assert second.get_secret_key("api_key") == "super-secret"
    assert second.get_all_secret_keys() == {"api_key": "super-secret"}

    logs = second.get_logs(function_name="greet")
    assert [log["id"] for log in logs] == [log_id]
    assert logs[0]["params"] == {"name": "world"}
    assert logs[0]["output"] == "hello world"
    assert logs[0]["time_spent"] == 0.25
    assert logs[0]["log_type"] == "info"
