# PR2: Continuous integration

Expect the Linux job to fail on the first attempt. That is the point.

---

```
Read AGENTS.md and docs/PLAN.md before doing anything. This is PR2.
PR1 (pytest migration) must already be merged.

GOAL
No CI has ever run on this repository. Every claim in the README and
the design document is currently unenforced. Fix that.

TASK
1. Add `.github/workflows/ci.yml`, triggered on push and pull_request
   against main.
   - Matrix: Python 3.10, 3.11, 3.12 on ubuntu-latest, plus Python 3.11
     on windows-latest.
   - Steps: checkout, setup-python with pip caching,
     `pip install -e ".[dev]"`, `flake8 src tests`,
     `pytest --cov=src --cov-report=term-missing --cov-report=xml`.
   - Upload the coverage XML as a build artifact.
   - Integration and model tests stay deselected. CI must not depend on
     NVD, USAJOBS, or a downloaded GGUF file being available.

2. The Linux job will probably fail first. This repository has only
   ever run on Windows: `setup.bat`, `omnigab.bat`, backslash paths,
   possibly case-sensitive import problems, possibly a hard dependency
   on `llama-cpp-python` importing at module scope.

   Fix the real portability bugs. Do NOT paper over them by dropping
   Linux from the matrix or by adding blanket skips. If a test truly
   cannot run on Linux, skip that single test with an explicit
   `pytest.mark.skipif(sys.platform != "win32", reason=...)` and a
   reason that names the actual constraint.

   If `llama-cpp-python` cannot install on the CI runner, make the
   import lazy so that importing `src.config` or the extraction modules
   does not require it. The gate and the schema have no business needing
   a GPU library to import.

3. Add the workflow status badge to the top of README.md.

NON-GOALS
- No coverage threshold gate yet. The current number is unknown and a
  gate that fails on day one just gets disabled. PR3 adds the gate.
- No release automation, no publishing, no Dependabot.
- No changes to test logic.

ACCEPTANCE
- A green run on Actions across the whole matrix.
- The Linux jobs pass, which proves the code is not silently
  Windows-only.
- Total wall clock under five minutes.
- Coverage number reported in the job log. Write it down.
- README carries the badge.

REPORT
The coverage percentage, overall and for `src/core/agent.py`
specifically. Every portability bug you found, what caused it, and how
you fixed it. Any test you had to skip on Linux and the exact reason.
```
