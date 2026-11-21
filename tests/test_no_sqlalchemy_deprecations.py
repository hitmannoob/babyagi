"""Runtime guard: the database layer must not trigger SQLAlchemy deprecations.

``tests/test_acceptance.py`` checks legacy APIs statically (grep), and the
``-W error::DeprecationWarning`` in ``check.sh`` only enforces this at
import/collection time because pytest captures warnings raised while tests
run.  This test exercises the public DB layer inside ``catch_warnings`` so a
deprecated SQLAlchemy code path (for example ``MovedIn20Warning``) fails the
suite instead of being silently collected.
"""

import datetime
import warnings

import pytest
from sqlalchemy.exc import SADeprecationWarning

from babyagi.functionz.db.db_router import DBRouter


@pytest.fixture()
def router(tmp_path):
    return DBRouter(db_path=f"sqlite:///{tmp_path / 'runtime-warnings.db'}")


def _is_sqlalchemy_warning(warning):
    return issubclass(warning.category, SADeprecationWarning) or "sqlalchemy" in (
        warning.filename or ""
    ).lower()


def test_db_operations_emit_no_sqlalchemy_deprecation_warnings(router):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")

        router.add_function("base", "def base():\n    return 1\n")
        router.add_function(
            "user",
            "def user():\n    return base()\n",
            metadata={"description": "uses base"},
            dependencies=["base"],
            triggers=["upstream"],
            input_parameters=[{"name": "x", "type": "int"}],
            output_parameters=[{"name": "y", "type": "int"}],
            imports=["json"],
        )
        router.update_function("user", code="def user():\n    return 2\n")
        router.get_function("user")
        router.get_all_functions()
        router.get_function_versions("user")
        router.get_function_imports("user")
        router.get_all_imports()
        router.activate_function_version("user", 1)

        now = datetime.datetime(2024, 1, 1, 12, 0, 0)
        log_id = router.add_log("user", "started", now)
        child_id = router.add_log("user", "child", now, parent_log_id=log_id)
        router.get_logs()
        router.update_log(child_id, message="updated")
        router.update_log_params(log_id, {"x": 1})

        router.add_secret_key("api_key", "secret")
        router.get_secret_key("api_key")
        router.get_all_secret_keys()

        router.remove_function("user")

    sqlalchemy_warnings = [
        f"{w.category.__name__}: {w.message} ({w.filename}:{w.lineno})"
        for w in caught
        if _is_sqlalchemy_warning(w)
    ]
    assert sqlalchemy_warnings == [], (
        "database layer emitted SQLAlchemy deprecation warnings:\n"
        + "\n".join(sqlalchemy_warnings)
    )
