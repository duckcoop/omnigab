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
import sys
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup


def _log(msg: str) -> None:
    """Verbose logger. Goes to stdout (which the desktop_app captures and
    leaves in the launching terminal). Single source so the [usajobs] prefix
    + timestamp format stays uniform.
    """
    stamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    print(f"[usajobs] {stamp} {msg}", file=sys.stdout, flush=True)


# Plain-browser UA for detail-page requests. USAJOBS does NOT block
# scrapers, but it does return a different (lighter) layout for obvious
# bot UA strings, so we pretend to be a regular Chrome.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36"
)


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


# Common short-form / abbreviated location strings the LLM tends to emit
# (often truncated mid-word, e.g. "Wash" for "Washington"). Map them to
# canonical "City, ST" so USAJOBS can actually find matches. Anything not
# in this table and shorter than 3 chars after stripping is dropped.
_LOCATION_ALIASES = {
    "dc":        "Washington, DC",
    "d.c":       "Washington, DC",
    "d.c.":      "Washington, DC",
    "washington dc": "Washington, DC",
    "washington d.c.": "Washington, DC",
    "washington d.c": "Washington, DC",
    "washington": "Washington, DC",
    "wash":      "",                      # truncated, drop
    "nyc":       "New York, NY",
    "new york":  "New York, NY",
    "la":        "Los Angeles, CA",
    "sf":        "San Francisco, CA",
    "chi":       "Chicago, IL",
    "boston":    "Boston, MA",
    "philly":    "Philadelphia, PA",
    "atl":       "Atlanta, GA",
    "dallas":    "Dallas, TX",
    "houston":   "Houston, TX",
    "denver":    "Denver, CO",
    "seattle":   "Seattle, WA",
    "miami":     "Miami, FL",
    # State-only inputs the model might emit
    "maryland":  "Maryland",
    "virginia":  "Virginia",
    "md":        "Maryland",
    "va":        "Virginia",
}


def _normalize_location(loc: str) -> str:
    """Expand common short forms / catch truncations. Returns the
    canonical "City, ST" / "State" form, or "" if the input is so
    truncated it can't be reasonably interpreted (in which case the
    caller should search without a location filter).
    """
    if not loc:
        return ""
    key = loc.strip().rstrip(",.").lower()
    if key in _LOCATION_ALIASES:
        return _LOCATION_ALIASES[key]
    # If it already looks like a real "City, ST" or contains a comma + 2
    # letters, leave it alone.
    if "," in loc and len(loc.strip()) >= 4:
        return loc.strip()
    # Single token, 3+ chars, not a known short form — pass through. The
    # USAJOBS search will either match (city name) or return zero results
    # (in which case our caller retries without location).
    if len(key) >= 3:
        return loc.strip()
    # Anything else is too short to be meaningful (e.g. "Wash", "NY ", "C").
    return ""


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
        raw_location = str(arguments.get("location") or "").strip()
        # Normalize short/truncated location strings ("DC" -> "Washington, DC",
        # "Wash" -> dropped, etc.) so USAJOBS gets a string it can actually
        # match on. See _normalize_location().
        location = _normalize_location(raw_location)
        if raw_location and not location:
            _log(f"  [run] dropping unparseable location {raw_location!r}")
        elif location != raw_location:
            _log(f"  [run] normalized location {raw_location!r} -> {location!r}")
        try:
            # Raised cap (was 25) so callers can request the full 50-listing
            # batch the evaluator now expects.
            max_jobs = max(1, min(75, int(arguments.get("max_jobs") or 10)))
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

        # ---- AI-focus overrides + query expansion ----
        # When the user is hunting for AI/ML roles, the entry-level filter
        # would hide GS-12+ AI specialist postings (which is most of them).
        # We:
        #   * widen the keyword to "Artificial Intelligence" so USAJOBS
        #     surfaces postings tagged with "(AI)" / "(AIML)" / "(ML)";
        #   * force-include both 2210 (IT) and 1550 (CS) series;
        #   * disable entry_level so we don't filter the actual roles out;
        #   * downstream we boost titles with the (AI)/(AIML) parenthetical.
        #
        # Multi-query expansion: USAJOBS keyword search is narrow. To find a
        # comprehensive set of AI/ML roles we run 3 internal queries and
        # merge the results dedup'd by URL. Same trick for plain IT searches
        # (Cybersecurity + IT Specialist + Network Administrator).
        queries_to_run: list[str] = []
        if ai_focus:
            queries_to_run = [
                "Artificial Intelligence",
                "Machine Learning",
                "Data Scientist",
            ]
            if "2210" not in series_codes:
                series_codes.insert(0, "2210")
            if "1550" not in series_codes:
                series_codes.append("1550")
            entry_level = False
        else:
            # Single-query mode is the default; the caller's keyword wins.
            queries_to_run = [clean_query]

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

        # ---- Multi-query merge ----
        # Run each query variant through the Playwright scrape. Allocate
        # per-query max so the total stays roughly at max_jobs after dedup.
        per_query_cap = max(10, (max_jobs // len(queries_to_run)) + 5)
        merged: list[dict] = []
        seen_urls: set[str] = set()
        per_query_meta: list[dict] = []
        first_url = ""
        total_seen_text = ""

        _log(f"MULTI-QUERY plan: {queries_to_run} (per-query cap={per_query_cap}, "
             f"target merged max_jobs={max_jobs})")

        for q in queries_to_run:
            try:
                partial = self._run_via_playwright(
                    q, location, per_query_cap, days_ago, entry_level,
                    series_codes, user_certs, raw_query, ai_focus=ai_focus,
                )
            except Exception as exc:
                _log(f"[multi-query] '{q}' FAILED: {exc!r}")
                per_query_meta.append({"query": q, "ok": False, "error": str(exc)})
                continue

            if not first_url:
                first_url = partial.get("url", "")
                total_seen_text = partial.get("total_available", "")

            new_count = 0
            for job in partial.get("results", []):
                url = job.get("url", "")
                if not url or url in seen_urls:
                    continue
                seen_urls.add(url)
                merged.append(job)
                new_count += 1
                if len(merged) >= max_jobs:
                    break

            per_query_meta.append({
                "query": q,
                "ok": True,
                "scraped": partial.get("found", 0),
                "new_unique": new_count,
            })
            _log(f"[multi-query] '{q}' contributed {new_count} new (total now {len(merged)})")
            if len(merged) >= max_jobs:
                break

        # ---- Sparse-result fallback: retry without the location filter ----
        # If we had a location filter applied and ended up with very few
        # results (less than a third of what was asked for), the location
        # is probably too narrow OR the model passed a truncated string.
        # Re-run the queries without location and merge in the extras.
        sparse_threshold = max(3, max_jobs // 3)
        if location and len(merged) < sparse_threshold:
            _log(f"[multi-query] sparse ({len(merged)} < {sparse_threshold}) "
                 f"with location={location!r}; retrying nationwide")
            for q in queries_to_run:
                if len(merged) >= max_jobs:
                    break
                try:
                    partial = self._run_via_playwright(
                        q, "", per_query_cap, days_ago, entry_level,
                        series_codes, user_certs, raw_query, ai_focus=ai_focus,
                    )
                except Exception as exc:
                    _log(f"[multi-query] retry '{q}' FAILED: {exc!r}")
                    continue
                new_count = 0
                for job in partial.get("results", []):
                    url = job.get("url", "")
                    if not url or url in seen_urls:
                        continue
                    seen_urls.add(url)
                    job["fallback_no_location"] = True
                    merged.append(job)
                    new_count += 1
                    if len(merged) >= max_jobs:
                        break
                _log(f"[multi-query] retry '{q}' contributed {new_count} new "
                     f"(nationwide; total now {len(merged)})")

        # If multi-query was just one query and we have no merge fallbacks
        # to honor, hand back the direct return so the rich diagnostic
        # fields (dead_links_discarded etc.) survive.
        if len(queries_to_run) == 1 and len(merged) == 0:
            try:
                return self._run_via_playwright(
                    queries_to_run[0], location, max_jobs, days_ago, entry_level,
                    series_codes, user_certs, raw_query, ai_focus=ai_focus,
                )
            except Exception as exc:
                _log(f"[usajobs_search] Playwright failed: {exc}. Browser handoff.")
                return self._run_via_browser_handoff(
                    clean_query, location, days_ago, entry_level,
                    series_codes, user_certs, raw_query, ai_focus=ai_focus,
                )

        return {
            "ok": True,
            "mode": "playwright_scrape_multi",
            "source": "usajobs.gov",
            "raw_query": raw_query,
            "queries_run": queries_to_run,
            "per_query": per_query_meta,
            "series_codes": series_codes,
            "entry_level": entry_level,
            "ai_focus": ai_focus,
            "location": location or "(anywhere)",
            "url": first_url,
            "total_available": total_seen_text,
            "found": len(merged),
            "results": merged,
        }

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
                   entry_level: bool, series_codes: list[str],
                   page_num: int = 1) -> str:
        """Compose the USAJOBS search URL exactly the way the website does."""
        parts = [
            f"k={quote_plus(query)}",
            f"l={quote_plus(location)}",
            f"dap={days_ago}",
            f"p={page_num}",
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
        """Scrape USAJOBS, then deep-fetch each result's full description and
        STRICTLY enforce series codes by walking additional pages if results
        are filtered out.

        Two-stage pipeline:
          STAGE A (Playwright, sync, ONE search page only):
            Walk through up to MAX_PAGES_TO_SCAN result pages to collect
            stub cards (title + URL + visible metadata).
          STAGE B (requests + ThreadPoolExecutor):
            Deep-fetch each stub's detail URL IN PARALLEL. USAJOBS detail
            pages are server-rendered, so we don't need a browser for them.
            Each fetch has a 12s timeout. Failures skip and are logged.
        """
        from playwright.sync_api import sync_playwright

        # Pagination + budgets. Tuned so that with max_jobs=50 the tool
        # can walk through enough search pages to gather ~100 stubs, fetch
        # each detail page in parallel (10–15 workers), and still finish
        # inside the wider OVERALL_BUDGET_S window. The desktop client's
        # stream timeout is already 600s, so we have plenty of headroom.
        MAX_PAGES_TO_SCAN = 8       # was 4 — needed to reach 50 keepers
        FETCH_TIMEOUT_S = 15        # was 12
        FETCH_WORKERS = 15          # was 10
        OVERALL_BUDGET_S = 240      # was 90

        first_page_url = self._build_url(query, location, days_ago, entry_level,
                                          series_codes, page_num=1)
        series_set = {str(c) for c in (series_codes or [])}
        stubs: list[dict] = []
        scanned_cards = 0
        count_text = ""
        t_overall = time.monotonic()

        _log(f"START search: query={query!r} location={location!r} "
             f"max_jobs={max_jobs} entry_level={entry_level} "
             f"series_codes={series_codes} ai_focus={ai_focus}")

        # ---------- STAGE A: collect stub cards via Playwright ----------
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                ctx = browser.new_context(viewport={"width": 1366, "height": 900})
                search_page = ctx.new_page()

                # Target ~2x max_jobs stubs so we have a buffer for series filtering.
                # Aim for ~2x the requested count so we have a buffer for
                # series-filter drops. Floored at 30 so a tiny max_jobs
                # still scans broadly enough to find quality matches.
                target_stubs = max(max_jobs * 2, 30)

                for page_num in range(1, MAX_PAGES_TO_SCAN + 1):
                    if len(stubs) >= target_stubs:
                        break
                    if (time.monotonic() - t_overall) > OVERALL_BUDGET_S * 0.5:
                        _log(f"  [stage A] budget threshold hit; stopping pagination")
                        break

                    page_url = self._build_url(query, location, days_ago,
                                                entry_level, series_codes,
                                                page_num=page_num)
                    t0 = time.monotonic()
                    try:
                        # `domcontentloaded` is enough — we just need the
                        # Angular shell to mount. We can't reliably wait for
                        # networkidle because USAJOBS keeps polling analytics
                        # endpoints indefinitely.
                        search_page.goto(page_url, wait_until="domcontentloaded",
                                          timeout=20000)
                        # Wait specifically for the result container to appear.
                        try:
                            search_page.wait_for_selector(
                                "#search-results .bg-white.p-4",
                                timeout=10000,
                            )
                        except Exception:
                            pass
                        search_page.wait_for_timeout(500)
                    except Exception as exc:
                        _log(f"  [stage A] page {page_num} navigation failed: {exc}")
                        break

                    elapsed = time.monotonic() - t0
                    cards = search_page.locator(
                        "#search-results .bg-white.p-4").all()
                    _log(f"  [stage A] page {page_num} loaded in {elapsed:.1f}s, "
                         f"{len(cards)} cards")
                    if not cards:
                        # Search exhausted — no point fetching page+1.
                        break

                    # USAJOBS default page size is 25. If page 1 returned
                    # fewer than that, we already have the entire result set
                    # and walking to page 2 would just waste 6-10 seconds
                    # waiting for an empty page.
                    if page_num == 1 and len(cards) < 25:
                        for card in cards:
                            if len(stubs) >= target_stubs:
                                break
                            scanned_cards += 1
                            try:
                                s = self._extract_card(card)
                            except Exception:
                                continue
                            if s.get("url"):
                                stubs.append(s)
                        _log(f"  [stage A] page 1 incomplete page "
                             f"({len(cards)} < 25) — search exhausted, "
                             f"skipping further pages")
                        break

                    if page_num == 1:
                        try:
                            count_text = search_page.locator(
                                "text=/\\d+\\s*–\\s*\\d+\\s*of\\s*[\\d,]+/"
                            ).first.inner_text(timeout=2000)
                        except Exception:
                            count_text = ""

                    if not cards:
                        break

                    for card in cards:
                        if len(stubs) >= target_stubs:
                            break
                        scanned_cards += 1
                        try:
                            stub = self._extract_card(card)
                        except Exception:
                            continue
                        if not stub.get("url"):
                            continue
                        stubs.append(stub)
            finally:
                browser.close()

        _log(f"[stage A] DONE. Scanned {scanned_cards} cards, "
             f"collected {len(stubs)} stubs in "
             f"{time.monotonic() - t_overall:.1f}s")

        # ---------- STAGE B: parallel deep-fetch via requests ----------
        keepers: list[dict] = []
        dropped_series: list[str] = []
        fetch_failures: list[str] = []

        def fetch_one(stub):
            """Verify the URL resolves (no 404, no timeout), parse the
            page, and classify the listing's application status.

            Return tuple: (status_str, payload_dict, error_or_none)
              status_str ∈ {"ok", "closed", "dead_link", "fail"}
                * ok        — page loaded, posting accepting applications
                * closed    — page loaded but no longer accepting
                * dead_link — HTTP 4xx/5xx; URL discarded entirely
                * fail      — network/timeout; stub kept for graceful display
            """
            url = stub.get("url") or ""
            if not url:
                return ("fail", stub, "no url")
            t0 = time.monotonic()
            try:
                resp = requests.get(
                    url,
                    headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
                    timeout=FETCH_TIMEOUT_S,
                    allow_redirects=True,
                )
                # Explicit URL verification — any non-2xx is a dead link
                # and the listing is dropped entirely (the agent never sees
                # the URL, preventing it from hallucinating an "Apply" link
                # that returns 404).
                if resp.status_code >= 400:
                    _log(f"  [stage B] FETCH {url} -> HTTP {resp.status_code} "
                         f"DEAD LINK (discarded)")
                    return ("dead_link", stub, f"HTTP {resp.status_code}")
                if resp.status_code != 200:
                    _log(f"  [stage B] FETCH {url} -> HTTP {resp.status_code} "
                         f"(unusual, treating as fail)")
                    return ("fail", stub, f"HTTP {resp.status_code}")

                enriched = self._parse_detail_html(stub, resp.text)
                detail_status = enriched.get("status", "unknown")
                series = enriched.get("series_code", "?")
                dt = time.monotonic() - t0

                if detail_status == "closed":
                    _log(f"  [stage B] FETCH {url[:60]}... -> 200 ({dt:.1f}s) "
                         f"series={series} STATUS=closed (discarded)")
                    return ("closed", enriched, "no longer accepting")

                _log(f"  [stage B] FETCH {url[:60]}... -> 200 ({dt:.1f}s) "
                     f"series={series} status={detail_status}")
                return ("ok", enriched, None)
            except requests.Timeout:
                _log(f"  [stage B] FETCH {url[:60]}... -> TIMEOUT "
                     f"({FETCH_TIMEOUT_S}s)")
                return ("fail", stub, "timeout")
            except Exception as exc:
                _log(f"  [stage B] FETCH {url[:60]}... -> ERROR {exc!r}")
                return ("fail", stub, str(exc))

        _log(f"[stage B] START parallel deep-fetch of {len(stubs)} stubs "
             f"({FETCH_WORKERS} workers, {FETCH_TIMEOUT_S}s each)")
        t_fetch = time.monotonic()

        dead_links: list[str] = []
        closed_dropped: list[str] = []

        with ThreadPoolExecutor(max_workers=FETCH_WORKERS) as pool:
            futures = {pool.submit(fetch_one, s): s for s in stubs}
            for fut in as_completed(futures, timeout=OVERALL_BUDGET_S):
                try:
                    result = fut.result()
                except Exception as exc:
                    _log(f"  [stage B] worker exception: {exc!r}")
                    continue
                if result is None:
                    continue
                status, payload, err = result

                if status == "dead_link":
                    # 404/500 — drop entirely. We don't pass this URL on
                    # because the model must never present a link the user
                    # would click and find broken.
                    dead_links.append(payload.get("url", ""))
                    continue

                if status == "closed":
                    # Posting page exists but no longer accepting.
                    closed_dropped.append(payload.get("title", ""))
                    continue

                if status == "fail":
                    fetch_failures.append(err or "unknown")
                    # Keep the stub so model still gets title + url for
                    # display, BUT only if we couldn't verify it. If we
                    # have a strict series filter, drop fails (we can't
                    # confirm series so we can't honor the strict filter).
                    if not series_set:
                        keepers.append(payload)
                    continue

                # status == "ok" — verified URL, page loaded, posting open.
                sc = payload.get("series_code")
                if series_set and sc and sc not in series_set:
                    dropped_series.append(sc)
                    continue
                keepers.append(payload)

        _log(f"[stage B] DONE in {time.monotonic() - t_fetch:.1f}s. "
             f"{len(keepers)} verified open keepers, "
             f"{len(closed_dropped)} closed (dropped), "
             f"{len(dead_links)} dead links (dropped), "
             f"{len(fetch_failures)} network failures, "
             f"{len(dropped_series)} dropped off-series")

        # ---------- STAGE C: scoring + ranking ----------
        _log(f"[stage C] EVAL: scoring {len(keepers)} results against resume")
        t_eval = time.monotonic()
        self._refresh_resume()
        resume_loaded = self._cached_resume_vector is not None
        if not resume_loaded:
            _log(f"  [stage C] WARNING: no resume vector loaded — "
                 f"match_percent will be null for every result. "
                 f"Drop a resume into data/docs/active_resume.* to enable scoring.")
        for job in keepers:
            text_blob = "\n".join(filter(None, [
                job.get("title", ""), job.get("agency", ""),
                job.get("location", ""), job.get("summary", ""),
                job.get("description", ""), job.get("qualifications", ""),
            ]))
            pct = self._match_percent(text_blob)
            # Always write the field — None signals "no resume" to the
            # model so it writes "Match: n/a" rather than skipping the line.
            job["match_percent"] = pct
            _log(f"  [stage C] {job.get('title', '?')[:50]} -> "
                 f"match_percent={pct}")
            if user_certs:
                from tools.resume_intel import cert_matches
                matched = cert_matches(user_certs, text_blob)
                if matched:
                    job["cert_matches"] = matched

            # JOB-side cert + clearance extraction (independent of user).
            from tools.resume_intel import (
                extract_required_certs, extract_clearance, skills_gap,
            )
            required = extract_required_certs(text_blob)
            if required:
                job["required_certs"] = required
            clr = extract_clearance(text_blob)
            if clr:
                job["clearance_required"] = clr

            # Skills gap analyzer: required - have.
            # Only meaningful when we have the user's resume text + certs.
            resume_text = self._cached_resume_text or ""
            if resume_text or user_certs:
                gap = skills_gap(
                    job_text=text_blob,
                    resume_text=resume_text,
                    resume_certs=user_certs,
                )
                # Drop empty fields so the model isn't distracted.
                if gap["missing_certs"]:
                    job["missing_certs"] = gap["missing_certs"]
                if gap["missing_skills"]:
                    job["missing_skills"] = gap["missing_skills"]
                if gap["missing_clearance"]:
                    job["missing_clearance"] = gap["missing_clearance"]
        _log(f"[stage C] DONE eval in {time.monotonic() - t_eval:.2f}s")

        # AI-designated tag.
        ai_marker_count = 0
        for job in keepers:
            if _AI_TITLE_RE.search(job.get("title", "") or ""):
                job["ai_designated"] = True
                ai_marker_count += 1

        # Rank:
        #   1. AI-focus mode bumps (AI)/(AIML)/(ML) titles to the top.
        #   2. More cert matches first.
        #   3. Higher resume-match-percent first.
        #   4. Salary-bearing postings above silent ones.
        def sort_key(j):
            ai_bonus = 0 if (ai_focus and j.get("ai_designated")) else 1
            return (
                ai_bonus,
                -len(j.get("cert_matches", [])),
                -(j.get("match_percent") or 0),
                0 if j.get("salary") else 1,
            )
        keepers.sort(key=sort_key)
        keepers = keepers[:max_jobs]

        # ---- Slim model-facing results ----
        # The full `description` (~8 KB) and `qualifications` (~4 KB) per
        # job were used internally for resume-match scoring and cert
        # detection. The model itself only needs to PRESENT the job, so
        # we strip those before returning. Without this slim step a
        # 13-job batch is ~150 KB of JSON, which truncates mid-record
        # inside the agent's observation buffer and causes the model to
        # template-collapse (every job renders with the first job's
        # title and URL because the rest of the JSON is unreadable).
        slim_results = []
        for j in keepers:
            slim_results.append({
                "title": j.get("title", ""),
                "agency": j.get("agency", ""),
                "sub_agency": j.get("sub_agency", ""),
                "location": j.get("location", ""),
                "salary": j.get("salary", ""),
                "grade": j.get("grade", ""),
                "series_code": j.get("series_code", ""),
                "status": j.get("status", "unknown"),
                "summary": (j.get("summary") or j.get("description", ""))[:280],
                "match_percent": j.get("match_percent"),
                "cert_matches": j.get("cert_matches"),
                # Job-side fields: what the posting REQUIRES, independent
                # of what the user has. Model uses these to highlight gaps.
                "required_certs": j.get("required_certs"),
                "clearance_required": j.get("clearance_required"),
                # Skills-gap analyzer output (what user is missing).
                "missing_certs": j.get("missing_certs"),
                "missing_skills": j.get("missing_skills"),
                "missing_clearance": j.get("missing_clearance"),
                "ai_designated": j.get("ai_designated"),
                "url": j.get("url", ""),
            })

        return {
            "ok": True,
            "mode": "playwright_scrape",
            "source": "usajobs.gov",
            "raw_query": raw_query,
            "query_sent": query,
            "series_codes": series_codes,
            "series_enforced": bool(series_set),
            "entry_level": entry_level,
            "ai_focus": ai_focus,
            "ai_designated_count": ai_marker_count,
            "scanned_cards": scanned_cards,
            "dropped_off_series": dropped_series,
            "dead_links_discarded": dead_links,
            "closed_listings_discarded": closed_dropped,
            "network_failures": fetch_failures,
            "verification": "All returned URLs returned HTTP 200 and reported "
                            "status='open' on the live USAJOBS page.",
            "location": location or "(anywhere)",
            "url": first_page_url,
            "total_available": count_text,
            "found": len(slim_results),
            "results": slim_results,
            "ranking": ("ai_designated desc, cert_matches desc, match_percent desc"
                         if ai_focus else "cert_matches desc, match_percent desc"),
        }

    # Phrases that indicate the posting is no longer accepting applications.
    # We check the rendered body text in lowercase.
    _CLOSED_MARKERS = (
        "this job announcement has closed",
        "no longer accepting applications",
        "closed to applications",
        "this announcement is closed",
        "job announcement is closed",
    )

    def _parse_detail_html(self, stub: dict, html: str) -> dict:
        """Parse a server-rendered USAJOBS detail page (HTML string).

        Extracts:
          * series_code     — OPM occupational series (e.g. '2210').
          * status          — 'open' / 'closed' / 'unknown'. Closed listings
                              are filtered out by the caller.
          * description     — Summary + Duties text.
          * qualifications  — full requirements/qualifications text.

        Uses BeautifulSoup so it can run in parallel threads (Playwright
        sync contexts are NOT thread-safe).
        """
        try:
            soup = BeautifulSoup(html, "html.parser")
        except Exception:
            stub["status"] = "unknown"
            return stub

        def text_of(sel: str) -> str:
            try:
                el = soup.select_one(sel)
                if el is None:
                    return ""
                return el.get_text(separator="\n", strip=True)
            except Exception:
                return ""

        # --- Series code --------------------------------------------------
        series_code = ""
        for sel in [
            "dt:-soup-contains('Job series') + dd",
            "dt:-soup-contains('Series') + dd",
        ]:
            try:
                el = soup.select_one(sel)
                if el is not None:
                    m = re.search(r"\b(\d{4})\b", el.get_text(" ", strip=True))
                    if m:
                        series_code = m.group(1)
                        break
            except Exception:
                pass
        if not series_code:
            body_text = soup.get_text(" ", strip=True)
            m = re.search(
                r"(?:Job\s+series|Series)[:\s]+(\d{4})\b",
                body_text, re.IGNORECASE,
            )
            if m:
                series_code = m.group(1)
        if series_code:
            stub["series_code"] = series_code

        # --- Application status -----------------------------------------
        # Three signals, in priority order:
        #   1. Explicit closed markers in the visible body text.
        #   2. A status badge ("Accepting applications" / "Closed").
        #   3. The presence of an Apply button (.apply-button, button:apply).
        body_text_lower = soup.get_text(" ", strip=True).lower()
        status = "unknown"
        if any(m in body_text_lower for m in self._CLOSED_MARKERS):
            status = "closed"
        else:
            badge = soup.select_one(
                ".usajobs-joa-summary__status, "
                ".usajobs-joa-overview__status, "
                "[class*='joa-summary__status']"
            )
            if badge:
                badge_txt = badge.get_text(" ", strip=True).lower()
                if "accepting" in badge_txt or "open" in badge_txt:
                    status = "open"
                elif "closed" in badge_txt or "no longer" in badge_txt:
                    status = "closed"
            if status == "unknown":
                # Fallback: "Accepting applications" pill appears in the
                # Overview sidebar on every active posting.
                if "accepting applications" in body_text_lower:
                    status = "open"
        stub["status"] = status

        # --- Description + qualifications --------------------------------
        summary_txt = text_of("#summary") or text_of("section[aria-labelledby*='summary']")
        duties_txt = text_of("#duties") or text_of("section[aria-labelledby*='duties']")
        quals_txt = (
            text_of("#qualifications")
            or text_of("section[aria-labelledby*='qualifications']")
            or text_of("#requirements")
            or text_of("section[aria-labelledby*='requirements']")
        )

        full_desc = "\n\n".join(p for p in [summary_txt, duties_txt] if p)
        if not full_desc:
            full_desc = text_of("main") or text_of(".usajobs-joa-summary")

        if full_desc:
            stub["description"] = full_desc[:8000]
        if quals_txt:
            stub["qualifications"] = quals_txt[:4000]
        if not stub.get("summary") and summary_txt:
            stub["summary"] = summary_txt[:1500]
        return stub

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

        # --- URL normalization + validation -----------------------------
        # USAJOBS Angular emits relative paths like "/job/123456" or
        # protocol-relative "//www.usajobs.gov/job/...". We prefix the
        # base origin so every URL is fully absolute, then validate the
        # shape (https + usajobs.gov host + /job/<digits>) so malformed
        # references like "#" or "javascript:void(0)" never make it
        # downstream. Anything that fails validation becomes "" and is
        # filtered out before the deep-fetch stage.
        clean_url = self._normalize_jobs_url(href)
        return {
            "title": title,
            "agency": agency,
            "sub_agency": sub_agency,
            "location": location,
            "salary": salary,
            "grade": grade,
            "posted": posted,
            "closing": closing,
            "summary": "",
            "url": clean_url,
        }

    # Strict USAJOBS posting URL pattern: https://www.usajobs.gov/job/<digits>
    # Optional trailing path/query is allowed but the /job/<digits> segment
    # is mandatory. Rejects pretty much everything else.
    _USAJOBS_URL_RE = re.compile(
        r"^https://www\.usajobs\.gov/job/\d+(?:[/?#].*)?$",
        re.IGNORECASE,
    )

    @classmethod
    def _normalize_jobs_url(cls, href: str) -> str:
        """Return an absolute, validated USAJOBS posting URL, or "" if
        the input cannot be turned into a real posting link.
        """
        if not href:
            return ""
        href = href.strip()
        # javascript:, mailto:, fragment-only, etc. → discard.
        low = href.lower()
        if low.startswith(("javascript:", "mailto:", "tel:", "#")):
            return ""
        # Protocol-relative → https.
        if href.startswith("//"):
            href = "https:" + href
        # Root-relative → prefix the canonical origin.
        elif href.startswith("/"):
            href = "https://www.usajobs.gov" + href
        # Bare path with no leading slash, but obviously a path → prefix.
        elif not href.startswith(("http://", "https://")):
            if "/job/" in href or href.lstrip().lower().startswith("job/"):
                href = "https://www.usajobs.gov/" + href.lstrip("/")
            else:
                return ""
        # Force https.
        if href.startswith("http://"):
            href = "https://" + href[len("http://"):]
        # Final shape check.
        if not cls._USAJOBS_URL_RE.match(href):
            return ""
        return href

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
