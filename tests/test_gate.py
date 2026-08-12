"""Adversarial tests for the verification gate.

The gate's whole value is that it says no. So most of these tests are
attacks: plausible-looking extractions that a language model realistically
produces and that must not reach the user.

Run:
    venv\\Scripts\\python.exe tests\\test_gate.py
"""

from __future__ import annotations

import sys

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

PASSED, FAILED = [], []


def check(name: str, got, want):
    if got == want:
        PASSED.append(name)
        print(f"  PASS  {name}")
    else:
        FAILED.append((name, f"got {got!r}, want {want!r}"))
        print(f"  FAIL  {name}: got {got!r}, want {want!r}")


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


print("\n=== 1. The honest case ===")
check("clean extraction is verified", verify(make(), BILL).verdict, VERIFIED)

print("\n=== 2. Invented evidence must be rejected ===")
# The failure that matters most: a fluent, entirely fabricated sentence.
check(
    "fabricated quote rejected",
    verify(make(
        evidence_amount="The total amount payable on this invoice is $142.87.",
    ), BILL).verdict,
    REJECTED,
)
check(
    "quote from a different bill rejected",
    verify(make(
        evidence_date="Payment is due within 30 days of the invoice date.",
    ), BILL).verdict,
    REJECTED,
)
check(
    "empty evidence rejected",
    verify(make(evidence_amount=""), BILL).verdict,
    REJECTED,
)
check(
    "too-short quote rejected",
    verify(make(evidence_amount="$142.87"), BILL).verdict,
    REJECTED,
)

print("\n=== 3. Real quote, wrong number: flag, do not reject ===")
# The quote is genuine so a human can settle it instantly. Silently
# dropping it would lose a real obligation.
res = verify(make(amount_due="$1,428.70"), BILL)
check("transposed amount flagged", res.verdict, FLAGGED)
check("flagged item is still showable", res.showable, True)
check("flagged item is not badged", res.badged, False)

check(
    "wrong year flagged",
    verify(make(due_date="March 15, 2025"), BILL).verdict,
    FLAGGED,
)
check(
    "late-fee amount misreported as total flagged",
    verify(make(amount_due="$9.50"), BILL).verdict,
    FLAGGED,
)

print("\n=== 4. Shape checks ===")
check(
    "prose in the amount field flagged",
    verify(make(amount_due="one hundred forty two dollars"), BILL).verdict,
    FLAGGED,
)
check(
    "missing amount flagged",
    verify(make(amount_due=""), BILL).verdict,
    FLAGGED,
)

print("\n=== 5. Formatting differences must NOT cause failure ===")
# PDF extraction mangles whitespace and punctuation constantly. If the
# gate is brittle here it rejects correct extractions and becomes useless.
check(
    "collapsed whitespace still verifies",
    verify(make(
        evidence_amount="Your  payment   of $142.87 is due by March 15, 2026.",
    ), BILL).verdict,
    VERIFIED,
)
# A PDF that renders an en dash and curly quotes where the model typed
# ASCII. This is the single most common false rejection risk.
CURLY_DOC = (
    "Invoice \u2013 City Power \u0026 Light\n"
    "The customer\u2019s payment of $142.87 is due by March 15, 2026.\n"
)
check(
    "curly apostrophe and en dash fold to ascii",
    verify(BillExtraction(
        provider="City Power & Light",
        amount_due="$142.87",
        due_date="March 15, 2026",
        evidence_amount="The customer's payment of $142.87 is due by "
                        "March 15, 2026.",
        evidence_date="The customer's payment of $142.87 is due by "
                      "March 15, 2026.",
    ), CURLY_DOC).verdict,
    VERIFIED,
)
check(
    "amount without thousands separator matches",
    verify(BillExtraction(
        provider="X", amount_due="$1234.00", due_date="March 15, 2026",
        evidence_amount="Total amount due $1,234.00 on this statement.",
        evidence_date="Your payment is due by March 15, 2026.",
    ), "Total amount due $1,234.00 on this statement.\n"
       "Your payment is due by March 15, 2026.").verdict,
    VERIFIED,
)

print("\n=== 6. Case sensitivity should not matter ===")
check(
    "uppercase quote still matches",
    verify(make(
        evidence_amount="YOUR PAYMENT OF $142.87 IS DUE BY MARCH 15, 2026.",
    ), BILL).verdict,
    VERIFIED,
)

print("\n=== 7. Summary counting ===")
results = [
    verify(make(), BILL),
    verify(make(amount_due="$1,428.70"), BILL),
    verify(make(evidence_amount="Totally made up sentence here."), BILL),
]
s = summarize(results)
check("summary total", s["total"], 3)
check("summary verified", s["verified"], 1)
check("summary flagged", s["flagged"], 1)
check("summary rejected", s["rejected"], 1)

print("\n" + "=" * 60)
print(f"  passed: {len(PASSED)}")
print(f"  failed: {len(FAILED)}")
if FAILED:
    print("\n  FAILURES:")
    for name, detail in FAILED:
        print(f"    {name}: {detail}")
    sys.exit(1)
print("\n  ALL GREEN")
