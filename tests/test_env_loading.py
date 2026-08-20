"""Settings in .env have to reach os.environ, or they do nothing.

`usajobs_search` reads USAJOBS_API_KEY straight from the environment. The
`.env` file was parsed for the API token only, so a key put in the obvious
place was silently ignored and the tool fell back to browser-handoff mode,
returning zero listings with no error anywhere.
"""

from __future__ import annotations

import os

import pytest

from security import load_env_file


@pytest.fixture
def env_file(tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        "USAJOBS_API_KEY=abc123\n"
        "USAJOBS_API_EMAIL=someone@example.com\n"
        "\n"
        "# a comment line\n"
        'QUOTED="with quotes"\n',
        encoding="utf-8")
    return path


def test_loads_keys_into_environment(env_file, monkeypatch):
    for key in ("USAJOBS_API_KEY", "USAJOBS_API_EMAIL", "QUOTED"):
        monkeypatch.delenv(key, raising=False)
    applied = load_env_file(env_file)
    assert set(applied) == {"USAJOBS_API_KEY", "USAJOBS_API_EMAIL", "QUOTED"}
    assert os.environ["USAJOBS_API_KEY"] == "abc123"
    assert os.environ["QUOTED"] == "with quotes"


def test_real_environment_wins(env_file, monkeypatch):
    # A value set for the process is a deliberate override and must not be
    # clobbered by a file on disk.
    monkeypatch.setenv("USAJOBS_API_KEY", "from-the-shell")
    applied = load_env_file(env_file)
    assert "USAJOBS_API_KEY" not in applied
    assert os.environ["USAJOBS_API_KEY"] == "from-the-shell"


def test_missing_file_is_not_an_error(tmp_path):
    assert load_env_file(tmp_path / "nope.env") == []
