"""USAJOBS search tool — federal/government job listings.

Two execution modes:

1. **API mode** (best). If the env vars USAJOBS_API_KEY and USAJOBS_API_EMAIL
   are set, the tool hits the official JSON API at data.usajobs.gov/api/search.
   Returns rich structured data. Free signup at
   https://developer.usajobs.gov/APIRequest (instant email-delivered key).

2. **Browser-handoff mode** (fallback). Without an API key, the public
   www.usajobs.gov search page is a SPA whose listings are rendered by
   JavaScript — there's nothing to scrape from the initial HTML response.
   Rather than fail or spin up Playwright (slow and Cloudflare-friendly
   on other sites), the tool opens the search URL in the user's real
   browser and returns the URL plus instructions.

Why this is the right call for the user's stated use case:
- Space Force, DoD, federal cyber roles all live on USAJOBS.
- There's no captcha on either path.
- API mode gives match scoring; browser mode lets the user browse
  manually with the right filters pre-applied.
"""

from __future__ import annotations

import json
import os
import time
import json
import os
import re
import time
import webbrowser
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import requests


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RESULTS_DIR = DATA_DIR / "usajobs_runs"


## --- USAJOBS occupational series ("job categories") ---------------------
## Federal IT/cyber roles are all under series 2210 (Information Technology
## Management). Software/CS-leaning roles are under 1550. Filtering by series
## code is the single most reliable way to narrow USAJOBS results —
## keyword-only searches return zero hits because postings are titled by
## series ("IT Specialist (INFOSEC)") not by tech buzzwords.
IT_SERIES = "2210"
CS_SERIES = "1550"

# Trigger words that indicate the user wants the IT series.
_IT_HINTS = {
    "it", "info tech", "information technology", "cyber", "cybersec",
    "cybersecurity", "network", "sysadmin", "system administrator",
    "help desk", "helpdesk", "infosec", "security analyst", "soc",
    "incident response", "siem", "devops", "cloud", "support",
}
_CS_HINTS = {
    "software", "developer", "engineer", "programmer", "computer scientist",
    "ml", "machine learning", "data scientist",
}

# AI-flavored hints. When any of these appear in the raw query, we switch to
# AI-focus mode: target "Artificial Intelligence" as the keyword, disable
# the entry-level filter (federal AI roles are typically GS-12+), and boost
# results whose title carries an (AI)/(AIML)/(ML) parenthetical.
_AI_HINTS = {
    "ai", "a.i.", "artificial intelligence", "machine learning", "ml",
    "deep learning", "neural network", "llm", "large language model",
    "generative ai", "genai", "mlops", "ai/ml", "ai engineering",
    "data science", "data scientist",
}

# Titles like "IT Specialist (AI)" or "Computer Scientist (AIML)" are the
# tell-tale signal for an AI-designated federal role. Boost these in ranking.
_AI_TITLE_RE = re.compile(
    r"\((\s*(AI|AIML|ML|Artificial\s+Intelligence|Machine\s+Learning)\s*)\)",
    re.IGNORECASE,
)


def _infer_series(query: str) -> list[str]:
    """Look at the free-form query and return the matching OPM series codes.

    Uses word-boundary matching so 'it' doesn't match inside 'janitor',
    'soc' doesn't match inside 'association', etc.
    """
    q = query.lower()
    out: list[str] = []
    if any(re.search(r"\b" + re.escape(h) + r"\b", q) for h in _IT_HINTS):
        out.append(IT_SERIES)
    if any(re.search(r"\b" + re.escape(h) + r"\b", q) for h in _CS_HINTS):
        out.append(CS_SERIES)
    return out


def _is_ai_query(query: str) -> bool:
    """Detect whether the user is asking specifically for AI/ML roles."""
    q = query.lower()
    return any(re.search(r"\b" + re.escape(h) + r"\b", q) for h in _AI_HINTS)


# Cert short-codes we want stripped from the keyword string before sending
# to USAJOBS. Federal postings don't index certs as keywords, so leaving
# them in the query kills the result count to zero.
#
# NB: `\b` does NOT fire after `+` (it's not a word char). We anchor the
# pattern with lookarounds `(?<!\w)` / `(?!\w)` instead so `Security+ `
# (followed by space) matches correctly.
_CERT_STRIP_RE = re.compile(
    r"(?<!\w)("
    r"Security\+|Network\+|A\+|Linux\+|Server\+|Cloud\+|CySA\+|PenTest\+|CASP\+"
    r"|CCNA|CCNP|CCIE|CISSP|CCSP|SSCP|CEH|OSCP|OSWE|CISM|CISA|CRISC|PMP|ITIL"
    r"|GSEC|GCIH|GCIA|GPEN|GREM|MCSA|MCSE"
    r"|AZ-?\d{3}|MS-?\d{3}|SY0-?\d{3}|N10-?\d{3}|220-?\d{3,4}"
    r"|AWS\s+(Certified\s+)?(Cloud\s+Practitioner|Solutions\s+Architect|Developer)"
    r"|CompTIA"
    r")(?!\w)",
    re.IGNORECASE,
)


def _sanitize_query(query: str) -> str:
    """Drop cert names and recruiter-jargon from the keyword string."""
    cleaned = _CERT_STRIP_RE.sub(" ", query)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,;|")
    # Common LLM-generated noise: "entry level" + "jobs" + repeats.
    cleaned = re.sub(r"\b(jobs?|positions?|roles?|openings?)\b", "", cleaned,
                     flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


class UsaJobsSearchTool:
    name = "usajobs_search"
    description = (
        "Search USAJOBS for federal/government jobs (DoD, Space Force, NSA, "
        "civilian IT, etc.). No Cloudflare, no captcha. Federal listings are "
        "indexed by OPM series code — this tool auto-injects series 2210 for "
        "IT/cyber queries and 1550 for CS/software queries. Keep `query` "
        "short and generic ('Cybersecurity', 'IT Specialist'); do NOT include "
        "cert names — they will be stripped because federal postings don't "
        "index by cert. Use `entry_level=true` for student/early-career roles "
        "(GS-04 through GS-07 + Pathways)."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string",
                      "description": "Simple keywords like 'Cybersecurity', "
                                     "'IT Specialist', 'Network Administrator'. "
                                     "Cert names and 'jobs/positions' words are stripped."},
            "location": {"type": "string",
                         "description": "City, state, or zip. Optional."},
            "max_jobs": {"type": "integer", "default": 10, "maximum": 25},
            "days_ago": {"type": "integer", "default": 30,
                         "description": "Posted within the last N days."},
            "entry_level": {"type": "boolean", "default": False,
                            "description": "GS-04 through GS-07 + Pathways "
                                           "(Students / Recent Graduates) hiring paths."},
            "series_codes": {"type": "array", "items": {"type": "string"},
                             "description": "OPM occupational series codes (e.g. ['2210']). "
                                            "Auto-inferred from the query when omitted."},
            "ai_focus": {"type": "boolean", "default": False,
                         "description": "Target federal AI / ML roles specifically. "
                                        "Searches for 'Artificial Intelligence', forces "
                                        "series 2210+1550, disables entry_level filter "
                                        "(AI roles are typically GS-12+), and boosts "
                                        "titles containing (AI)/(AIML)/(ML)."},
        },
        "required": ["query"],
    }

    def __init__(self, embedder=None, resume_text_getter=None, resume_certs_getter=None):
        """
        embedder: shared EmbeddingEngine for resume-match scoring.
        resume_text_getter: callable returning the active resume text.
        resume_certs_getter: callable returning the user's certifications list.
            Lets us reuse IndeedApplyTool's cert cache so swapping the
            active resume updates both tools simultaneously.
        """
        self.embedder = embedder
        self._resume_getter = resume_text_getter
        self._certs_getter = resume_certs_getter
        self._cached_resume_text: str | None = None
        self._cached_resume_vector = None

    # ----- public entry point -----

    def run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        raw_query = str(arguments.get("query") or "").strip()
        if not raw_query:
            return {"ok": False, "error": "query is required"}
        location = str(arguments.get("location") or "").strip()
        try:
            max_jobs = max(1, min(25, int(arguments.get("max_jobs") or 10)))
        except (TypeError, ValueError):
            max_jobs = 10
        try:
            days_ago = max(1, min(60, int(arguments.get("days_ago") or 30)))
        except (TypeError, ValueError):
            days_ago = 30
        entry_level = bool(arguments.get("entry_level"))
        ai_focus = bool(arguments.get("ai_focus")) or _is_ai_query(raw_query)

        # Strip cert names + jargon from the keyword string. USAJOBS doesn't
        # index by cert — leaving "Security+ Network+ CCNA" in the query
        # returns zero results.
        clean_query = _sanitize_query(raw_query)
        if not clean_query:
            # The query was nothing but cert names. Default to a generic IT
            # search since we'll inject series 2210 anyway.
            clean_query = "IT Specialist"

        # Series codes: explicit > inferred from query > none.
        series_codes = arguments.get("series_codes")
        if not series_codes:
            series_codes = _infer_series(raw_query) or _infer_series(clean_query)
        series_codes = [str(c) for c in (series_codes or [])]

        # ---- AI-focus overrides ----
        # When the user is hunting for AI/ML roles, the entry-level filter
        # would hide GS-12+ AI specialist postings (which is most of them).
        # We:
        #   * widen the keyword to "Artificial Intelligence" so USAJOBS
        #     surfaces postings tagged with "(AI)" / "(AIML)" / "(ML)";
        #   * force-include both 2210 (IT) and 1550 (CS) series;
        #   * disable entry_level so we don't filter the actual roles out;
        #   * downstream we boost titles with the (AI)/(AIML) parenthetical.
        if ai_focus:
            clean_query = "Artificial Intelligence"
            if "2210" not in series_codes:
                series_codes.insert(0, "2210")
            if "1550" not in series_codes:
                series_codes.append("1550")
            entry_level = False

        # Get user certs for per-result cert_matches display ONLY.
        # Do NOT inject them into the query.
        user_certs: list[str] = []
        if self._certs_getter is not None:
            try:
                user_certs = list(self._certs_getter() or [])
            except Exception:
                user_certs = []

        api_key = os.environ.get("USAJOBS_API_KEY", "").strip()
        api_email = os.environ.get("USAJOBS_API_EMAIL", "").strip()

        # Preferred order:
        #   1. Official API (cleanest, but requires free signup)
        #   2. Headless Playwright scrape (no signup, USAJOBS has no Cloudflare)
        #   3. Browser handoff (open the URL in user's browser, last resort)
        if api_key and api_email:
            return self._run_via_api(
                clean_query, location, max_jobs, days_ago, entry_level,
                series_codes, api_key, api_email, user_certs, raw_query,
                ai_focus=ai_focus,
            )

        # Try Playwright. If something fails (Playwright not installed,
        # browser launch error, network), gracefully fall back to handoff.
        try:
            return self._run_via_playwright(
                clean_query, location, max_jobs, days_ago, entry_level,
                series_codes, user_certs, raw_query, ai_focus=ai_focus,
            )
        except Exception as exc:
            print(f"[usajobs_search] Playwright scrape failed: {exc}. Falling back to browser handoff.")
            return self._run_via_browser_handoff(
                clean_query, location, days_ago, entry_level,
                series_codes, user_certs, raw_query, ai_focus=ai_focus,
            )

    # ----- API mode -----

    def _run_via_api(self, query, location, max_jobs, days_ago, entry_level,
                      series_codes: list[str], api_key, api_email,
                      user_certs: list[str], raw_query: str,
                      ai_focus: bool = False) -> dict[str, Any]:
        params: list[tuple[str, str]] = [
            ("Keyword", query),
            ("ResultsPerPage", str(max_jobs)),
            ("DatePosted", str(days_ago)),  # 1-60
        ]
        if location:
            params.append(("LocationName", location))
        if entry_level:
            # GS-04 through GS-07 is the right band for student / early-career
            # roles (Pathways programs sit here). 05-09 was too wide.
            params.append(("PayGradeLow", "04"))
            params.append(("PayGradeHigh", "07"))
            # Pathways hiring paths: students + recent graduates.
            params.append(("HiringPath", "student"))
            params.append(("HiringPath", "graduates"))
        for code in series_codes:
            params.append(("JobCategoryCode", code))

        headers = {
            "Host": "data.usajobs.gov",
            "User-Agent": api_email,
            "Authorization-Key": api_key,
            "Accept": "application/json",
        }

        try:
            resp = requests.get("https://data.usajobs.gov/api/search",
                                params=params, headers=headers, timeout=15)
        except requests.RequestException as exc:
            return {"ok": False, "error": f"USAJOBS API request failed: {exc}"}

        if resp.status_code != 200:
            return {"ok": False, "error": f"USAJOBS API HTTP {resp.status_code}",
                    "body": resp.text[:300]}

        try:
            data = resp.json()
        except ValueError:
            return {"ok": False, "error": "USAJOBS API returned non-JSON"}

        items = data.get("SearchResult", {}).get("SearchResultItems", []) or []
        listings: list[dict] = []
        for item in items[:max_jobs]:
            d = item.get("MatchedObjectDescriptor", {}) or {}
            locations = ", ".join(
                loc.get("LocationName", "") for loc in (d.get("PositionLocation") or [])
            ) or d.get("PositionLocationDisplay", "")
            pay_range = ""
            remunerations = d.get("PositionRemuneration") or []
            if remunerations:
                pr = remunerations[0]
                lo = pr.get("MinimumRange", "")
                hi = pr.get("MaximumRange", "")
                unit = pr.get("RateIntervalCode", "")
                if lo or hi:
                    pay_range = f"${lo}–${hi} {unit}".strip()
            listings.append({
                "title": d.get("PositionTitle", ""),
                "agency": d.get("OrganizationName", "") or d.get("DepartmentName", ""),
                "location": locations,
                "salary": pay_range,
                "series": ", ".join(s.get("Series", "") for s in (d.get("JobCategory") or [])),
                "grade": d.get("UserArea", {}).get("Details", {}).get("LowGrade", ""),
                "posted": d.get("PublicationStartDate", "")[:10],
                "closing": d.get("ApplicationCloseDate", "")[:10],
                "summary": d.get("QualificationSummary", "") or d.get("UserArea", {}).get(
                    "Details", {}).get("JobSummary", ""),
                "url": d.get("PositionURI", ""),
            })

        self._refresh_resume()
        for job in listings:
            text = " ".join(filter(None, [job.get("summary", ""),
                                          job.get("title", ""), job.get("agency", "")]))
            pct = self._match_percent(text)
            if pct is not None:
                job["match_percent"] = pct
            if user_certs:
                from tools.resume_intel import cert_matches
                matched = cert_matches(user_certs, text)
                if matched:
                    job["cert_matches"] = matched

        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        try:
            artifact = RESULTS_DIR / f"run_{time.strftime('%Y%m%d_%H%M%S')}.json"
            artifact.write_text(json.dumps({"query": query, "results": listings},
                                            indent=2), encoding="utf-8")
        except Exception:
            pass

        return {
            "ok": True,
            "mode": "api",
            "source": "usajobs.gov",
            "raw_query": raw_query,
            "query_sent": query,
            "series_codes": series_codes,
            "entry_level": entry_level,
            "location": location or "(anywhere)",
            "found": len(listings),
            "results": listings,
        }

    # ----- browser-handoff mode (no API key) -----

    # ----- Playwright scrape mode (no API key needed) -----

    def _build_url(self, query: str, location: str, days_ago: int,
                   entry_level: bool, series_codes: list[str]) -> str:
        """Compose the USAJOBS search URL exactly the way the website does."""
        parts = [
            f"k={quote_plus(query)}",
            f"l={quote_plus(location)}",
            f"dap={days_ago}",
            "p=1",
        ]
        for code in series_codes:
            parts.append(f"jc={quote_plus(code)}")
        if entry_level:
            for grade in ("04", "05", "06", "07"):
                parts.append(f"pgs={grade}")
            parts.append("hp=student")
            parts.append("hp=graduates")
        return "https://www.usajobs.gov/Search/Results?" + "&".join(parts)

    def _run_via_playwright(self, query, location, max_jobs, days_ago, entry_level,
                              series_codes: list[str],
                              user_certs: list[str],
                              raw_query: str,
                              ai_focus: bool = False) -> dict[str, Any]:
        """Scrape rendered Angular results via headless Chromium.

        USAJOBS is government — no Cloudflare — so plain Playwright with
        default settings is enough. We wait for `networkidle` because
        the Angular app fetches results after DOMContentLoaded.

        Cards are inside `#search-results` with class `bg-white p-4`.
        Each card contains:
          - h2 a              -> title + apply URL
          - h3                -> department / sub-agency
          - p (multi)         -> location, agency, salary, grade
        """
        from playwright.sync_api import sync_playwright

        url = self._build_url(query, location, days_ago, entry_level, series_codes)

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                page = browser.new_page(viewport={"width": 1280, "height": 900})
                page.goto(url, wait_until="networkidle", timeout=30000)
                # Tiny extra settle for late hydration.
                page.wait_for_timeout(800)

                # Each search hit's container has class 'bg-white p-4' inside #search-results.
                cards = page.locator("#search-results .bg-white.p-4").all()
                listings: list[dict] = []
                for card in cards:
                    if len(listings) >= max_jobs * 2:
                        break  # gather a few extra to allow cert-ranking to choose the best
                    try:
                        listings.append(self._extract_card(card))
                    except Exception:
                        continue

                # Also grab the total-count text for the response payload.
                try:
                    count_text = page.locator(
                        "text=/\\d+\\s*–\\s*\\d+\\s*of\\s*[\\d,]+/").first.inner_text()
                except Exception:
                    count_text = ""
            finally:
                browser.close()

        # Resume match + cert overlay.
        self._refresh_resume()
        for job in listings:
            text_blob = " ".join(filter(None, [
                job.get("title", ""), job.get("agency", ""),
                job.get("location", ""), job.get("summary", ""),
            ]))
            pct = self._match_percent(text_blob)
            if pct is not None:
                job["match_percent"] = pct
            if user_certs:
                from tools.resume_intel import cert_matches
                matched = cert_matches(user_certs, text_blob)
                if matched:
                    job["cert_matches"] = matched

        # Flag AI-designated postings so we can both rank-boost them and
        # surface the marker to the user.
        ai_marker_count = 0
        for job in listings:
            if _AI_TITLE_RE.search(job.get("title", "") or ""):
                job["ai_designated"] = True
                ai_marker_count += 1

        # Rank:
        #   1. In ai_focus mode, jobs whose TITLE carries (AI)/(AIML)/(ML)
        #      always sort first — these are the federal AI-specialist roles
        #      the user is hunting for.
        #   2. Then jobs that mention the user's certs.
        #   3. Then by match_percent (resume cosine sim).
        #   4. Postings with a salary string rank above those without
        #      (salary-less cards tend to be summary/program pages).
        def sort_key(j):
            ai_bonus = 0 if (ai_focus and j.get("ai_designated")) else 1
            return (
                ai_bonus,
                -len(j.get("cert_matches", [])),
                -(j.get("match_percent") or 0),
                0 if j.get("salary") else 1,
            )
        listings.sort(key=sort_key)
        listings = listings[:max_jobs]

        return {
            "ok": True,
            "mode": "playwright_scrape",
            "source": "usajobs.gov",
            "raw_query": raw_query,
            "query_sent": query,
            "series_codes": series_codes,
            "entry_level": entry_level,
            "ai_focus": ai_focus,
            "ai_designated_count": ai_marker_count,
            "location": location or "(anywhere)",
            "url": url,
            "total_available": count_text,
            "found": len(listings),
            "results": listings,
            "ranking": ("ai_designated desc, cert_matches desc, match_percent desc"
                         if ai_focus else "cert_matches desc, match_percent desc"),
        }

    # Full US state names + abbreviations + DC + territories. Used to
    # recognize a location row like "Washington, District of Columbia".
    _US_STATES = {
        "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
        "connecticut", "delaware", "florida", "georgia", "hawaii", "idaho",
        "illinois", "indiana", "iowa", "kansas", "kentucky", "louisiana",
        "maine", "maryland", "massachusetts", "michigan", "minnesota",
        "mississippi", "missouri", "montana", "nebraska", "nevada",
        "new hampshire", "new jersey", "new mexico", "new york",
        "north carolina", "north dakota", "ohio", "oklahoma", "oregon",
        "pennsylvania", "rhode island", "south carolina", "south dakota",
        "tennessee", "texas", "utah", "vermont", "virginia", "washington",
        "west virginia", "wisconsin", "wyoming",
        "district of columbia", "puerto rico", "guam", "virgin islands",
        "american samoa", "northern mariana islands",
        # 2-letter abbreviations
        "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga", "hi",
        "id", "il", "in", "ia", "ks", "ky", "la", "me", "md", "ma", "mi",
        "mn", "ms", "mo", "mt", "ne", "nv", "nh", "nj", "nm", "ny", "nc",
        "nd", "oh", "ok", "or", "pa", "ri", "sc", "sd", "tn", "tx", "ut",
        "vt", "va", "wa", "wv", "wi", "wy", "dc", "pr",
    }

    @classmethod
    def _looks_like_location(cls, text: str) -> bool:
        """True if `text` matches a 'City, State' pattern or is 'Remote' /
        'Multiple Locations' / 'Anywhere in the U.S.'."""
        t = text.strip()
        low = t.lower()
        if "remote" in low or "multiple locations" in low or "anywhere" in low:
            return True
        # City, State pattern: at least one comma, and the segment after a
        # comma is a known US state (full name or 2-letter).
        if "," in t:
            tail = t.rsplit(",", 1)[-1].strip().lower()
            if tail in cls._US_STATES:
                return True
        return False

    def _extract_card(self, card) -> dict:
        """Pull structured fields from one USAJOBS Angular result card."""
        title = ""
        href = ""
        try:
            link = card.locator("h2 a, h3 a").first
            title = (link.inner_text() or "").strip()
            href = link.get_attribute("href") or ""
        except Exception:
            pass

        try:
            row_text = card.inner_text()
        except Exception:
            row_text = ""
        rows = [r.strip() for r in row_text.splitlines() if r.strip()
                and r.strip() != title and r.strip() != "Save job"]

        agency = ""
        sub_agency = ""
        location = ""
        salary = ""
        grade = ""
        posted = ""
        closing = ""

        for r in rows:
            low = r.lower()
            if r.startswith("$") or "per year" in low or "per hour" in low:
                if not salary:
                    salary = r
                m = re.search(r"GS\s*\d+", r, re.IGNORECASE)
                if m and not grade:
                    grade = m.group(0).upper()
            elif low.startswith("open ") and "/" in r:
                posted = r
            elif "close" in low and "/" in r:
                closing = r
            elif self._looks_like_location(r):
                if not location:
                    location = r
            elif "department" in low or "agency" in low or "office" in low \
                    or "force" in low or "guard" in low or "command" in low \
                    or "administration" in low:
                if not agency:
                    agency = r
                elif not sub_agency:
                    sub_agency = r

        return {
            "title": title,
            "agency": agency,
            "sub_agency": sub_agency,
            "location": location,
            "salary": salary,
            "grade": grade,
            "posted": posted,
            "closing": closing,
            "summary": "",  # would require detail-page fetch
            "url": href if href.startswith("http") else (
                f"https://www.usajobs.gov{href}" if href else ""),
        }

    def _run_via_browser_handoff(self, query, location, days_ago, entry_level,
                                   series_codes: list[str],
                                   user_certs: list[str],
                                   raw_query: str,
                                   ai_focus: bool = False) -> dict[str, Any]:
        """Build a properly-filtered USAJOBS URL and open it in the user's
        real browser. URL params:
          k     = keywords (sanitized, no cert names)
          l     = location
          dap   = days_ago (1-60)
          jc    = JobCategoryCode (occupational series; repeatable)
          pgs   = PayGradeStart (one entry per grade; repeatable)
          hp    = HiringPath (repeatable: student, graduates, public, etc.)
        """
        parts = [
            f"k={quote_plus(query)}",
            f"l={quote_plus(location)}",
            f"dap={days_ago}",
            "p=1",
        ]
        for code in series_codes:
            parts.append(f"jc={quote_plus(code)}")
        if entry_level:
            # GS-04 through GS-07 is the student / early-career band.
            for grade in ("04", "05", "06", "07"):
                parts.append(f"pgs={grade}")
            # Pathways hiring paths bring in college-student programs.
            parts.append("hp=student")
            parts.append("hp=graduates")

        url = "https://www.usajobs.gov/Search/Results?" + "&".join(parts)

        try:
            webbrowser.open_new_tab(url)
            opened = True
        except Exception:
            opened = False

        # Build a human-readable summary so the model can explain the search
        # to the user without parsing the URL itself.
        applied_filters = []
        if series_codes:
            applied_filters.append(f"Series {', '.join(series_codes)}")
        if entry_level:
            applied_filters.append("GS-04 to GS-07")
            applied_filters.append("Students/Recent Graduates")
        if location:
            applied_filters.append(f"within 25 mi of {location}")

        return {
            "ok": True,
            "mode": "browser_handoff",
            "source": "usajobs.gov",
            "raw_query": raw_query,
            "query_sent": query,
            "series_codes": series_codes,
            "entry_level": entry_level,
            "location": location or "(anywhere)",
            "filters_applied": applied_filters,
            "url": url,
            "opened_in_browser": opened,
            "note": (
                "USAJOBS search opened in your default browser. The URL is "
                "pre-filtered by OPM series code"
                + (f" ({', '.join(series_codes)})" if series_codes else "")
                + ". Cert names were stripped from the keyword field — federal "
                "postings index by series code, not by cert. For structured "
                "JSON results in-app, set USAJOBS_API_KEY + USAJOBS_API_EMAIL "
                "env vars (free key at https://developer.usajobs.gov/APIRequest)."
            ),
            "your_certs": user_certs,  # shown to user, not used in query
        }

    # ----- resume match (shared shape with IndeedApplyTool) -----

    def _refresh_resume(self) -> None:
        if self.embedder is None or self._resume_getter is None:
            return
        try:
            text = self._resume_getter()
        except Exception:
            text = None
        if text == self._cached_resume_text:
            return
        self._cached_resume_text = text
        if text:
            try:
                self._cached_resume_vector = self.embedder.embed_query(text[:4000])
            except Exception:
                self._cached_resume_vector = None
        else:
            self._cached_resume_vector = None

    def _match_percent(self, job_text: str) -> int | None:
        if not job_text or self._cached_resume_vector is None or self.embedder is None:
            return None
        try:
            import numpy as np
            v = self.embedder.embed_query(job_text[:4000])
            a = np.asarray(self._cached_resume_vector).flatten()
            b = np.asarray(v).flatten()
            denom = (np.linalg.norm(a) * np.linalg.norm(b)) or 1.0
            sim = float(np.dot(a, b) / denom)
            return max(0, min(100, int(round((sim - 0.2) / 0.65 * 100))))
        except Exception:
            return None
