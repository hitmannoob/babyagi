"""End-to-end tests for the public Functionz facade.

These complement the DBRouter-level tests by exercising the registration and
execution code paths in ``babyagi/functionz/core`` against a temporary SQLite
database.
"""

import pytest

from babyagi.functionz.core.framework import Functionz


@pytest.fixture()
def func(tmp_path):
    return Functionz(db_type="local", db_path=f"sqlite:///{tmp_path / 'functions.db'}")


def test_add_read_update_and_execute(func):
    func.add_function(
        name="add",
        code="def add(a, b):\n    return a + b",
        metadata={"description": "add two numbers"},
        input_parameters=[{"name": "a", "type": "int"}, {"name": "b", "type": "int"}],
        output_parameters=[{"name": "result", "type": "int"}],
    )

    stored = func.get_function("add")
    assert stored["version"] == 1
    assert stored["metadata"] == {"description": "add two numbers"}
    assert stored["input_parameters"] == [
        {"name": "a", "type": "int"},
        {"name": "b", "type": "int"},
    ]
    assert stored["output_parameters"] == [{"name": "result", "type": "int"}]

    assert func.execute_function("add", 2, 3) == 5

    logs = func.get_logs(function_name="add")
    assert len(logs) == 1
    assert logs[0]["log_type"] == "success"
    assert logs[0]["output"] == 5

    func.update_function(name="add", code="def add(a, b):\n    return a * b")

    updated = func.get_function("add")
    assert updated["version"] == 2
    assert updated["code"] == "def add(a, b):\n    return a * b"
    assert func.execute_function("add", 2, 3) == 6


def test_register_function_decorator(func):
    @func.register_function(metadata={"description": "double a number"})
    def double(x):
        return x * 2

    stored = func.get_function("double")
    assert stored is not None
    assert stored["metadata"] == {"description": "double a number"}

    assert double(4) == 8
    assert func.get_function("double")["version"] == 1


def test_update_without_changes_does_not_create_version(func):
    func.add_function(
        name="same",
        code="def same():\n    return 1",
        metadata={"description": "unchanged"},
    )

    func.update_function(
        name="same",
        code="def same():\n    return 1",
        metadata={"description": "unchanged"},
    )

    assert func.get_function("same")["version"] == 1


def test_dependency_is_resolved_during_execution(func):
    func.add_function(name="increment", code="def increment(x):\n    return x + 1")
    func.add_function(
        name="increment_twice",
        code="def increment_twice(x):\n    return increment(increment(x))",
        dependencies=["increment"],
    )

    assert func.get_function("increment_twice")["dependencies"] == ["increment"]
    assert func.execute_function("increment_twice", 1) == 3


def test_secret_keys_are_injected_into_execution_scope(func):
    func.add_key("token", "s3cr3t")
    func.add_function(name="read_token", code="def read_token():\n    return token")

    assert func.get_all_secret_keys() == {"token": "s3cr3t"}
    assert func.execute_function("read_token") == "s3cr3t"


def test_execution_error_is_logged_and_raised(func):
    func.add_function(name="boom", code="def boom():\n    raise ValueError('boom')")

    with pytest.raises(ValueError):
        func.execute_function("boom")

    logs = func.get_logs(function_name="boom")
    assert len(logs) == 1
    assert logs[0]["log_type"] == "error"
    assert "boom" in logs[0]["message"]
