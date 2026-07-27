"""Extraction schema for bills and invoices.

This is the contract between the language model and the rest of the app.
The model is asked to fill in exactly these fields and nothing else, which
lets `gate.py` check every one of them mechanically.

The design rule driving the shape of this schema: every extracted value
must be accompanied by the verbatim sentence it came from. Without that
quote there is nothing to check the value against, and an unverifiable
due date is worse than no due date at all, because the user stops
checking.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict, field
from typing import Any


# JSON schema handed to llama.cpp for grammar-constrained decoding. The
# grammar guarantees syntactically valid JSON with these keys; it cannot
# guarantee the values are true. That is the gate's job.
BILL_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "provider": {
            "type": "string",
            "description": "Company or organization billing the user.",
        },
        "amount_due": {
            "type": "string",
            "description": "Amount owed, exactly as written in the document, "
                           "including the currency symbol. Example: $89.99",
        },
        "due_date": {
            "type": "string",
            "description": "Payment due date exactly as written in the "
                           "document. Do not reformat it.",
        },
        "account_number": {
            "type": "string",
            "description": "Account or invoice number, or empty string if "
                           "the document does not state one.",
        },
        "evidence_amount": {
            "type": "string",
            "description": "The complete sentence or line from the document "
                           "that contains the amount due. Copy it exactly, "
                           "character for character.",
        },
        "evidence_date": {
            "type": "string",
            "description": "The complete sentence or line from the document "
                           "that contains the due date. Copy it exactly, "
                           "character for character.",
        },
    },
    "required": ["provider", "amount_due", "due_date",
                 "evidence_amount", "evidence_date"],
}


EXTRACTION_INSTRUCTION = """\
Extract the payment obligation from the document text below.

Rules:
  * Copy `amount_due` and `due_date` exactly as they appear. Do not \
reformat, round, or convert them.
  * `evidence_amount` must be the complete line or sentence from the \
document containing the amount. Copy it character for character.
  * `evidence_date` must be the complete line or sentence containing the \
due date, copied the same way.
  * If the document does not state a field, use an empty string. Never \
guess, infer, or calculate a value that is not written down.

Your evidence quotes are checked against the document automatically. A \
quote that does not appear in the document verbatim causes the whole \
extraction to be discarded, so copying carefully matters more than \
filling every field.
"""


@dataclass
class BillExtraction:
    """One extraction attempt, before verification."""

    provider: str = ""
    amount_due: str = ""
    due_date: str = ""
    account_number: str = ""
    evidence_amount: str = ""
    evidence_date: str = ""

    # Populated by the gate, not by the model.
    page: int | None = None
    source_file: str = ""

    @classmethod
    def from_model_json(cls, payload: dict[str, Any]) -> "BillExtraction":
        """Build from raw model output, ignoring unexpected keys.

        Small models occasionally emit extra fields even under a grammar.
        Dropping them here keeps a stray key from crashing the pipeline.
        """
        known = {f for f in cls.__dataclass_fields__}
        clean = {k: v for k, v in (payload or {}).items() if k in known}
        for key, value in list(clean.items()):
            if key in ("page",):
                continue
            clean[key] = "" if value is None else str(value)
        return cls(**clean)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# Verdicts the gate can return. Deliberately three states rather than a
# boolean: "flagged" is what makes the difference between a tool that
# silently drops real obligations and one that asks the user to look.
VERIFIED = "verified"      # quote found, values inside it. Safe to show.
FLAGGED = "flagged"        # quote found, values not inside it. Ask the user.
REJECTED = "rejected"      # quote not in the document. Never show.


@dataclass
class GateResult:
    """Outcome of running one extraction through the verification gate."""

    verdict: str
    extraction: BillExtraction
    reasons: list[str] = field(default_factory=list)

    @property
    def showable(self) -> bool:
        """True if this may be surfaced to the user in any form."""
        return self.verdict in (VERIFIED, FLAGGED)

    @property
    def badged(self) -> bool:
        """True only if it may be shown as confirmed rather than unchecked."""
        return self.verdict == VERIFIED

    def to_dict(self) -> dict[str, Any]:
        return {
            "verdict": self.verdict,
            "reasons": list(self.reasons),
            "extraction": self.extraction.to_dict(),
        }
