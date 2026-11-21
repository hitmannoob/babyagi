"""End-to-end trigger execution tests for the public Functionz facade.

These pin the runtime behaviour behind the ``triggers`` column: executing a
function also executes every function that lists it as a trigger, and the
resulting log rows are linked back to the triggering log. They exercise the
``get_triggers_for_function`` and ``add_log`` database paths against a
temporary SQLite file on SQLAlchemy 2.x.
"""

import pytest

from babyagi.functionz.core.framework import Functionz


@pytest.fixture()
def func(tmp_path):
    return Functionz(db_type="local", db_path=f"sqlite:///{tmp_path / 'functions.db'}")


def _single_log(func, function_name):
    logs = func.get_logs(function_name=function_name)
    assert len(logs) == 1
    return logs[0]


def test_trigger_runs_after_function_with_its_output(func):
    func.add_function(
        name="upstream",
        code="def upstream(x):\n    return x + 1",
        input_parameters=[{"name": "x"}],
    )
    func.add_function(
        name="downstream",
        code="def downstream(value):\n    return value * 10",
        input_parameters=[{"name": "value"}],
        triggers=["upstream"],
    )

    assert func.execute_function("upstream", 4) == 5

    upstream_log = _single_log(func, "upstream")
    downstream_log = _single_log(func, "downstream")

    assert upstream_log["output"] == 5
    assert downstream_log["output"] == 50
    assert downstream_log["log_type"] == "success"
    # The triggered run is a child of the triggering run.
    assert downstream_log["parent_log_id"] == upstream_log["id"]
    assert downstream_log["triggered_by_log_id"] == upstream_log["id"]


def test_trigger_without_input_parameters_is_called_without_arguments(func):
    func.add_function(name="source", code="def source():\n    return 3")
    func.add_function(
        name="sink",
        code="def sink():\n    return 'done'",
        triggers=["source"],
    )

    assert func.execute_function("source") == 3

    source_log = _single_log(func, "source")
    sink_log = _single_log(func, "sink")
    assert sink_log["output"] == "done"
    assert sink_log["triggered_by_log_id"] == source_log["id"]
