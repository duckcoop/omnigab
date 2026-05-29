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


# Canonical tech/skill vocabulary for federal IT/cyber/AI roles. Each
# entry is (canonical_label, [regex variants]). Matching is case-
# insensitive and word-boundary aware so "Python" in "in Python 3.11"
# matches but "Python" in "Pythonista" doesn't.
TECH_SKILL_PATTERNS: list[tuple[str, list[str]]] = [
    # Languages
    ("Python", [r"\bpython\b"]),
    ("Java", [r"\bjava\b(?!\s*script)"]),
    ("JavaScript", [r"\bjavascript\b", r"\bjs\b"]),
    ("TypeScript", [r"\btypescript\b"]),
    ("C++", [r"\bc\+\+(?!\w)"]),
    ("C#", [r"\bc#(?!\w)"]),
    ("Go", [r"\bgolang\b"]),
    ("Rust", [r"\brust\b(?!\s*belt)"]),
    ("SQL", [r"\bsql\b"]),
    ("Bash", [r"\bbash\b", r"\bshell\s+scripting\b"]),
    ("PowerShell", [r"\bpowershell\b"]),
    # Cloud
    ("AWS", [r"\bAWS\b", r"\bamazon\s+web\s+services\b"]),
    ("Azure", [r"\bazure\b"]),
    ("GCP", [r"\bGCP\b", r"\bgoogle\s+cloud\b"]),
    ("Kubernetes", [r"\bkubernetes\b", r"\bk8s\b"]),
    ("Docker", [r"\bdocker\b"]),
    ("Terraform", [r"\bterraform\b"]),
    # OS / infra
    ("Linux", [r"\blinux\b"]),
    ("RHEL", [r"\bRHEL\b", r"\bred\s+hat\s+enterprise\s+linux\b"]),
    ("Windows Server", [r"\bwindows\s+server\b"]),
    ("Active Directory", [r"\bactive\s+directory\b", r"\bAD\b"]),
    # Security tooling
    ("SIEM", [r"\bSIEM\b"]),
    ("Splunk", [r"\bsplunk\b"]),
    ("Wireshark", [r"\bwireshark\b"]),
    ("Nessus", [r"\bnessus\b"]),
    ("Burp Suite", [r"\bburp\s+suite\b"]),
    ("Metasploit", [r"\bmetasploit\b"]),
    # Federal frameworks
    ("NIST 800-53", [r"\bNIST\s+800[-\s]?53\b"]),
    ("NIST 800-171", [r"\bNIST\s+800[-\s]?171\b"]),
    ("FedRAMP", [r"\bfedramp\b"]),
    ("FISMA", [r"\bFISMA\b"]),
    ("RMF", [r"\bRMF\b", r"\brisk\s+management\s+framework\b"]),
    ("ATO", [r"\bATO\b", r"\bauthority\s+to\s+operate\b"]),
    # Networking
    ("TCP/IP", [r"\bTCP/IP\b"]),
    ("BGP", [r"\bBGP\b"]),
    ("OSPF", [r"\bOSPF\b"]),
    ("VPN", [r"\bVPN\b"]),
    ("Firewall", [r"\bfirewall\b"]),
    ("IDS/IPS", [r"\bIDS/IPS\b", r"\bintrusion\s+detection\b"]),
    # AI / ML
    ("TensorFlow", [r"\btensorflow\b"]),
    ("PyTorch", [r"\bpytorch\b"]),
    ("scikit-learn", [r"\bscikit[-\s]?learn\b", r"\bsklearn\b"]),
    ("LLM", [r"\bLLMs?\b", r"\blarge\s+language\s+models?\b"]),
    ("NLP", [r"\bNLP\b", r"\bnatural\s+language\s+processing\b"]),
    ("Computer Vision", [r"\bcomputer\s+vision\b", r"\bCV\b"]),
    ("Deep Learning", [r"\bdeep\s+learning\b"]),
    ("MLOps", [r"\bMLOps\b"]),
    # Workflow
    ("Agile", [r"\bagile\b"]),
    ("Scrum", [r"\bscrum\b"]),
    ("CI/CD", [r"\bCI/CD\b", r"\bcontinuous\s+integration\b"]),
    ("Git", [r"\bgit\b(?!hub)", r"\bgithub\b", r"\bgitlab\b"]),
    ("ITIL", [r"\bITIL\b"]),
]

_COMPILED_SKILLS = [
    (name, [re.compile(p, re.IGNORECASE) for p in patterns])
    for name, patterns in TECH_SKILL_PATTERNS
]


def extract_tech_skills(text: str) -> list[str]:
    """Return canonical tech skills mentioned in `text`. Deterministic
    order matches TECH_SKILL_PATTERNS so output is stable.
    """
    if not text:
        return []
    found: list[str] = []
    for name, patterns in _COMPILED_SKILLS:
        if any(p.search(text) for p in patterns):
            found.append(name)
    return found


def skills_gap(*, job_text: str, resume_text: str,
                resume_certs: list[str] | None = None,
                resume_clearance: str | None = None) -> dict:
    """Compute the gap between what the posting wants and what the user has.

    Returns a dict with:
      missing_certs        — required by posting, not held by user
      missing_skills       — tech skills in posting not in resume (top 6)
      missing_clearance    — posting clearance level if user has none
      matched_certs        — overlap (informational, mirrors cert_matches)
      matched_skills       — overlap (informational)
    """
    resume_certs = resume_certs or []

    # ----- certs -----
    job_certs = set(extract_required_certs(job_text))
    user_certs = set(resume_certs)
    matched_certs = sorted(job_certs & user_certs, key=lambda c: c.lower())
    missing_certs = sorted(job_certs - user_certs, key=lambda c: c.lower())

    # ----- tech skills -----
    job_skills = extract_tech_skills(job_text)
    resume_skills = set(extract_tech_skills(resume_text))
    matched_skills: list[str] = []
    missing_skills: list[str] = []
    for s in job_skills:   # preserves canonical order
        if s in resume_skills:
            matched_skills.append(s)
        else:
            missing_skills.append(s)
    # Cap missing list so the agent's per-job line stays readable.
    missing_skills = missing_skills[:6]

    # ----- clearance -----
    job_clearance = extract_clearance(job_text)
    missing_clearance: str | None = None
    if job_clearance and job_clearance not in ("None / Public Trust",):
        user_has = bool(resume_clearance and resume_clearance not in
                         ("None / Public Trust",))
        if not user_has:
            missing_clearance = job_clearance

    return {
        "missing_certs": missing_certs,
        "missing_skills": missing_skills,
        "missing_clearance": missing_clearance,
        "matched_certs": matched_certs,
        "matched_skills": matched_skills,
    }
