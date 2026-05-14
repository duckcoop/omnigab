# Evolution Log

## Cycle 1 - Generator extraction prompt

- Proposed change: make `generator.py` use a more explicit troubleshooting prompt, ask for 4-8 short bullets, include exact values, and increase generated context from 800 to 1400 characters.
- Baseline evolution score: 0.6623.
- Sandbox evolution score: 0.6675.
- Result: failed survival gate. The score improved by 0.78%, below the required 5%.
- Notes: expected fact coverage improved from 0.3051 to 0.3593, but average faithfulness fell from 0.7961 to 0.7347 and speed fell from 9.8631 to 8.4667 tokens/sec.

## Cycle 2 - Larger markdown-aware chunks

- Proposed change: make `ingest.py` prefer markdown heading boundaries and expand chunks to 900 characters with 128 overlap.
- Baseline evolution score: 0.6623.
- Sandbox evolution score: 0.6458.
- Result: failed survival gate. The score regressed by 2.49%.
- Notes: the index shrank from 39 to 25 chunks and context precision rose slightly, but expected fact coverage fell from 0.3051 to 0.2450 and speed fell from 9.8631 to 8.7974 tokens/sec.

## Cycle 3 - Deterministic context-copy prompt

- Proposed change: make `generator.py` ask for concise bullets copied from the provided context, expand context to 2000 characters, and use deterministic decoding on the initial attempt.
- Baseline evolution score: 0.6623.
- Sandbox evolution score: 0.6930.
- Result: failed survival gate. The score improved by 4.64%, just below the required 5%.
- Notes: average faithfulness improved from 0.7961 to 0.8962, but expected fact coverage edged down from 0.3051 to 0.2970 and speed fell from 9.8631 to 9.1129 tokens/sec.

## Cycle 4 - Heading-prefixed chunks

- Proposed change: make `ingest.py` prefix each chunk with its source document and active markdown heading path before embedding.
- Baseline evolution score: 0.6623.
- Sandbox evolution score: 0.7298.
- Result: survived. The score improved by 10.19%, above the required 5%.
- Notes: average faithfulness improved from 0.7961 to 0.9189, context precision improved from 0.8857 to 0.9333, expected fact coverage improved from 0.3051 to 0.3371, and speed was 9.5938 tokens/sec.
- Promotion: applied to main `ingest.py`.
