# TODOS

Deferred work from the 2026-07-15 engineering review of the life-admin pivot.
Design doc: `~/.gstack/projects/omnigab/xcn-unknown-design-20260714-194820.md`.
Each item was considered and explicitly deferred — not forgotten.

## OCR for scanned/image PDFs
- **What:** Extract text from image-only PDFs and phone photos (tesseract vs a local vision model, e.g. Qwen2.5-VL GGUF).
- **Why:** v1 handles text PDFs only; scanned docs land as `needs_ocr` rows.
- **Context:** The `needs_ocr` document status doubles as a demand counter — decide when it's the top complaint. The choice of engine is Open Question 1 in the design doc.
- **Blocked by:** nothing; v2 scope.

## .ics calendar export
- **What:** Export confirmed obligations as an .ics feed the user's real calendar subscribes to.
- **Why:** Reminders without living in a new app — the ambient-delivery mechanic.
- **Context:** Approach B territory; pairs well with the lifecycle work (done/recurrence) landing in PR2.
- **Blocked by:** PR2 (obligation lifecycle).

## Packaged installer / winget distribution
- **What:** PyInstaller or Inno Setup build + winget manifest; CI release pipeline.
- **Why:** `git clone + setup.bat` filters out non-developers; "usable by everyone" needs a double-click install.
- **Context:** Explicitly deferred in the design's Distribution Plan; do after the 10-minute stranger test passes reliably via setup.bat.
- **Blocked by:** PR1 + PR2 shipped and stable.

## Cross-document reconciliation ("the auditor")
- **What:** Link documents over time and flag mismatches ("bill says $89.99, contract says $74.99 — sources attached").
- **Why:** The most retellable demo in the niche; uniquely enabled by local-forever storage.
- **Context:** v2 headline per the design doc (Approach C). Requires extraction precision to be proven first — the eval numbers gate this.
- **Blocked by:** eval showing high verified precision at the default model.

## Reminders while the app is closed
- **What:** Windows Task Scheduler registration (or service) so due-date toasts fire without the app running.
- **Why:** v1 reminders are only-while-running (design Open Question 5).
- **Blocked by:** PR2 reminder loop existing.

## Content-level dedup for re-downloaded documents
- **What:** Detect that `statement (1).pdf` re-downloaded from a provider portal is the same bill despite different bytes and filename; merge rather than duplicate obligations.
- **Why:** Byte-hash dedup only catches identical files; re-downloads create duplicate Upcoming entries. (Outside-voice finding #10, deferred via D18.)
- **Context:** Needs cross-document obligation matching — same machinery the auditor needs; build them together.
- **Blocked by:** reconciliation design (above).

## `llama-cpp-python` ships no wheels on PyPI, which PR2's CI will hit

- **What:** PyPI carries an sdist only for `llama-cpp-python` 0.3.34, zero wheels, on every platform. A bare `pip install -e .` therefore tries a source build that needs CMake and a C++ toolchain. `setup.bat` never notices because `scripts/install_llama_cpp.py` installs a prebuilt wheel from `abetlen.github.io` first, and the dependency is already satisfied by the time `pip install -r requirements.txt` runs.
- **Why:** PR2 puts `pip install -e ".[dev]"` in a GitHub Actions job on `ubuntu-latest` and `windows-latest`. Neither will resolve the dependency from PyPI without a compile step measured in minutes, against a five minute wall clock budget for the whole workflow.
- **Context:** Found during PR0 while verifying a clean venv install, which succeeds when `--extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu` is passed and fails without it. Options for PR2, none free: add that index to the workflow's pip invocation; or move `llama-cpp-python` to an optional extra so the offline test suite installs without it, which suits a default `pytest` run that already needs no model. The second is cleaner and touches `pyproject.toml` only, but it is a dependency-shape decision, not a packaging mechanics one, so PR0 left it alone.
- **Blocked by:** nothing. Decide it as part of PR2 rather than discovering it in a red CI run.

## `flake8 src tests` is not clean, and never has been

- **What:** 63 findings at the PR0 commit, unchanged by PR0 itself (verified by diffing flake8 output before and after). Mostly `F401` unused imports and `E127` continuation-line indentation, concentrated in `src/tools/usajobs_search.py` (28), `src/tools/resume_intel.py`, `src/rag_agent.py`, `src/demo_ui.py`, and `src/job_agent.py`. Three are in `tests/test_omnigab.py`.
- **Why:** AGENTS.md section 4 and section 7 both present a clean flake8 as the current state, and `verify.bat` gates on it. Both are wrong today, so the gate is unusable as written and the first person to trust it gets a false failure.
- **Context:** Found during PR0 while checking whether the packaging change introduced lint. It did not. Fixing 63 findings across 15 files inside a packaging PR would have made the diff unreviewable, which is why this is written down rather than folded in. `F811` in `usajobs_search.py` (json, os, time each imported twice) and `F841` in `job_agent.py` are worth a real look; the rest is mechanical.
- **Blocked by:** nothing. Best done as its own commit, ideally right before PR2 so CI turns green on its first run rather than its fifth.

## `tests/test_usajobs.py` computes the repo root one level too high

- **What:** Line 24 is `ROOT = Path(__file__).resolve().parent`, which resolves to `tests/`, not the repo root. `SRC = ROOT / "src"` therefore points at `tests/src`, which does not exist, and `os.chdir(str(SRC))` at line 61 raises `FileNotFoundError` before the tool is ever called. The other three test files use `.parent.parent` correctly.
- **Why:** The file cannot have run successfully in some time. Anyone using it to debug USAJOBS verbose output hits an unrelated traceback first.
- **Context:** Found during PR0 while deleting the `sys.path.insert` lines. Not fixed there because PR1 deletes the `os.chdir` call outright, which removes the only remaining use of `SRC` and makes the constant moot. Fixing the line in PR0 would have left dead code for PR1 to delete anyway.
- **Blocked by:** nothing, but it is PR1's to absorb.

## Flat top-level module names now reach site-packages

- **What:** PR0 installs `src/` with `package-dir = {"" = "src"}`, so `config`, `core`, `tools`, `jobs`, `security`, `generator`, `ingest`, `embeddings`, `verifier`, and `vectorstore` become importable top-level names in any environment that installs omnigab. Several are generic enough to collide with an unrelated distribution.
- **Why:** A collision would surface as an import resolving to somebody else's module, which fails confusingly and far from its cause. Today the app owns its venv, so nothing collides; it becomes real the moment omnigab is installed alongside anything else.
- **Context:** The fix is an `omnigab.` namespace, which means rewriting every intra-module import (`from core.model_manager import ...` becomes `from omnigab.core.model_manager import ...`) across roughly 45 files. That was an explicit non-goal for PR0 precisely because mixing a rename that size into the packaging change makes both unreviewable.
- **Blocked by:** nothing technical. Wants to land alone, after PR1 so the test suite can prove nothing broke.

## Migrate legacy test harness to pytest
- **What:** Port `tests/test_omnigab.py`'s subsystem checks (db, scraper, resume-builder, python-eval, cve) to pytest.
- **Why:** Two test systems is a standing tax; one runner, one CI step, parametrize everywhere.
- **Pros:** unified tooling. **Cons:** ~a day of porting with no user-visible payoff.
- **Context:** Eng review 8A introduced pytest for the new obligation tests only; the custom harness keeps covering jobs/RAG until ported.
- **Blocked by:** nothing — anytime.
