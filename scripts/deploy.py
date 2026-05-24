#!/usr/bin/env python3
"""OmniAgent deployment script: lint, then optionally commit + push.

Usage examples
--------------
  python scripts/deploy.py                # lint only
  python scripts/deploy.py --commit "msg" # lint, commit if clean
  python scripts/deploy.py --commit "msg" --push   # lint, commit, push
  python scripts/deploy.py --auto                  # lint + auto-commit + push
  python scripts/deploy.py --rebrand               # one-shot for the OmniAgent rebrand commit
  python scripts/deploy.py --skip-lint --push      # push without linting (use sparingly)

Lint is scoped to source folders (src/, scripts/, desktop_app.py) and
honours .flake8 at the repo root. Push only happens with --push,
--auto, or --rebrand to keep accidental pushes out of CI loops.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
LINT_TARGETS = ["src", "scripts", "desktop_app.py"]


def _run(cmd: list[str], cwd: Path | None = None, capture: bool = False) -> subprocess.CompletedProcess:
    """Run a command, surface its stdout/stderr live unless capture=True."""
    return subprocess.run(
        cmd,
        cwd=str(cwd or PROJECT_ROOT),
        capture_output=capture,
        text=True,
        check=False,
    )


def _resolve_flake8() -> list[str] | None:
    """Find a runnable flake8. Prefer the venv copy so the script works
    regardless of which Python the user invoked it with.
    """
    venv_python = PROJECT_ROOT / "venv" / "Scripts" / "python.exe"
    if venv_python.exists():
        check = _run([str(venv_python), "-m", "flake8", "--version"], capture=True)
        if check.returncode == 0:
            return [str(venv_python), "-m", "flake8"]

    exe = shutil.which("flake8")
    if exe:
        return [exe]

    check = _run([sys.executable, "-m", "flake8", "--version"], capture=True)
    if check.returncode == 0:
        return [sys.executable, "-m", "flake8"]

    return None


def lint() -> int:
    """Run flake8 over the scoped targets. Returns its exit code (0 = clean)."""
    flake = _resolve_flake8()
    if flake is None:
        print("[omniagent-deploy] flake8 not installed. Install with:")
        print("         venv\\Scripts\\python.exe -m pip install flake8")
        return 1

    print(f"[deploy] Linting {', '.join(LINT_TARGETS)}...")
    result = _run(flake + LINT_TARGETS)
    if result.returncode == 0:
        print("[omniagent-deploy] Lint passed.")
    else:
        print(f"[deploy] Lint failed (exit {result.returncode}).")
    return result.returncode


def working_tree_dirty() -> bool:
    out = _run(["git", "status", "--porcelain"], capture=True)
    return bool(out.stdout.strip())


def stage_all() -> int:
    """Stage everything except files that flake8 already told us to skip
    (models, vectorstore, data, logs, venv).
    """
    return _run(["git", "add", "-A",
                 ":!venv", ":!models", ":!vectorstore", ":!logs",
                 ":!data/playwright_profile", ":!data/indeed_runs"]).returncode


def commit(message: str) -> int:
    return _run(["git", "commit", "-m", message]).returncode


def push() -> int:
    return _run(["git", "push"]).returncode


def current_branch() -> str:
    out = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], capture=True)
    return out.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Lint, commit, and push.")
    parser.add_argument("--skip-lint", action="store_true",
                        help="Skip the flake8 check (not recommended).")
    parser.add_argument("--commit", metavar="MSG",
                        help="Commit staged + untracked changes with MSG.")
    parser.add_argument("--push", action="store_true",
                        help="Push current branch after committing.")
    parser.add_argument("--auto", action="store_true",
                        help="Lint, commit with an auto-generated message, push.")
    parser.add_argument("--rebrand", action="store_true",
                        help="One-shot for the OmniAgent rebrand: lint, commit with the "
                             "rebrand message, and push.")
    parser.add_argument("--force", action="store_true",
                        help="Commit + push even if lint fails.")
    args = parser.parse_args()

    if args.rebrand and not args.commit:
        args.commit = (
            "rebrand: OmniAgent — universal local AI agent\n\n"
            "* Project renamed from Local RAG Agent to OmniAgent.\n"
            "* Hardware autotuner picks model size based on detected RAM/VRAM.\n"
            "* Strict Python 3.12 enforcement in setup.bat for CUDA wheel compat.\n"
            "* Updated UI titles, console banners, batch files, and docs."
        )
        args.push = True

    if args.auto and not args.commit:
        args.commit = f"chore(omniagent): auto-commit on {current_branch()}"
        args.push = True

    # ----- lint -----
    if not args.skip_lint:
        code = lint()
        if code != 0 and not args.force:
            print("[omniagent-deploy] Aborting: fix lint or pass --force.")
            return code

    # ----- commit -----
    if args.commit:
        if not working_tree_dirty():
            print("[omniagent-deploy] Working tree clean. Nothing to commit.")
        else:
            print("[omniagent-deploy] Staging changes...")
            if stage_all() != 0:
                print("[omniagent-deploy] git add failed.")
                return 1
            print(f"[deploy] Committing: {args.commit}")
            rc = commit(args.commit)
            if rc != 0:
                print("[omniagent-deploy] git commit failed (nothing to commit, or hook rejection).")
                # An empty commit isn't a failure for our purposes if push was also requested.
                if not args.push:
                    return rc

    # ----- push -----
    if args.push:
        branch = current_branch()
        print(f"[deploy] Pushing branch {branch} to origin...")
        rc = push()
        if rc != 0:
            print("[omniagent-deploy] git push failed.")
            return rc
        print("[omniagent-deploy] Push complete.")

    print("[omniagent-deploy] Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
