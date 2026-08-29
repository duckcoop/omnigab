"""What "entry level" means, and why it stopped meaning almost nothing.

`entry_level=true` used to send USAJOBS two filters in one query: a pay
grade band and the Pathways student/graduate hiring paths. USAJOBS ANDs
its filters, so that asks for postings which are Pathways *and* low grade,
which in practice is Pathways alone. Measured against the live site for
series 2210 over a 30 day window:

    no filter                        668 postings
    pay grade 04-07 only             668 postings
    Pathways hiring path only          9 postings
    both, which is what it sent        9 postings

Two separate defects sit in that table. The search was returning a 1.3%
slice of the board while telling the user it was the whole of it, and the
pay-grade parameters were doing nothing whatsoever, which is why the
second row equals the first. The comment those parameters carried ("05-09
was too wide") described tuning that had never had any effect on anything.

Entry level is now a union: Pathways at any grade, merged with ordinary
postings at ENTRY_LEVEL_MAX_GRADE or below. The grade half is applied in
Python because no URL parameter on that page does it, so the parsing below
is the part that has to be right.

No network here. The live counterpart is in test_usajobs_scrape.py.
"""

from __future__ import annotations

import pytest

from tools.usajobs_search import (
    ENTRY_LEVEL_MAX_GRADE,
    UsaJobsSearchTool,
    is_entry_level_grade,
    parse_low_grade,
)


# ------------------------------------------------------- grade parsing

@pytest.mark.parametrize("text,expected", [
    # The three pay plans that appeared in one real page of IT results.
    ("Starting at $57,736 Per year (GG 7-11)PermanentFull-time", 7),
    ("Starting at $56,763 Per year (GS 7-9)InternshipsFull-time", 7),
    ("Starting at $143,913 Per year (NF 14)THIS IS A PRIVATE FUNDED", 14),
    # Shapes the card parser emits.
    ("GS 9", 9),
    ("GS-07", 7),
    ("GS 13", 13),
    # Lowest wins: the band is what the user can actually enter at.
    ("GS 5-9", 5),
    ("(GS 12-13) and (GS 7-9)", 7),
    # Nothing to read.
    ("", None),
    ("Full-time Permanent", None),
    (None, None),
])
def test_parse_low_grade(text, expected):
    assert parse_low_grade(text) == expected


def test_grade_parsing_is_not_gs_only():
    """The card parser matched `GS\\s*\\d+` and nothing else.

    Of the three postings in the result set that prompted this change, two
    were GG and NF. It read the grade of exactly one of them.
    """
    assert parse_low_grade("(GG 7-11)") == 7
    assert parse_low_grade("(NF 14)") == 14
    assert parse_low_grade("(NH 03)") == 3


# --------------------------------------------------- the entry decision

@pytest.mark.parametrize("job,keep", [
    ({"grade": "GS 7"}, True),
    ({"grade": "GS 9"}, True),                    # the cap itself is in
    ({"grade": "GS 11"}, False),
    ({"grade": "GS 13"}, False),
    ({"salary": "$143,913 Per year (NF 14)"}, False),
    ({"salary": "$57,736 Per year (GG 7-11)"}, True),   # band low is 7
])
def test_is_entry_level_grade(job, keep):
    assert is_entry_level_grade(job) is keep


def test_the_cap_is_the_documented_one():
    assert ENTRY_LEVEL_MAX_GRADE == 9
    assert is_entry_level_grade({"grade": f"GS {ENTRY_LEVEL_MAX_GRADE}"})
    assert not is_entry_level_grade({"grade": f"GS {ENTRY_LEVEL_MAX_GRADE + 1}"})


def test_an_unreadable_grade_is_kept_not_dropped():
    """Dropping it would repeat the mistake this tool was just fixed for.

    A posting whose pay line cannot be parsed is a posting we know nothing
    about, and silently removing it turns "could not read" into "not
    there", which is exactly how the scraper came to report 0 jobs out of
    668.
    """
    assert is_entry_level_grade({"title": "IT Specialist"})
    assert is_entry_level_grade({})
    assert is_entry_level_grade({"grade": "", "salary": "", "title": ""})


def test_grade_is_read_from_whichever_field_carries_it():
    """The scrape fills `grade` sometimes and only `salary` other times."""
    assert is_entry_level_grade({"grade": "GS 7", "salary": "(GS 13)"})
    assert not is_entry_level_grade({"grade": "", "salary": "(GS 13)"})


# ------------------------------------------------------ the search URL

@pytest.fixture
def tool():
    return UsaJobsSearchTool()


def test_the_dead_pay_grade_parameters_are_gone(tool):
    """668 results with them and 668 without. They never filtered anything."""
    url = tool._build_url("IT Specialist", "", 30, True, ["2210"])
    assert "pgs=" not in url
    assert "gsl=" not in url and "gsh=" not in url


def test_pathways_only_sends_the_hiring_paths(tool):
    url = tool._build_url("IT Specialist", "", 30, True, ["2210"])
    assert "hp=student" in url
    assert "hp=graduates" in url


def test_the_open_pass_sends_no_hiring_path(tool):
    """The half of the union that reaches the other 659 postings."""
    url = tool._build_url("IT Specialist", "", 30, False, ["2210"])
    assert "hp=" not in url
    assert "jc=2210" in url
    assert "k=IT+Specialist" in url


def test_url_still_carries_the_query_location_and_window(tool):
    url = tool._build_url("Cybersecurity", "Austin, TX", 14, False, [])
    assert "k=Cybersecurity" in url
    assert "l=Austin%2C+TX" in url
    assert "dap=14" in url
