#!/usr/bin/env bash
# Install the project requirements and run the test suite the way CI does.
set -euo pipefail

cd "$(dirname "$0")"

python -m pip install -q -r requirements.txt pytest
SQLALCHEMY_WARN_20=1 python -W error::DeprecationWarning -m pytest -q tests/
