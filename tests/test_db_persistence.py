"""Persistence tests for the database layer across engine/session recreation.

The rest of the suite exercises a single ``DBRouter`` instance per test. These
tests pin that data written through ``session_scope`` is committed to the
SQLite file and can be read back by a brand-new ``DBRouter`` (new engine and
session) on the same file. They guard the explicit-transaction semantics of
the SQLAlchemy 2.0 migration and the idempotency of ``create_all`` on reopen.
"""

import datetime

from babyagi.functionz.db.db_router import DBRouter


def test_data_survives_a_fresh_router_on_the_same_file(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'persist.db'}"
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

    # A new router creates a new engine/session on the same SQLite file.
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

    # Version history is persisted too, with the updated version active.
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
