#!/usr/bin/env bash
# Quality gate. Run this yourself before accepting any agent PR.
# Never take the agent's word that tests pass.
#
# Exit code 0 means the task is done. Anything else means it is not,
# whatever the summary said.
#
# Linux/macOS companion to verify.bat. Useful once CI runs on Linux,
# since it is the same gate the workflow applies.

set -uo pipefail

PY="${PYTHON:-python3}"

echo
echo "============================================================"
echo " 1/2  flake8"
echo "============================================================"
if ! "$PY" -m flake8 src tests; then
    echo
    echo "[verify] FAILED: flake8"
    exit 1
fi
echo "[verify] flake8 clean"

echo
echo "============================================================"
echo " 2/2  pytest"
echo "============================================================"
"$PY" -m pytest --cov=src --cov-report=term-missing
PYTEST_RC=$?

# Any non-zero code is a failure, including 5 (no tests collected). PR1
# tolerated 5 while tests/ held no test_ function; now that the suite is
# real, "collected nothing" means collection broke.
if [ "$PYTEST_RC" -ne 0 ]; then
    echo
    echo "[verify] FAILED: pytest (exit $PYTEST_RC)"
    exit 1
fi

echo
echo "============================================================"
echo " ALL GREEN"
echo "============================================================"
exit 0
