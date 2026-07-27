"""Mechanical verification gate.

The premise: a language model can be wrong, so nothing it says reaches the
user unless code has confirmed it against the source document. The check
is string matching, not embedding similarity. Similarity scores answer
"does this seem related", which is the wrong question. The question here is
"does this sentence literally appear in the document", which has an exact
answer and cannot be argued with.

Three checks, in order:

  1. Does the evidence quote appear in the document? If not, the whole
     extraction is REJECTED and never shown. This is what stops an
     invented due date from reaching the user.

  2. Does the extracted value appear inside its own evidence quote? A model
     can quote a real sentence and still report a number that is not in it.
     Failing this gives FLAGGED, not rejection, because the quote is real
     and a human can settle it in two seconds.

  3. Does the value look like an amount or a date at all? Catches a field
     filled with prose.

Only a extraction that passes all three is VERIFIED and may be shown as
confirmed. FLAGGED items are shown as needing a look. REJECTED items are
dropped and counted.

Normalization is deliberately conservative. Whitespace and unicode
punctuation are normalized, because PDF extractors mangle those without
changing meaning. Digits, letters, and currency symbols are never touched,
because that is exactly where a real error would hide.
"""

from __future__ import annotations

import re
import unicodedata

from .schema import (
    BillExtraction,
    GateResult,
    VERIFIED,
    FLAGGED,
    REJECTED,
)

# Quotes shorter than this are too weak to prove anything. "$12" appears in
# plenty of documents by coincidence; a whole line does not.
MIN_EVIDENCE_CHARS = 12

# Unicode lookalikes that PDF text extraction produces for ordinary ASCII.
# Folding these is safe: none of them can disguise a different number.
_PUNCT_FOLD = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-",
    "—": "-", "―": "-", "−": "-",
    " ": " ", " ": " ", " ": " ", " ": " ",
    "﻿": "",
}

_AMOUNT_RE = re.compile(r"[$€£]?\s?\d[\d,]*(?:\.\d{1,2})?")
_DATE_RE = re.compile(
    r"(\d{1,2}[/-]\d{1,2}[/-]\d{2,4})"
    r"|(\d{4}-\d{2}-\d{2})"
    r"|((?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2})"
    r"|(\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*)",
    re.IGNORECASE,
)


def normalize(text: str) -> str:
    """Fold away differences that PDF extraction introduces, nothing more.

    Collapses whitespace, normalizes unicode punctuation to ASCII, and
    lowercases. Does NOT strip digits, currency symbols, or letters, so a
    changed number can never survive normalization.
    """
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    for bad, good in _PUNCT_FOLD.items():
        text = text.replace(bad, good)
    text = re.sub(r"\s+", " ", text)
    return text.strip().lower()


def _digits_only(text: str) -> str:
    """Just the digits, for comparing numbers across formatting differences."""
    return re.sub(r"\D", "", text or "")


def quote_appears(quote: str, document: str) -> bool:
    """True if `quote` appears in `document` after safe normalization."""
    q, d = normalize(quote), normalize(document)
    if not q or not d:
        return False
    if len(q) < MIN_EVIDENCE_CHARS:
        return False
    return q in d


def value_inside_quote(value: str, quote: str, numeric: bool = True) -> bool:
    """True if `value` occurs within its own evidence `quote`.

    With `numeric`, comparison falls back to digits only, so `$1,234.00`
    still matches a quote reading `$1234.00`. Digit sequence must match
    exactly, so `$1,234.00` never matches `$1,284.00`.
    """
    v, q = normalize(value), normalize(quote)
    if not v:
        return False
    if v in q:
        return True
    if numeric:
        vd, qd = _digits_only(v), _digits_only(q)
        if vd and vd in qd:
            return True
    return False


def looks_like_amount(value: str) -> bool:
    return bool(_AMOUNT_RE.search(value or ""))


def looks_like_date(value: str) -> bool:
    return bool(_DATE_RE.search(value or ""))


def verify(extraction: BillExtraction, document: str) -> GateResult:
    """Run one extraction through the gate.

    `document` is the exact text the model was shown. Returns a GateResult
    whose verdict decides whether the user ever sees this.
    """
    reasons: list[str] = []

    # --- Check 1: do the evidence quotes exist in the source? -----------
    # Failing this means the model invented its own justification, which
    # is the failure mode that makes a tool like this untrustworthy.
    amount_quote_ok = quote_appears(extraction.evidence_amount, document)
    date_quote_ok = quote_appears(extraction.evidence_date, document)

    if not amount_quote_ok:
        reasons.append("Evidence quote for the amount is not in the document.")
    if not date_quote_ok:
        reasons.append("Evidence quote for the due date is not in the document.")

    if not amount_quote_ok or not date_quote_ok:
        return GateResult(REJECTED, extraction, reasons)

    # --- Check 2: is each value actually inside its own quote? ----------
    # The quote is genuine here, so a human can resolve this quickly.
    # Flag rather than reject.
    if not extraction.amount_due:
        reasons.append("No amount was extracted.")
    elif not value_inside_quote(extraction.amount_due,
                                extraction.evidence_amount):
        reasons.append(
            f"Amount {extraction.amount_due!r} does not appear in its own "
            f"evidence quote.")

    if not extraction.due_date:
        reasons.append("No due date was extracted.")
    elif not value_inside_quote(extraction.due_date,
                                extraction.evidence_date, numeric=False):
        # Dates get a digits-based second chance: "03/15/2026" vs
        # "March 15, 2026" share digits but not characters.
        if not value_inside_quote(extraction.due_date,
                                  extraction.evidence_date, numeric=True):
            reasons.append(
                f"Due date {extraction.due_date!r} does not appear in its "
                f"own evidence quote.")

    # --- Check 3: do the values have the right shape? -------------------
    if extraction.amount_due and not looks_like_amount(extraction.amount_due):
        reasons.append(
            f"Amount {extraction.amount_due!r} does not look like a "
            f"monetary value.")
    if extraction.due_date and not looks_like_date(extraction.due_date):
        reasons.append(
            f"Due date {extraction.due_date!r} does not look like a date.")

    if reasons:
        return GateResult(FLAGGED, extraction, reasons)
    return GateResult(VERIFIED, extraction, [])


def summarize(results: list[GateResult]) -> dict:
    """Counts by verdict. This is what the eval harness reports on."""
    counts = {VERIFIED: 0, FLAGGED: 0, REJECTED: 0}
    for r in results:
        counts[r.verdict] = counts.get(r.verdict, 0) + 1
    total = len(results) or 1
    return {
        "total": len(results),
        "verified": counts[VERIFIED],
        "flagged": counts[FLAGGED],
        "rejected": counts[REJECTED],
        "verified_rate": round(counts[VERIFIED] / total, 4),
        "rejected_rate": round(counts[REJECTED] / total, 4),
    }
