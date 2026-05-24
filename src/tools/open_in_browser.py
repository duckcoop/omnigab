"""Open a URL in the user's real default browser.

The nuclear-option fallback when Indeed/LinkedIn Cloudflare blocks the
automated scraper. The user's normal Chrome/Edge/Firefox has the right
cookies, the right TLS fingerprint, and is genuinely controlled by a
human — so no captcha fires. Trade-off: the tool doesn't get to read
the page contents, but the user can browse the results manually.
"""

from __future__ import annotations

import webbrowser
from typing import Any
from urllib.parse import quote_plus, urlparse


# Predefined templates the agent can use without spelling out URLs.
QUICK_LINKS = {
    "indeed": "https://www.indeed.com/jobs?q={q}&l={l}&fromage={days}&sort=date",
    "linkedin": "https://www.linkedin.com/jobs/search/?keywords={q}&location={l}&f_TPR=r{days_s}",
    "ziprecruiter": "https://www.ziprecruiter.com/jobs-search?search={q}&location={l}",
    "usajobs": "https://www.usajobs.gov/Search/Results?k={q}&l={l}&dap={days}",
    "glassdoor": "https://www.glassdoor.com/Job/jobs.htm?sc.keyword={q}&locT=C&locKeyword={l}",
}


class OpenInBrowserTool:
    name = "open_in_browser"
    description = (
        "Open a URL in the user's normal browser (bypasses Cloudflare since "
        "it's a real human browser, not automated). Use this when a scraping "
        "tool returns a captcha error, OR when the user explicitly asks to "
        "'open' a site, OR for sites the agent has no scraper for. Pass either "
        "a full `url`, or pick a template via `site` (one of: indeed, linkedin, "
        "ziprecruiter, usajobs, glassdoor) plus `query`/`location`."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Full URL to open. Mutually exclusive with `site`."},
            "site": {"type": "string",
                     "enum": list(QUICK_LINKS.keys()),
                     "description": "Pre-built search template. Use with `query` + optional `location`."},
            "query": {"type": "string", "description": "Search keywords (when `site` is given)."},
            "location": {"type": "string", "description": "Location filter (when `site` is given)."},
            "days_ago": {"type": "integer", "default": 14,
                         "description": "Recency filter (Indeed/USAJOBS)."},
        },
        "required": [],
    }

    def run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        url = (arguments.get("url") or "").strip()
        site = (arguments.get("site") or "").lower().strip()

        if not url and site in QUICK_LINKS:
            q = quote_plus(arguments.get("query") or "")
            loc = quote_plus(arguments.get("location") or "")
            try:
                days = max(1, min(60, int(arguments.get("days_ago") or 14)))
            except (TypeError, ValueError):
                days = 14
            # LinkedIn uses r2592000 for 30d, r604800 for 7d (seconds).
            days_s = str(days * 86400)
            template = QUICK_LINKS[site]
            url = template.format(q=q, l=loc, days=days, days_s=days_s)

        if not url:
            return {"ok": False, "error": "Provide `url` or (`site` + `query`)."}

        # Basic safety: only allow http/https schemes.
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return {"ok": False, "error": "Only http/https URLs allowed."}

        try:
            opened = webbrowser.open_new_tab(url)
        except Exception as exc:
            return {"ok": False, "error": f"Could not open browser: {exc}"}

        return {
            "ok": True,
            "opened": opened,
            "url": url,
            "note": "URL opened in user's default browser. The agent cannot see "
                    "the page contents — the user is now browsing manually.",
        }
