"""Subsystem checks: no UI, and no LLM outside the marked tests.

Ported from the hand-rolled harness that used to live in this file. That
version ran the same checks through a `Reporter` class and an argparse
flag per subsystem, and exited with the failure count. pytest already does
reporting and selection, so both are gone and what is left is the checks
themselves, one test per check.

The two groups that need the live network, cve_lookup and the USAJOBS
scraper, are marked `integration` and deselected by default:

    pytest                    # everything below except the marked groups
    pytest -m integration     # only the live ones
    pytest -k python_eval     # what --python-eval used to do

Nothing here needs a GGUF model. The resume drafter checks deliberately
exercise the no-model-loaded path, which is why none of them carry the
`model` marker.
"""

from __future__ import annotations

import pytest

from persistent_memory import KNOWN_CATEGORIES
from tools import cve_lookup
from tools.python_eval import PythonEvalTool
from tools.resume_drafter import ResumeDrafterTool
from tools.resume_intel import (
    extract_certs, cert_matches,
    extract_required_certs, extract_clearance,
)

# In the old harness an import failure was caught per subsystem and
# reported as one more failing check. Under pytest a bad import is a
# collection error, which is louder and harder to miss, so the six
# "import X" checks are not reimplemented as tests.


# ---------------------------------------------------------------- db

def test_open_storage_db(memory_db):
    """PersistentMemory constructs and creates its database file.

    The original check called `get_persistent_memory()` and reported the
    filename it opened; the assertion was that neither the connection nor
    the schema script raised. `memory_db` points at tmp_path instead of
    the user's real data/storage.db.
    """
    assert memory_db.db_path.exists()


def test_category_enum_complete():
    expected = {"preference", "fact", "instruction", "context",
                "goal", "certification", "application_history"}
    assert expected <= set(KNOWN_CATEGORIES)


def test_write_read_forget_round_trip(memory_db):
    memory_db.put("fact", "_test_omnigab_marker",
                  "sentinel value", source="test")
    assert memory_db.get("fact", "_test_omnigab_marker") == "sentinel value"
    assert memory_db.forget("fact", "_test_omnigab_marker") == 1


def test_recent_applications_query(memory_db):
    assert isinstance(memory_db.recent_applications(limit=5), list)


def test_snapshot_for_prompt(memory_db):
    assert isinstance(memory_db.snapshot_for_prompt(max_facts=10), str)


# ------------------------------------------- cert + clearance extraction

SAMPLE_RESUME = ("Cooper Preston\n"
                 "CompTIA Security+ (SY0-701), Network+, A+.\n"
                 "AWS Certified Cloud Practitioner.")

JOB_TEXT = (
    "Required: Active Top Secret/SCI clearance with CI poly. "
    "Must hold Security+ or CySA+. AWS Cloud Practitioner desirable. "
    "Familiarity with TS/SCI environments required."
)


def test_extract_certs():
    certs = extract_certs(SAMPLE_RESUME)
    assert {"Security+", "Network+", "A+", "AWS CCP"} <= set(certs)


def test_extract_required_certs():
    req = extract_required_certs(JOB_TEXT)
    assert "Security+" in req and "CySA+" in req


def test_extract_clearance_ts_sci_with_poly():
    assert extract_clearance(JOB_TEXT) in ("Polygraph (CI)", "TS/SCI")


def test_extract_clearance_public_trust():
    clearance = extract_clearance(
        "This is a Public Trust position, no clearance required.")
    assert clearance == "None / Public Trust"


def test_cert_matches_user_certs_against_job():
    overlap = cert_matches(["Security+", "Network+", "A+", "AWS CCP"], JOB_TEXT)
    assert "Security+" in overlap and "AWS CCP" in overlap


# ------------------------------------------------------ python_eval sandbox

def test_python_eval_arithmetic():
    result = PythonEvalTool().run({"code": "print(17 * 23 + 5)"})
    assert result.get("ok") and result.get("stdout", "").strip() == "396"


def test_python_eval_blocks_network():
    # Offline by construction, so this is not an integration test: the
    # sandbox patches socket.getaddrinfo before the user code runs, so the
    # urlopen call fails without a packet ever leaving the machine.
    result = PythonEvalTool().run({
        "code": "import urllib.request; urllib.request.urlopen('http://example.com')"
    })
    assert (not result.get("ok")) and \
        "network access disabled" in result.get("stderr", "")


def test_python_eval_timeout_fires():
    result = PythonEvalTool().run({"code": "import time; time.sleep(60)",
                                   "timeout_s": 2})
    assert result.get("timed_out")


# ------------------------------------------- cve_lookup (NVD + CISA KEV)

@pytest.fixture(scope="module")
def cve_tool(tmp_path_factory):
    """CveLookupTool with its KEV cache redirected out of the repository.

    cve_lookup caches the roughly 1 MB CISA catalog at
    data/kev_catalog.json for 24 hours, and a test must not write into the
    user's data directory. Module scoped, with a manual MonkeyPatch
    context because the `monkeypatch` fixture is function scoped: sharing
    one cache file across the three checks below keeps this to a single
    catalog download, which is what the real tool does too.
    """
    cache = tmp_path_factory.mktemp("kev") / "kev_catalog.json"
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(cve_lookup, "KEV_CACHE", cache)
        yield cve_lookup.CveLookupTool()


@pytest.mark.integration
def test_kev_recent(cve_tool):
    result = cve_tool.run({"action": "kev_recent", "days": 30})
    assert result.get("ok") and isinstance(result.get("entries"), list)


@pytest.mark.integration
def test_kev_search_by_keyword(cve_tool):
    result = cve_tool.run({"action": "kev_search", "keyword": "fortinet"})
    assert result.get("ok") and result.get("match_count", 0) > 0


@pytest.mark.integration
def test_nvd_lookup_honours_the_tool_contract(cve_tool):
    # The tool contract: ALWAYS return a dict with ok=True/False and a
    # human-readable error on failure, never throw. NVD itself is
    # unreliable (5-req/30s rate limit, frequent slow responses, periodic
    # 503s), so a clean error counts as a contract pass.
    result = cve_tool.run({"action": "cve", "cve_id": "CVE-2024-3094"})
    assert (result.get("ok") and result.get("found")) or \
        (result.get("ok") is False and result.get("error"))


# ---------------------------------------------------- USAJOBS scraper

@pytest.fixture(scope="module")
def scraper_result(usajobs_tool):
    """One live USAJOBS query, shared by the four checks below.

    The old harness ran the query once and asserted four things about the
    single result. A live query costs about 30 seconds, so a fixture per
    test would be four times the network traffic for the same coverage.
    max_jobs=3 was the default of the deleted --max flag.
    """
    return usajobs_tool.run({"query": "IT Specialist", "max_jobs": 3})


@pytest.mark.integration
def test_scraper_runs(scraper_result):
    assert scraper_result.get("ok")


@pytest.mark.integration
def test_scraper_urls_are_absolute_and_canonical(scraper_result):
    bad = [job.get("url", "") for job in scraper_result.get("results", [])
           if not job.get("url", "").startswith("https://www.usajobs.gov/job/")]
    assert not bad


@pytest.mark.integration
def test_scraper_keeps_only_open_listings(scraper_result):
    closed = [job for job in scraper_result.get("results", [])
              if job.get("status") == "closed"]
    assert not closed


@pytest.mark.integration
def test_scraper_surfaces_job_side_cert_and_clearance(scraper_result):
    saw_required = any("required_certs" in job or "clearance_required" in job
                       for job in scraper_result.get("results", []))
    # A query that returned nothing has no listing to inspect, which the
    # original check treated as a pass rather than a failure.
    assert saw_required or scraper_result.get("found", 0) == 0


# ------------------------------------------ resume drafter (no model call)

@pytest.fixture
def no_resume_ingest(monkeypatch):
    """Stop the drafter's best-effort resume ingest from writing to the repo.

    `ResumeDrafterTool.run()` starts by calling `ingest_resume()`, which
    rewrites baseresume.txt in the project root whenever a newer
    baseresume.pdf or .docx is sitting next to it. Correct for the app,
    out of bounds for a test. The import inside `run()` is a function-level
    `from resume_ingest import ingest_resume`, so replacing the attribute
    on the module is enough to intercept it.
    """
    import resume_ingest
    monkeypatch.setattr(resume_ingest, "ingest_resume", lambda *a, **kw: None)


@pytest.fixture
def drafter():
    return ResumeDrafterTool(
        generator_getter=lambda: None,
        persistent_memory=None,
        resume_text_getter=lambda: None,
    )


def test_drafter_accepts_none_dependencies(drafter):
    # The check is that the constructor tolerates None for every injected
    # dependency rather than raising. There is nothing else to look at on
    # a fresh instance.
    assert drafter is not None


def test_drafter_rejects_missing_inputs(drafter, no_resume_ingest):
    result = drafter.run({})
    assert (not result.get("ok")) and \
        "provide either job_url or job_description" in result.get("error", "")


def test_drafter_validation_chain_reaches_resume_or_model(drafter,
                                                          no_resume_ingest):
    # The drafter falls back to scanning data/docs/ for active_resume.* so
    # when the user already has a resume on disk we hit the "no model
    # loaded" path instead. Accept either error as proof that the
    # validation chain reached the resume/model-load stage cleanly.
    result = drafter.run(
        {"job_description": "Sample federal IT specialist posting."})
    error = (result.get("error") or "").lower()
    assert (not result.get("ok")) and \
        ("no active resume" in error or "no model loaded" in error)


def test_drafter_fails_gracefully_with_no_model(no_resume_ingest):
    tool = ResumeDrafterTool(
        generator_getter=lambda: None,
        persistent_memory=None,
        resume_text_getter=lambda: "Cooper Preston. Security+. Active student.",
    )
    result = tool.run({"job_description": "Federal IT specialist (AI). GS-12."})
    assert (not result.get("ok")) and \
        "no model loaded" in result.get("error", "")
