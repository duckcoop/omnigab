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

## Neither catalog model routes to `draft_federal_resume`

- **What:** Run through the real agent loop with the full tool catalog registered, both Qwen3.5 4B and 9B fail the same prompt: "Draft a federal resume for this posting: GS-12 IT Specialist (INFOSEC), Department of the Air Force, duties include RMF and incident response." The 4B calls no tool at all and answers from the model. The 9B calls `usajobs_search` instead. Every other case in the same probe passed on both models (5/6 each), including `usajobs_search` with six parameters and `cve_lookup`'s action enum, so this is not a large-schema problem.
- **Why:** The drafter is one of the app's headline capabilities and the agent cannot reliably reach it. Worse, the 9B's failure is the confusing kind: it silently substitutes a job search for a resume draft, so the user gets a plausible-looking answer to a question they did not ask.
- **Context:** Found while measuring tool-calling for the Qwen3.5 catalog swap, using a probe that stubs execution and inspects the emitted call. The likely cause is `ResumeDrafterTool.description`, which opens "Generate a tailored federal-style resume draft for a specific USAJOBS posting" and goes on to mention USAJOBS twice more plus a `match_percent >= 85` auto-trigger heuristic. Against `usajobs_search`, whose description is about finding USAJOBS postings, the two read as neighbours and the router picks the more prominent one. That is a tool-description problem, not a model one, which is why swapping models did not fix it and why it was left alone rather than folded into a catalog change.
- **Blocked by:** nothing, but it belongs with PR4, which moves the system prompt into files and is the natural place to look at how tools describe themselves. A fix wants the same probe as its test, otherwise it is unfalsifiable.

## Flat top-level module names now reach site-packages

- **What:** PR0 installs `src/` with `package-dir = {"" = "src"}`, so `config`, `core`, `tools`, `jobs`, `security`, `generator`, `ingest`, `embeddings`, `verifier`, and `vectorstore` become importable top-level names in any environment that installs omnigab. Several are generic enough to collide with an unrelated distribution.
- **Why:** A collision would surface as an import resolving to somebody else's module, which fails confusingly and far from its cause. Today the app owns its venv, so nothing collides; it becomes real the moment omnigab is installed alongside anything else.
- **Context:** The fix is an `omnigab.` namespace, which means rewriting every intra-module import (`from core.model_manager import ...` becomes `from omnigab.core.model_manager import ...`) across roughly 45 files. That was an explicit non-goal for PR0 precisely because mixing a rename that size into the packaging change makes both unreviewable.
- **Blocked by:** nothing technical. Wants to land alone, after PR1 so the test suite can prove nothing broke.

## `scripts/deploy.py` lints a wider target set that is still red, including three real bugs

- **What:** `LINT_TARGETS = ["src", "scripts", "desktop_app.py"]` at `scripts/deploy.py:28`, which is not the `src tests` that `verify.bat`, `verify.sh`, and AGENTS.md section 7 all use. PR0a took that wider set from 111 findings to 51, because it cleaned `src` but never touched the other two targets. All 51 residuals are in `desktop_app.py` (46) and `scripts/job_watcher.py` (5): 22 E127, 9 E231, 6 E306, 5 E702, 3 F841, 3 F821, 1 F811, 1 E401, 1 E128.
- **Why:** Two reasons, and the second is the real one. First, `deploy.py --auto/--commit/--push` refuses to proceed unless `--force` is passed, so "flake8 is clean now" is only true of the gate in AGENTS.md, not of the gate in the deploy path. Second, the three F821s are live bugs, not lint: `desktop_app.py:1065`, `:1122`, and `:1344` each build a `lambda` that reads the `except ... as <name>` variable, but Python unbinds that name when the except block exits, and the lambda does not run until `self.after(0, ...)` fires it on the Tk event loop. Every one of them raises `NameError` at the exact moment it is supposed to show the user an error message, so the failure path is louder and less informative than the failure it was reporting. `desktop_app.py:1340` already has the correct form (`lambda m=msg:`) four lines above one of them.
- **Context:** Found during PR0a by running flake8 over `deploy.py`'s target list rather than the task's. Not fixed there because `desktop_app.py` and `scripts/` were outside the stated scope, and because the F821 fixes are behavior changes: each one turns a crashing error handler into a working one, which needs a test and does not belong in a diff whose whole claim is that behavior is unchanged. PR1 added one file to the gap by moving `evolution_benchmark.py` from `tests/` to `scripts/`: it is flake8 clean today and `deploy.py` lints it, but `flake8 src tests` no longer sees it, so whoever reconciles the two target sets should pick that up too.
- **Blocked by:** nothing. The three F821s deserve their own small PR ahead of the cosmetic remainder, since they are the only findings in this repository that are bugs rather than formatting.

## AGENTS.md section 3 still describes the pre-PR0 packaging state

- **What:** Two bullets under "Known structural problems" were made false by PR0 and are still there. "`src/` is not an installable package ... There is no `pyproject.toml` and no `setup.py`" is wrong on both counts. "Requirements are entirely unpinned" is wrong: `pyproject.toml` pins every runtime dependency to a compatible-release range. The repository map at the top of the same section also still lists `requirements.txt  unpinned, all >=`.
- **Why:** AGENTS.md is loaded into every agent's context automatically and its own section 4 says an AGENTS.md that lies is worse than none. An agent reading these bullets would re-derive a packaging problem that is already solved, or avoid touching imports for a reason that no longer holds.
- **Context:** Found during PR0a while checking section 3 for a red-flake8 bullet to remove (there was none, so PR0a changed nothing there). Not fixed in PR0a because it is PR0's documentation debt, not lint, and section 9 says to write an unrelated finding down rather than fold it in. The `sys.path.insert` half of the first bullet is genuinely stale too, since PR0's acceptance criteria required removing those lines.
- **Blocked by:** nothing. A few minutes of editing, best folded into whichever PR next touches AGENTS.md section 3.

## Nineteen `print` sites in `src/` emit non-ASCII, which raises on a cp1252 console

- **What:** Seven modules under `src/` print characters outside ASCII: `verifier.py` and `demo_ui.py` (7 lines each, box drawing and emoji), plus one line each in `core/agent.py`, `core/model_manager.py`, `persistent_memory.py`, `resume_ingest.py`, and `tools/usajobs_search.py` (arrows, an ellipsis, an em dash). On a Windows console whose stdout encoding is cp1252 every one of them raises `UnicodeEncodeError` instead of printing, and the traceback replaces whatever the line was reporting.
- **Why:** PR2 puts a job on `windows-latest`. Two of these sit on paths the test suite reaches: `tools/usajobs_search.py:881` fires on every scraper run that has no resume vector, which is exactly the configuration `pytest -m integration` uses, and `persistent_memory.py:39` fires on the legacy database rename. pytest's own capture is UTF-8 so a captured run survives, but `pytest -s`, `verify.bat`, and any direct invocation do not. This is not hypothetical: the pre-PR1 harness in `tests/test_omnigab.py` died at its first check mark (U+2713) with `UnicodeEncodeError: 'charmap' codec can't encode character ... in position 11` when its output was piped, which is how PR1 found this.
- **Context:** Found during PR1 while stripping the non-ASCII out of the `Reporter` class and the USAJOBS runner, which the task prompt called out for the same reason. The test files are now pure ASCII; `src/` is not. Options: replace the characters with ASCII (smallest diff, loses the box drawing in `demo_ui.py`), or reconfigure stdout at entry-point startup with `sys.stdout.reconfigure(encoding="utf-8", errors="replace")`, which fixes all nineteen at once but only for code that runs under an entry point, not for a test importing a module directly.
- **Blocked by:** nothing. Cheapest to settle before PR2's Windows job rather than inside a red run.
