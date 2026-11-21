"""Regression pin for ``DBRouter.get_all_functions`` after the 2.0 migration.

``LocalDB.get_all_functions`` eagerly joins a function's versions and each
version's dependencies. A function whose active version has more than one
dependency therefore produces several SQL rows; the 2.0 port calls
``.unique()`` so callers still see each function exactly once.
"""

import pytest

from babyagi.functionz.db.db_router import DBRouter


@pytest.fixture()
def router(tmp_path):
    return DBRouter(db_path=f"sqlite:///{tmp_path / 'functions.db'}")


def test_get_all_functions_returns_each_function_once(router):
    router.add_function("leaf_a", "def leaf_a():\n    return 1\n")
    router.add_function("leaf_b", "def leaf_b():\n    return 2\n")
    router.add_function(
        "root",
        "def root():\n    return leaf_a() + leaf_b()\n",
        dependencies=["leaf_a", "leaf_b"],
    )

    functions = router.get_all_functions()

    assert sorted(function["name"] for function in functions) == [
        "leaf_a",
        "leaf_b",
        "root",
    ]
    root = next(function for function in functions if function["name"] == "root")
    assert sorted(root["dependencies"]) == ["leaf_a", "leaf_b"]


def test_get_all_functions_stays_deduplicated_across_versions(router):
    router.add_function("leaf_a", "def leaf_a():\n    return 1\n")
    router.add_function("leaf_b", "def leaf_b():\n    return 2\n")
    router.add_function(
        "root",
        "def root():\n    return leaf_a() + leaf_b()\n",
        dependencies=["leaf_a", "leaf_b"],
    )
    router.update_function(
        "root",
        code="def root():\n    return leaf_a() + leaf_b() + 1\n",
        dependencies=["leaf_a", "leaf_b"],
    )

    functions = router.get_all_functions()

    assert sorted(function["name"] for function in functions) == [
        "leaf_a",
        "leaf_b",
        "root",
    ]
    root = next(function for function in functions if function["name"] == "root")
    assert root["version"] == 2
    assert sorted(root["dependencies"]) == ["leaf_a", "leaf_b"]
