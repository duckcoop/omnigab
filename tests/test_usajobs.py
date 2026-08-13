"""Live end-to-end check of the usajobs_search tool.

Ported from the standalone runner that used to live here. That version
was an argparse CLI which printed the whole result and returned 0 only if
`result["ok"]` was true, so it made exactly two claims: the tool does not
raise, and it reports success. Both are preserved below; the printing is
gone, because pytest shows a failing result on its own.

The runner also computed the repository root one level too high
(`Path(__file__).resolve().parent` is `tests/`, not the root), so its
`chdir(str(SRC))` raised FileNotFoundError and the file had not run in
some time. The fix is the deletion: nothing under test needs a working
directory any more, so ROOT and SRC are gone rather than corrected. See
`isolated_cwd` in conftest.py.

Run it with:
    pytest -m integration tests/test_usajobs.py
"""

from __future__ import annotations

import pytest


@pytest.mark.integration
def test_usajobs_search_runs_and_reports_ok(usajobs_tool):
    # The old runner's argparse defaults, minus --no-embedder, which is
    # how conftest builds the tool. An embedder only fills in
    # match_percent, which nothing here asserts on.
    result = usajobs_tool.run({
        "query": "IT Specialist",
        "location": "",
        "max_jobs": 5,
        "days_ago": 30,
        "entry_level": False,
        "ai_focus": False,
    })
    assert result.get("ok")
