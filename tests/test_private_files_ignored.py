"""Files holding the user's real identity must not be committable.

`.gitignore` already protects the resume artifacts under `data/`, with a
comment saying why: they contain the user's real work history. The same
reasoning covers `baseresume.txt`, which `resume_ingest` writes at the
repository root from a `baseresume.pdf` or `.docx` dropped beside it, and
that one was missed. It holds a name, a street address, a phone number,
and an email.

Two things kept it invisible. It lives at the root rather than under
`data/`, so none of the `data/*resume*` patterns reach it, and it does not
exist in a fresh clone: it appears the first time someone actually runs
the app with a resume loaded. Nothing has ever been committed, and this
file exists so nothing ever is.

The check reads `.gitignore` and keys off the constants in
`resume_ingest`, so renaming the artifact without updating the ignore
rules fails here rather than silently publishing a home address to a
public repository.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import resume_ingest

REPO_ROOT = Path(__file__).resolve().parent.parent
GITIGNORE = REPO_ROOT / ".gitignore"


def _ignore_patterns() -> set[str]:
    text = GITIGNORE.read_text(encoding="utf-8")
    return {
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    }


def test_gitignore_exists_and_was_read():
    # Guards every test below: a missing file would make them fail for the
    # wrong reason, and a misread path would make them pass for one.
    assert GITIGNORE.is_file()
    assert len(_ignore_patterns()) > 10


def test_the_extracted_resume_is_ignored():
    """Keyed off the constant, so a rename cannot outrun the ignore rule."""
    name = resume_ingest.BASE_RESUME_TXT.name
    assert name in _ignore_patterns(), (
        f"{name} holds the user's real name, address and phone number and "
        f"is written into the repository root by resume_ingest. Add it to "
        f".gitignore."
    )


@pytest.mark.parametrize("source", resume_ingest._SOURCE_NAMES)
def test_the_source_resume_documents_are_ignored(source):
    """The PDF and DOCX are the originals, and carry strictly more."""
    assert source in _ignore_patterns()


def test_the_resume_lives_at_the_repository_root():
    """Why the data/ patterns never covered it.

    If this ever moves under data/, the ignore rules above become
    redundant rather than wrong, but the reason for them should stop being
    a mystery to whoever reads this next.
    """
    assert resume_ingest.BASE_RESUME_TXT.parent == REPO_ROOT


def test_the_data_resume_paths_are_still_ignored():
    """The protection that already existed, pinned so it cannot be lost."""
    patterns = _ignore_patterns()
    for pattern in ("data/resume_drafts/", "data/docs/active_resume.*",
                    "data/docs/*resume*"):
        assert pattern in patterns, f"{pattern} was protecting real user data"
