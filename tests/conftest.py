"""Shared fixtures for the omnigab test suite.

Two rules from AGENTS.md section 6 shape everything here. A test must pass
with no GPU, no model file, and no network. And no test may write outside
its own `tmp_path`, which rules out the user's real `data/storage.db`,
`vectorstore/`, and anything else under the repository.

Nothing in this file needs a marker. The `integration` and `model` markers
are declared in `pyproject.toml` and applied to individual tests.
"""

from __future__ import annotations

import pytest

from persistent_memory import PersistentMemory
from tools.usajobs_search import UsaJobsSearchTool


@pytest.fixture(autouse=True)
def isolated_cwd(tmp_path, monkeypatch):
    """Run every test from a throwaway working directory.

    This is what replaced the four bare `chdir(str(SRC))` calls the legacy
    harnesses made. Those existed because tests used to fix up `sys.path`
    by hand, so the modules under test could only be imported with `src/`
    as the working directory. Since PR0 the package is installed and every
    module resolves its paths from `__file__`, so no module under test
    needs a particular working directory any more. That was verified by
    importing all of them from an unrelated drive root.

    The directory switch is kept, pointed at `tmp_path` rather than
    `src/`, for the half of the job that is still worth doing: anything
    under test that writes to a relative path lands somewhere pytest
    deletes instead of in the repository. `monkeypatch.chdir` also
    restores the previous directory at teardown, which the bare call never
    did, so the global state no longer leaks from one check into the next.
    """
    monkeypatch.chdir(tmp_path)


@pytest.fixture
def memory_db(tmp_path) -> PersistentMemory:
    """A PersistentMemory backed by a database inside `tmp_path`.

    Deliberately not `get_persistent_memory()`. That singleton opens the
    user's real `data/storage.db`, and the round-trip check used to leave
    a `_test_omnigab_marker` row behind in it. Constructing the class
    directly is the same code path minus the singleton and minus the
    legacy `memory.db` rename, which only fires for the default path.
    """
    return PersistentMemory(tmp_path / "storage.db")


@pytest.fixture(scope="session")
def usajobs_tool() -> UsaJobsSearchTool:
    """The USAJOBS tool with no embedder and no resume behind it.

    Session scoped because the object holds no per-test state: it is three
    injected callables and nothing else. The live query it performs is the
    expensive part, and the tests that need one cache the result
    themselves.

    No embedder means no sentence-transformers load, which is what the old
    `--no-embedder` flag bought. The embedder only populated
    `match_percent` for the printed report, and no check ever asserted on
    it.
    """
    return UsaJobsSearchTool(
        embedder=None,
        resume_text_getter=lambda: None,
        resume_certs_getter=lambda: [],
    )
