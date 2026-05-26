"""omnigab background job watcher.

Headless script that periodically runs `usajobs_search` (no UI, no LLM
generation) and appends high-scoring matches to a local alerts log.

Designed to be wired into Windows Task Scheduler or a `while sleep` loop:

    venv\\Scripts\\python.exe scripts/job_watcher.py
    venv\\Scripts\\python.exe scripts/job_watcher.py --once
    venv\\Scripts\\python.exe scripts/job_watcher.py --threshold 80 --interval-min 60

Side effects:
  * Appends one JSON line per high-scoring hit to data/alerts.log
  * Records the hit in storage.db (application_history table) so we
    never alert twice on the same job_url.
  * Prints verbose `[watcher]` progress to stdout.

Does NOT load the LLM. Does NOT touch desktop UI. Safe to run alongside
the main app — both use the same SQLite file with WAL-mode locking.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

ALERTS_LOG = ROOT / "data" / "alerts.log"
DEFAULT_THRESHOLD = 85
DEFAULT_INTERVAL_MIN = 60


def _log(msg: str) -> None:
    stamp = datetime.now().strftime("%H:%M:%S")
    print(f"[watcher] {stamp} {msg}", flush=True)


def run_once(*, queries: list[str], location: str, max_jobs: int,
              threshold: int, embedder, indeed_helper, pm) -> int:
    """Execute one search pass. Returns the number of NEW high-scoring hits."""
    from tools.usajobs_search import UsaJobsSearchTool

    tool = UsaJobsSearchTool(
        embedder=embedder,
        resume_text_getter=indeed_helper._load_resume,
        resume_certs_getter=indeed_helper.resume_certs,
    )

    new_alerts = 0
    seen_urls = {row["job_url"]
                  for row in pm.recent_applications(limit=200)} if pm else set()

    for q in queries:
        _log(f"querying: {q!r}")
        try:
            result = tool.run({
                "query": q,
                "location": location,
                "max_jobs": max_jobs,
                "days_ago": 30,
                "ai_focus": q.lower() in {"artificial intelligence", "machine learning"},
            })
        except Exception as exc:
            _log(f"  ERROR: {exc!r}")
            continue
        if not result.get("ok"):
            _log(f"  tool returned error: {result.get('error', 'unknown')}")
            continue

        hits = result.get("results", []) or []
        _log(f"  -> {len(hits)} listings  (filtering for >= {threshold}%)")

        for job in hits:
            pct = job.get("match_percent")
            url = job.get("url", "")
            if not url or pct is None:
                continue
            if pct < threshold:
                continue
            if url in seen_urls:
                _log(f"  - SKIP (already alerted): {job.get('title','?')[:55]}")
                continue

            entry = {
                "alert_at": datetime.now().isoformat(timespec="seconds"),
                "priority": "HIGH" if pct >= 90 else "MEDIUM",
                "match_percent": pct,
                "title": job.get("title"),
                "agency": job.get("agency"),
                "location": job.get("location"),
                "salary": job.get("salary"),
                "series_code": job.get("series_code"),
                "required_certs": job.get("required_certs"),
                "clearance_required": job.get("clearance_required"),
                "cert_matches": job.get("cert_matches"),
                "url": url,
                "query": q,
            }
            ALERTS_LOG.parent.mkdir(parents=True, exist_ok=True)
            with ALERTS_LOG.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, default=str) + "\n")

            if pm is not None:
                try:
                    pm.record_application(
                        job_url=url,
                        job_title=job.get("title", "")[:200],
                        agency=job.get("agency", "")[:200],
                        match_percent=pct,
                        status="flagged",
                    )
                except Exception as exc:
                    _log(f"  WARN: could not record to DB: {exc!r}")

            seen_urls.add(url)
            new_alerts += 1
            _log(f"  ALERT [{entry['priority']}]  {pct}%  "
                 f"{job.get('title','?')[:55]}  ({job.get('agency','?')[:30]})")
    return new_alerts


def main() -> int:
    parser = argparse.ArgumentParser(
        description="omnigab background USAJOBS watcher")
    parser.add_argument("--once", action="store_true",
                        help="Run a single pass and exit (cron mode)")
    parser.add_argument("--interval-min", type=int, default=DEFAULT_INTERVAL_MIN,
                        help=f"Minutes between passes when running as a loop "
                             f"(default {DEFAULT_INTERVAL_MIN})")
    parser.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD,
                        help=f"Minimum match_percent to trigger an alert "
                             f"(default {DEFAULT_THRESHOLD})")
    parser.add_argument("--queries", default="",
                        help="Comma-separated queries (default: AI/ML/IT mix)")
    parser.add_argument("--location", default="",
                        help="Optional location filter; omit for nationwide")
    parser.add_argument("--max-jobs", type=int, default=20,
                        help="Max listings per query per pass (default 20)")
    args = parser.parse_args()

    if args.queries:
        queries = [q.strip() for q in args.queries.split(",") if q.strip()]
    else:
        queries = [
            "Artificial Intelligence",
            "Machine Learning",
            "IT Specialist",
            "Cybersecurity",
        ]

    _log(f"omnigab job watcher starting")
    _log(f"  queries:   {queries}")
    _log(f"  location:  {args.location or '(nationwide)'}")
    _log(f"  threshold: {args.threshold}% match")
    _log(f"  alerts:    {ALERTS_LOG}")
    _log(f"  mode:      {'one-shot' if args.once else f'loop every {args.interval_min} min'}")

    import os
    os.chdir(str(SRC))

    _log("loading embedder…")
    t0 = time.monotonic()
    from embeddings import EmbeddingEngine
    embedder = EmbeddingEngine()
    _log(f"  embedder ready in {time.monotonic() - t0:.1f}s")

    from tools.indeed_apply import IndeedApplyTool
    indeed_helper = IndeedApplyTool(embedder=embedder)
    indeed_helper._load_resume()
    if indeed_helper._resume_text:
        _log(f"  resume loaded ({len(indeed_helper._resume_text)} chars); "
             f"certs: {indeed_helper.resume_certs() or '(none)'}")
    else:
        _log("  WARN: no active_resume — match% scoring may be unreliable")

    pm = None
    try:
        from persistent_memory import get_persistent_memory
        pm = get_persistent_memory()
        _log(f"  storage.db ready ({len(pm.all_rows())} fact rows, "
             f"{len(pm.recent_applications(limit=200))} prior applications)")
    except Exception as exc:
        _log(f"  WARN: persistent memory unavailable: {exc!r}")

    pass_num = 0
    try:
        while True:
            pass_num += 1
            _log(f"=== pass #{pass_num} ===")
            t_pass = time.monotonic()
            new = run_once(
                queries=queries,
                location=args.location,
                max_jobs=args.max_jobs,
                threshold=args.threshold,
                embedder=embedder,
                indeed_helper=indeed_helper,
                pm=pm,
            )
            _log(f"=== pass #{pass_num} done: {new} new alerts, "
                 f"{time.monotonic() - t_pass:.1f}s ===")

            if args.once:
                return 0

            _log(f"sleeping {args.interval_min} min…")
            time.sleep(args.interval_min * 60)
    except KeyboardInterrupt:
        _log("interrupted by user. Exiting.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
