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
    echo "[verify] Until PR0a lands this reports 63 pre-existing findings."
    exit 1
fi
echo "[verify] flake8 clean"

echo
echo "============================================================"
echo " 2/2  pytest"
echo "============================================================"
"$PY" -m pytest --cov=src --cov-report=term-missing
PYTEST_RC=$?

# Exit 5 means pytest collected no tests. That is the expected state
# until PR1 lands, because none of the four files under tests/ define a
# test_ function yet. Warn rather than fail, so this gate is usable
# during PR0a. Delete this branch once PR1 is merged, so that "no tests
# collected" goes back to being a real failure.
if [ "$PYTEST_RC" -eq 5 ]; then
    echo
    echo "[verify] WARNING: pytest collected no tests. Expected until PR1."
elif [ "$PYTEST_RC" -ne 0 ]; then
    echo
    echo "[verify] FAILED: pytest (exit $PYTEST_RC)"
    exit 1
fi

echo
echo "============================================================"
echo " ALL GREEN"
echo "============================================================"
exit 0
