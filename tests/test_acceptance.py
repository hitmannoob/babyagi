"""Acceptance guard tests for the SQLAlchemy 2.0 migration.

These tests encode the three acceptance criteria from the project goal:

1. requirements.txt requires SQLAlchemy 2.x and no longer pins below 2.0.
2. No code under babyagi/ uses the legacy SQLAlchemy 1.x APIs.

Criterion 3 (the database layer registers, reads and updates functions) is
covered by ``tests/test_db_layer.py`` and ``tests/test_db_router.py``.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BABYAGI_DIR = REPO_ROOT / "babyagi"
REQUIREMENTS = REPO_ROOT / "requirements.txt"

LEGACY_PATTERNS = {
    "session.query()": re.compile(r"\.query\s*\("),
    "engine.execute()": re.compile(r"engine\.execute\s*\("),
    "declarative_base() from sqlalchemy.ext.declarative": re.compile(
        r"from\s+sqlalchemy\.ext\.declarative\s+import\s+[^\n]*declarative_base"
    ),
}


def _python_files():
    return sorted(BABYAGI_DIR.rglob("*.py"))


def test_requirements_require_sqlalchemy_2():
    lines = [
        line.strip()
        for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    sqlalchemy_lines = [line for line in lines if line.lower().startswith("sqlalchemy")]

    assert len(sqlalchemy_lines) == 1, f"expected one sqlalchemy pin, got {sqlalchemy_lines!r}"
    pin = sqlalchemy_lines[0]
    assert ">=2.0" in pin, f"SQLAlchemy pin must require 2.x: {pin!r}"
    assert "<3" in pin, f"SQLAlchemy pin must stay below 3.x: {pin!r}"
    assert "<2.0" not in pin and "<2," not in pin, f"SQLAlchemy pin must not cap below 2.0: {pin!r}"


def test_no_legacy_sqlalchemy_apis_under_babyagi():
    offenders = []
    for path in _python_files():
        source = path.read_text(encoding="utf-8", errors="replace")
        for name, pattern in LEGACY_PATTERNS.items():
            for match in pattern.finditer(source):
                line_number = source.count("\n", 0, match.start()) + 1
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{line_number}: {name}")

    assert not offenders, "legacy SQLAlchemy usage remains:\n" + "\n".join(offenders)


def test_runtime_sqlalchemy_is_2_x():
    """Criterion 3 must be verified against SQLAlchemy 2.x, not assumed."""
    import sqlalchemy

    major = int(sqlalchemy.__version__.split(".", 1)[0])
    assert major >= 2, f"tests must run on SQLAlchemy 2.x, got {sqlalchemy.__version__}"


def test_check_sh_runs_the_acceptance_command():
    """Goal item 4: check.sh installs requirements and runs the strict suite."""
    script = (REPO_ROOT / "check.sh").read_text(encoding="utf-8")

    assert "-r requirements.txt" in script
    assert "SQLALCHEMY_WARN_20=1" in script
    assert "python -W error::DeprecationWarning -m pytest -q tests/" in script
