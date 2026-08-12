# PR5: Page-indexed PDF extraction

Phase 2 starts here. Item 1 on the roadmap in `docs/EXTRACTION.md`.

---

```
Read AGENTS.md, docs/PLAN.md, and docs/EXTRACTION.md before doing
anything. This is PR5. PR1 (pytest) must already be merged.

GOAL
Turn a PDF into page-indexed text, so a quote that the verification gate
confirms can be traced back to a specific page and eventually
highlighted for the user. This is item 1 of the extraction roadmap in
docs/EXTRACTION.md.

CONTEXT YOU NEED
- `src/extraction/schema.py` already defines `BillExtraction.page` and
  `BillExtraction.source_file`. Both exist and are never set today.
  This PR is what sets them.
- pymupdf is already a dependency. Do not add another PDF library.
- `src/ingest.py` already does some PDF reading for the RAG pipeline.
  Read it first. If there is reusable logic, reuse it. If its approach
  is wrong for this purpose, say why in a comment rather than silently
  writing a second parser.

TASK
Create `src/extraction/pdf.py` exposing something like:

    extract_pages(path) -> PagedDocument

where `PagedDocument` carries:
  - `pages: list[tuple[int, str]]`, 1-indexed page numbers
  - `text: str`, the whole document, which is what the gate searches
  - `status: str`, one of "ok", "needs_ocr", "error"
  - `error: str`, populated only when status is "error"
  - a method to resolve a verified quote back to its page number

FAILURE STATES ARE FIRST-CLASS
The design document is explicit that silence is the enemy: "every
dropped document ends up in exactly one named state the user can see."
So:

- A scanned image-only PDF returns status "needs_ocr". It must NOT
  return empty text with status "ok". Detect this by checking whether
  the extracted text across all pages is below a threshold relative to
  page count, and document the threshold you chose and why.
- A corrupt or encrypted PDF returns status "error" with a specific
  message. It must never raise, and it must never stall processing of
  any other file.
- A password-protected PDF is its own error message, not a generic one.

QUOTE-TO-PAGE RESOLUTION
Use the same `normalize()` from `src/extraction/gate.py` so that a quote
which the gate accepted also resolves to a page. If they normalize
differently you will get quotes that verify but cannot be located, which
is a confusing bug to chase later. Import it, do not reimplement it.

NON-GOALS
- No OCR. `needs_ocr` is a state, not a feature. It is deferred in
  docs/TODOS.md.
- No watcher thread, no drop folder, no UI, no database writes.
- No model call. That is PR6.

TESTS
Generate fixtures programmatically (fpdf2 is already a dependency) so
that no real personal document is ever committed.

- text PDF: correct page count, correct per-page text, a known quote
  resolves to the correct page
- multi-page: a quote on page 3 resolves to 3, not 1
- image-only PDF: status "needs_ocr", no raise
- corrupt bytes: status "error", specific message, no raise
- encrypted PDF: status "error", message names encryption
- a quote spanning a page break: define the behavior, test it, and
  document the decision in a comment
- a quote containing curly quotes and an en dash still resolves,
  matching the gate's normalization

ACCEPTANCE
- Every case above has a test and all pass offline.
- No new dependency.
- `flake8 src tests` clean.
- `docs/EXTRACTION.md` "What is not built yet" section updated to strike
  item 1.

REPORT
The needs_ocr threshold you chose and your reasoning. The page-break
behavior you decided on and why. Anything in src/ingest.py you reused or
deliberately did not.
```
