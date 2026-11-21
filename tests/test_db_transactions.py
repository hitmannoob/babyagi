"""Transaction-boundary tests for ``LocalDB.session_scope``.

The SQLAlchemy 2.0 migration moved the database layer onto explicit
transactions: ``session_scope()`` commits on success and rolls back when a
``SQLAlchemyError`` escapes the block. These tests pin that behaviour against
a temporary SQLite file so a future change cannot silently start relying on
implicit/autocommit semantics.
"""

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

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
