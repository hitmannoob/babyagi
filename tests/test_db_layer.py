"""Behaviour tests for the functionz database layer.

These tests pin the public behaviour of ``DBRouter``/``LocalDB`` against a
temporary SQLite file. They are written to pass on both SQLAlchemy 1.4 and
2.0 so they can guard the migration.
"""

import datetime

import pytest

from babyagi.functionz.db.db_router import DBRouter
from babyagi.functionz.db.local_db import LocalDB


@pytest.fixture()
def router(tmp_path):
    db_file = tmp_path / "functions.db"
    return DBRouter(db_path=f"sqlite:///{db_file}")


def test_add_and_get_function(router):
    router.add_function(
        "greet",
        "def greet(name):\n    return 'hi ' + name\n",
        metadata={"description": "greets"},
        input_parameters=[{"name": "name", "type": "str"}],
        output_parameters=[{"name": "result", "type": "str"}],
    )

    function = router.get_function("greet")

    assert function["name"] == "greet"
    assert function["version"] == 1
    assert function["code"].startswith("def greet")
    assert function["metadata"] == {"description": "greets"}
    assert function["input_parameters"] == [{"name": "name", "type": "str"}]
    assert function["output_parameters"] == [{"name": "result", "type": "str"}]
    assert function["dependencies"] == []
    assert function["imports"] == []
    assert function["triggers"] == []
    # created_date is serialized as an ISO timestamp string
    assert datetime.datetime.fromisoformat(function["created_date"])


def test_get_missing_function_returns_none(router):
    assert router.get_function("does-not-exist") is None


def test_created_date_default_is_naive_utc(router):
    """Version timestamps stay naive UTC after the SA 2.0 migration.

    The migration replaced ``datetime.utcnow`` with
    ``datetime.now(timezone.utc).replace(tzinfo=None)``; this pins the
    parity: a naive datetime close to the current UTC wall clock.
    """

    def naive_utc_now():
        return datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)

    before = naive_utc_now()
    router.add_function("stamped", "v1")
    after_add = naive_utc_now()

    first = datetime.datetime.fromisoformat(
        router.get_function("stamped")["created_date"]
    )
    assert first.tzinfo is None
    assert before <= first <= after_add

    router.update_function("stamped", code="v2")
    after_update = naive_utc_now()

    versions = {v["version"]: v for v in router.get_function_versions("stamped")}
    second = datetime.datetime.fromisoformat(versions[2]["created_date"])
    assert second.tzinfo is None
    assert first <= second <= after_update


def test_update_function_creates_new_active_version(router):
    router.add_function("f", "def f():\n    return 1\n")
    router.update_function("f", code="def f():\n    return 2\n")

    active = router.get_function("f")
    assert active["version"] == 2
    assert active["code"] == "def f():\n    return 2\n"

    versions = sorted(router.get_function_versions("f"), key=lambda v: v["version"])
    assert [v["version"] for v in versions] == [1, 2]
    assert versions[0]["code"] == "def f():\n    return 1\n"
    assert versions[0]["is_active"] is False
    assert versions[1]["is_active"] is True


def test_update_function_keeps_unspecified_fields(router):
    router.add_function(
        "f",
        "code-v1",
        metadata={"description": "keep me"},
        input_parameters=[{"name": "a"}],
        triggers=["downstream"],
    )
    router.update_function("f", code="code-v2")

    active = router.get_function("f")
    assert active["code"] == "code-v2"
    assert active["metadata"] == {"description": "keep me"}
    assert active["input_parameters"] == [{"name": "a"}]
    assert active["triggers"] == ["downstream"]


def test_activate_function_version(router):
    router.add_function("f", "v1")
    router.update_function("f", code="v2")

    router.activate_function_version("f", 1)

    assert router.get_function("f")["version"] == 1
    versions = {v["version"]: v for v in router.get_function_versions("f")}
    assert versions[1]["is_active"] is True
    assert versions[2]["is_active"] is False


def test_remove_function(router):
    router.add_function("f", "code")
    router.remove_function("f")
    assert router.get_function("f") is None
    assert router.get_all_functions() == []


def test_dependencies(router):
    router.add_function("base", "def base():\n    return 1\n")
    router.add_function(
        "user", "def user():\n    return base()\n", dependencies=["base"]
    )

    assert router.get_function("user")["dependencies"] == ["base"]

    versions = router.get_function_versions("user")
    assert len(versions) == 1
    assert versions[0]["dependencies"] == ["base"]


def test_missing_dependencies_are_ignored(router):
    router.add_function("user", "code", dependencies=["not-registered"])
    assert router.get_function("user")["dependencies"] == []


def test_imports(router):
    router.add_import("numpy", source="pip", lib="numpy")
    router.add_function("f", "code", imports=["json"])

    all_imports = {imp["name"]: imp for imp in router.get_all_imports()}
    assert all_imports["numpy"]["source"] == "pip"
    assert all_imports["numpy"]["lib"] == "numpy"
    # imports referenced by add_function are auto-created as external
    assert all_imports["json"]["source"] == "external"

    function_imports = [imp["name"] for imp in router.get_function_imports("f")]
    assert function_imports == ["json"]
    assert router.get_function_imports("missing") == []


def test_add_import_is_idempotent(router):
    router.add_import("numpy", source="pip")
    router.add_import("numpy", source="pip")
    imports = [imp for imp in router.get_all_imports() if imp["name"] == "numpy"]
    assert len(imports) == 1


def test_triggers(router):
    router.add_function("downstream", "code", triggers=["upstream"])
    router.add_function("other", "code")

    assert router.get_function("downstream")["triggers"] == ["upstream"]
    assert router.get_triggers_for_function("upstream") == ["downstream"]
    assert router.get_triggers_for_function("downstream") == []


def test_get_all_functions_returns_active_versions(router):
    router.add_function("a", "a-v1")
    router.add_function("b", "b-v1")
    router.update_function("a", code="a-v2")

    functions = {f["name"]: f for f in router.get_all_functions()}
    assert set(functions) == {"a", "b"}
    assert functions["a"]["version"] == 2
    assert functions["a"]["code"] == "a-v2"
    assert functions["b"]["version"] == 1


def test_logs_add_and_filter(router):
    now = datetime.datetime(2024, 1, 1, 12, 0, 0)

    first_id = router.add_log(
        "f",
        "started",
        now,
        params={"x": 1},
        output={"intermediate": True},
        time_spent=0.5,
    )
    second_id = router.add_log(
        "f", "finished", now + datetime.timedelta(hours=1), output=[1, 2, 3]
    )
    router.add_log("g", "other", now + datetime.timedelta(hours=2))

    assert isinstance(first_id, int)
    assert first_id != second_id

    logs = router.get_logs(function_name="f")
    assert [log["id"] for log in logs] == [first_id, second_id]
    assert logs[0]["params"] == {"x": 1}
    assert logs[0]["output"] == {"intermediate": True}
    assert logs[0]["time_spent"] == 0.5
    assert logs[0]["log_type"] == "info"

    filtered = router.get_logs(
        start_date=now, end_date=now + datetime.timedelta(minutes=30)
    )
    assert [log["id"] for log in filtered] == [first_id]


def test_log_update(router):
    log_id = router.add_log("f", "message", datetime.datetime(2024, 1, 1))
    router.update_log(log_id, message="updated", time_spent=1.25)

    log = router.get_logs(function_name="f")[0]
    assert log["message"] == "updated"
    assert log["time_spent"] == 1.25


def test_update_log_params(router):
    log_id = router.add_log("f", "message", datetime.datetime(2024, 1, 1))
    router.update_log_params(log_id, {"a": 1})
    assert router.get_logs(function_name="f")[0]["params"] == {"a": 1}


def test_log_bundle_links_parent_and_children(router):
    now = datetime.datetime(2024, 1, 1)
    parent_id = router.add_log("parent", "parent", now)
    child_a = router.add_log("child", "a", now, parent_log_id=parent_id)
    child_b = router.add_log("child", "b", now, parent_log_id=parent_id)

    bundle = router.get_log_bundle(child_a)
    ids = {log["id"] for log in bundle}
    assert parent_id in ids
    assert child_a in ids
    assert child_b in ids

    # triggered_by is preserved and filterable
    triggered_id = router.add_log(
        "triggered", "run", now, triggered_by_log_id=parent_id
    )
    triggered = router.get_logs(triggered_by_log_id=parent_id)
    assert [log["id"] for log in triggered] == [triggered_id]


def test_secret_keys(router):
    router.add_secret_key("api_key", "super-secret")

    assert router.get_secret_key("api_key") == "super-secret"
    assert router.get_all_secret_keys() == {"api_key": "super-secret"}
    assert router.get_secret_key("missing") is None

    # adding an existing key updates it in place
    router.add_secret_key("api_key", "rotated")
    assert router.get_secret_key("api_key") == "rotated"
    assert router.get_all_secret_keys() == {"api_key": "rotated"}


def test_secret_value_is_encrypted_at_rest(router):
    router.add_secret_key("api_key", "plain-value")
    with router.session_scope() as session:
        from babyagi.functionz.db.models import SecretKey

        stored = session.query(SecretKey).filter_by(name="api_key").one()
        assert stored._encrypted_value != b"plain-value"
        assert b"plain-value" not in stored._encrypted_value


def test_local_db_roundtrip(tmp_path):
    db = LocalDB(db_path=f"sqlite:///{tmp_path / 'local.db'}")
    with db.session_scope() as session:
        db.add_or_update_function(
            session,
            "local_fn",
            "code",
            {"description": "local"},
            ["dep"],
            ["trig"],
            [{"name": "in"}],
            [{"name": "out"}],
        )

    with db.session_scope() as session:
        function = db.get_function(session, "local_fn")
        assert function is not None
        active = db.get_active_version(session, function)
        assert active.code == "code"
        assert active.function_metadata == {"description": "local"}
        assert active.triggers == ["trig"]
