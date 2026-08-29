"""Private-sector board results go through the same deterministic renderer.

`job_boards_search` has been registered in the tool catalog for a while and
the agent never called it: SYSTEM_PROMPT routed every private-sector job
request to `open_in_browser`, which opens a tab and returns no listings.
Worse, had the model called it, `RENDERED_TOOLS` held only
`usajobs_search`, so the board results would have been handed to the model
as raw JSON with URLs in it, and the model would have had to transcribe
them. That is exactly what invariant I5 forbids and what job_renderer
exists to prevent.

The renderer itself needed almost nothing: `jobs.sources.posting()` was
written to emit the keys job_renderer reads. These tests pin that
agreement down, because it is currently held together by a docstring and
would break silently if either side moved.

No network. The payloads below are the shapes `search_many` returns,
copied from a live run.
"""

from __future__ import annotations

import pytest

from core import job_renderer
from core.agent import Agent
from jobs.sources import posting

BOARD_PAYLOAD = {
    "ok": True,
    "query": "IT Specialist",
    "location": "(anywhere)",
    "found": 2,
    "results": [
        posting(
            title="IT Specialist (Data Center Technician)",
            company="Amazon",
            url="https://www.amazon.jobs/en/jobs/10482267/it-specialist",
            location="US, VA, Herndon",
            summary="Data center operations.",
            source="amazon",
        ),
        posting(
            title="Senior Backend Engineer",
            company="Acme Remote",
            url="https://remoteok.com/remote-jobs/12345",
            location="Remote",
            source="remoteok",
        ),
    ],
    "handoffs": [
        {"source": "linkedin", "label": "LinkedIn",
         "url": "https://www.linkedin.com/jobs/search/?keywords=IT+Specialist",
         "reason": "LinkedIn's terms prohibit automated access."},
        {"source": "indeed_web", "label": "Indeed (browser)",
         "url": "https://www.indeed.com/jobs?q=IT+Specialist",
         "reason": "Cloudflare challenge."},
    ],
    "errors": [],
    "sources_searched": ["amazon", "remoteok"],
}

HANDOFF_ONLY_PAYLOAD = {
    "ok": True,
    "query": "welder",
    "location": "(anywhere)",
    "found": 0,
    "results": [],
    "handoffs": BOARD_PAYLOAD["handoffs"],
    "errors": [{"source": "amazon", "error": "HTTPError: 503"}],
    "sources_searched": ["amazon", "remoteok"],
}


# ------------------------------------------------------------- the wiring

def test_job_boards_search_output_is_rendered_by_python():
    """Without this the model would be transcribing board URLs by hand."""
    assert "job_boards_search" in Agent.RENDERED_TOOLS
    assert "usajobs_search" in Agent.RENDERED_TOOLS


def test_posting_emits_the_keys_the_renderer_reads():
    """The contract between jobs.sources and core.job_renderer.

    posting() maps `company` onto `agency` precisely so one renderer can
    serve both federal and private-sector results. Nothing enforced that.
    """
    item = posting(title="T", company="C", url="https://example.invalid/1",
                   location="L", salary="S", source="amazon")
    for key in ("title", "agency", "location", "salary", "url", "source"):
        assert key in item, f"job_renderer reads {key!r}"
    assert item["agency"] == "C"


# ------------------------------------------------------------- rendering

def test_board_results_render_with_their_own_source_label():
    block = job_renderer.render_results(BOARD_PAYLOAD)
    assert "**1. IT Specialist (Data Center Technician)**" in block
    assert "Amazon" in block
    assert "[View on Amazon Jobs](https://www.amazon.jobs/en/jobs/10482267/it-specialist)" in block
    assert "[View on RemoteOK](https://remoteok.com/remote-jobs/12345)" in block
    # "Apply on USAJOBS" is the federal label and must not leak onto a
    # private-sector posting.
    assert "Apply on USAJOBS" not in block


def test_series_and_verification_claims_stay_federal_only():
    """Board postings have no OPM series, and no URL was HTTP checked.

    Printing "Series ?" is noise; claiming the links were verified would
    be a statement the code did not earn.
    """
    block = job_renderer.render_results(BOARD_PAYLOAD)
    assert "Series" not in block
    assert "HTTP 200" not in block


def test_handoff_links_are_rendered_not_written_by_the_model():
    block = job_renderer.render_results(BOARD_PAYLOAD)
    assert "they block automated access" in block
    assert "[LinkedIn](https://www.linkedin.com/jobs/search/?keywords=IT+Specialist)" in block
    assert "[Indeed (browser)](https://www.indeed.com/jobs?q=IT+Specialist)" in block


def test_a_search_with_only_handoffs_still_renders_something():
    """Zero API results is not an empty answer when links were produced."""
    block = job_renderer.render_results(HANDOFF_ONLY_PAYLOAD)
    assert block
    assert "LinkedIn" in block


def test_a_failed_board_is_named_in_the_footer():
    """A short list because a board was down must not read as the whole picture."""
    block = job_renderer.render_results(HANDOFF_ONLY_PAYLOAD)
    assert "amazon" in block
    assert "failed" in block


# --------------------------------------------------------- model digest

def test_the_model_never_sees_a_url():
    """summarize_for_model is what reaches the context window.

    The model cannot copy a URL wrong if it was never shown one.
    """
    digest = job_renderer.summarize_for_model(BOARD_PAYLOAD)
    assert "http" not in digest
    assert "amazon.jobs" not in digest
    assert "IT Specialist (Data Center Technician)" in digest
    assert "Amazon" in digest


def test_handoff_only_digest_does_not_claim_nothing_was_found():
    """The old digest said "no open postings" while three links existed.

    The model repeats what the digest tells it, so a digest that reports a
    blank result makes the assistant contradict the block rendered directly
    underneath its own reply.
    """
    digest = job_renderer.summarize_for_model(HANDOFF_ONLY_PAYLOAD)
    assert "LinkedIn" in digest
    assert "Indeed" in digest
    assert digest != "The job search returned no open postings."


def test_handoff_only_digest_reports_the_failed_source():
    digest = job_renderer.summarize_for_model(HANDOFF_ONLY_PAYLOAD)
    assert "amazon" in digest


@pytest.mark.parametrize("payload", [
    {"ok": False, "error": "boom"},
    {"ok": True, "results": [], "handoffs": []},
    "not a dict",
])
def test_unrenderable_payloads_fall_back_to_model_output(payload):
    """Returning '' is the signal for "let the model answer normally"."""
    assert job_renderer.render_results(payload) == ""
