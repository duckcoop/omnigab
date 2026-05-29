"""omnigab modular test suite — no UI, no LLM by default.

Runs independent checks on each subsystem with verbose per-step logging.
Designed for "did I just break X?" debugging without launching the
full desktop app.

Usage:
    venv\\Scripts\\python.exe test_omnigab.py --all
    venv\\Scripts\\python.exe test_omnigab.py --db --cert-filter
    venv\\Scripts\\python.exe test_omnigab.py --scraper --max 3
    venv\\Scripts\\python.exe test_omnigab.py --resume-builder
    venv\\Scripts\\python.exe test_omnigab.py --python-eval --cve

Exit code is the count of failing checks (0 = all green).
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))


# ---------------------------------------------------------------- logging

class Reporter:
    def __init__(self):
        self.failures: list[tuple[str, str]] = []
        self.passes: list[str] = []
        self.t_start = time.monotonic()

    def _stamp(self) -> str:
        return datetime.now().strftime("%H:%M:%S")

    def section(self, name: str):
        bar = "=" * 70
        print(f"\n{bar}\n {name}\n{bar}", flush=True)

    def step(self, msg: str):
        print(f"[{self._stamp()}] · {msg}", flush=True)

    def ok(self, label: str, detail: str = ""):
        suffix = f"  ({detail})" if detail else ""
        print(f"[{self._stamp()}] ✓ {label}{suffix}", flush=True)
        self.passes.append(label)

    def fail(self, label: str, detail: str = ""):
        suffix = f"  ({detail})" if detail else ""
        print(f"[{self._stamp()}] ✗ FAIL: {label}{suffix}", flush=True)
        self.failures.append((label, detail))

    def summary(self):
        elapsed = time.monotonic() - self.t_start
        bar = "=" * 70
        print(f"\n{bar}\n Summary\n{bar}")
        print(f"  passed:   {len(self.passes)}")
        print(f"  failed:   {len(self.failures)}")
        print(f"  elapsed:  {elapsed:.1f}s")
        if self.failures:
            print("\n  FAILURES:")
            for label, detail in self.failures:
                print(f"    ✗ {label}  {detail}")
        else:
            print("\n  ALL GREEN")


# ---------------------------------------------------------------- checks

def check_db(rep: Reporter):
    rep.section("DB / PersistentMemory")
    import os
    os.chdir(str(SRC))
    try:
        from persistent_memory import get_persistent_memory, KNOWN_CATEGORIES
    except Exception as exc:
        rep.fail("import persistent_memory", repr(exc))
        return

    rep.step("opening storage.db")
    try:
        pm = get_persistent_memory()
        rep.ok("open storage.db", f"path={pm.db_path.name}")
    except Exception as exc:
        rep.fail("open storage.db", repr(exc))
        return

    rep.step(f"verifying category enum has {len(KNOWN_CATEGORIES)} known categories")
    expected = {"preference", "fact", "instruction", "context",
                "goal", "certification", "application_history"}
    missing = expected - set(KNOWN_CATEGORIES)
    if missing:
        rep.fail("category enum complete", f"missing: {missing}")
    else:
        rep.ok("category enum complete", f"{KNOWN_CATEGORIES}")

    rep.step("write+read+forget round-trip")
    try:
        row_id = pm.put("fact", "_test_omnigab_marker",
                        "sentinel value", source="test")
        val = pm.get("fact", "_test_omnigab_marker")
        if val != "sentinel value":
            rep.fail("round-trip read", f"expected sentinel, got {val!r}")
        else:
            removed = pm.forget("fact", "_test_omnigab_marker")
            if removed != 1:
                rep.fail("round-trip forget", f"removed={removed}")
            else:
                rep.ok("write+read+forget", f"row_id={row_id}")
    except Exception as exc:
        rep.fail("round-trip", repr(exc))

    rep.step("recent_applications query")
    try:
        rows = pm.recent_applications(limit=5)
        rep.ok("recent_applications", f"{len(rows)} rows on file")
    except Exception as exc:
        rep.fail("recent_applications", repr(exc))

    rep.step("snapshot_for_prompt")
    try:
        snap = pm.snapshot_for_prompt(max_facts=10)
        rep.ok("snapshot_for_prompt",
               f"{len(snap)} chars, prefix={snap[:60]!r}" if snap
               else "empty (no facts yet)")
    except Exception as exc:
        rep.fail("snapshot_for_prompt", repr(exc))


def check_cert_filter(rep: Reporter):
    rep.section("Cert + Clearance extraction")
    try:
        from tools.resume_intel import (
            extract_certs, cert_matches,
            extract_required_certs, extract_clearance,
        )
    except Exception as exc:
        rep.fail("import resume_intel", repr(exc))
        return

    sample_resume = ("Cooper Preston\n"
                     "CompTIA Security+ (SY0-701), Network+, A+.\n"
                     "AWS Certified Cloud Practitioner.")
    rep.step("extract_certs from sample resume")
    certs = extract_certs(sample_resume)
    expected = {"Security+", "Network+", "A+", "AWS CCP"}
    missing = expected - set(certs)
    if missing:
        rep.fail("extract_certs", f"missing {missing} (got {certs})")
    else:
        rep.ok("extract_certs", f"{certs}")

    job_text = (
        "Required: Active Top Secret/SCI clearance with CI poly. "
        "Must hold Security+ or CySA+. AWS Cloud Practitioner desirable. "
        "Familiarity with TS/SCI environments required."
    )

    rep.step("extract_required_certs from sample job")
    req = extract_required_certs(job_text)
    if "Security+" in req and "CySA+" in req:
        rep.ok("extract_required_certs", f"{req}")
    else:
        rep.fail("extract_required_certs", f"got {req}")

    rep.step("extract_clearance — TS/SCI w/ poly")
    clr = extract_clearance(job_text)
    if clr in ("Polygraph (CI)", "TS/SCI"):
        rep.ok("extract_clearance", f"{clr}")
    else:
        rep.fail("extract_clearance", f"expected CI poly or TS/SCI, got {clr!r}")

    rep.step("extract_clearance — Public Trust")
    clr2 = extract_clearance("This is a Public Trust position, no clearance required.")
    if clr2 == "None / Public Trust":
        rep.ok("clearance: public trust")
    else:
        rep.fail("clearance: public trust", f"got {clr2!r}")

    rep.step("cert_matches user-cert ↔ job overlap")
    user = ["Security+", "Network+", "A+", "AWS CCP"]
    overlap = cert_matches(user, job_text)
    if "Security+" in overlap and "AWS CCP" in overlap:
        rep.ok("cert_matches", f"{overlap}")
    else:
        rep.fail("cert_matches", f"got {overlap}")


def check_python_eval(rep: Reporter):
    rep.section("python_eval sandbox")
    try:
        from tools.python_eval import PythonEvalTool
    except Exception as exc:
        rep.fail("import python_eval", repr(exc))
        return
    tool = PythonEvalTool()

    rep.step("arithmetic")
    r = tool.run({"code": "print(17 * 23 + 5)"})
    if r.get("ok") and r.get("stdout", "").strip() == "396":
        rep.ok("arithmetic", "stdout=396")
    else:
        rep.fail("arithmetic", f"got {r}")

    rep.step("network is blocked")
    r = tool.run({
        "code": "import urllib.request; urllib.request.urlopen('http://example.com')"
    })
    if (not r.get("ok")) and "network access disabled" in r.get("stderr", ""):
        rep.ok("network blocked")
    else:
        rep.fail("network blocked", f"stderr={r.get('stderr','')[:200]}")

    rep.step("timeout fires")
    r = tool.run({"code": "import time; time.sleep(60)", "timeout_s": 2})
    if r.get("timed_out"):
        rep.ok("timeout fires", "2s budget killed sleep(60)")
    else:
        rep.fail("timeout fires", f"got {r}")


def check_cve(rep: Reporter):
    rep.section("cve_lookup (NIST NVD + CISA KEV)")
    try:
        from tools.cve_lookup import CveLookupTool
    except Exception as exc:
        rep.fail("import cve_lookup", repr(exc))
        return
    tool = CveLookupTool()

    rep.step("CISA KEV catalog cached download + parse")
    r = tool.run({"action": "kev_recent", "days": 30})
    if r.get("ok") and isinstance(r.get("entries"), list):
        rep.ok("kev_recent", f"{r.get('count', 0)} entries in last 30d")
    else:
        rep.fail("kev_recent", f"got {r}")

    rep.step("KEV keyword search (fortinet)")
    r = tool.run({"action": "kev_search", "keyword": "fortinet"})
    if r.get("ok") and r.get("match_count", 0) > 0:
        rep.ok("kev_search", f"{r['match_count']} fortinet hits")
    else:
        rep.fail("kev_search", f"got {r}")

    rep.step("NVD lookup for CVE-2024-3094")
    r = tool.run({"action": "cve", "cve_id": "CVE-2024-3094"})
    # The tool contract: ALWAYS return a dict with ok=True/False and a
    # human-readable error on failure — never throw. NVD itself is
    # unreliable (5-req/30s rate limit, frequent slow responses, periodic
    # 503s), so a clean error counts as a contract pass.
    if r.get("ok") and r.get("found"):
        severity = (r.get("cvss") or {}).get("severity")
        rep.ok("cve lookup", f"severity={severity}")
    elif isinstance(r, dict) and r.get("ok") is False and r.get("error"):
        rep.ok("cve lookup",
               f"clean error returned: {r['error'][:80]!r}")
    else:
        rep.fail("cve lookup", f"got {r}")


def check_scraper(rep: Reporter, max_jobs: int):
    rep.section(f"USAJOBS scraper (max_jobs={max_jobs})")
    try:
        import os
        os.chdir(str(SRC))
        from tools.usajobs_search import UsaJobsSearchTool
    except Exception as exc:
        rep.fail("import usajobs_search", repr(exc))
        return

    tool = UsaJobsSearchTool(
        embedder=None, resume_text_getter=lambda: None,
        resume_certs_getter=lambda: [],
    )

    rep.step("running query 'IT Specialist' (no embedder)")
    t0 = time.monotonic()
    try:
        r = tool.run({"query": "IT Specialist", "max_jobs": max_jobs})
    except Exception as exc:
        rep.fail("scraper run", repr(exc))
        return
    elapsed = time.monotonic() - t0

    if not r.get("ok"):
        rep.fail("scraper ok", f"{r.get('error', '?')}")
        return
    found = r.get("found", 0)
    rep.ok("scraper run", f"{found} listings in {elapsed:.1f}s")

    rep.step("verifying all URLs are absolute USAJOBS posting URLs")
    bad = [j.get("url", "") for j in r.get("results", [])
            if not (j.get("url", "").startswith("https://www.usajobs.gov/job/"))]
    if bad:
        rep.fail("URL shape", f"{len(bad)} malformed URLs: {bad[:3]}")
    else:
        rep.ok("URL shape", f"all {found} URLs absolute + canonical")

    rep.step("verifying every kept listing has status='open'")
    closed = [j for j in r.get("results", []) if j.get("status") == "closed"]
    if closed:
        rep.fail("status filter", f"{len(closed)} closed listings slipped through")
    else:
        rep.ok("status filter", "no closed listings in keepers")

    rep.step("verifying job-side cert/clearance fields surfaced")
    saw_required = any("required_certs" in j or "clearance_required" in j
                        for j in r.get("results", []))
    if saw_required or found == 0:
        rep.ok("job cert/clearance extraction",
               "at least one job carried required_certs or clearance_required"
               if saw_required else "no listings to inspect")
    else:
        rep.fail("job cert/clearance extraction",
                 "none of the returned jobs had required_certs or clearance_required")


def check_resume_builder(rep: Reporter):
    rep.section("Resume drafter (smoke, no model call)")
    try:
        import os
        os.chdir(str(SRC))
        from tools.resume_drafter import ResumeDrafterTool
    except Exception as exc:
        rep.fail("import resume_drafter", repr(exc))
        return

    rep.step("instantiate with no generator (should not crash)")
    try:
        tool = ResumeDrafterTool(
            generator_getter=lambda: None,
            persistent_memory=None,
            resume_text_getter=lambda: None,
        )
        rep.ok("instantiate", "constructor accepted None deps")
    except Exception as exc:
        rep.fail("instantiate", repr(exc))
        return

    rep.step("missing inputs returns clean error")
    r = tool.run({})
    if (not r.get("ok")) and "provide either job_url or job_description" in r.get("error", ""):
        rep.ok("input validation", "rejects empty input")
    else:
        rep.fail("input validation", f"got {r}")

    rep.step("with description but no resume → resume-missing error")
    # The drafter falls back to scanning data/docs/ for active_resume.* —
    # so when the user already has a resume on disk, we hit the "no model
    # loaded" path instead. Accept either error as proof that the validation
    # chain reached the resume/model-load stage cleanly.
    r = tool.run({"job_description": "Sample federal IT specialist posting."})
    err = (r.get("error") or "").lower()
    if (not r.get("ok")) and ("no active resume" in err
                              or "no model loaded" in err):
        rep.ok("validation chain reaches resume/model check",
               f"error={r.get('error')!r}")
    else:
        rep.fail("validation chain", f"got {r}")

    rep.step("with description + resume + no model → graceful 'no model loaded'")
    tool2 = ResumeDrafterTool(
        generator_getter=lambda: None,
        persistent_memory=None,
        resume_text_getter=lambda: "Cooper Preston. Security+. Active student.",
    )
    r = tool2.run({"job_description": "Federal IT specialist (AI). GS-12."})
    if (not r.get("ok")) and "no model loaded" in r.get("error", ""):
        rep.ok("no-model graceful fail")
    else:
        rep.fail("no-model graceful fail", f"got {r}")


# ---------------------------------------------------------------- main

def main() -> int:
    parser = argparse.ArgumentParser(description="omnigab modular test suite")
    parser.add_argument("--all", action="store_true", help="run every check")
    parser.add_argument("--db", action="store_true", help="storage.db + persistent_memory")
    parser.add_argument("--cert-filter", action="store_true", help="cert + clearance extraction")
    parser.add_argument("--python-eval", action="store_true", help="python_eval sandbox")
    parser.add_argument("--cve", action="store_true", help="cve_lookup NVD + KEV")
    parser.add_argument("--scraper", action="store_true", help="USAJOBS live scrape")
    parser.add_argument("--resume-builder", action="store_true",
                        help="resume drafter smoke tests")
    parser.add_argument("--max", type=int, default=3,
                        help="max_jobs for scraper test (default 3)")
    args = parser.parse_args()

    # If no flags, default to --all.
    any_flag = any([args.db, args.cert_filter, args.python_eval, args.cve,
                    args.scraper, args.resume_builder])
    if not any_flag and not args.all:
        args.all = True

    rep = Reporter()

    if args.all or args.db:
        check_db(rep)
    if args.all or args.cert_filter:
        check_cert_filter(rep)
    if args.all or args.python_eval:
        check_python_eval(rep)
    if args.all or args.cve:
        check_cve(rep)
    if args.all or args.scraper:
        check_scraper(rep, args.max)
    if args.all or args.resume_builder:
        check_resume_builder(rep)

    rep.summary()
    return len(rep.failures)


if __name__ == "__main__":
    sys.exit(main())
