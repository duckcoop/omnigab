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
echo " 1/3  flake8"
echo "============================================================"
if ! "$PY" -m flake8 src tests; then
    echo
    echo "[verify] FAILED: flake8"
    exit 1
fi
echo "[verify] flake8 clean"

echo
echo "============================================================"
echo " 2/3  pyflakes (whole repo)"
echo "============================================================"
# The full ruleset runs on src and tests only, because desktop_app.py and
# scripts/ still carry cosmetic findings. The pyflakes subset is the bug
# half of flake8 (undefined names, unused imports, redefinitions) and the
# whole repo passes it, so gate on it everywhere. This is what would have
# caught the two handlers that raised NameError instead of showing the
# user an error.
if ! "$PY" -m flake8 --select=F src tests scripts desktop_app.py; then
    echo
    echo "[verify] FAILED: pyflakes"
    exit 1
fi
echo "[verify] pyflakes clean"

echo
echo "============================================================"
echo " 3/3  pytest"
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
