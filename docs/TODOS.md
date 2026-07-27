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

## Migrate legacy test harness to pytest
- **What:** Port `tests/test_omnigab.py`'s subsystem checks (db, scraper, resume-builder, python-eval, cve) to pytest.
- **Why:** Two test systems is a standing tax; one runner, one CI step, parametrize everywhere.
- **Pros:** unified tooling. **Cons:** ~a day of porting with no user-visible payoff.
- **Context:** Eng review 8A introduced pytest for the new obligation tests only; the custom harness keeps covering jobs/RAG until ported.
- **Blocked by:** nothing — anytime.
