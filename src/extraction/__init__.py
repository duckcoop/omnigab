"""Document extraction with mechanical verification.

Public surface:
    BillExtraction    what the model is asked to produce
    GateResult        what the gate decides about it
    verify            the gate itself
    VERIFIED / FLAGGED / REJECTED   verdicts
"""

from .schema import (
    BILL_JSON_SCHEMA,
    EXTRACTION_INSTRUCTION,
    BillExtraction,
    GateResult,
    VERIFIED,
    FLAGGED,
    REJECTED,
)
from .gate import verify, summarize, normalize, quote_appears

__all__ = [
    "BILL_JSON_SCHEMA",
    "EXTRACTION_INSTRUCTION",
    "BillExtraction",
    "GateResult",
    "VERIFIED",
    "FLAGGED",
    "REJECTED",
    "verify",
    "summarize",
    "normalize",
    "quote_appears",
]
