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
# Canonical "base resume" path. Plain text so it's easy for the user to
# edit. Loaded with absolute priority over the data/docs/active_resume.*
# fallback so the drafter has one obvious place to update master truth.
BASE_RESUME_TXT = PROJECT_ROOT / "baseresume.txt"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36 omnigab-drafter"
)


_DRAFTER_SYSTEM_PROMPT = """You are a federal-resume drafter. You will be given:
  1. The user's BASE resume (master truth — never invent past it).
  2. A target federal job posting (title, agency, duties, qualifications).
  3. The user's saved profile facts (certs, goals, preferences).

## Step 1 — Keyword extraction (REQUIRED, do this silently in a
##           <thinking> block before writing the resume)
Read the posting's Duties + Qualifications sections. Extract the top 8-12
KEYWORD PHRASES that federal HR keyword-screeners will look for. Each
phrase should be a concrete noun-or-verb-phrase from the posting itself
(NOT a paraphrase). Examples of good keywords:
  * "incident response"
  * "Risk Management Framework (RMF)"
  * "Active Directory user provisioning"
  * "Python automation"
  * "Authority to Operate (ATO) packages"
Examples of bad keywords (too generic):
  * "communication skills"
  * "team player"
  * "technology"

## Step 2 — Bullet rewriting
For EACH work-experience bullet in the user's base resume:
  * Identify which keyword(s) from Step 1 naturally relate to that bullet's
    real content.
  * Rewrite the bullet so the keyword appears in plain English — without
    adding any factual claim the base resume didn't already support.
  * If a bullet doesn't map to any keyword, keep it but tighten the wording.
  * If a Step-1 keyword has NO matching bullet in the base resume, do NOT
    fabricate one. Instead, surface the gap in the Federal-Specific Addenda
    section as "Areas of demonstrable coursework / project work" with
    references the user can fill in.

## Output structure (in this order):

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

Hard rules:
- NEVER invent experience, dates, employers, or credentials.
- Every rewritten bullet must still be a TRUE statement supported by the
  base resume — keyword incorporation must be natural, not bolted on.
- When the posting requires X and the user has Y instead, write a bridge
  sentence in the addenda section (coursework, projects, certs, transfer
  of related skill) — do NOT claim experience the user doesn't have.
- Output the resume markdown directly after closing the </thinking> block.
  No "here is your draft" preamble.
- Length target: 600-1000 words AFTER the thinking block."""


class ResumeDrafterTool:
    name = "draft_federal_resume"
    description = (
        "Generate a tailored federal-style resume draft for a specific "
        "USAJOBS posting. Reads the user's master resume from baseresume.txt "
        "in the project root (falls back to data/docs/active_resume.* if "
        "absent), extracts 8-12 keyword phrases from the posting, then "
        "rewrites work-experience bullets to incorporate those keywords "
        "without inventing claims. Provide either `job_url` (auto-fetched) "
        "OR `job_description` text. Output is written to data/resume_drafts/ "
        "as both .md and .json. Auto-trigger heuristic: call when a "
        "usajobs_search result has match_percent >= 85."
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

    # The 14B is great for the chat agent but too slow for the large
    # generation a resume draft requires (~400+s observed). The 7B at
    # Q4 cuts that to ~80-120s with comparable quality on this template
    # task. We hot-swap to it for the draft, then swap back.
    PREFERRED_MODEL = "Qwen2.5-7B-Instruct-Q4_K_M.gguf"

    def __init__(self, *, generator_getter, persistent_memory=None,
                 resume_text_getter=None, model_manager=None):
        """
        generator_getter:    callable -> live Generator (so the drafter
                             always uses the current model after hot-swap).
        persistent_memory:   PersistentMemory instance for profile facts.
        resume_text_getter:  callable -> active resume text (from IndeedApplyTool).
        model_manager:       optional ModelManager. When provided, the drafter
                             will hot-swap to PREFERRED_MODEL (7B) for the
                             generation and swap the original model back
                             afterwards. Without it, uses whatever is loaded.
        """
        self._gen_getter = generator_getter
        self._pm = persistent_memory
        self._resume_getter = resume_text_getter
        self._mm = model_manager

    def _try_swap_to(self, model_filename: str) -> bool:
        """Hot-swap the ModelManager to `model_filename`. Auto-download via
        ensure_model_downloaded if not on disk. Returns True if the swap
        succeeded (mm.current_model_name now equals filename).
        """
        if self._mm is None:
            return False
        try:
            from core.model_manager import ensure_model_downloaded
            if not ensure_model_downloaded(model_filename):
                print(f"[drafter] {model_filename} not on disk and download failed")
                return False
            self._mm.load(model_filename)
            return self._mm.current_model_name == model_filename
        except Exception as exc:
            print(f"[drafter] hot-swap to {model_filename} failed: {exc!r}")
            return False

    # ----- entry -----

    def run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        job_url = (arguments.get("job_url") or "").strip()
        job_desc = (arguments.get("job_description") or "").strip()
        job_title = (arguments.get("job_title") or "").strip()
        agency = (arguments.get("agency") or "").strip()

        # 0. Auto-ingest: if user updated baseresume.pdf/.docx, refresh .txt.
        try:
            from resume_ingest import ingest_resume
            ingest_resume()
        except Exception:
            pass  # ingest is best-effort; .txt may already exist

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
                    "error": ("no active resume found. Drop baseresume.pdf "
                              "or baseresume.docx in the project root, or "
                              "upload one via the Jobs tab.")}

        # 3. Gather profile facts from persistent memory.
        profile = self._profile_snapshot()

        # 4. Generate the draft. Hot-swap to the 7B if a ModelManager was
        # provided and the 7B is available — speeds drafts ~3-4× over 14B.
        prompt = self._build_prompt(resume, job_desc, profile)
        t0 = time.monotonic()
        original_model = None
        swap_note = ""
        try:
            if self._mm is not None:
                original_model = self._mm.current_model_name
                if original_model != self.PREFERRED_MODEL:
                    swapped = self._try_swap_to(self.PREFERRED_MODEL)
                    if swapped:
                        swap_note = (f"hot-swapped {original_model} → "
                                     f"{self.PREFERRED_MODEL} for drafting")
                    else:
                        swap_note = (f"7B unavailable, drafting with "
                                     f"{original_model}")
            gen = self._gen_getter() if self._gen_getter else None
            if gen is None:
                return {"ok": False, "error": "no model loaded"}
            # 7B handles this task with a lower temperature than the 14B
            # (less drift in the keyword incorporation step).
            draft_md = gen.generate_raw(prompt, max_tokens=1500,
                                         temperature=0.18)
        except Exception as exc:
            # Swap back even on failure.
            if original_model and self._mm is not None:
                if self._mm.current_model_name != original_model:
                    try:
                        self._mm.load(original_model)
                    except Exception:
                        pass
            return {"ok": False, "error": f"generation failed: {exc!r}"}
        finally:
            # Always restore the user's chat model so the agent isn't
            # accidentally left on the smaller 7B after a draft.
            if original_model and self._mm is not None:
                if self._mm.current_model_name != original_model:
                    try:
                        self._mm.load(original_model)
                    except Exception as exc:
                        print(f"[drafter] WARN: failed to restore {original_model}: {exc}")
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
            "model_used": (self._mm.current_model_name
                            if self._mm else "(no manager)"),
            "swap_note": swap_note,
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
        """Resolve the user's master resume text. Search order:

          1. baseresume.txt in the project root — the canonical source.
             Plain text, owner-edited, never auto-generated. Treated as
             master truth.
          2. The getter (typically IndeedApplyTool._load_resume) which
             scans data/docs/active_resume.*.
          3. Direct scan of data/docs/ for any *resume* file.
        """
        # 1) Canonical base file in the project root.
        if BASE_RESUME_TXT.exists():
            try:
                txt = BASE_RESUME_TXT.read_text(encoding="utf-8", errors="ignore")
                if txt.strip():
                    return txt
            except OSError:
                pass

        # 2) Configured getter (IndeedApplyTool's _load_resume, etc.).
        if self._resume_getter:
            try:
                txt = self._resume_getter()
                if txt:
                    return txt
            except Exception:
                pass

        # 3) Last-resort scan of data/docs/.
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
