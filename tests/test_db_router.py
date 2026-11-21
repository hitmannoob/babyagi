"""Behaviour-pinning tests for the functionz database layer.

These tests exercise :class:`babyagi.functionz.db.db_router.DBRouter` (and the
underlying ``LocalDB``) against a throw-away SQLite file.  They describe the
behaviour of the layer as it exists today so that the SQLAlchemy 2.0 migration
can be checked for accidental behaviour changes.
"""

from datetime import datetime, timedelta

import pytest

from babyagi.functionz.db.db_router import DBRouter

FUNC_CODE = "def hello(name):\n    return f'Hello, {name}!'"


@pytest.fixture()
def db(tmp_path):
    return DBRouter(db_type="local", db_path=f"sqlite:///{tmp_path / 'test.db'}")


def add_hello(db, **kwargs):
    defaults = dict(
        name="hello",
        code=FUNC_CODE,
        metadata={"description": "say hello"},
        input_parameters=[{"name": "name", "type": "str"}],
        output_parameters=[{"name": "result", "type": "str"}],
    )
    defaults.update(kwargs)
    db.add_function(**defaults)


# ---------------------------------------------------------------------------
# Function registration / reading
# ---------------------------------------------------------------------------

def test_add_and_get_function(db):
    add_hello(db)
    stored = db.get_function("hello")

    assert stored is not None
    assert stored["name"] == "hello"
    assert stored["version"] == 1
    assert stored["code"] == FUNC_CODE
    assert stored["metadata"] == {"description": "say hello"}
    assert stored["input_parameters"] == [{"name": "name", "type": "str"}]
    assert stored["output_parameters"] == [{"name": "result", "type": "str"}]
    assert stored["dependencies"] == []
    assert stored["imports"] == []
    assert stored["triggers"] == []
    assert isinstance(stored["created_date"], str)


def test_get_unknown_function_returns_none(db):
    assert db.get_function("does_not_exist") is None


def test_get_all_functions(db):
    add_hello(db)
    db.add_function(name="other", code="def other():\n    return 1")

    functions = {f["name"]: f for f in db.get_all_functions()}

    assert set(functions) == {"hello", "other"}
    assert functions["hello"]["code"] == FUNC_CODE
    assert functions["other"]["version"] == 1


def test_metadata_defaults_to_empty_dict(db):
    db.add_function(name="bare", code="def bare():\n    pass")
    stored = db.get_function("bare")

    assert stored["metadata"] == {}
    assert stored["input_parameters"] == []
    assert stored["output_parameters"] == []


# ---------------------------------------------------------------------------
# Versioning / updates
# ---------------------------------------------------------------------------

def test_update_creates_new_active_version(db):
    add_hello(db)
    db.update_function("hello", code="def hello():\n    return 'hi'")

    stored = db.get_function("hello")
    assert stored["version"] == 2
    assert stored["code"] == "def hello():\n    return 'hi'"
    # Metadata is carried over from the previous active version.
    assert stored["metadata"] == {"description": "say hello"}

    versions = db.get_function_versions("hello")
    assert [v["version"] for v in versions] == [1, 2]
    assert [v["is_active"] for v in versions] == [False, True]
    assert versions[0]["code"] == FUNC_CODE


def test_activate_old_version(db):
    add_hello(db)
    db.update_function("hello", code="def hello():\n    return 'hi'")

    db.activate_function_version("hello", 1)

    stored = db.get_function("hello")
    assert stored["version"] == 1
    assert stored["code"] == FUNC_CODE

    versions = {v["version"]: v["is_active"] for v in db.get_function_versions("hello")}
    assert versions == {1: True, 2: False}


def test_update_unknown_function_is_noop(db):
    db.update_function("missing", code="def missing():\n    pass")
    assert db.get_function("missing") is None


def test_get_function_versions_unknown_is_empty(db):
    assert db.get_function_versions("missing") == []


def test_remove_function(db):
    add_hello(db)
    assert db.get_function("hello") is not None

    db.remove_function("hello")

    assert db.get_function("hello") is None
    assert db.get_all_functions() == []
    assert db.get_function_versions("hello") == []


# ---------------------------------------------------------------------------
# Dependencies and imports
# ---------------------------------------------------------------------------

def test_register_function_with_dependencies(db):
    db.add_function(name="base", code="def base():\n    return 1")
    add_hello(db, dependencies=["base"])

    stored = db.get_function("hello")
    assert stored["dependencies"] == ["base"]


def test_dependencies_are_kept_per_version(db):
    db.add_function(name="base", code="def base():\n    return 1")
    add_hello(db, dependencies=["base"])
    db.update_function("hello", code="def hello():\n    return 2", dependencies=["base"])

    versions = db.get_function_versions("hello")
    assert all(v["dependencies"] == ["base"] for v in versions)


def test_imports_registered_with_function(db):
    add_hello(db, imports=["os", "json"])

    stored = db.get_function("hello")
    assert sorted(stored["imports"]) == ["json", "os"]

    all_imports = {imp["name"]: imp for imp in db.get_all_imports()}
    assert set(all_imports) == {"os", "json"}
    assert all_imports["os"]["source"] == "external"

    function_imports = {imp["name"] for imp in db.get_function_imports("hello")}
    assert function_imports == {"os", "json"}


def test_add_import_is_idempotent_and_get_all_imports(db):
    db.add_import("requests", "pip", lib="requests")
    db.add_import("requests", "pip", lib="requests")

    imports = db.get_all_imports()
    assert len(imports) == 1
    assert imports[0] == {"name": "requests", "source": "pip", "lib": "requests"}


def test_get_function_imports_unknown_is_empty(db):
    assert db.get_function_imports("missing") == []


def test_triggers_round_trip(db):
    add_hello(db, triggers=["triggered_by_me"])
    assert db.get_function("hello")["triggers"] == ["triggered_by_me"]

    db.update_function("hello", code="def hello():\n    return 3", triggers=["other_trigger"])
    stored = db.get_function("hello")
    assert stored["version"] == 2
    assert stored["triggers"] == ["other_trigger"]


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------

def test_add_and_read_logs(db):
    now = datetime(2024, 1, 1, 12, 0, 0)
    log_id = db.add_log(
        function_name="hello",
        message="started",
        timestamp=now,
        params={"x": 1, "when": now},
        output={"ok": True},
        time_spent=0.5,
        log_type="info",
    )

    logs = db.get_logs()
    assert len(logs) == 1
    log = logs[0]
    assert log["id"] == log_id
    assert log["function_name"] == "hello"
    assert log["message"] == "started"
    assert log["timestamp"] == now.isoformat()
    assert log["params"] == {"x": 1, "when": now.isoformat()}
    assert log["output"] == {"ok": True}
    assert log["time_spent"] == 0.5
    assert log["log_type"] == "info"
    assert log["parent_log_id"] is None
    assert log["triggered_by_log_id"] is None


def test_logs_filter_by_function_name_and_dates(db):
    t0 = datetime(2024, 1, 1, 10, 0, 0)
    db.add_log("a", "a1", t0)
    db.add_log("a", "a2", t0 + timedelta(hours=1))
    db.add_log("b", "b1", t0 + timedelta(hours=2))

    assert [log["message"] for log in db.get_logs(function_name="a")] == ["a1", "a2"]
    assert [log["message"] for log in db.get_logs(function_name="b")] == ["b1"]
    assert [log["message"] for log in db.get_logs(start_date=t0 + timedelta(minutes=30))] == ["a2", "b1"]
    assert [log["message"] for log in db.get_logs(end_date=t0 + timedelta(minutes=30))] == ["a1"]


def test_add_child_log_and_filter_by_trigger(db):
    parent_id = db.add_log("parent", "parent log", datetime(2024, 1, 1))
    child_id = db.add_log(
        "child", "child log", datetime(2024, 1, 1), parent_log_id=parent_id
    )
    triggered_id = db.add_log(
        "triggered", "triggered log", datetime(2024, 1, 1), triggered_by_log_id=parent_id
    )
    assert child_id != triggered_id

    logs = db.get_logs(triggered_by_log_id=parent_id)
    assert [log["id"] for log in logs] == [triggered_id]


def test_update_log_and_params(db):
    log_id = db.add_log("hello", "message", datetime(2024, 1, 1), params={"a": 1})

    db.update_log(log_id, message="updated", time_spent=2.5)
    db.update_log_params(log_id, {"b": 2})

    log = db.get_logs()[0]
    assert log["message"] == "updated"
    assert log["time_spent"] == 2.5
    assert log["params"] == {"b": 2}


def test_update_unknown_log_raises(db):
    with pytest.raises(ValueError):
        db.update_log(999, message="nope")

    with pytest.raises(ValueError):
        db.update_log_params(999, {"a": 1})


def test_get_log_bundle_includes_parent_and_children(db):
    parent_id = db.add_log("parent", "parent", datetime(2024, 1, 1))
    child_id = db.add_log("child", "child", datetime(2024, 1, 1), parent_log_id=parent_id)
    db.add_log("child", "sibling", datetime(2024, 1, 1), parent_log_id=parent_id)
    grandchild_id = db.add_log("grandchild", "grandchild", datetime(2024, 1, 1), parent_log_id=child_id)

    bundle = db.get_log_bundle(child_id)

    # Child, its parent, its sibling and the parent's other child are included.
    assert {log["id"] for log in bundle} >= {parent_id, child_id, grandchild_id}
    assert len(bundle) == 4


# ---------------------------------------------------------------------------
# Secret keys
# ---------------------------------------------------------------------------

def test_secret_key_add_get_update(db):
    db.add_secret_key("api_key", "secret-value")
    assert db.get_secret_key("api_key") == "secret-value"

    db.add_secret_key("api_key", "new-secret")
    assert db.get_secret_key("api_key") == "new-secret"


def test_get_all_secret_keys(db):
    db.add_secret_key("one", "1")
    db.add_secret_key("two", "2")

    keys = db.get_all_secret_keys()
    assert keys == {"one": "1", "two": "2"}


def test_get_unknown_secret_key_returns_none(db):
    assert db.get_secret_key("missing") is None
