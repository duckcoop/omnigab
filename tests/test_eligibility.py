"""Who a federal posting is open to, and whether that includes the user.

The scoring this replaces was a cosine similarity between the user's
resume embedding and the job text. On one real result set for an IT
student holding Security+:

    IT SPECIALIST (SYSADMIN), NH-3/4       29%   ranked best
    IT Cybersecurity Specialist,
      CES Recent Graduate                  20%   ranked worse

The 29% posting is open to "Federal employees - Competitive service" and
the user cannot apply to it. The 20% posting is open to "Recent
graduates", which is what he is. Similarity measures shared vocabulary,
and a senior sysadmin listing shares more IT nouns with an IT resume than
an HR-worded Pathways listing does.

USAJOBS states the answer in a "This job is open to" block on every
posting, as an `h2` followed by one `h3` per audience. The fixtures below
reproduce that markup, including the two traps the real pages set:

  * the heading sits in its own wrapper with the audiences in a sibling,
    so the nearest enclosing element names nobody
  * the block can carry a "Clarification from the agency" heading, which
    is agency prose and not an audience

No network. The live counterpart is at the bottom, behind the integration
marker.
"""

from __future__ import annotations

import pytest

from jobs.eligibility import (
    HARD_PATHS,
    HIRING_PATHS,
    assess,
    extract_hiring_paths,
    paths_from_headings,
    paths_from_text,
)

bs4 = pytest.importorskip("bs4")
BeautifulSoup = bs4.BeautifulSoup

STUDENT = {"public", "students", "recent_graduates"}
PUBLIC_ONLY = {"public"}


def _page(*audiences: str, clarification: bool = True) -> str:
    """A detail page shaped like the real one: heading and audiences are
    siblings, not parent and child."""
    blocks = "".join(f"<div><h3>{name}</h3><p>Some description.</p></div>"
                     for name in audiences)
    extra = ("<div><h3>Clarification from the agency</h3>"
             "<p>Open to veterans of the Space Force.</p></div>"
             if clarification else "")
    return f"""
    <html><body>
      <div class="page-section">
        <div><h2>This job is open to</h2><span>Help</span></div>
        {blocks}{extra}
      </div>
      <div class="posting-body">
        <h3>Requirements</h3>
        <p>Veterans preference applies. Students may be considered.
           Military spouses. Native Americans. Senior executives.</p>
      </div>
    </body></html>
    """


def _soup(html: str):
    return BeautifulSoup(html, "html.parser")


# ------------------------------------------------------------ extraction

def test_the_audience_headings_are_read_not_the_surrounding_prose():
    """The trap that makes a naive scan useless.

    The body of a posting is full of the words "Veterans", "Students" and
    "Military spouses" in prose about preference and qualifications. Only
    the block counts.
    """
    paths = extract_hiring_paths(_soup(_page("Recent graduates")))
    assert paths == ["recent_graduates"]


def test_the_nearest_wrapper_is_skipped_for_one_that_holds_the_audiences():
    """The heading's own parent contains no `h3`, so it names nobody."""
    assert extract_hiring_paths(_soup(_page("The public"))) == ["public"]


def test_the_agency_clarification_is_not_an_audience():
    paths = extract_hiring_paths(_soup(_page("Recent graduates")))
    assert "veterans" not in paths, "clarification prose is not a hiring path"


def test_multiple_audiences_are_all_returned():
    paths = extract_hiring_paths(_soup(_page(
        "Federal employees - Competitive service", "Veterans",
        "Military spouses")))
    assert paths == ["federal_competitive", "veterans", "military_spouses"]


def test_a_page_with_no_such_block_returns_nothing():
    assert extract_hiring_paths(_soup("<html><body><p>hi</p></body></html>")) == []


@pytest.mark.parametrize("printed,key", [
    ("The public", "public"),
    ("Federal employees - Competitive service", "federal_competitive"),
    ("Federal employees - Excepted service", "federal_excepted"),
    ("Internal to an agency", "internal_agency"),
    ("Recent graduates", "recent_graduates"),
    ("Students", "students"),
    ("Veterans", "veterans"),
    ("Senior executives", "senior_executives"),
    # USAJOBS renders the ampersand both ways for the same path.
    ("National Guard & reserves", "national_guard"),
    ("National Guard and reserves", "national_guard"),
    ("Land & base management", "land_management"),
])
def test_every_printed_label_maps_to_its_key(printed, key):
    assert paths_from_headings([printed]) == [key]


def test_an_unknown_heading_is_ignored_rather_than_guessed_at():
    assert paths_from_headings(["Open to interpretive dancers"]) == []


def test_a_long_label_is_not_shadowed_by_a_short_one_inside_it():
    """The text fallback blanks each hit so this cannot go wrong.

    "Federal employees - Competitive service" contains no other label, but
    a future one might, and the ordering is what stops it counting twice.
    """
    keys = paths_from_text("Federal employees - Competitive service")
    assert keys == ["federal_competitive"]


# -------------------------------------------------------------- verdicts

def test_a_posting_open_to_your_path_is_eligible():
    verdict = assess(["recent_graduates"], STUDENT)
    assert verdict.verdict == "eligible"
    assert verdict.matched == ["recent_graduates"]
    assert "recent graduates" in verdict.reason


def test_open_to_the_public_is_eligible_for_anyone():
    assert assess(["public"], PUBLIC_ONLY).verdict == "eligible"


def test_federal_employees_only_is_blocked_for_an_outsider():
    """The posting that was being ranked first. It is a dead end."""
    verdict = assess(["federal_competitive"], STUDENT)
    assert verdict.blocked
    assert "federal employees" in verdict.reason.lower()


def test_internal_to_an_agency_is_blocked():
    assert assess(["internal_agency", "career_transition"], STUDENT).blocked


def test_a_hard_path_alongside_a_soft_one_is_conditional_not_blocked():
    """The user asked for hard blocks hidden and everything else marked.

    A federal-employee vacancy that also takes veterans is not a dead end
    for a veteran, and the tool does not know the user is not one unless
    they said so.
    """
    verdict = assess(["federal_competitive", "veterans", "military_spouses"],
                     STUDENT)
    assert verdict.verdict == "conditional"
    assert not verdict.blocked
    # Naming only the soft paths would read as "open to veterans", hiding
    # that this is really a federal-employee vacancy.
    assert "federal employees" in verdict.reason.lower()
    assert "veterans" in verdict.reason.lower()


def test_claiming_the_path_turns_conditional_into_eligible():
    paths = ["federal_competitive", "veterans"]
    assert assess(paths, STUDENT).verdict == "conditional"
    assert assess(paths, STUDENT | {"veterans"}).verdict == "eligible"


def test_an_unreadable_block_is_conditional_never_blocked():
    """Hiding a job because a page failed to parse repeats an old mistake.

    The scraper once reported zero jobs out of 668 because a selector
    broke. "Could not read it" must never render as "not for you".
    """
    verdict = assess([], STUDENT)
    assert verdict.verdict == "conditional"
    assert not verdict.blocked
    assert "did not say" in verdict.reason


# ------------------------------------------------------- the vocabulary

def test_every_hard_path_is_a_known_path():
    assert HARD_PATHS <= set(HIRING_PATHS)


def test_hard_paths_are_the_ones_with_no_route_in():
    """A membership fact, not a preference. Guarded so the list cannot
    quietly grow to include something a determined applicant can reach."""
    assert HARD_PATHS == {
        "federal_competitive", "federal_excepted", "internal_agency",
        "career_transition", "senior_executives",
    }


def test_public_is_never_a_hard_path():
    assert "public" not in HARD_PATHS
    assert "students" not in HARD_PATHS
    assert "recent_graduates" not in HARD_PATHS


# -------------------------------------------------------------- the live page

@pytest.mark.integration
@pytest.mark.parametrize("job_id,expected", [
    # The posting the old scorer ranked best, which the user cannot apply to.
    ("881220500", "federal_competitive"),
    # The one he identified as a good fit, ranked worse.
    ("880946700", "recent_graduates"),
])
def test_live_posting_audiences(job_id, expected):
    import requests

    from tools.usajobs_search import USER_AGENT

    response = requests.get(f"https://www.usajobs.gov/job/{job_id}",
                            headers={"User-Agent": USER_AGENT}, timeout=30)
    if response.status_code != 200:
        pytest.skip(f"USAJOBS returned {response.status_code}")
    paths = extract_hiring_paths(BeautifulSoup(response.text, "html.parser"))
    assert expected in paths, (
        f"job {job_id} parsed as {paths}. USAJOBS may have changed the "
        f"'This job is open to' markup again."
    )


# ------------------------------------------------------------- fit bands

from jobs.eligibility import (  # noqa: E402  (grouped with its own tests)
    LONG_SHOT, POSSIBLE, STRONG, fit,
)


def _fit(job=None, paths=("recent_graduates",), profile=STUDENT,
         cap=9, low=7):
    verdict = assess(list(paths), set(profile))
    return fit(dict(job or {}), verdict, grade_cap=cap, low_grade=low)


def test_an_early_career_path_at_a_low_grade_is_a_strong_fit():
    """The posting the old scorer ranked below two it could not apply to."""
    band, reasons = _fit()
    assert band == STRONG
    assert "open to recent graduates" in reasons
    assert "opens at GS-07" in reasons


def test_a_grade_above_the_cap_is_a_long_shot_even_when_open_to_you():
    """The $143,913 NF-14 the user called out as obviously not entry level."""
    band, reasons = _fit(paths=("public", "students"), low=14)
    assert band == LONG_SHOT
    assert any("above the GS-09" in r for r in reasons)


def test_a_path_you_have_not_claimed_is_always_a_long_shot():
    """No amount of cert overlap makes a vacancy you cannot enter a good bet."""
    band, reasons = _fit({"cert_matches": ["Security+", "A+"]},
                         paths=("federal_competitive", "veterans"))
    assert band == LONG_SHOT
    assert "none of which you have claimed" in reasons[0]


def test_matched_certs_raise_the_band_and_are_named():
    band, reasons = _fit({"cert_matches": ["Security+"]},
                         paths=("public",), low=9)
    assert band == STRONG
    assert "names your Security+" in reasons


def test_a_clearance_you_lack_lowers_the_band_and_says_so():
    plain, _ = _fit()
    guarded, reasons = _fit({"missing_clearance": "Top Secret"})
    assert plain == STRONG and guarded == POSSIBLE
    assert "needs a Top Secret clearance" in reasons


def test_open_to_everyone_is_possible_rather_than_strong():
    """"Anyone may apply" is the absence of a barrier, not a reason to.

    A posting open to the public at an entry grade with nothing tying it
    to this user is a fair bet, not a strong one. Reserving the top band
    for postings that name a path the user holds is what stops every
    result being a Strong fit, which would be the percentage problem back
    in three words.
    """
    assert _fit(paths=("public",), profile=PUBLIC_ONLY)[0] == POSSIBLE


def test_every_band_carries_its_reasons():
    """A band with no reasons is the percentage problem again, coarser."""
    for kwargs in ({}, {"low": 14}, {"paths": ("federal_competitive",),
                                     "profile": PUBLIC_ONLY}):
        band, reasons = _fit(**kwargs)
        assert band in (STRONG, POSSIBLE, LONG_SHOT)
        assert reasons, f"{band} explained nothing"


def test_no_grade_reference_still_bands_on_eligibility():
    """The Pathways pass runs with no grade filter by design."""
    band, reasons = _fit(cap=None, low=None)
    assert band in (POSSIBLE, STRONG)
    assert "open to recent graduates" in reasons
