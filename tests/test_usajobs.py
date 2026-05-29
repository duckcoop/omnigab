"""Standalone runner for the usajobs_search tool.

Run from the project root:
    venv\\Scripts\\python.exe test_usajobs.py

Or with overrides:
    venv\\Scripts\\python.exe test_usajobs.py --query "Cybersecurity" --max 3 --entry-level

Bypasses the FastAPI server, the desktop UI, and the LLM. Just imports
the tool, calls run(), and prints the raw result. Useful for debugging
the [usajobs] verbose log output without retrying through the chat UI.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))


def main() -> int:
    parser = argparse.ArgumentParser(description="Standalone usajobs_search test")
    parser.add_argument("--query", default="IT Specialist",
                        help='Job keywords (default: "IT Specialist")')
    parser.add_argument("--location", default="",
                        help='Location filter (e.g. "Austin, TX")')
    parser.add_argument("--max", type=int, default=5, dest="max_jobs",
                        help="Max results (default 5)")
    parser.add_argument("--days", type=int, default=30,
                        help="Posted within last N days (default 30)")
    parser.add_argument("--entry-level", action="store_true",
                        help="Restrict to GS-04 through GS-07 + Pathways")
    parser.add_argument("--ai-focus", action="store_true",
                        help="Federal AI / ML focus mode")
    parser.add_argument("--no-embedder", action="store_true",
                        help="Skip loading sentence-transformers (faster, no match%)")
    parser.add_argument("--out", default="", help="Optional path to dump JSON result")
    args = parser.parse_args()

    print("=" * 70)
    print(" USAJOBS standalone test")
    print("=" * 70)
    print(f"  query       : {args.query}")
    print(f"  location    : {args.location or '(anywhere)'}")
    print(f"  max_jobs    : {args.max_jobs}")
    print(f"  days_ago    : {args.days}")
    print(f"  entry_level : {args.entry_level}")
    print(f"  ai_focus    : {args.ai_focus}")
    print(f"  no_embedder : {args.no_embedder}")
    print("=" * 70)

    # cwd has to be src/ for the tool's relative imports to resolve.
    os.chdir(str(SRC))

    # Optional embedder + resume hookup so match_percent / cert_matches
    # actually populate. Skip with --no-embedder to keep the test fast.
    embedder = None
    resume_text_getter = lambda: None
    resume_certs_getter = lambda: []

    if not args.no_embedder:
        print("[test] loading embedder…")
        t0 = time.monotonic()
        from embeddings import EmbeddingEngine
        embedder = EmbeddingEngine()
        print(f"[test] embedder ready in {time.monotonic() - t0:.1f}s")

        # If a resume is on disk under data/docs/active_resume.*, hand it to
        # the tool the same way the live app does.
        from tools.indeed_apply import IndeedApplyTool   # imports just for getter
        ia = IndeedApplyTool(embedder=embedder)
        ia._load_resume()
        if ia._resume_text:
            print(f"[test] resume loaded ({len(ia._resume_text)} chars); "
                  f"certs detected: {ia.resume_certs() or '(none)'}")
            resume_text_getter = ia._load_resume
            resume_certs_getter = ia.resume_certs
        else:
            print("[test] no active_resume found in data/docs/")

    from tools.usajobs_search import UsaJobsSearchTool
    tool = UsaJobsSearchTool(
        embedder=embedder,
        resume_text_getter=resume_text_getter,
        resume_certs_getter=resume_certs_getter,
    )

    print()
    print("[test] calling tool.run()…")
    print()
    t_start = time.monotonic()

    arguments = {
        "query": args.query,
        "location": args.location,
        "max_jobs": args.max_jobs,
        "days_ago": args.days,
        "entry_level": args.entry_level,
        "ai_focus": args.ai_focus,
    }

    try:
        result = tool.run(arguments)
    except Exception as exc:
        print(f"\n[test] TOOL CRASHED: {exc!r}")
        import traceback
        traceback.print_exc()
        return 1

    elapsed = time.monotonic() - t_start

    print()
    print("=" * 70)
    print(f" Result (elapsed: {elapsed:.1f}s)")
    print("=" * 70)
    print(f"  ok              : {result.get('ok')}")
    print(f"  mode            : {result.get('mode')}")
    print(f"  query_sent      : {result.get('query_sent')}")
    print(f"  series_codes    : {result.get('series_codes')}")
    print(f"  scanned_cards   : {result.get('scanned_cards')}")
    print(f"  found           : {result.get('found')}")
    print(f"  dropped_off_series: {result.get('dropped_off_series')}")
    print(f"  total_available : {result.get('total_available')}")
    print(f"  url             : {result.get('url')}")
    print()

    for i, job in enumerate(result.get("results", []), 1):
        print(f"--- Result {i} ---")
        print(f"  title         : {job.get('title')}")
        print(f"  agency        : {job.get('agency')}")
        print(f"  location      : {job.get('location')}")
        print(f"  salary        : {job.get('salary')}")
        print(f"  grade         : {job.get('grade')}")
        print(f"  series_code   : {job.get('series_code')}")
        print(f"  match_percent : {job.get('match_percent')}")
        print(f"  cert_matches  : {job.get('cert_matches')}")
        print(f"  ai_designated : {job.get('ai_designated')}")
        desc = job.get('description', '') or ''
        quals = job.get('qualifications', '') or ''
        print(f"  description   : {len(desc)} chars  "
              f"(preview: {desc[:160].strip()!r}…)")
        print(f"  qualifications: {len(quals)} chars")
        print(f"  url           : {job.get('url')}")
        print()

    if args.out:
        out_path = Path(args.out).resolve()
        out_path.write_text(json.dumps(result, indent=2, default=str),
                            encoding="utf-8")
        print(f"[test] full JSON written to {out_path}")

    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
