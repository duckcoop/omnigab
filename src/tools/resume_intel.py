"""Resume intelligence: pull structured signals (certifications, etc.)
out of free-form resume text.

Used by IndeedApplyTool and UsaJobsSearchTool to:
  1. Bias the search query toward listings that mention the user's certs.
  2. Tag each result with the specific certs it matches, so the user can
     see "this job mentions your Security+ and Network+" at a glance.

The extractor is regex-based on purpose — fast, deterministic, no LLM
round-trip, and the cert vocabulary is small enough to enumerate.
"""

from __future__ import annotations

import re


# Each entry is (canonical_name, [variant_regexes...]).
# Variants are matched case-insensitively against the resume and job text.
# IMPORTANT: `\b` after `+` does NOT work — `+` is not a word char, so `\b`
# only fires at transitions between word and non-word. We use `\+(?!\w)`
# (negative lookahead) instead so "Security+" matches but "Security+plus"
# (theoretical false positive) wouldn't.
CERT_PATTERNS: list[tuple[str, list[str]]] = [
    # CompTIA core
    ("Security+",     [r"\bSecurity\+(?!\w)", r"\bCompTIA\s+Security\+(?!\w)", r"\bSY0-?\d{3}\b"]),
    ("Network+",      [r"\bNetwork\+(?!\w)", r"\bCompTIA\s+Network\+(?!\w)", r"\bN10-?\d{3}\b"]),
    ("A+",            [r"(?<!\w)A\+(?!\w)", r"\bCompTIA\s+A\+(?!\w)", r"\b220-?\d{3,4}\b"]),
    ("Linux+",        [r"\bLinux\+(?!\w)", r"\bCompTIA\s+Linux\+(?!\w)"]),
    ("Server+",       [r"\bServer\+(?!\w)", r"\bCompTIA\s+Server\+(?!\w)"]),
    ("Cloud+",        [r"\bCloud\+(?!\w)", r"\bCompTIA\s+Cloud\+(?!\w)"]),
    ("CySA+",         [r"\bCySA\+(?!\w)", r"\bCompTIA\s+CySA\+(?!\w)"]),
    ("PenTest+",      [r"\bPenTest\+(?!\w)", r"\bCompTIA\s+PenTest\+(?!\w)"]),
    ("CASP+",         [r"\bCASP\+(?!\w)", r"\bCompTIA\s+CASP\+(?!\w)",
                       r"\bAdvanced\s+Security\s+Practitioner\b"]),

    # Cisco
    ("CCNA",          [r"\bCCNA\b"]),
    ("CCNP",          [r"\bCCNP\b"]),
    ("CCIE",          [r"\bCCIE\b"]),

    # (ISC)²
    ("CISSP",         [r"\bCISSP\b"]),
    ("CCSP",          [r"\bCCSP\b"]),
    ("SSCP",          [r"\bSSCP\b"]),

    # Cloud
    ("AWS SAA",       [r"\bAWS[-\s]?(Certified)?[-\s]*Solutions[-\s]Architect[-\s]Associate\b",
                       r"\bSolutions\s+Architect\s+Associate\b", r"\bSAA[-\s]?C0\d\b"]),
    ("AWS CCP",       [r"\bAWS[-\s]?(Certified)?[-\s]*Cloud[-\s]Practitioner\b",
                       r"\bCloud\s+Practitioner\b", r"\bCLF[-\s]?C0\d\b"]),
    ("AWS Dev",       [r"\bAWS[-\s]?(Certified)?[-\s]*Developer\b", r"\bDVA[-\s]?C0\d\b"]),
    ("AZ-900",        [r"\bAZ[-\s]?900\b", r"\bAzure\s+Fundamentals\b"]),
    ("AZ-104",        [r"\bAZ[-\s]?104\b", r"\bAzure\s+Administrator\b"]),
    ("AZ-500",        [r"\bAZ[-\s]?500\b", r"\bAzure\s+Security\s+Engineer\b"]),
    ("GCP ACE",       [r"\bGoogle\s+Cloud[-\s](Associate\s+)?Engineer\b",
                       r"\bGCP\s+ACE\b"]),

    # Microsoft
    ("MCSA",          [r"\bMCSA\b"]),
    ("MCSE",          [r"\bMCSE\b"]),
    ("MS-900",        [r"\bMS[-\s]?900\b", r"\bMicrosoft\s+365\s+Fundamentals\b"]),

    # Offensive
    ("OSCP",          [r"\bOSCP\b", r"\bOffensive\s+Security\s+Certified\s+Professional\b"]),
    ("OSWE",          [r"\bOSWE\b"]),
    ("CEH",           [r"\bCEH\b", r"\bCertified\s+Ethical\s+Hacker\b"]),

    # Management
    ("CISM",          [r"\bCISM\b"]),
    ("CISA",          [r"\bCISA\b"]),
    ("CRISC",         [r"\bCRISC\b"]),
    ("PMP",           [r"\bPMP\b", r"\bProject\s+Management\s+Professional\b"]),
    ("ITIL",          [r"\bITIL\b"]),

    # Cyber-specific / DoD
    ("GSEC",          [r"\bGSEC\b", r"\bGIAC\s+Security\s+Essentials\b"]),
    ("GCIH",          [r"\bGCIH\b", r"\bGIAC\s+Certified\s+Incident\s+Handler\b"]),
    ("GCIA",          [r"\bGCIA\b", r"\bGIAC\s+Certified\s+Intrusion\s+Analyst\b"]),
    ("GPEN",          [r"\bGPEN\b"]),
    ("GREM",          [r"\bGREM\b"]),
    ("DoD 8570",      [r"\bDo[Dd][\s-]?8570\b"]),
    ("DoD 8140",      [r"\bDo[Dd][\s-]?8140\b"]),
]

_COMPILED: list[tuple[str, list[re.Pattern]]] = [
    (name, [re.compile(p, re.IGNORECASE) for p in patterns])
    for name, patterns in CERT_PATTERNS
]


def extract_certs(text: str) -> list[str]:
    """Return the de-duplicated list of canonical cert names found in `text`.

    Order matches CERT_PATTERNS so output is stable and predictable.
    """
    if not text:
        return []
    found: list[str] = []
    for name, patterns in _COMPILED:
        if any(p.search(text) for p in patterns):
            found.append(name)
    return found


def cert_matches(resume_certs: list[str], job_text: str) -> list[str]:
    """Subset of `resume_certs` that ALSO appear in the job description.

    Lets the UI show "your Security+ matches this listing" without
    re-extracting from the resume each call.
    """
    if not resume_certs or not job_text:
        return []
    # Build a quick lookup from canonical name -> compiled patterns.
    name_to_patterns = dict(_COMPILED)
    out: list[str] = []
    for name in resume_certs:
        patterns = name_to_patterns.get(name)
        if not patterns:
            continue
        if any(p.search(job_text) for p in patterns):
            out.append(name)
    return out


# Security-clearance levels recognized in federal job postings. Ordered
# from least to most restrictive — when multiple appear, the highest wins.
CLEARANCE_PATTERNS: list[tuple[str, list[str]]] = [
    ("None / Public Trust", [
        r"\bpublic\s+trust\b",
        r"\bno\s+(security\s+)?clearance\b",
        r"\bclearance\s+not\s+required\b",
    ]),
    ("Confidential", [r"\bconfidential\s+clearance\b"]),
    ("Secret", [
        r"\b(?:active\s+)?secret\s+clearance\b",
        r"\bsecret\s+security\s+clearance\b",
        r"\bDoD\s+Secret\b",
    ]),
    ("Top Secret", [
        r"\b(?:active\s+)?top\s+secret\s+clearance\b",
        r"\btop\s+secret\s+security\s+clearance\b",
        r"\bDoD\s+Top\s+Secret\b",
    ]),
    ("TS/SCI", [
        r"\bTS[-\s/]?SCI\b",
        r"\btop\s+secret[/ ]+SCI\b",
        r"\bTS\s+with\s+SCI\b",
        r"\bSCI\s+eligibility\b",
    ]),
    ("Polygraph (CI)", [
        r"\bCI\s+poly(graph)?\b",
        r"\bcounter[\s-]?intelligence\s+poly\b",
    ]),
    ("Polygraph (FS)", [
        r"\bFS\s+poly(graph)?\b",
        r"\bfull[\s-]?scope\s+poly\b",
        r"\blifestyle\s+poly\b",
    ]),
]

_COMPILED_CLEARANCE = [
    (name, [re.compile(p, re.IGNORECASE) for p in patterns])
    for name, patterns in CLEARANCE_PATTERNS
]


def extract_clearance(job_text: str) -> str | None:
    """Return the highest clearance level mentioned in the job text, or None.

    Ordering matches CLEARANCE_PATTERNS (last match wins → highest level).
    """
    if not job_text:
        return None
    found = None
    for name, patterns in _COMPILED_CLEARANCE:
        if any(p.search(job_text) for p in patterns):
            found = name   # later iterations override → highest survives
    return found


def extract_required_certs(job_text: str) -> list[str]:
    """Return the canonical list of certs mentioned in the job text.

    Same extractor as `extract_certs`, but semantically the result here is
    'what the posting requires/desires' rather than 'what the user holds'.
    """
    return extract_certs(job_text)
