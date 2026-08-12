# PR9: End-to-end smoke test

Answers exactly one question: is the app still whole.

---

```
Read AGENTS.md and docs/PLAN.md before doing anything. This is PR9.
PR6 (constrained decoding) must already be merged.

GOAL
One command that exercises the golden path end to end and tells me
whether the whole application still works. Unit tests catch broken
functions. This catches a broken application: wiring that came apart,
a config path that moved, a tool that no longer registers.

TASK
Build `tests/smoke.py`, runnable as `python -m tests.smoke`.

Steps, each reporting pass or fail and elapsed time independently:

1. Config loads and every path in `src/config.py` resolves.
2. The tool registry builds. `build_default_toolset` returns the
   expected tool names. Assert the exact expected set, so a tool
   silently failing to register is caught. Note that `indeed_apply` is
   deliberately NOT registered; assert its absence too, so nobody
   re-adds it by accident.
3. Model loads through `ModelManager`.
4. A chat turn with no tool call returns non-empty text.
5. A chat turn that should call a tool actually emits a tool call.
6. `rag_search` against a seeded temporary index returns a hit.
7. Persistent memory round-trips a fact through a temporary database.
8. A job search returns results and every URL passes the shape check
   already used in `tests/test_omnigab.py` (absolute, canonical,
   starting with the expected prefix).
9. Extraction against a fixture bill returns a VERIFIED GateResult with
   the correct amount and date.

TWO MODES
- `--mock` (default): fakes for the model and the network. Runs in CI
  in seconds. This is what runs on every push.
- `--real`: loads the actual 1.5B model and hits the live network. Run
  manually before a release.

OUTPUT
A step-by-step table with pass or fail and timing, then a one-line
verdict. Non-zero exit code if any step fails.

Failure output must name the step and the reason in one line. Not a
stack trace dump. When this fails at 11pm the useful output is "step 6
rag_search: index empty, 0 hits for seeded query", not 40 lines of
traceback. Put the traceback behind a `--verbose` flag.

NON-GOALS
- Not a load test, not a benchmark, not a correctness eval. Accuracy is
  PR8's job.
- No new dependency.
- Do not duplicate assertions that already live in the unit tests. This
  checks wiring, not logic.

ACCEPTANCE
- `python -m tests.smoke --mock` completes in under 60 seconds in CI and
  exits non-zero on any failure.
- Prove it fails correctly: temporarily break one wire (unregister a
  tool), show the output, restore it, and paste both outputs in the PR
  description. An always-green smoke test is worse than none, because it
  is believed.
- `--real` is documented in the README as the pre-release check.
- The mock mode runs in CI on every push.

REPORT
The broken-wire output you produced as proof. Total runtime in both
modes. Anything you found broken while wiring this up, which is the
usual outcome of writing the first smoke test.
```
