# AGENTS.md

Standing context for any AI coding agent working in this repository.
Read this fully before your first edit in a session. Claude Code loads
this file into context automatically at the start of every session.

If anything in this file contradicts a task prompt, this file wins,
and you should say so instead of silently picking one.

---

## 1. What OmniGab is

A private life-admin assistant that runs entirely on the user's own
computer. A Qwen3.5 GGUF model runs through llama.cpp on the local GPU
or CPU. There is no server, no account, and no API key. The user drops
bills and leases into a folder, the app extracts the obligations inside
them, shows the evidence it used, and reminds them before deadlines hit.

The project began as a local job-search agent and pivoted to household
paperwork. Both surfaces still exist in the codebase. The job-search
tools are shipped and working. The extraction pipeline is half built:
the schema and the verification gate exist and are tested, the model
call and the evaluation harness do not exist yet.

Read `docs/EXTRACTION.md` and `omnigab-design-doc.pdf` before touching
anything under `src/extraction/`.

---

## 2. Hard invariants

These are not preferences. Breaking one of them breaks the product's
reason to exist. If a task seems to require breaking one, stop and ask.

**I1. Nothing the model asserts reaches the user unless code has
confirmed it against a source.**
This is the whole thesis. Every extracted value carries the verbatim
sentence it came from, and `src/extraction/gate.py` string-matches that
sentence against the document. No match means the extraction is
discarded, not softened.

**I2. Verification is exact string matching, never embedding
similarity.**
`src/verifier.py` scores chat answers by cosine similarity and that is
correct for chat. It is wrong for extraction. `$142.87` and `$1,428.70`
score as highly similar and one of them costs real money. Never
introduce a similarity threshold, fuzzy matcher, or Levenshtein
distance into the extraction path.

**I3. The gate has three verdicts, not a boolean.**
`VERIFIED` is shown and badged. `FLAGGED` is shown and explicitly
marked as needing a human look. `REJECTED` is never shown. A boolean
forces every uncertain case into either lying to the user or hiding a
real obligation from them. Do not collapse these to two states.

**I4. Normalization never touches digits, letters, or currency
symbols.**
`normalize()` in `gate.py` folds whitespace, unicode punctuation, and
case, because PDF extractors mangle those without changing meaning. It
must never touch the characters where a real error would hide.

**I5. The model never emits a URL that reaches the user.**
Job results are rendered deterministically in Python by
`src/core/job_renderer.py` from verified tool output. The model writes
commentary only. A fabricated apply link destroys trust in the whole
app. Do not move URL rendering back into the prompt.

**I6. No network call happens unless the user asked for it.**
Web search, job board queries, CVE lookups, and model downloads are
the complete list. Adding telemetry, crash reporting, analytics, or a
remote config fetch is out of scope permanently, not just for now.

**I7. Tests must pass with no GPU, no downloaded model, and no
network.**
Anything that needs a live network or a real model is an integration
test, marked as such, and excluded from the default run. See section 6.

**I8. Never advise the user to avoid adding sensitive documents.**
That advice is false here and defeats the purpose. This applies to the
system prompt, the README, and the UI copy.

---

## 3. Repository map

Real paths. Verify before you assume.

```
omnigab/
├── setup.bat                    one-shot Windows installer
├── omnigab.bat                  launcher
├── desktop_app.py               tkinter desktop shell (84 KB, monolithic)
├── requirements.txt             unpinned, all >=
├── .flake8                      max-line-length 120, E501 ignored
│
├── src/
│   ├── config.py                paths, curated model catalog, knobs
│   ├── core/model_catalog.py    hugging face browse, download, profiling
│   ├── core/
│   │   ├── agent.py             THE tool-calling loop + system prompt
│   │   ├── model_manager.py     GGUF load, hot swap, VRAM autotune
│   │   ├── job_renderer.py      deterministic job list rendering
│   │   └── tool_protocol.py     Tool / ToolCall / ToolResult
│   ├── extraction/
│   │   ├── schema.py            BillExtraction, GateResult, BILL_JSON_SCHEMA
│   │   └── gate.py              verify(), normalize(), the three checks
│   ├── jobs/sources.py          multi-board search
│   ├── tools/                   rag_search, web_search, memory, usajobs,
│   │                            job_boards, cve_lookup, python_eval,
│   │                            resume_drafter, open_in_browser
│   ├── web_app.py               FastAPI backend (37 KB)
│   ├── generator.py             llama.cpp wrapper
│   ├── embeddings.py            sentence-transformers
│   ├── vectorstore.py           FAISS
│   ├── persistent_memory.py     SQLite
│   ├── security.py              input validation, audit log
│   └── verifier.py              similarity scoring for CHAT ONLY
│
├── skills/                      drop-in skills (skill.json + skill.py)
├── docs/                        SETUP_GUIDE, EXTRACTION, TODOS
├── tests/                       pytest, markers in pyproject.toml
│   ├── conftest.py              tmp cwd, tmp db, USAJOBS tool fixtures
│   ├── test_gate.py             20 parametrized gate cases
│   ├── test_omnigab.py          subsystem checks, 7 of them integration
│   └── test_usajobs.py          live USAJOBS run, integration
└── data/                        gitignored user state
```

### Known structural problems

Do not "fix" these opportunistically. They are scheduled work with
their own task prompts, and touching them mid-task creates unreviewable
diffs.

- `src/` is not an installable package. All four files under `tests/`
  do `sys.path.insert(0, ... / "src")` and modules import each other as
  top-level names (`from core.model_manager import ...`,
  `from security import ...`). There is no `pyproject.toml` and no
  `setup.py`.
- There is no `.github/` directory. CI has never run.
- `src/core/agent.py` holds an approximately 5,000 word system prompt
  as a module-level string constant, mixing job-search product logic
  into the core loop. It also contains two contradictory sections about
  job formatting: one specifies a four-line-per-job format, a later one
  says the model must not list jobs at all because Python renders them.
  The later one is correct.
- `src/config.py` does file I/O at import time
  (`GGUF_MODEL_PATH = MODELS_DIR / _load_selected_model()`).
- `CONTEXT_WINDOW = 8192` in config coexists with
  `load_context_override()`. Two sources of truth.
- Requirements are entirely unpinned. A clone six months from now may
  not build.
- Windows only. No CI has ever run on this repository.

---

## 4. Commands

```bash
pytest                       # unit only, no network, no model, no GPU
pytest -m integration        # live network, opt in
pytest -m model              # needs a real GGUF on disk (nothing yet)
pytest --cov=src --cov-report=term-missing
flake8 src tests             # full ruleset, src and tests
flake8 --select=F src tests scripts desktop_app.py   # bugs, whole repo
verify.bat                   # all three above, one exit code
verify.bat --no-pause        # same, for scripts (CI=1 does this too)
```

On Windows, prefix with `venv\Scripts\python.exe -m` if the venv is not
active. `verify.bat` does that for you and is the gate to run before
accepting any change; `verify.sh` is its Linux and macOS twin.

The full ruleset covers `src` and `tests` only, because `desktop_app.py`
and `scripts/` still carry cosmetic findings. The pyflakes subset
(`--select=F`: undefined names, unused imports, redefinitions) is the
half that catches real bugs, the whole repository passes it, and
`verify.bat` gates on it everywhere. Keep it that way.

Selection replaced the old per-subsystem argparse flags:
`--python-eval` is `pytest -k python_eval`, `--all` is the default run
plus `pytest -m integration`.

When you change the way tests are run, update this section in the same
commit. An AGENTS.md that lies is worse than no AGENTS.md.

---

## 5. Code style

- Python 3.10 to 3.12. Type hints on public functions.
  `from __future__ import annotations` at the top of new modules.
- flake8 clean against the committed `.flake8`. Line length 120.
- Comments explain **why**, not what. The existing codebase does this
  well. Match it. When you make a non-obvious choice, leave the reason
  in a comment, including the option you rejected.
- Docstrings on modules and public functions, written for a reader who
  has not seen the design doc.
- No new third-party dependency without saying so explicitly in your
  summary and justifying it. Every dependency is weight a stranger has
  to download before the tool works.
- Prose in this repository (README, docs, commit messages, code
  comments) uses no em dashes and no en dashes. Use commas, colons,
  parentheses, or a second sentence. Hyphens inside compound words like
  `page-indexed` are fine.
- Commit messages: imperative mood, lowercase first word, no trailing
  period, no AI attribution footer. Match the existing log
  (`add extraction schema and mechanical verification gate for bills`).

---

## 6. Testing rules

- Default `pytest` run must pass on a machine with no GPU, no model
  file, and no network. This is not negotiable, because it is what CI
  runs and what a stranger runs.
- Anything touching the live network gets `@pytest.mark.integration`.
  Anything needing a real GGUF file gets `@pytest.mark.model`. Both are
  deselected by default via `addopts` in `pyproject.toml`.
- Never `os.chdir()` in a test. Use `tmp_path` and `monkeypatch.chdir`
  if a test truly needs a working directory.
- Never write to `data/`, `vectorstore/`, or the user's real
  `storage.db` from a test. Use `tmp_path` fixtures.
- Prefer `@pytest.mark.parametrize` over loops of asserts. The gate
  tests in particular are a table of cases and should read like one.
- When you fix a bug, the commit that fixes it contains a test that
  fails without the fix. No exceptions.
- Adversarial tests are the valuable ones here. The gate's entire worth
  is that it says no, so a test suite that only covers the happy path
  measures nothing.

---

## 7. Definition of done

A task is not done until all of these are true:

1. `pytest` passes.
2. `flake8 src tests` is clean.
3. New behavior has a test that would fail without the change.
4. No hard invariant from section 2 was weakened.
5. Documentation that the change made wrong is updated in the same
   commit (README, `docs/`, this file).
6. Your summary states what you did NOT do and why, plus anything you
   are unsure about.

Do not report success while any check fails. Say what failed.

---

## 8. Shipping

Work lands on `main` directly. No branch, no pull request per task.

This replaced a PR-per-task flow. The reason for the change is worth
recording, because the old rule was not wrong in principle: on a solo
repository the pull request was reviewed by the same person who asked for
the work, so it added a step without adding a reader. It also produced a
seven-deep stack of dependent PRs, one of which was closed rather than
merged, after which five more reported "merged" while `main` had moved not
at all. A branch that nobody else is reading is bookkeeping.

**The gate replaces the review.** Nothing is pushed until `verify.bat`
exits 0: flake8 on `src tests`, pyflakes across the whole repository, and
the full test suite. That gate is now the thing standing between a mistake
and `main`, so treat a red run as a hard stop rather than something to
explain in the summary.

**Never commit files you did not create.** If the working tree holds
untracked files that are not yours, stage your own paths explicitly.
Never `git add -A` or `git add .`.

**Then:**

```bash
verify.bat --no-pause
git add <your paths>
git commit
git push
```

**The commit message is the report.** With no PR body, the commit is the
only place the reasoning survives, so it carries what the PR description
used to: what changed and why, the decisions that had a rejected
alternative and what that alternative was, the verification actually run
with real numbers rather than what should happen, and what was
deliberately not done. Write it for someone reading `git log` in six
months who cannot ask a question.

The diff shows what changed. The message exists to say why, because the
diff will still be readable in a year and the reasoning will not.

**Do not rewrite published history.** Once something is pushed it stays.
Fix a mistake with another commit that explains itself.

## 9. How to work

- Plan before editing. State the files you will touch and why, then
  wait for confirmation on anything beyond a single-file change.
- One task, one concern. If you discover an unrelated problem, write it
  down in `docs/TODOS.md` and keep going. Do not fold it in. PR0 is the
  model here: it found four unrelated problems and wrote up all four
  rather than fixing any of them.
- Prefer small, reviewable diffs. A 600 line diff nobody reads is worse
  than three 200 line diffs that get read.
- Read before you write. This codebase has strong reasons behind
  non-obvious choices, and most of them are documented in a comment
  right above the code. If something looks wrong, look for the comment
  first.
- If you are about to delete or rewrite something you do not understand,
  stop and ask instead.

---

## 10. Out of scope, permanently

Not deferred. Do not propose these.

- Any cloud API, hosted inference, or remote model call.
- Telemetry, analytics, crash reporting, remote config.
- Scraping LinkedIn, Handshake, or Indeed. Their terms prohibit
  automated access and they enforce it against user accounts. The
  browser handoff in `src/tools/open_in_browser.py` is the deliberate
  answer, not a shortfall.
- Similarity-based verification anywhere in the extraction path.

## 11. Deferred, tracked in docs/TODOS.md

Real work, wrong time. Each has a written condition that promotes it.
Read `docs/TODOS.md` before proposing any of them: OCR for scanned
PDFs, .ics calendar export, packaged installer, cross-document
reconciliation, reminders while the app is closed, content-level dedup.
