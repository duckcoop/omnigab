# PR1: Migrate to pytest

Boring on purpose. This PR moves tests, it does not write new ones.

---

```
Read AGENTS.md and docs/PLAN.md before doing anything. This is PR1.
PR0 (packaging) must already be merged.

GOAL
One test runner. Migrate both bespoke harnesses to pytest without
losing a single assertion.

CURRENT STATE
- `tests/test_gate.py` runs 20 assertions through a module-level
  `check(name, got, want)` function that executes at import time and
  calls `sys.exit(1)` at the bottom. Not discoverable, not
  parametrizable.
- `tests/test_omnigab.py` is a custom harness with a `Reporter` class,
  argparse flags (`--db`, `--cert-filter`, `--python-eval`, `--cve`,
  `--scraper`, `--resume-builder`), and an exit code equal to the
  failure count. Three of its check functions call `os.chdir(str(SRC))`,
  which leaks global state.
- `tests/test_usajobs.py` also exists and also calls `os.chdir` (line
  61). Migrate it too.
- `tests/evolution_benchmark.py` also does `sys.path.insert`. Decide
  whether it is a test or a benchmark. If it is a benchmark, move it out
  of `tests/` so pytest does not collect it, and say so. If it is a
  test, migrate it.

TASK
1. Port `tests/test_gate.py` to pytest.
   - The gate tests are a table of cases. Express them as
     `@pytest.mark.parametrize` with the existing test names as ids, so
     a failure prints the same human-readable name it does today.
   - Preserve all 20 assertions exactly. Same inputs, same expected
     verdicts. Do not "improve" a case.
   - Keep the BILL and CURLY_DOC fixtures as module constants or
     pytest fixtures.

2. Port `tests/test_omnigab.py`.
   - One test function or parametrized group per current check.
   - `check_cve` and `check_scraper` hit the live network. Mark them
     `@pytest.mark.integration`.
   - Anything requiring a real GGUF file gets `@pytest.mark.model`.
   - Delete the `Reporter` class and the argparse system entirely.
     pytest already does reporting and selection.
   - Replace every `os.chdir(str(SRC))` with a proper fixture. If a
     module genuinely requires a specific working directory to import,
     use `monkeypatch.chdir(tmp_path)` scoped to that test and say so in
     a comment explaining why the module needs it.
   - Never let a test write to `data/`, `vectorstore/`, or the real
     `storage.db`. The db round-trip test currently writes a
     `_test_omnigab_marker` row into the user's live database. Point it
     at a `tmp_path` database instead.

3. Port `tests/test_usajobs.py` the same way.

4. Add `tests/conftest.py` with shared fixtures.

5. Remove the "migrate legacy test harness to pytest" entry from
   `docs/TODOS.md`.

6. Update AGENTS.md section 4 with the new commands.

NON-GOALS
- Do NOT add new test coverage. Not one new assertion. New coverage is
  PR3.
- Do NOT fix any bug you find. Write it into docs/TODOS.md and keep
  going.
- Do NOT refactor the code under test.

ACCEPTANCE
- `pytest` passes offline, with no model file present, and with no
  network. Verify by actually disabling the network if you can.
- `pytest -m integration` runs the live NVD and USAJOBS checks.
- Assertion count is greater than or equal to before. State both
  numbers.
- `grep -rn "os.chdir" tests/` returns nothing.
- No test writes outside `tmp_path`.
- `flake8 src tests` is clean.

REPORT
Assertion count before and after. Any check you could not port cleanly
and why. Anything you moved into docs/TODOS.md.
```
