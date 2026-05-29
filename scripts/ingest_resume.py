"""CLI wrapper for src/resume_ingest.py.

Usage:
    venv\\Scripts\\python.exe scripts/ingest_resume.py
    venv\\Scripts\\python.exe scripts/ingest_resume.py --force
    venv\\Scripts\\python.exe scripts/ingest_resume.py --quiet

Looks for baseresume.{pdf,docx} in the project root and extracts text
into baseresume.txt. Idempotent — re-runs are no-ops unless --force.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert baseresume.pdf or baseresume.docx → baseresume.txt"
    )
    parser.add_argument("--force", action="store_true",
                        help="re-extract even if baseresume.txt is current")
    parser.add_argument("--quiet", action="store_true",
                        help="suppress progress output")
    args = parser.parse_args()

    from resume_ingest import ingest_resume

    result = ingest_resume(force=args.force, verbose=not args.quiet)
    if result.ok:
        if result.action == "extracted":
            print(f"[ingest] OK — extracted {result.chars_written} chars from "
                  f"{result.source.name} → {result.target.name}")
        elif result.action == "up-to-date":
            print(f"[ingest] OK — {result.target.name} is current "
                  f"({result.chars_written} bytes)")
        else:
            print(f"[ingest] OK — using existing {result.target.name}")
        return 0
    print(f"[ingest] FAILED ({result.action}): {result.error}",
          file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
