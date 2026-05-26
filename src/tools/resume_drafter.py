"""draft_federal_resume — tailored federal-style resume generator.

Federal resumes (USAJOBS-style) differ from private-sector ones:
  * Long-form (3-7 pages typical), not 1-page
  * EVERY relevant skill listed explicitly with months/years
  * Each job: title, employer, dates (mm/yyyy–mm/yyyy), hours/week,
    salary, supervisor with permission-to-contact
  * Duties section mirrors the posting's "Duties" / "Qualifications"
    text — federal HR uses keyword matching for the initial cull

This tool reads the user's BASE resume + the JOB DESCRIPTION + the user's
saved certifications/goals/preferences from persistent memory, then asks
the local LLM to produce a tailored draft. Triggered automatically by
the agent when usajobs_search returns a job with match_percent >= 85,
OR manually by calling the tool directly with a job_url.

The tool calls the SAME local model the agent uses — no extra inference
budget, no cloud round-trip. Output is written to data/resume_drafts/
as both markdown (for editing) and structured JSON (for further tooling).
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DRAFT_DIR = PROJECT_ROOT / "data" / "resume_drafts"
DATA_DOCS = PROJECT_ROOT / "data" / "docs"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36 omnigab-drafter"
)


_DRAFTER_SYSTEM_PROMPT = """You are a federal-resume drafter. You will be given:
  1. The user's base resume text.
  2. A target federal job posting (title, agency, duties, qualifications).
  3. The user's saved profile facts (certs, goals, preferences).

Produce a tailored federal-style resume draft in this EXACT structure:

# Professional Summary
2-3 sentences positioning the user for THIS role. Mirror keywords from
the posting's duties section.

# Targeted Skills
Bulleted list of 8-12 skills, each mapping to a phrase from the posting.
Format: `- Skill name (years/months experience, source)`

# Work Experience
For each position from the base resume, in reverse-chronological order:
**Job Title** — Employer · mm/yyyy–mm/yyyy · hours/week
- Duty bullet 1 (rewritten to mirror posting language where truthful)
- Duty bullet 2
- Duty bullet 3
(do NOT invent jobs, hours, or duties the user didn't list)

# Education
- Institution, degree program, expected graduation. Note active enrollment
  explicitly if the posting accepts Pathways / Recent Graduate.

# Certifications
Bulleted list, certs the user holds (NOT certs the posting requires that
the user doesn't have — never claim credentials you weren't told they hold).

# Federal-specific addenda
- US Citizenship: state if confirmed in base resume.
- Security Clearance: state current status from base resume; if posting
  requires higher, write "Eligible to obtain; willing to undergo
  background investigation" only if the base resume's clearance
  paragraph supports that claim.
- Veterans' preference: only if base resume mentions it.

Rules:
- NEVER invent experience, dates, or credentials.
- When the posting requires X and the user has Y instead, write a bridge
  sentence explaining the substitution (e.g. coursework, projects, certs).
- Output ONLY the resume markdown — no preamble, no "here is your draft".
- Length target: 600-900 words."""


class ResumeDrafterTool:
    name = "draft_federal_resume"
    description = (
        "Generate a tailored federal-style resume draft for a specific "
        "USAJOBS posting. Provide either `job_url` (we'll fetch + parse) "
        "OR `job_description` text directly. Uses the user's active "
        "resume from data/docs/ plus persistent_memory profile facts. "
        "Output is written to data/resume_drafts/ as both .md and .json. "
        "Auto-trigger heuristic: call when a usajobs_search result has "
        "match_percent >= 85 (the agent should decide based on results)."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "job_url": {"type": "string",
                        "description": "USAJOBS posting URL. Tool fetches + parses."},
            "job_description": {"type": "string",
                                "description": "Raw job text (use if you already have it)."},
            "job_title": {"type": "string",
                          "description": "Job title (for the draft filename)."},
            "agency": {"type": "string",
                       "description": "Hiring agency (for the draft filename)."},
        },
        "required": [],
    }

    def __init__(self, *, generator_getter, persistent_memory=None,
                 resume_text_getter=None):
        """
        generator_getter:    callable -> live Generator (so the drafter
                             always uses the current model after hot-swap).
        persistent_memory:   PersistentMemory instance for profile facts.
        resume_text_getter:  callable -> active resume text (from IndeedApplyTool).
        """
        self._gen_getter = generator_getter
        self._pm = persistent_memory
        self._resume_getter = resume_text_getter

    # ----- entry -----

    def run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        job_url = (arguments.get("job_url") or "").strip()
        job_desc = (arguments.get("job_description") or "").strip()
        job_title = (arguments.get("job_title") or "").strip()
        agency = (arguments.get("agency") or "").strip()

        # 1. Resolve the job description.
        if not job_desc and job_url:
            fetched = self._fetch_job_page(job_url)
            if fetched.get("error"):
                return {"ok": False, "error": fetched["error"]}
            job_desc = fetched["text"]
            job_title = job_title or fetched.get("title", "")
            agency = agency or fetched.get("agency", "")
        if not job_desc:
            return {"ok": False,
                    "error": "provide either job_url or job_description"}

        # 2. Load the user's base resume.
        resume = self._load_user_resume()
        if not resume:
            return {"ok": False,
                    "error": ("no active resume found. Upload one via the "
                              "Jobs tab (Choose file…) before drafting.")}

        # 3. Gather profile facts from persistent memory.
        profile = self._profile_snapshot()

        # 4. Generate the draft via the local model.
        gen = self._gen_getter() if self._gen_getter else None
        if gen is None:
            return {"ok": False, "error": "no model loaded"}

        prompt = self._build_prompt(resume, job_desc, profile)
        t0 = time.monotonic()
        try:
            draft_md = gen.generate_raw(prompt, max_tokens=1800,
                                         temperature=0.25)
        except Exception as exc:
            return {"ok": False, "error": f"generation failed: {exc!r}"}
        elapsed = time.monotonic() - t0

        # 5. Persist.
        DRAFT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        slug = self._slug(job_title or "untitled") or "draft"
        md_path = DRAFT_DIR / f"{stamp}_{slug}.md"
        json_path = DRAFT_DIR / f"{stamp}_{slug}.json"

        header = (
            f"<!-- omnigab resume draft -->\n"
            f"<!-- Generated: {time.strftime('%Y-%m-%d %H:%M:%S')} -->\n"
            f"<!-- Target: {job_title or '(unknown title)'} @ {agency or '(unknown agency)'} -->\n"
            f"<!-- Source: {job_url or 'direct text input'} -->\n\n"
        )
        md_path.write_text(header + draft_md, encoding="utf-8")
        json_path.write_text(json.dumps({
            "generated_at": time.time(),
            "job_title": job_title,
            "agency": agency,
            "job_url": job_url,
            "generation_seconds": round(elapsed, 2),
            "resume_chars_in": len(resume),
            "job_desc_chars_in": len(job_desc),
            "draft_chars_out": len(draft_md),
            "draft_markdown": draft_md,
        }, indent=2), encoding="utf-8")

        # 6. Log to application_history so the watcher can dedupe.
        if self._pm is not None and job_url:
            try:
                self._pm.record_application(
                    job_url=job_url,
                    job_title=job_title or "(unknown)",
                    agency=agency or "",
                    match_percent=None,
                    status="drafted",
                )
            except Exception:
                pass

        return {
            "ok": True,
            "job_title": job_title,
            "agency": agency,
            "draft_path": str(md_path),
            "draft_chars": len(draft_md),
            "generation_seconds": round(elapsed, 2),
            "draft_preview": draft_md[:600],
        }

    # ----- helpers -----

    def _build_prompt(self, resume: str, job_desc: str, profile: str) -> str:
        # Cap inputs so we stay well inside the 8192 context.
        resume = resume[:3000]
        job_desc = job_desc[:4000]
        user_block = (
            f"USER PROFILE (from persistent memory):\n{profile or '(none)'}\n\n"
            f"USER BASE RESUME:\n{resume}\n\n"
            f"TARGET JOB POSTING:\n{job_desc}\n\n"
            "Draft the tailored federal resume now, in the prescribed structure."
        )
        return (
            "<|im_start|>system\n" + _DRAFTER_SYSTEM_PROMPT + "<|im_end|>\n"
            "<|im_start|>user\n" + user_block + "<|im_end|>\n"
            "<|im_start|>assistant\n"
        )

    def _load_user_resume(self) -> str:
        if self._resume_getter:
            try:
                txt = self._resume_getter()
                if txt:
                    return txt
            except Exception:
                pass
        # Fallback: scan data/docs/ for active_resume.* or any *resume*.
        candidates = (sorted(DATA_DOCS.glob("active_resume.*"))
                       + sorted(DATA_DOCS.glob("*resume*")))
        for p in candidates:
            try:
                if p.suffix.lower() in (".txt", ".md"):
                    return p.read_text(encoding="utf-8", errors="ignore")
                if p.suffix.lower() == ".pdf":
                    try:
                        import pymupdf
                        with pymupdf.open(str(p)) as doc:
                            return "\n".join(page.get_text() for page in doc)
                    except Exception:
                        continue
                if p.suffix.lower() == ".docx":
                    try:
                        import docx2txt
                        return docx2txt.process(str(p)) or ""
                    except Exception:
                        continue
            except Exception:
                continue
        return ""

    def _profile_snapshot(self) -> str:
        if self._pm is None:
            return ""
        try:
            return self._pm.snapshot_for_prompt(max_facts=40)
        except Exception:
            return ""

    def _fetch_job_page(self, url: str) -> dict[str, Any]:
        try:
            resp = requests.get(url, headers={"User-Agent": USER_AGENT},
                                timeout=15)
        except requests.RequestException as exc:
            return {"error": f"could not fetch {url}: {exc}"}
        if resp.status_code != 200:
            return {"error": f"HTTP {resp.status_code} for {url}"}
        soup = BeautifulSoup(resp.text, "html.parser")
        title = ""
        agency = ""
        try:
            h1 = soup.select_one("h1")
            if h1:
                title = h1.get_text(strip=True)
            agency_el = soup.select_one(
                ".usajobs-joa-summary__agency, [class*='joa-summary__agency']"
            )
            if agency_el:
                agency = agency_el.get_text(" ", strip=True)
        except Exception:
            pass
        # Body text: prefer #summary + #duties + #qualifications, else main.
        sections = []
        for sel in ("#summary", "#duties", "#qualifications", "#requirements"):
            el = soup.select_one(sel)
            if el:
                sections.append(el.get_text("\n", strip=True))
        body = "\n\n".join(sections) if sections else (
            soup.select_one("main") or soup
        ).get_text("\n", strip=True)
        return {"title": title, "agency": agency, "text": body[:8000]}

    @staticmethod
    def _slug(s: str) -> str:
        s = re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_").lower()
        return s[:50]
