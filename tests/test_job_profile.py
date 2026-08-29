"""The user's hiring-path profile: what they can apply under.

`eligibility.assess` needs to know which paths the user holds, and that is
a fact about a person rather than about a posting. A resume does not say
whether somebody is a veteran, a current federal employee, or still
enrolled, so it has to be asked for and stored.

It is a setting rather than a constant because the app is not written for
one person, which is the whole reason the Settings tab grew a card for it.

Nothing here touches the real `data/` directory; every test redirects
`JOB_PROFILE_PATH` into `tmp_path`.
"""

from __future__ import annotations

import json

import pytest

import config
from jobs.eligibility import HIRING_PATHS, PROFILE_CHOICES


@pytest.fixture
def profile_path(tmp_path, monkeypatch):
    path = tmp_path / "job_profile.json"
    monkeypatch.setattr(config, "JOB_PROFILE_PATH", path)
    return path


# ------------------------------------------------------------- defaults

def test_an_untouched_install_claims_only_the_public_path(profile_path):
    """The default must hide nothing the user could have applied for.

    Everyone can apply to a posting open to the public, so it is the only
    safe thing to assume about somebody who has not answered yet.
    """
    assert config.load_job_profile() == ["public"]


def test_a_corrupt_file_falls_back_rather_than_raising(profile_path):
    profile_path.write_text("{not json", encoding="utf-8")
    assert config.load_job_profile() == ["public"]


def test_a_file_with_the_wrong_shape_falls_back(profile_path):
    profile_path.write_text(json.dumps({"paths": "veterans"}), encoding="utf-8")
    assert config.load_job_profile() == ["public"]


def test_an_empty_list_falls_back_to_the_default(profile_path):
    profile_path.write_text(json.dumps({"paths": []}), encoding="utf-8")
    assert config.load_job_profile() == ["public"]


# ---------------------------------------------------------- round trips

def test_saving_and_loading_preserves_the_selection(profile_path):
    config.save_job_profile(["recent_graduates", "veterans"])
    assert config.load_job_profile() == ["public", "recent_graduates",
                                         "veterans"]


def test_public_is_forced_on_when_saving(profile_path):
    """Untickable in the UI, and guaranteed here rather than trusted.

    A user who ticked only "veteran" would otherwise have every ordinary
    vacancy hidden from them, which is the opposite of the point.
    """
    config.save_job_profile(["veterans"])
    assert "public" in json.loads(profile_path.read_text(encoding="utf-8"))["paths"]


def test_public_is_forced_on_when_loading_a_file_that_lacks_it(profile_path):
    profile_path.write_text(json.dumps({"paths": ["veterans"]}),
                            encoding="utf-8")
    assert "public" in config.load_job_profile()


def test_duplicates_collapse(profile_path):
    config.save_job_profile(["veterans", "veterans", "public"])
    assert config.load_job_profile().count("veterans") == 1


def test_unticking_everything_returns_to_public_only(profile_path):
    config.save_job_profile(["veterans"])
    config.save_job_profile([])
    assert config.load_job_profile() == ["public"]


# ------------------------------------------------------------ validation

def test_an_unknown_path_is_refused(profile_path):
    """Typos must not silently become a filter that matches nothing."""
    with pytest.raises(ValueError, match="Unknown hiring path"):
        config.save_job_profile(["veterans", "spaceforce"])
    assert not profile_path.exists()


# ------------------------------------------------- the offered choices

@pytest.mark.parametrize("key,label,explanation", PROFILE_CHOICES)
def test_every_offered_choice_is_a_real_hiring_path(key, label, explanation):
    """A choice that is not in the vocabulary can never match a posting."""
    assert key in HIRING_PATHS
    assert label and explanation


def test_the_choices_are_all_savable(profile_path):
    config.save_job_profile([key for key, _, _ in PROFILE_CHOICES])
    saved = config.load_job_profile()
    for key, _, _ in PROFILE_CHOICES:
        assert key in saved


def test_public_is_not_offered_as_a_checkbox():
    """A tickbox nobody can sensibly untick only invites mistakes."""
    assert "public" not in {key for key, _, _ in PROFILE_CHOICES}


def test_internal_to_an_agency_is_not_offered():
    """It is specific to whichever agency posted the job.

    Unlike "veteran" or "student", it is not a fact about a person, so
    there is nothing for a user to truthfully tick.
    """
    assert "internal_agency" not in {key for key, _, _ in PROFILE_CHOICES}


def test_choice_keys_are_unique():
    keys = [key for key, _, _ in PROFILE_CHOICES]
    assert len(keys) == len(set(keys))
