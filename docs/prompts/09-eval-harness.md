# PR8: The evaluation harness

The payoff PR. This is the one that produces a number nobody else in
this niche publishes.

The kill criterion is already fixed at 70 percent verified recall on the
3B model. Do not renegotiate it after seeing results.

---

```
Read AGENTS.md, docs/PLAN.md, docs/EXTRACTION.md, and evals/RUBRIC.md
before doing anything. This is PR8. PR7 (rubric and corpus) must
already be merged.

GOAL
Run the full extraction pipeline over the labeled corpus and publish
precision and recall per field for the 1.5B, 3B, and 7B models. No
adjectives about accuracy anywhere. Numbers, with the corpus size next
to them.

TASK
Build `evals/run.py`, runnable as `python -m evals.run`.

1. **Matching.** Match each prediction to the answer key by the position
   of its verified quote, not by field order or by array index. From the
   design document: "predictions are matched to the answer key by the
   position of their verified quote, so one wrong field can't drag down
   the scoring of the others." A document producing two extractions must
   score each against the right expected obligation.

2. **Report per field**: precision, recall, F1 for provider,
   amount_due, due_date, account_number.

3. **Report the verdict split**: verified, flagged, rejected counts and
   rates. This is not secondary. The rejection rate is the product
   claim. A model that rejects everything scores perfect precision and
   is useless, so report both and make the tradeoff visible.

4. **Report verified recall separately** from raw recall. Verified
   recall is: of the obligations that actually exist in the corpus, how
   many did we surface with a VERIFIED badge. That is the number the
   kill criterion is written against.

5. **Report the needs_ocr rate** over the scanned documents in the
   corpus, rather than excluding them. Excluding the hard cases inflates
   every other number.

6. **Model matrix.** `--model {1.5b,3b,7b,all}`. Where a model is not on
   disk, say so and skip it explicitly rather than reporting a partial
   matrix as if it were complete.

7. **Output**: a human-readable table to stdout, and a JSON file under
   `evals/results/` stamped with the model, the corpus commit hash, and
   the date. The commit hash matters: a result without the corpus
   version it ran against is not reproducible.

8. **README table.** Write the real numbers into README.md, with the
   corpus size and date next to them. No sentence anywhere claiming the
   extraction is accurate, reliable, or robust. The table says what it
   says.

9. **CI.** Add a job running the harness against the real 1.5B model
   over a small held-out subset on every push, so the pipeline cannot
   rot silently. Add a scheduled workflow (weekly) running the full
   corpus across all available models and publishing the output as an
   artifact.

THE KILL CRITERION
Already written into the design document, before any results existed:

  If verified recall at the 3B model comes in under roughly 70 percent
  on the corpus, the generative approach loses, and extraction pivots to
  a design where regular expressions find candidate dates and amounts
  and the model only labels them.

Do not adjust the threshold. Do not add a caveat that reframes the
result. Do not tune the prompt and rerun until it passes and report only
the passing run. If it comes in under 70 percent, report that plainly,
state it in the README, and I will decide about the pivot.

Report every run you do, including the ones that came in worse.

NON-GOALS
- No prompt tuning inside this PR. Measure first. Tuning based on the
  eval is legitimate work, and it is a separate PR with its own
  before-and-after numbers.
- Do not change the gate to make numbers look better. That is the one
  change that would invalidate everything.

TESTS
- Scoring logic unit-tested against a hand-built fixture where the
  correct precision and recall are obvious by inspection.
- Quote-position matching tested against a document with two
  obligations, where naive index matching would score them backwards.
- A test that the harness reports a skipped model rather than silently
  omitting it.

ACCEPTANCE
- `python -m evals.run --model 3b` prints the per-field table plus the
  verdict split.
- Results JSON carries the corpus commit hash.
- README has the real table.
- CI runs the 1.5B subset on push. The scheduled full run exists.
- The kill criterion outcome is stated explicitly in the README, pass or
  fail.

REPORT
The numbers. All of them, including any run that came in worse than
another. Whether the kill criterion passed. Your read on where the
failures cluster: which field, which document type, which model size.
That analysis is worth more than the headline number.
```
