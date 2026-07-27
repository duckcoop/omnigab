"""Job sources: one uniform interface over several very different boards.

Why a registry instead of one scraper per board
-----------------------------------------------
Job boards fall into three groups, and pretending otherwise leads to
fragile code and, in a couple of cases, a banned account:

  API      The board publishes a documented, public JSON endpoint. These
           are stable, fast, and allowed. USAJOBS, Amazon Jobs, Greenhouse,
           Lever and RemoteOK all live here.

  SCRAPE   No API, but automation is tolerated. Needs a real browser and
           breaks whenever the markup changes. Indeed is here, and it
           throws Cloudflare challenges regularly.

  HANDOFF  Automation is actively prohibited and detected. We do not
           scrape these. Instead we build the search URL the user would
           have typed and open it in their own logged-in browser. They
           get the results; their account stays safe.

Each source declares its `access` so the UI can be honest about what it
is doing, and so nobody later assumes a HANDOFF source returns listings.

All sources normalize to the same posting dict, which is the shape
`core/job_renderer.py` already renders. Adding a board should not require
touching the display layer.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

USER_AGENT = "omnigab/1.0 (local job search; +https://github.com/duckcoop/omnigab)"
TIMEOUT_S = 15

API = "api"
SCRAPE = "scrape"
HANDOFF = "handoff"


def _get_json(url: str) -> Any:
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    })
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def posting(title: str, company: str, url: str, location: str = "",
            salary: str = "", summary: str = "", source: str = "") -> dict:
    """Normalized posting. Keys match what job_renderer expects."""
    return {
        "title": (title or "").strip(),
        "agency": (company or "").strip(),
        "location": (location or "").strip(),
        "salary": (salary or "").strip(),
        "summary": (summary or "").strip()[:280],
        "url": (url or "").strip(),
        "source": source,
        "match_percent": None,
        "cert_matches": [],
    }


@dataclass
class JobSource:
    """Base class. Subclasses implement `search` or `handoff_url`."""

    key: str = ""
    label: str = ""
    access: str = API
    note: str = ""
    enabled: bool = True
    # Set on HANDOFF sources to explain why we do not automate them.
    handoff_reason: str = ""

    def search(self, query: str, location: str = "",
               limit: int = 10) -> list[dict]:
        raise NotImplementedError

    def handoff_url(self, query: str, location: str = "") -> str:
        raise NotImplementedError

    def describe(self) -> dict:
        return {
            "key": self.key,
            "label": self.label,
            "access": self.access,
            "note": self.note,
            "enabled": self.enabled,
            "handoff_reason": self.handoff_reason,
        }


# --------------------------------------------------------------- API sources

@dataclass
class AmazonJobs(JobSource):
    key: str = "amazon"
    label: str = "Amazon Jobs"
    access: str = API
    note: str = "Public search endpoint on amazon.jobs."

    def search(self, query, location="", limit=10):
        params = {
            "base_query": query or "",
            "result_limit": max(1, min(int(limit or 10), 50)),
            "sort": "recent",
        }
        if location:
            params["loc_query"] = location
        url = "https://www.amazon.jobs/en/search.json?" + urllib.parse.urlencode(params)
        data = _get_json(url)
        out = []
        for j in (data.get("jobs") or [])[:limit]:
            path = j.get("job_path") or ""
            out.append(posting(
                title=j.get("title", ""),
                company="Amazon",
                location=j.get("location", ""),
                summary=j.get("description_short") or j.get("basic_qualifications", ""),
                url=f"https://www.amazon.jobs{path}" if path else "",
                source=self.key,
            ))
        return out


@dataclass
class GreenhouseBoard(JobSource):
    """Greenhouse hosts boards for thousands of companies.

    `company` is the board token in the URL, e.g. `stripe` for
    boards.greenhouse.io/stripe. Filtering is client side because the
    public endpoint returns the whole board at once.
    """

    key: str = "greenhouse"
    label: str = "Greenhouse board"
    access: str = API
    note: str = "Public board API. Requires a company board token."
    company: str = ""

    def search(self, query, location="", limit=10):
        if not self.company:
            return []
        url = (f"https://boards-api.greenhouse.io/v1/boards/"
               f"{urllib.parse.quote(self.company)}/jobs")
        data = _get_json(url)
        needle = (query or "").lower().strip()
        loc_needle = (location or "").lower().strip()
        out = []
        for j in data.get("jobs") or []:
            title = j.get("title", "")
            loc = ((j.get("location") or {}) or {}).get("name", "")
            if needle and needle not in title.lower():
                continue
            if loc_needle and loc_needle not in loc.lower():
                continue
            out.append(posting(
                title=title, company=self.company.title(), location=loc,
                url=j.get("absolute_url", ""), source=self.key,
            ))
            if len(out) >= limit:
                break
        return out


@dataclass
class LeverBoard(JobSource):
    key: str = "lever"
    label: str = "Lever board"
    access: str = API
    note: str = "Public postings API. Requires a company token."
    company: str = ""

    def search(self, query, location="", limit=10):
        if not self.company:
            return []
        url = (f"https://api.lever.co/v0/postings/"
               f"{urllib.parse.quote(self.company)}?mode=json")
        data = _get_json(url)
        needle = (query or "").lower().strip()
        out = []
        for j in data or []:
            title = j.get("text", "")
            cats = j.get("categories") or {}
            loc = cats.get("location", "")
            if needle and needle not in title.lower():
                continue
            if location and location.lower() not in str(loc).lower():
                continue
            out.append(posting(
                title=title, company=self.company.title(), location=loc,
                url=j.get("hostedUrl", ""), source=self.key,
            ))
            if len(out) >= limit:
                break
        return out


@dataclass
class RemoteOK(JobSource):
    key: str = "remoteok"
    label: str = "RemoteOK"
    access: str = API
    note: str = "Public JSON feed of remote roles."

    def search(self, query, location="", limit=10):
        data = _get_json("https://remoteok.com/api")
        needle = (query or "").lower().strip()
        out = []
        # First element is a legal/metadata notice, not a posting.
        for j in (data or [])[1:]:
            title = j.get("position") or j.get("title") or ""
            tags = " ".join(j.get("tags") or [])
            if needle and needle not in f"{title} {tags}".lower():
                continue
            out.append(posting(
                title=title,
                company=j.get("company", ""),
                location=j.get("location") or "Remote",
                salary=self._salary(j),
                url=j.get("url", ""),
                summary=j.get("description", ""),
                source=self.key,
            ))
            if len(out) >= limit:
                break
        return out

    @staticmethod
    def _salary(j: dict) -> str:
        lo, hi = j.get("salary_min"), j.get("salary_max")
        if lo and hi:
            return f"${int(lo):,} - ${int(hi):,}"
        return ""


# ----------------------------------------------------------- HANDOFF sources

@dataclass
class BrowserHandoff(JobSource):
    """Builds the search URL and lets the user's own browser do the work.

    This is not a fallback or a limitation. For boards that prohibit
    automation, it is the correct design: the user is already logged in,
    sees the real site, and never risks their account. omnigab's job is to
    save them the typing.
    """

    access: str = HANDOFF
    url_template: str = ""

    def handoff_url(self, query, location=""):
        return self.url_template.format(
            q=urllib.parse.quote_plus(query or ""),
            loc=urllib.parse.quote_plus(location or ""),
        )

    def search(self, query, location="", limit=10):
        # Deliberately returns nothing. Callers check `access` first.
        return []


LINKEDIN = BrowserHandoff(
    key="linkedin", label="LinkedIn",
    note="Opens a prefilled LinkedIn search in your browser.",
    handoff_reason=(
        "LinkedIn's terms prohibit automated access and they enforce it "
        "with account restrictions. Opening the search in your own "
        "logged-in browser gets the same results with no risk to your "
        "account."),
    url_template=("https://www.linkedin.com/jobs/search/"
                  "?keywords={q}&location={loc}"),
)

HANDSHAKE = BrowserHandoff(
    key="handshake", label="Handshake",
    note="Opens a prefilled Handshake search in your browser.",
    handoff_reason=(
        "Handshake requires a school single sign-on session, which cannot "
        "be automated safely or reliably. Your browser already has it."),
    url_template="https://app.joinhandshake.com/job-search/?query={q}",
)

INDEED_HANDOFF = BrowserHandoff(
    key="indeed_web", label="Indeed (browser)",
    note="Opens a prefilled Indeed search in your browser.",
    handoff_reason=(
        "Indeed serves Cloudflare challenges to automated traffic. The "
        "built-in Indeed tool still exists for Easy Apply, but plain "
        "searching is faster and more reliable in your own browser."),
    url_template="https://www.indeed.com/jobs?q={q}&l={loc}",
)


# ------------------------------------------------------------------ registry

def default_registry() -> dict[str, JobSource]:
    """Sources available out of the box.

    Greenhouse and Lever are omitted here because they need a company
    token; construct them directly when you know the company.
    """
    sources = [
        AmazonJobs(),
        RemoteOK(),
        LINKEDIN,
        HANDSHAKE,
        INDEED_HANDOFF,
    ]
    return {s.key: s for s in sources}


def search_many(sources: list[JobSource], query: str, location: str = "",
                limit_each: int = 10) -> dict:
    """Query every API source, collect handoff links for the rest.

    One source failing never fails the whole search: boards go down, and a
    partial result with an honest error list beats an exception.
    """
    results: list[dict] = []
    handoffs: list[dict] = []
    errors: list[dict] = []

    for src in sources:
        if not src.enabled:
            continue
        if src.access == HANDOFF:
            handoffs.append({
                "source": src.key,
                "label": src.label,
                "url": src.handoff_url(query, location),
                "reason": src.handoff_reason,
            })
            continue
        try:
            results.extend(src.search(query, location, limit_each))
        except Exception as exc:
            errors.append({"source": src.key,
                           "error": f"{type(exc).__name__}: {exc}"})

    return {
        "ok": True,
        "query": query,
        "location": location or "(anywhere)",
        "found": len(results),
        "results": results,
        "handoffs": handoffs,
        "errors": errors,
    }
