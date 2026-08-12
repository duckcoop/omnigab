# PR7: Rubric and fixture corpus

The one that takes real hours, and the one you should mostly do
yourself. Labeling 30 documents by hand is what makes the resulting
numbers defensible.

Note the two-commit rule below. It is the whole point of this PR.

---

```
Read AGENTS.md, docs/PLAN.md, and docs/EXTRACTION.md before doing
anything. This is PR7. PR6 (constrained decoding) must already be
merged.

GOAL
Build the answer key that PR8 will score against, in the order that
keeps the scores meaningful.

THE ORDERING RULE, WHICH IS NOT NEGOTIABLE
The rubric is written and committed BEFORE a single document is
labeled, in a separate commit. From the design document: "The rubric
gets committed to the repository before any labeling starts, since
otherwise the scores end up measuring my labeling mood instead of the
model."

If you label first and write the rubric after, the rubric encodes
whatever you already decided and the evaluation measures nothing. Two
commits, rubric strictly first. `git log` must show this.

TASK, PART 1: the rubric
Write `evals/RUBRIC.md`. For each field in `BILL_JSON_SCHEMA`
(provider, amount_due, due_date, account_number, evidence_amount,
evidence_date), define exactly what counts as correct.

Then resolve the ambiguous cases explicitly, because these are where
labeling drifts:

- Total due versus minimum payment due. Which is `amount_due`?
- Statement date, billing period end, and payment due date all present.
  Which is `due_date`?
- Two amounts with two different dates (current charges due one date,
  past due immediately). One extraction or two?
- A lease with a notice deadline and no dollar amount.
- An autopay statement that says "do not pay, this will be drafted."
  Is there an obligation at all?
- A bill with a late fee. The gate tests already treat reporting the
  late fee as `amount_due` as a flag-worthy error. The rubric must say
  so.
- Credit balance or negative amount due.
- A due date written as "upon receipt" or "net 30".
- A document with no obligation in it at all. What is the correct
  output, and does an empty extraction count as a correct answer or a
  miss?

For each case: state the correct label and one sentence on why. Where
you are unsure, write down the decision anyway and mark it as a
judgment call. An arbitrary rule applied consistently beats no rule.

STOP AFTER PART 1. Commit the rubric. Then continue.

TASK, PART 2: the corpus
Build `evals/corpus/` with 30 or more documents and a machine-readable
answer key.

- Span at least: utility bill, credit card statement, insurance
  renewal, medical bill, lease or rental agreement, internet or phone
  bill, and at least two documents with no obligation at all as
  negative controls.
- Include at least three scanned image PDFs, so PR8 can report the
  `needs_ocr` rate honestly rather than quietly excluding them.
- Every document sanitized. No real account number, name, address,
  phone number, or amount tied to a real person, anywhere in version
  control. This repository is public.
- Answer key as `evals/corpus/answers.json`, keyed by filename,
  containing every field plus the expected page number and the expected
  gate verdict.

I will do the hand-labeling myself. Your job in part 2 is the
scaffolding: the directory structure, the answer key format, the
loader, the sanitization test, and a template I fill in per document.
Do not invent labels for documents you have not been given.

TESTS
- A test that scans every file in `evals/corpus/` for anything matching
  a plausible live account number, SSN, phone number, or email, and
  fails if it finds one. This runs in CI on every push.
- A test that every document in the corpus has an entry in
  `answers.json` and vice versa. A silently unlabeled document is a
  silently excluded test case.
- A loader test round-tripping the answer key.

NON-GOALS
- No scoring code. That is PR8. If you write a precision calculation in
  this PR, you have gone out of scope.
- Do not generate synthetic bills and label them yourself as if they
  were real. Synthetic fixtures are fine for unit tests and useless for
  measuring real accuracy, and mixing them into the corpus would inflate
  the published number. If you generate any, they live in a clearly
  separate `evals/corpus/synthetic/` directory and PR8 reports them
  separately.

ACCEPTANCE
- `git log --oneline` shows the rubric commit strictly before the first
  corpus commit.
- The sanitization test passes and runs in CI.
- The answer key schema is documented in RUBRIC.md.
- Scaffolding is complete enough that I can add a document and its
  labels without touching code.

REPORT
Every ambiguous case where you had to make a judgment call, and the call
you made. Anything in the schema that the rubric revealed as
underspecified, since that is a real finding about the design.
```
