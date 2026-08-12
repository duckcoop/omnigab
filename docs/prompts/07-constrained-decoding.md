# PR6: The model call with grammar-constrained decoding

Item 2 on the extraction roadmap. The first PR where the model actually
runs against a bill.

---

```
Read AGENTS.md, docs/PLAN.md, and docs/EXTRACTION.md before doing
anything. This is PR6. PR5 (page-indexed PDF) must already be merged.

GOAL
Wire the extraction schema to a real llama.cpp call using
grammar-constrained decoding, so the model's output is always parseable
JSON, and run every result through the verification gate before it
leaves the module.

CONTEXT YOU NEED
- `src/extraction/schema.py` already has `BILL_JSON_SCHEMA` (built for
  grammar-constrained decoding) and `EXTRACTION_INSTRUCTION`. Use them.
  Do not write new ones.
- `src/extraction/gate.py` has `verify(extraction, document)` returning
  a `GateResult`. Every path goes through it.
- `src/generator.py` wraps llama.cpp. `src/core/model_manager.py` owns
  loading and hot swapping. Read both before designing the interface.
- llama-cpp-python supports JSON schema constrained decoding via
  `response_format={"type": "json_object", "schema": ...}` or via
  `LlamaGrammar.from_json_schema`. Check which the installed version
  supports and use that. State which one you used.

TASK
Create `src/extraction/extract.py` exposing something like:

    extract_bill(paged_doc, generator) -> list[GateResult]

Requirements:

1. **Page windows sized against the real loaded context.** Do not
   hardcode a window size. Ask the model manager what `n_ctx` is
   actually loaded (the user can override it in Settings, and it
   auto-sizes against VRAM), subtract the instruction and schema
   overhead, and size windows from what is left. A window that overflows
   the context silently truncates the document and produces confident
   extractions from text the model never saw.

2. **Grammar-constrained decoding, always.** Not "prefer JSON, parse
   defensively." The grammar guarantees syntactic validity. Parse
   errors after this should be zero, not rare.

3. **Every result goes through `verify()` before returning.** The public
   function returns `GateResult` objects. There must be no code path
   that hands a caller a raw `BillExtraction`. Invariant I1 in
   AGENTS.md.

4. **Populate `page` and `source_file`** on each extraction, using the
   quote-to-page resolution built in PR5.

5. **Return the rejected ones too**, with their verdict. The caller
   decides what to show. The rejection rate is itself a product claim
   and PR8 needs to count it, so the module must not silently drop
   rejections.

NON-GOALS
- Do NOT tune for accuracy. No prompt tweaking to make a sample bill
  work. Measurement is PR8, and tuning before you can measure is
  guessing.
- No UI, no database, no watcher.
- Do not modify `gate.py` or `schema.py`. If you believe one of them
  needs a change, stop and tell me why before changing it.

TESTS
- Unit tests use a fake generator returning canned JSON strings. These
  must run offline with no model file.
- Window sizing: given a fake context of N tokens, windows are sized
  correctly and a document longer than one window produces multiple
  windows with the expected overlap.
- A fake generator returning a fabricated evidence quote produces a
  REJECTED GateResult, proving the gate is actually in the path.
- One `@pytest.mark.model` integration test running the real 1.5B model
  against a generated fixture bill, end to end.
- A loop test asserting 200 consecutive constrained calls against a
  fixture produce zero JSON parse errors. Mark it `model` if it needs a
  real model, and keep the count configurable so CI can run a smaller
  number.

ACCEPTANCE
- Zero JSON parse errors across the 200-call test. Exactly zero. If it
  is not zero, the grammar is not actually being applied, and you should
  investigate that rather than adding a retry.
- Default `pytest` run passes offline with no model file.
- No unverified extraction is reachable from outside the module. Prove
  it: grep for the public surface and show me.
- `docs/EXTRACTION.md` "What is not built yet" updated to strike item 2.

REPORT
Which llama-cpp-python constrained-decoding API you used and why. Your
window sizing arithmetic, including the overhead estimate. The parse
error count from the 200-call test. Anything about the model's behavior
that surprised you, without tuning to fix it.
```
