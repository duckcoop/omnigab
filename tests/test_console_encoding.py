"""Nothing under src/ may write non-ASCII to stdout.

Python on Windows picks the locale encoding for a redirected stdout, which
is cp1252 here and on a CI runner. Printing a character outside that set
raises UnicodeEncodeError, so a decorative arrow or box-drawing character
in a log line does not degrade, it replaces the message with a traceback
at the exact moment the message mattered.

This is not hypothetical. The pre-pytest harness died at its first check
mark (U+2713) when its output was piped, and 19 lines under src/ had the
same defect: arrows, an ellipsis, an em dash, box drawing, and emoji.

The test reads source rather than running anything, so it holds for code
paths no test exercises, which is most of the printing in this project.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import config

SRC = Path(config.__file__).resolve().parent
# Lines that put text on stdout. _log is usajobs_search's own printer.
EMITTERS = ("print(", "_log(")


def _source_files() -> list[Path]:
    return sorted(p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts)


def _offending_lines(path: Path) -> list[tuple[int, str]]:
    out = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not any(token in line for token in EMITTERS):
            continue
        if any(ord(char) > 127 for char in line):
            out.append((number, line.strip()))
    return out


def test_source_tree_was_found():
    # Guards the test itself: an empty glob would make everything below
    # pass for the wrong reason.
    assert len(_source_files()) > 20


@pytest.mark.parametrize("path", _source_files(), ids=lambda p: p.name)
def test_no_non_ascii_on_stdout_lines(path: Path):
    offenders = _offending_lines(path)
    assert not offenders, (
        f"{path.name} writes non-ASCII to stdout, which raises "
        f"UnicodeEncodeError on a cp1252 console: "
        + "; ".join(f"line {n}: {text[:60]!r}" for n, text in offenders)
    )


def test_non_printed_unicode_is_still_allowed():
    """The rule is about stdout, not about source files.

    `gate.py` deliberately holds curly quotes and dashes in its punctuation
    folding table. That data has to contain the characters it folds, and it
    is never printed, so a blanket ban on unicode in source would be the
    wrong rule and would break the extraction gate.
    """
    fold_table = (SRC / "extraction" / "gate.py").read_text(encoding="utf-8")
    assert any(ord(char) > 127 for char in fold_table)
