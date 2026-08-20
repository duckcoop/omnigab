# OmniGab improvement plan

Nine pull requests in three phases. Foundation first, feature second,
proof third. Each PR has a scope, a set of non-goals, and acceptance
criteria that can be checked mechanically.

The ordering is deliberate. Building the extraction feature on top of a
repository with no CI and two bespoke test harnesses means the eval
numbers land with nothing enforcing that they stay true. Harden first,
then the feature arrives with real numbers behind it.

---

## Where the repository actually stands

Honest assessment, because a plan built on flattery is useless.

**What is genuinely strong.** The verification gate is a real idea,
well argued, and covered by 20 adversarial assertions. The design
document commits to a kill criterion before results exist, which most
people never do. Job results are rendered deterministically in Python
so the model cannot invent an apply link. Comments explain why rather
than what. The privacy story is architectural rather than a promise.

**What a skeptical reviewer finds in ten minutes.**

| Gap | Why it matters |
|---|---|
| No CI has ever run | Nothing enforces that any of the above stays true |
| Two bespoke test harnesses, neither pytest | No discovery, no fixtures, no coverage, no parametrize |
| Tests call live NVD and USAJOBS | Flaky by construction, cannot run in CI |
| `os.chdir()` at four sites under `tests/` | Global state leaking between tests |
| `src/` is not a package, `sys.path.insert` everywhere | No `pyproject.toml`, imports work by accident |
| Zero tests on `src/core/agent.py` | 29 KB, the heart of the system, completely uncovered |
| ~5,000 word system prompt as a module constant | Untestable, unversioned, contains two contradictory sections |
| Requirements entirely unpinned | A clone in six months may not build |
| Windows only | A reviewer on a Mac cannot run it |
| Extraction roadmap items 1 to 4 unbuilt | The feature the design doc is about does not run yet |

The system prompt contradiction is worth calling out specifically.
`SYSTEM_PROMPT` in `src/core/agent.py` contains a section headed
"Format, REQUIRED four lines per job" and then, a few lines later,
"Job search results are rendered for you ... do NOT list the jobs
yourself and do NOT write any URLs." Both are in the live prompt. Small
models degrade sharply on contradictory instructions, and this one sits
directly on top of invariant I5.

---

## Phase 1: make the repository testable and enforced

Four PRs. No new user-facing behavior. This phase exists so that
everything after it is protected.

### PR0: package the project

**Scope.** Add `pyproject.toml`. Make `src/` an installable package so
`pip install -e .` works and `sys.path.insert` can be deleted. Pin
every runtime dependency to a compatible release range. Add a `[dev]`
extra with pytest, pytest-cov, and flake8.

**Non-goals.** No renaming modules, no restructuring imports beyond
what packaging requires, no behavior change.

**Acceptance.**
- `pip install -e ".[dev]"` succeeds on a clean Python 3.11 venv.
- `python -c "import omnigab"` (or the chosen package name) succeeds
  from a directory that is not the repo root.
- No file in `tests/` contains `sys.path.insert`.
- `setup.bat` and `omnigab.bat` still work unchanged from a user's
  point of view.

**Risk.** This is the highest-risk PR in the plan because every entry
point imports by top-level name. Do it first, alone, and verify the
desktop app and the FastAPI app both still start.

**Status: done**, commit `2114669` on branch `pr0-package-the-project`.
8 files, +177/-41. Both entry points verified live. It surfaced four
things that were invisible from the outside, two of which became the
inserted PRs below:

1. `flake8 src tests` has never been clean. 63 findings, none introduced
   by PR0. Becomes PR0a.
2. `llama-cpp-python` publishes an sdist only on PyPI, zero wheels, so
   CI cannot install the package without a source build. Becomes PR1a.
3. `tests/test_usajobs.py` line 24 computes the repo root one level too
   high, so `os.chdir` raises before the tool is ever called. That file
   has been broken for some time. PR1 absorbs it.
4. The flat layout installs 22 loose top-level module names into
   site-packages. Nothing collides today. Written up in `docs/TODOS.md`,
   unscheduled.

---

### PR0a: get flake8 to zero

**Scope.** 63 pre-existing findings: roughly 22 E127 continuation
indent, 14 F401 unused imports, 6 E266, 3 F811, 1 W391, 1 F841.
Concentrated in `src/tools/usajobs_search.py`.

Four are not mechanical and need reading rather than deleting: `json`,
`os`, and `time` are each imported twice within eight lines in
`usajobs_search.py`, and `job_agent.py:77` assigns a local `ns` that is
never used, which is often a real bug rather than dead weight.

**Non-goals.** No behavior change. No reformatting of code flake8 is not
complaining about. No `# noqa`, and no loosening `.flake8`. The point is
a clean baseline, not a quiet one.

**Why before PR1 rather than before PR2.** `verify.bat` gates on flake8,
and `verify.bat` is how you check PR1. Landing PR1's large diff on a red
baseline means you cannot tell new lint from old.

**Acceptance.**
- `flake8 src tests` exits 0.
- `python tests/test_gate.py` still reports 20 passed.
- Both entry points still start. Removing an "unused" import that had a
  side effect is exactly how a lint pass breaks an app.

---

### PR1: migrate to pytest

**Scope.** Port `tests/test_gate.py` to parametrized pytest, one case
per row of a table, preserving all 20 assertions and their names. Port
the subsystem checks in `tests/test_omnigab.py` (db, cert filter,
python_eval, cve, scraper, resume builder) to pytest. Mark network
tests `@pytest.mark.integration` and model-dependent tests
`@pytest.mark.model`, and deselect both by default in `addopts`.
Replace every `os.chdir` with a fixture. Delete the custom `Reporter`
class and the argparse flag system.

**Non-goals.** No new test coverage. This PR moves tests, it does not
write them. Keeping the diff boring is the point.

**Acceptance.**
- `pytest` passes with the network disabled and no model file present.
- `pytest -m integration` runs the live NVD and USAJOBS checks.
- Assertion count is greater than or equal to the count before the
  migration. State the before and after numbers in the summary.
- No `os.chdir` anywhere under `tests/`.
- `docs/TODOS.md` loses the "migrate legacy test harness to pytest"
  entry.
- AGENTS.md section 4 is updated to the new commands.

**Status: done**, branch `pr1-migrate-to-pytest`. 45 tests collected: 37
in the default run, 8 behind `-m integration`. Before the port there were
44 pass/fail decisions that could run (20 in `test_gate.py`, at import
rather than as tests, plus 24 in `test_omnigab.py`), and one in
`test_usajobs.py` that could not. `tests/evolution_benchmark.py`
moved to `scripts/` because it is a benchmark, not a test: it has no
assertions, needs a loaded model, and writes its stats into
`data/evolution/`. It also surfaced one thing worth writing down, now in
`docs/TODOS.md`: nineteen `print` sites under `src/` emit non-ASCII and
raise `UnicodeEncodeError` on a cp1252 console, two of them on paths the
integration tests reach, which PR2's `windows-latest` job will hit.

---

### PR1a: make llama.cpp an optional dependency

**Scope.** Move `llama-cpp-python` out of `[project.dependencies]` into
an `inference` extra, and make every module-scope `import llama_cpp`
lazy. When the library is absent, model loading fails with a message
naming the fix rather than a raw ImportError.

**Why this exists.** PR0 found that `llama-cpp-python` publishes an sdist
only on PyPI, zero wheels, every platform. `pip install -e ".[dev]"`
therefore attempts a source build needing CMake and a C++ toolchain,
which no CI runner will finish inside a five minute budget. `setup.bat`
never notices because it installs a prebuilt CUDA wheel from
`abetlen.github.io` first.

The alternative is adding that index URL to the workflow. It works, and
it makes CI depend on one person's GitHub Pages, so an outage there
turns CI red for reasons unrelated to the code.

**The deeper reason.** Invariant I7 says tests pass with no GPU and no
model. A repository where importing `src/extraction/gate.py` requires a
GPU inference library does not really satisfy that, it just happens to
work because your venv has everything. The gate, the schema, and the
tool protocol have no business needing llama.cpp to import. CI is what
exposed a defect that was already there.

**Non-goals.** No change to how inference works, how models load, or how
GPU offload is configured. This changes when `llama_cpp` is imported,
not what it does. Not folded into PR2: if the refactor and the workflow
land together and CI goes green, you cannot tell which one did it.

**Acceptance.**
- Fresh venv, `pip install -e ".[dev]"` with no extra index, no
  `llama-cpp-python` installed, `pytest` passes. Paste the pip output.
- `pip install -e ".[dev,inference]"` still resolves with the CUDA
  index supplied.
- Both entry points still start on a machine where inference is
  installed, with CUDA initializing as before.

**Status: done**, branch `pr1a-optional-inference`. Dependency resolution
went from 6 failing combinations to 0, across 3.10, 3.11, and 3.12 on both
linux and windows wheel tags. Only numpy had the interpreter-range bug;
the other 19 pins resolve on all three. A fresh 3.12 venv installs
`-e ".[dev]"` with no extra index, no compiler, and no
`llama-cpp-python`, and `pytest` reports 45 passed there.

One module-scope import moved (`src/generator.py:30`), which was the only
one in the repository. Five tests were added under a simulated absence of
the library. The three `nvidia-*-cu12` packages moved into the extra with
it: they exist only to feed CUDA DLLs to the llama-cpp wheel, and
`scripts/install_llama_cpp.py` pip installs them itself on the CUDA path,
so the declaration was never what put them on a user's machine.

`setup.bat` needed no change, but `docs/SETUP_GUIDE.md` did: its manual
install path said `pip install -r requirements.txt` installs
llama-cpp-python, which stopped being true, so that path now calls
`scripts/install_llama_cpp.py` explicitly.

---

### PR2: continuous integration

**Scope.** GitHub Actions workflow running on push and pull request.
Matrix over Python 3.10, 3.11, 3.12 on `ubuntu-latest`, plus 3.11 on
`windows-latest`. Steps: install with the dev extra, run flake8, run
pytest with coverage, upload the coverage report as an artifact. Add a
status badge to the README.

**Non-goals.** No coverage threshold gate yet, because the current
number is unknown and a failing gate on day one just gets disabled. Add
the gate in PR3 once the number is real.

**Acceptance.**
- A green run visible on the repository's Actions tab.
- The Linux job passes, which proves the code is not silently
  Windows-only.
- Total wall clock under five minutes.
- Integration tests are not run by default in CI.

**Note.** Expect the Linux job to fail on the first attempt. That is
the point of the PR. Fix real portability bugs; do not paper over them
by restricting the matrix to Windows.

---

### PR3: test the agent loop

**Scope.** The highest-value untested surface in the repository.
`src/core/agent.py`, tested with a fake model that returns scripted
strings, so no GGUF file is needed.

Cover at minimum:

- `_extract_balanced_json` with nested braces, braces inside strings,
  escaped quotes, unterminated JSON, and trailing text after the close.
- `TOOL_CALL_RE` against a well-formed call, a call with surrounding
  prose, two calls in one response, and a truncated tag.
- `MAX_TOOL_HOPS`: a model that calls a tool forever must terminate at
  4 hops and return something coherent.
- `MAX_OBSERVATION_CHARS`: a 20,000 character tool result gets
  truncated to 12,000 without producing invalid JSON in the message.
- Unknown tool name: must degrade gracefully, never raise.
- Tool raising an exception: must be caught and surfaced as a tool
  result, not a crash.
- History trimming at `max_history = 8`.

Then add a coverage floor to the CI job set at the number this PR
actually achieves, minus a small margin.

**Non-goals.** No refactor of `agent.py`. Test what is there. The
prompt extraction happens in PR4.

**Acceptance.**
- `src/core/agent.py` coverage above 70 percent, reported in the PR
  summary with the exact number.
- Every test runs without a model file.
- CI fails if coverage drops below the new floor.

---

### PR4: extract and de-conflict the system prompt

**Scope.** Move `SYSTEM_PROMPT` out of `src/core/agent.py` into
`src/prompts/system.md`, loaded at runtime. Split the job-search
specific guidance into `src/prompts/jobs.md` and compose it only when
job tools are registered. Resolve the four-line-per-job contradiction
by deleting the obsolete formatting section, since `job_renderer.py`
owns that output. Add a test asserting the assembled prompt contains no
instruction to emit URLs.

**Non-goals.** No rewrite of the prompt's substance. Move it, split it,
delete the one contradiction. Rewriting behavior and moving files in the
same diff makes the regression unreviewable.

**Acceptance.**
- `agent.py` shrinks by roughly 250 lines.
- Prompt files are plain markdown, diffable, and readable on GitHub.
- A test asserts the assembled prompt for a job-tool-free registry does
  not contain job-search instructions.
- A manual before-and-after check on five representative queries shows
  no behavior regression. Record the five queries and both outputs in
  the PR description.

**Why this matters beyond tidiness.** Once the prompt is a file, you can
diff it, version it, and eventually A/B it against the eval harness from
PR8. As a constant inside a 29 KB module it can only be changed by
feel.

---

## Phase 2: finish the extraction core

The roadmap from `docs/EXTRACTION.md`, in the order that document
specifies. The gate already exists and is tested. These four PRs are
everything around it.

### PR5: page-indexed PDF extraction

**Scope.** A module that turns a PDF into page-indexed text so a
verified quote can be traced back to a page number. pymupdf is already
a dependency. Output shape: a list of `(page_number, text)` plus a
whole-document string the gate can search. Populate
`BillExtraction.page` and `BillExtraction.source_file`, which already
exist in the schema and are currently never set.

Handle the failure states the design document names explicitly. A
scanned image PDF produces a visible `needs_ocr` state, never a silent
skip. A corrupt file produces an error with details and never stalls
the file behind it.

**Non-goals.** No OCR. No watcher thread. No UI.

**Acceptance.**
- Text PDF: page indices correct, verified quote resolves to the right
  page.
- Image-only PDF: returns `needs_ocr`, does not raise, does not return
  empty text silently.
- Corrupt PDF: returns a structured error.
- Every case has a test, using generated fixtures so no real personal
  document is committed.

---

### PR6: the model call with grammar-constrained decoding

**Scope.** Wire `BILL_JSON_SCHEMA` and `EXTRACTION_INSTRUCTION` from
`src/extraction/schema.py` into an actual llama.cpp call using
grammar-constrained decoding, so output is always parseable JSON. Size
page windows against the model's actual loaded context rather than a
hardcoded number. Run every result through `verify()` before it leaves
the module. The public function returns `GateResult`, never a raw
`BillExtraction`.

**Non-goals.** No accuracy tuning. Getting numbers is PR8's job, and
tuning before you can measure is guessing.

**Acceptance.**
- 200 consecutive calls against a fixture produce zero JSON parse
  errors. Grammar constraint means this should be exactly zero, not
  low.
- Unit tests use a fake generator and need no model file.
- One `@pytest.mark.model` integration test runs the real 1.5B model
  end to end.
- No code path returns an unverified extraction to a caller.

---

### PR7: rubric and fixture corpus

**Scope.** Commit `evals/RUBRIC.md` describing exactly what a correct
extraction is for every field, including the ambiguous cases: total due
versus minimum payment, statement date versus due date, a bill with two
amounts, a lease with a notice deadline rather than a payment.

Then, and only then, build the corpus: at least 30 sanitized documents
with a hand-labeled answer key in `evals/corpus/`.

**The rubric is a separate commit that lands before any labeling
starts.** This is not ceremony. If you label first and write the rubric
after, the rubric encodes what you already decided and the scores
measure your labeling mood instead of the model.

**Non-goals.** No scoring code. That is PR8.

**Acceptance.**
- `git log` shows the rubric commit strictly before the first corpus
  commit.
- 30 or more documents, spanning at least utility bill, credit card
  statement, insurance renewal, medical bill, and lease.
- Every document sanitized. No real account number, name, or address in
  version control. A test greps the corpus for anything resembling a
  live account number and fails if it finds one.
- The answer key is machine-readable JSON keyed by filename.

---

### PR8: the evaluation harness

**Scope.** A command line harness that runs the full extraction
pipeline over the corpus and publishes precision and recall per field
for the 1.5B, 3B, and 7B models. Match predictions to the answer key by
the position of the verified quote, so one wrong field cannot drag down
the scoring of the others. Report the three-way verdict split
(verified, flagged, rejected) alongside the accuracy numbers, because
the rejection rate is itself the product claim.

Write the results into the README as a table. No adjectives about
accuracy anywhere, only numbers with the corpus size next to them.

**The kill criterion, from the design document, is already fixed.** If
verified recall at the 3B model comes in under roughly 70 percent, the
generative approach loses and extraction pivots to regular expressions
finding candidate dates and amounts with the model only labeling them.
Do not renegotiate the threshold after seeing results. If it fails,
report that it failed and say so plainly in the README.

**Acceptance.**
- `python -m evals.run --model 3b` prints per-field precision and
  recall plus the verdict split.
- CI runs the harness against the real 1.5B model on every push, over a
  small held-out subset, so the pipeline cannot rot silently.
- The full corpus run happens on a schedule and publishes its output.
- README carries the real table.
- The kill criterion outcome is stated explicitly either way.

---

## Phase 3: prove the whole thing works

### PR9: end-to-end smoke test

**Scope.** One command that boots the stack and exercises the golden
path: load a model, run a chat turn with no tool call, run a
`rag_search` against a seeded index, run a job search against a
recorded fixture, run an extraction against a fixture bill, and report
pass or fail per step with timings.

Two modes. `--mock` uses fakes throughout and runs in CI in seconds.
`--real` loads the actual 1.5B model and hits the live network, run
manually before a release.

**Non-goals.** Not a load test, not a benchmark. This answers one
question: is the app still whole.

**Acceptance.**
- `python -m tests.smoke --mock` completes in under 60 seconds in CI
  and returns a non-zero exit code on any failure.
- `python -m tests.smoke --real` documented in the README as the
  pre-release check.
- Failure output names the step and the reason, not a stack trace dump.

---

## What each phase lets you say out loud

Useful framing for an interview, and also a reasonable test of whether
a phase was worth doing.

**After Phase 1.** "The verification gate was the interesting part, so I
made it impossible to break by accident. CI runs on Linux and Windows
across three Python versions, the agent loop has a coverage floor, and
the tests run with no GPU, no model, and no network, because that is
what a stranger cloning the repo actually has."

**After Phase 2.** "I published precision and recall per field across
three model sizes on a 30 document corpus, and I wrote the kill
criterion into the design document before I had any results, so I could
not move it afterward. Here is the number, and here is what I would
have done if it had come in under 70 percent."

**After Phase 3.** "One command tells me whether the whole thing still
works. It runs mocked in CI on every push and against the real model
before a release."

The second one is the strongest. Almost nobody in this space publishes
extraction accuracy at all, and committing a kill criterion in advance
is a specific, demonstrable piece of engineering judgment rather than a
claim about being rigorous.

---

## Sequencing summary

| PR | Title | Depends on | Rough size |
|---|---|---|---|
| PR0 | Package the project | none | small, high risk (done) |
| PR0a | Get flake8 to zero | PR0 | small, wide |
| PR1 | Migrate to pytest | PR0a | medium |
| PR1a | Optional inference extra | PR1 | small, deep |
| PR2 | Continuous integration | PR1a | small |
| PR3 | Test the agent loop | PR2 | medium |
| PR4 | Extract the system prompt | PR3 | medium |
| PR5 | Page-indexed PDF | PR1 | medium |
| PR6 | Constrained decoding | PR5 | medium |
| PR7 | Rubric and corpus | PR6 | large, mostly manual |
| PR8 | Eval harness | PR7 | medium |
| PR9 | Smoke test | PR6 | small |

PR5 only needs PR1, so Phase 2 can start as soon as pytest exists if
you would rather interleave than finish Phase 1 first. PR7 is the one
that takes real hours, because labeling 30 documents by hand is not
something an agent should do for you. Doing it yourself is also what
makes the resulting numbers defensible.
