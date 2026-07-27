# Extraction core

The first milestone of the life-admin pivot. This is the part that decides whether the product is trustworthy, so it is built and tested before any UI exists.

## The problem it solves

A language model asked to read a bill will produce a due date and an amount. Sometimes those are correct. Sometimes it invents them, fluently and confidently. A tool that occasionally invents a due date is worse than no tool at all, because the user stops checking, and the one time it is wrong is the time it matters.

So the rule is: nothing the model says reaches the user unless code has confirmed it against the source document.

## Why string matching and not similarity

There is already a `src/verifier.py` in this repo that scores claims by embedding similarity against source chunks, with a threshold of 0.35. That is the right tool for grading a chat answer, where the model is expected to paraphrase.

It is the wrong tool here. Similarity answers "does this seem related to the document". The question that actually matters is "does this sentence appear in the document", and that question has an exact answer that cannot be argued with. `$142.87` and `$1,428.70` are highly similar strings and one of them will cost you real money.

So the gate is mechanical: exact string containment after conservative normalization.

## The three checks

Run in order, in `src/extraction/gate.py`:

**1. Does the evidence quote appear in the document?**

The model must return the complete sentence it took each value from. Code searches the document for that sentence. No match means the model invented its own justification, which is the failure mode that destroys trust, so the whole extraction is **REJECTED** and never shown.

**2. Is the extracted value inside its own quote?**

A model can quote a real sentence and still report a number that is not in it. This one gets **FLAGGED**, not rejected. The quote is genuine, so a human can settle it in two seconds, and silently dropping it would lose a real obligation.

**3. Do the values have the right shape?**

An amount that is prose, a date that is not a date. Also **FLAGGED**.

## Three verdicts, not a boolean

| Verdict | Shown to user | Badged as confirmed |
| --- | --- | --- |
| `VERIFIED` | yes | yes |
| `FLAGGED` | yes, marked as needing a look | no |
| `REJECTED` | never | no |

The middle state is the important design decision. A boolean gate forces every uncertain case into either lying to the user or hiding a real obligation from them. `FLAGGED` is what lets the system be honest about partial confidence.

## Normalization is deliberately conservative

PDF text extraction mangles whitespace and turns ASCII punctuation into unicode lookalikes. If the gate is brittle about that, it rejects correct extractions and becomes useless in practice.

So `normalize()` folds:

- runs of whitespace into single spaces
- curly quotes, en and em dashes, non-breaking spaces into ASCII
- case

And it never touches digits, letters, or currency symbols, because that is precisely where a real error would hide. A changed number cannot survive normalization.

Amounts get a digits-only fallback so `$1,234.00` matches a document reading `$1234.00`. The digit sequence must match exactly, so `$1,234.00` still never matches `$1,284.00`.

## Testing

`tests/test_gate.py`, 20 assertions, no model or GPU required.

Most of them are attacks, because the gate's entire value is that it says no:

- fabricated but fluent evidence sentence
- evidence lifted from a different document
- transposed amount (`$142.87` reported as `$1,428.70`)
- wrong year on a real date
- the late fee reported as the total due
- quote too short to prove anything
- empty evidence

Plus the false-rejection cases that would make it unusable if it were too strict: collapsed whitespace, curly punctuation, missing thousands separators, uppercase.

```
venv\Scripts\python.exe tests\test_gate.py
```

## What is not built yet

Per the roadmap, in order:

1. **Page-indexed PDF extraction** so a verified quote can be traced to a page number and highlighted for the user.
2. **The model call itself**, using `BILL_JSON_SCHEMA` for grammar-constrained decoding so the output is always parseable JSON.
3. **The fixture corpus and rubric.** The rubric gets committed before any labeling starts, otherwise the scores measure labeling mood rather than model performance.
4. **The eval harness**, publishing precision and recall per field for the 1.5B, 3B, and 7B models.

The kill criterion is already written down: if verified recall at the 3B model comes in under roughly 70%, the generative approach loses and extraction pivots to regular expressions finding candidate dates and amounts with the model only labeling them. Deciding that threshold before seeing results is the point.

## Files

```
src/extraction/
├── __init__.py      public surface
├── schema.py        BillExtraction, GateResult, JSON schema, model instruction
└── gate.py          verify(), normalize(), the three checks

tests/test_gate.py   20 adversarial assertions
```
