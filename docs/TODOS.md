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

## `scripts/deploy.py` lints a wider target set that is still red, including three real bugs

- **What:** `LINT_TARGETS = ["src", "scripts", "desktop_app.py"]` at `scripts/deploy.py:28`, which is not the `src tests` that `verify.bat`, `verify.sh`, and AGENTS.md section 7 all use. PR0a took that wider set from 111 findings to 51, because it cleaned `src` but never touched the other two targets. All 51 residuals are in `desktop_app.py` (46) and `scripts/job_watcher.py` (5): 22 E127, 9 E231, 6 E306, 5 E702, 3 F841, 3 F821, 1 F811, 1 E401, 1 E128.
- **Why:** Two reasons, and the second is the real one. First, `deploy.py --auto/--commit/--push` refuses to proceed unless `--force` is passed, so "flake8 is clean now" is only true of the gate in AGENTS.md, not of the gate in the deploy path. Second, the three F821s are live bugs, not lint: `desktop_app.py:1065`, `:1122`, and `:1344` each build a `lambda` that reads the `except ... as <name>` variable, but Python unbinds that name when the except block exits, and the lambda does not run until `self.after(0, ...)` fires it on the Tk event loop. Every one of them raises `NameError` at the exact moment it is supposed to show the user an error message, so the failure path is louder and less informative than the failure it was reporting. `desktop_app.py:1340` already has the correct form (`lambda m=msg:`) four lines above one of them.
- **Context:** Found during PR0a by running flake8 over `deploy.py`'s target list rather than the task's. Not fixed there because `desktop_app.py` and `scripts/` were outside the stated scope, and because the F821 fixes are behavior changes: each one turns a crashing error handler into a working one, which needs a test and does not belong in a diff whose whole claim is that behavior is unchanged.
- **Blocked by:** nothing. The three F821s deserve their own small PR ahead of the cosmetic remainder, since they are the only findings in this repository that are bugs rather than formatting.

## AGENTS.md section 3 still describes the pre-PR0 packaging state

- **What:** Two bullets under "Known structural problems" were made false by PR0 and are still there. "`src/` is not an installable package ... There is no `pyproject.toml` and no `setup.py`" is wrong on both counts. "Requirements are entirely unpinned" is wrong: `pyproject.toml` pins every runtime dependency to a compatible-release range. The repository map at the top of the same section also still lists `requirements.txt  unpinned, all >=`.
- **Why:** AGENTS.md is loaded into every agent's context automatically and its own section 4 says an AGENTS.md that lies is worse than none. An agent reading these bullets would re-derive a packaging problem that is already solved, or avoid touching imports for a reason that no longer holds.
- **Context:** Found during PR0a while checking section 3 for a red-flake8 bullet to remove (there was none, so PR0a changed nothing there). Not fixed in PR0a because it is PR0's documentation debt, not lint, and section 9 says to write an unrelated finding down rather than fold it in. The `sys.path.insert` half of the first bullet is genuinely stale too, since PR0's acceptance criteria required removing those lines.
- **Blocked by:** nothing. A few minutes of editing, best folded into whichever PR next touches AGENTS.md section 3.

## Migrate legacy test harness to pytest
- **What:** Port `tests/test_omnigab.py`'s subsystem checks (db, scraper, resume-builder, python-eval, cve) to pytest.
- **Why:** Two test systems is a standing tax; one runner, one CI step, parametrize everywhere.
- **Pros:** unified tooling. **Cons:** ~a day of porting with no user-visible payoff.
- **Context:** Eng review 8A introduced pytest for the new obligation tests only; the custom harness keeps covering jobs/RAG until ported.
- **Blocked by:** nothing — anytime.
