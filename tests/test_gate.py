"""Adversarial tests for the verification gate.

The gate's whole value is that it says no. So most of these tests are
attacks: plausible-looking extractions that a language model realistically
produces and that must not reach the user.

The cases are a table, one row per verdict, parametrized so that a failure
names the case the same way the old hand-rolled runner did.

Run:
    pytest tests/test_gate.py
"""

from __future__ import annotations

import pytest

from extraction import (
    BillExtraction,
    verify,
    summarize,
    VERIFIED,
    FLAGGED,
    REJECTED,
)

# A realistic bill, including the formatting noise a PDF extractor leaves
# behind: curly quotes, an en dash, and inconsistent spacing.
BILL = """
CITY POWER & LIGHT
Account Number: 4471-9982-01

Service period: February 1 - February 28, 2026

Previous balance                     $0.00
Current charges                     $142.87
Total amount due                    $142.87

Your payment of $142.87 is due by March 15, 2026.
A late fee of $9.50 applies to payments received after the due date.

Questions? Call 1-800-555-0143.
"""

# A PDF that renders an en dash and curly quotes where the model typed
# ASCII. This is the single most common false rejection risk. Written as
# escapes rather than literal characters so the file itself stays ASCII.
CURLY_DOC = (
    "Invoice \u2013 City Power \u0026 Light\n"
    "The customer\u2019s payment of $142.87 is due by March 15, 2026.\n"
)


def make(**kw) -> BillExtraction:
    base = dict(
        provider="City Power & Light",
        amount_due="$142.87",
        due_date="March 15, 2026",
        account_number="4471-9982-01",
        evidence_amount="Your payment of $142.87 is due by March 15, 2026.",
        evidence_date="Your payment of $142.87 is due by March 15, 2026.",
    )
    base.update(kw)
    return BillExtraction(**base)


# (case name, extraction, document, expected verdict). The name is the id
# pytest prints, so a failure reads the same as it did under the old
# runner: FAILED tests/test_gate.py::test_verdict[fabricated quote rejected]
VERDICT_CASES: list[tuple[str, BillExtraction, str, str]] = [

    # --- 1. The honest case ---------------------------------------------
    ("clean extraction is verified", make(), BILL, VERIFIED),

    # --- 2. Invented evidence must be rejected --------------------------
    # The failure that matters most: a fluent, entirely fabricated sentence.
    ("fabricated quote rejected",
     make(evidence_amount="The total amount payable on this invoice is $142.87."),
     BILL, REJECTED),
    ("quote from a different bill rejected",
     make(evidence_date="Payment is due within 30 days of the invoice date."),
     BILL, REJECTED),
    ("empty evidence rejected",
     make(evidence_amount=""),
     BILL, REJECTED),
    ("too-short quote rejected",
     make(evidence_amount="$142.87"),
     BILL, REJECTED),

    # --- 3. Real quote, wrong number: flag, do not reject ---------------
    # The quote is genuine so a human can settle it instantly. Silently
    # dropping it would lose a real obligation.
    ("transposed amount flagged",
     make(amount_due="$1,428.70"),
     BILL, FLAGGED),
    ("wrong year flagged",
     make(due_date="March 15, 2025"),
     BILL, FLAGGED),
    ("late-fee amount misreported as total flagged",
     make(amount_due="$9.50"),
     BILL, FLAGGED),

    # --- 4. Shape checks ------------------------------------------------
    ("prose in the amount field flagged",
     make(amount_due="one hundred forty two dollars"),
     BILL, FLAGGED),
    ("missing amount flagged",
     make(amount_due=""),
     BILL, FLAGGED),

    # --- 5. Formatting differences must NOT cause failure ---------------
    # PDF extraction mangles whitespace and punctuation constantly. If the
    # gate is brittle here it rejects correct extractions and becomes useless.
    ("collapsed whitespace still verifies",
     make(evidence_amount="Your  payment   of $142.87 is due by March 15, 2026."),
     BILL, VERIFIED),
    ("curly apostrophe and en dash fold to ascii",
     BillExtraction(
         provider="City Power & Light",
         amount_due="$142.87",
         due_date="March 15, 2026",
         evidence_amount="The customer's payment of $142.87 is due by "
                         "March 15, 2026.",
         evidence_date="The customer's payment of $142.87 is due by "
                       "March 15, 2026.",
     ),
     CURLY_DOC, VERIFIED),
    ("amount without thousands separator matches",
     BillExtraction(
         provider="X", amount_due="$1234.00", due_date="March 15, 2026",
         evidence_amount="Total amount due $1,234.00 on this statement.",
         evidence_date="Your payment is due by March 15, 2026.",
     ),
     "Total amount due $1,234.00 on this statement.\n"
     "Your payment is due by March 15, 2026.", VERIFIED),

    # --- 6. Case sensitivity should not matter --------------------------
    ("uppercase quote still matches",
     make(evidence_amount="YOUR PAYMENT OF $142.87 IS DUE BY MARCH 15, 2026."),
     BILL, VERIFIED),
]


@pytest.mark.parametrize(
    "extraction, document, expected",
    [case[1:] for case in VERDICT_CASES],
    ids=[case[0] for case in VERDICT_CASES],
)
def test_verdict(extraction: BillExtraction, document: str,
                 expected: str) -> None:
    assert verify(extraction, document).verdict == expected


# Section 3 again, on the same transposed-amount result the table above
# checks the verdict of. A flagged item is the whole reason the gate has
# three verdicts instead of two: it stays visible to the user, but never
# wearing the confirmed badge.
@pytest.mark.parametrize(
    "attribute, expected",
    [("showable", True), ("badged", False)],
    ids=["flagged item is still showable", "flagged item is not badged"],
)
def test_flagged_visibility(attribute: str, expected: bool) -> None:
    result = verify(make(amount_due="$1,428.70"), BILL)
    assert getattr(result, attribute) == expected


# --- 7. Summary counting ------------------------------------------------
@pytest.mark.parametrize(
    "key, expected",
    [("total", 3), ("verified", 1), ("flagged", 1), ("rejected", 1)],
    ids=["summary total", "summary verified",
         "summary flagged", "summary rejected"],
)
def test_summary_counts(key: str, expected: int) -> None:
    results = [
        verify(make(), BILL),
        verify(make(amount_due="$1,428.70"), BILL),
        verify(make(evidence_amount="Totally made up sentence here."), BILL),
    ]
    assert summarize(results)[key] == expected
