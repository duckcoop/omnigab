"""Indeed Apply tool — search, scrape, and (optionally) submit Easy Apply.

Design notes
------------
* Built-in tool, NOT a sandboxed skill: Playwright needs full filesystem
  + network + a browser process, all of which the skill sandbox blocks.
* Defaults to safe: stops at the final Submit button and returns the URL
  for human review. Pass `confirm_submit: true` to truly auto-submit.
* Uses a persistent Chromium profile under data/playwright_profile so the
  user's Indeed login survives between runs. The first run will pause
  and ask the user to log in via the browser window.
* Indeed throws Cloudflare challenges and rate-limits aggressively; the
  tool detects challenge pages and returns a structured error rather
  than retrying blindly.

Tool surface
------------
arguments:
  action:    "search" | "apply"
  query:     job title / keyword (defaults provided for IT + USSF Cyber)
  location:  "Remote" / city, state / zip
  max_jobs:  cap on listings to process (default 5)
  confirm_submit: bool — if true, click the final Submit button. Default false.
  headless:  bool — default False so the user sees what's happening.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
PROFILE_DIR = DATA_DIR / "playwright_profile"
RESULTS_DIR = DATA_DIR / "indeed_runs"

# Defaults matching the user's stated targets.
DEFAULT_QUERIES = [
    "entry level IT help desk",
    "entry level IT support",
    "Space Force cyber operations",
    "DoD cyber operations entry level",
]
DEFAULT_LOCATION = "United States"

# Hooks for Cooper's pre-defined screener answers. The skill of the same
# name owns the data; this tool just consumes the values that map to the
# Indeed field names we encounter.
COOPER_SCREENER_DEFAULTS = {
    "years_of_experience": "1",
    "earliest_start": "Immediately",
    "us_citizen": "Yes",
    "security_clearance": "No (eligible)",
    "willing_to_relocate": "Yes",
    "salary_expectation": "55000",
}


class IndeedApplyTool:
    name = "indeed_apply"
    description = (
        "Search Indeed for jobs (default: entry-level IT, Space Force Cyber Ops), "
        "scrape titles/company/location/salary/description, score each one against "
        "the user's resume, and fill out Easy Apply forms. Defaults to stopping "
        "at the Submit button. Returns rich structured data — use the fields "
        "directly, never invent placeholders."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["search", "apply"], "default": "search"},
            "query": {"type": "string", "description": "Job keywords. Multiple comma-separated allowed."},
            "location": {"type": "string", "default": DEFAULT_LOCATION},
            "max_jobs": {"type": "integer", "default": 5, "maximum": 25},
            "confirm_submit": {"type": "boolean", "default": False,
                               "description": "If true, click Submit on Easy Apply. Otherwise stop one step before."},
            "headless": {"type": "boolean", "default": False},
            "fetch_details": {"type": "boolean", "default": False,
                              "description": "Open each result's detail page for full description. "
                                             "Slow (3-5s per job). Default off — uses search snippets."},
        },
        "required": ["action"],
    }

    def __init__(self, embedder=None):
        """`embedder` lets the tool compute a resume↔description similarity
        score. If None, match_percent will be omitted from results.

        Certifications detected in the resume are cached on this instance
        and (a) added as soft boosts to the search query, and (b) reported
        per-result as `cert_matches` so the user sees which of their certs
        the listing actually mentions.
        """
        self.embedder = embedder
        self._resume_text: str | None = None
        self._resume_vector = None
        self._resume_path: Path | None = None
        self._resume_mtime: float = 0.0
        self._resume_certs: list[str] = []

    def _load_resume(self) -> str | None:
        """Find a resume in data/docs/ (any file with 'resume' in the name).

        Cached per-file by mtime so swapping the active resume from the UI
        takes effect immediately without restarting the server.
        """
        docs_dir = DATA_DIR / "docs"
        if not docs_dir.exists():
            self._resume_text = None
            self._resume_vector = None
            self._resume_path = None
            return None

        # active_resume.* takes priority, otherwise any *resume* match.
        candidates = sorted(docs_dir.glob("active_resume.*")) or sorted(docs_dir.glob("*resume*"))
        if not candidates:
            self._resume_text = None
            self._resume_vector = None
            self._resume_path = None
            return None

        path = candidates[0]
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return None

        # Fast path: cached and file unchanged.
        if (self._resume_text is not None
                and self._resume_path == path
                and self._resume_mtime == mtime):
            return self._resume_text

        # Re-read.
        text: str | None = None
        suffix = path.suffix.lower()
        try:
            if suffix in (".txt", ".md"):
                text = path.read_text(encoding="utf-8", errors="ignore")
            elif suffix == ".pdf":
                try:
                    import pymupdf
                    with pymupdf.open(str(path)) as doc:
                        text = "\n".join(p.get_text() for p in doc)
                except Exception:
                    text = None
            elif suffix == ".docx":
                try:
                    import docx2txt
                    text = docx2txt.process(str(path)) or ""
                except Exception:
                    text = None
        except Exception:
            text = None

        self._resume_text = text
        self._resume_path = path
        self._resume_mtime = mtime
        self._resume_vector = None
        if text and self.embedder:
            try:
                self._resume_vector = self.embedder.embed_query(text[:4000])
            except Exception:
                self._resume_vector = None

        # Pull certifications out of the resume text. Cheap (regex), runs
        # only on resume change, exposed via resume_certs() for other tools.
        if text:
            from tools.resume_intel import extract_certs
            self._resume_certs = extract_certs(text)
        else:
            self._resume_certs = []
        return text

    def resume_certs(self) -> list[str]:
        """Certifications detected in the active resume (cached)."""
        if self._resume_text is None:
            self._load_resume()
        return list(self._resume_certs)

    def _match_percent(self, job_text: str) -> int | None:
        """Cosine-similarity-based match score (0-100). None if no resume or
        no embedder is available.
        """
        if not job_text or self._resume_vector is None or self.embedder is None:
            return None
        try:
            import numpy as np
            job_vec = self.embedder.embed_query(job_text[:4000])
            a = np.asarray(self._resume_vector).flatten()
            b = np.asarray(job_vec).flatten()
            denom = (np.linalg.norm(a) * np.linalg.norm(b)) or 1.0
            sim = float(np.dot(a, b) / denom)
            # Cosine sim of sentence-transformer outputs typically ranges
            # 0.2-0.85 for related vs identical IT job text. Stretch to
            # a more intuitive 0-100% scale.
            pct = max(0, min(100, int(round((sim - 0.2) / 0.65 * 100))))
            return pct
        except Exception:
            return None

    def run(self, arguments: dict[str, Any]) -> dict[str, Any]:
        action = str(arguments.get("action") or "search").lower()
        query = str(arguments.get("query") or "").strip()
        location = str(arguments.get("location") or DEFAULT_LOCATION)
        try:
            max_jobs = max(1, min(25, int(arguments.get("max_jobs") or 5)))
        except (TypeError, ValueError):
            max_jobs = 5
        confirm_submit = bool(arguments.get("confirm_submit") or False)
        headless = bool(arguments.get("headless") or False)
        # `fetch_details` opens each result's detail page for the full
        # description. Slow (~3-5s/job) and triggers Cloudflare more often,
        # so it's off by default — search-page snippets are enough for
        # presentation and match scoring.
        fetch_details = bool(arguments.get("fetch_details") or False)

        queries = [q.strip() for q in query.split(",") if q.strip()] if query else DEFAULT_QUERIES

        try:
            from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
        except ImportError:
            return {
                "ok": False,
                "error": "Playwright not installed. Run: venv\\Scripts\\python.exe -m pip install playwright && venv\\Scripts\\python.exe -m playwright install chromium",
            }

        PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)

        # Load resume + extract certs up front so we can bias the query
        # and tag matches per listing.
        self._load_resume()
        resume_certs = list(self._resume_certs)

        # Soft-boost: append the top 3 cert names to each query as
        # additional keywords. Indeed treats space-separated tokens as
        # ranking signals, not strict filters, so this nudges relevant
        # listings up without excluding listings that don't mention them.
        if resume_certs:
            cert_boost = " ".join(resume_certs[:3])
            queries = [f"{q} {cert_boost}".strip() for q in queries]

        results: list[dict] = []
        applied: list[dict] = []
        run_started = time.strftime("%Y%m%d_%H%M%S")
        artifact = RESULTS_DIR / f"run_{run_started}.json"

        # Stealth setup: Cloudflare flags Playwright instantly because
        # the bundled "Chrome for Testing" build ships with the automation
        # banner enabled, navigator.webdriver=true, and missing plugin data.
        # We:
        #   1. Prefer the user's real Chrome install (channel="chrome") so
        #      the UA, build hash, and codec list all match a real browser.
        #   2. Strip --enable-automation from the default args.
        #   3. Inject an init script that nukes the automation tells before
        #      any page script can read them.
        #   4. Use a current-looking UA string in case channel=chrome
        #      isn't available.
        launch_kwargs = dict(
            user_data_dir=str(PROFILE_DIR),
            headless=headless,
            viewport={"width": 1366, "height": 900},
            locale="en-US",
            timezone_id="America/New_York",
            user_agent=("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/130.0.0.0 Safari/537.36"),
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-features=IsolateOrigins,site-per-process",
                "--disable-site-isolation-trials",
                "--no-default-browser-check",
            ],
            ignore_default_args=["--enable-automation"],
        )

        STEALTH_INIT = """
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5].map(() => ({}))
            });
            Object.defineProperty(navigator, 'languages', {
                get: () => ['en-US', 'en']
            });
            window.chrome = { runtime: {}, app: {} };
            const _q = window.navigator.permissions && window.navigator.permissions.query;
            if (_q) {
                window.navigator.permissions.query = (parameters) => (
                    parameters.name === 'notifications'
                        ? Promise.resolve({ state: Notification.permission })
                        : _q(parameters)
                );
            }
        """

        with sync_playwright() as pw:
            try:
                ctx = pw.chromium.launch_persistent_context(channel="chrome", **launch_kwargs)
            except Exception:
                # Real Chrome not installed — bundled Chromium fallback.
                ctx = pw.chromium.launch_persistent_context(**launch_kwargs)

            ctx.add_init_script(STEALTH_INIT)
            page = ctx.new_page()

            for q in queries:
                listings = self._search_listings(
                    page, q, location, max_jobs, PWTimeout, fetch_details=fetch_details,
                )
                results.extend(listings)

                if action == "apply":
                    for listing in listings[:max_jobs]:
                        outcome = self._apply_one(
                            page, listing, confirm_submit=confirm_submit, pw_timeout=PWTimeout,
                        )
                        applied.append({"url": listing["url"], "title": listing["title"], **outcome})
                        time.sleep(2)  # polite pacing

            artifact.write_text(json.dumps({
                "queries": queries, "location": location,
                "results": results, "applied": applied,
            }, indent=2), encoding="utf-8")

            ctx.close()

        return {
            "ok": True,
            "queries": queries,
            "location": location,
            "found": len(results),
            "results": results[:max_jobs * len(queries)],
            "applied": applied,
            "auto_submit": confirm_submit,
            "fetch_details": fetch_details,
            "artifact": str(artifact),
            "note": (
                "Applications stopped at the Submit button by default. "
                "Re-run with confirm_submit=true to actually send them."
                if not confirm_submit and applied else None
            ),
        }

    # ----- internals --------------------------------------------------

    def _search_listings(self, page, query, location, max_jobs, PWTimeout,
                          fetch_details: bool = False) -> list[dict]:
        url = f"https://www.indeed.com/jobs?q={quote_plus(query)}&l={quote_plus(location)}&fromage=14&sort=date"
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except PWTimeout:
            return [{"error": "page timeout", "query": query}]

        # If we hit a real challenge, give the user time to solve it manually.
        if self._is_blocked(page):
            if not self._wait_for_challenge(page, timeout_s=90):
                return [{"error": "blocked by Cloudflare / captcha (timeout solving)",
                         "query": query, "url": url,
                         "screenshot": str(RESULTS_DIR / "challenge.png")}]

        # Wait for the result list to actually render. Indeed loads cards
        # asynchronously, so wait_until=domcontentloaded only guarantees the
        # shell is there. Multiple selectors because Indeed A/B-tests the DOM.
        card_selector = ("div.job_seen_beacon, li.css-1ac2h1w, div.cardOutline, "
                         "[data-jk], div.jobsearch-SerpJobCard")
        try:
            page.wait_for_selector(card_selector, timeout=15000)
        except PWTimeout:
            try:
                page.screenshot(path=str(RESULTS_DIR / f"no_results_{quote_plus(query)}.png"),
                                full_page=True)
            except Exception:
                pass
            return [{"error": "no job cards rendered in 15s",
                     "query": query, "url": url,
                     "hint": "Indeed may have changed selectors, or your IP is throttled. "
                             "Check the screenshot under data/indeed_runs/."}]

        # Indeed lazy-loads cards as you scroll. Trigger a few scroll passes
        # so all `max_jobs` cards exist in the DOM before we read them.
        try:
            for _ in range(min(4, (max_jobs // 5) + 2)):
                page.mouse.wheel(0, 2500)
                page.wait_for_timeout(600)
        except Exception:
            pass

        # Make sure resume + its embedding are warm before we hit per-card work.
        self._load_resume()

        cards = page.query_selector_all(card_selector)
        listings = []
        # Indeed shows the same job multiple times via promoted / sponsored
        # slots. Dedupe by listing URL (or title+company if URL is missing).
        seen_keys: set[str] = set()
        for card in cards:
            if len(listings) >= max_jobs:
                break
            try:
                title_el = card.query_selector("h2 a, h2.jobTitle a, a.jcs-JobTitle")
                company_el = card.query_selector(
                    '[data-testid="company-name"], span.companyName, '
                    'span[data-testid="company-name"]'
                )
                location_el = card.query_selector(
                    '[data-testid="text-location"], div.companyLocation, '
                    'div[data-testid="text-location"]'
                )
                salary_el = card.query_selector(
                    '[data-testid="attribute_snippet_testid"], '
                    'div.metadata.salary-snippet-container, '
                    'div.salary-snippet-container, '
                    'div.salaryOnly'
                )
                desc_el = card.query_selector('[data-testid="job-snippet"], div.job-snippet')

                title = title_el.inner_text().strip() if title_el else ""
                if not title:
                    continue   # cards without a title are usually ads / dividers
                href = title_el.get_attribute("href") if title_el else ""
                if href and href.startswith("/"):
                    href = "https://www.indeed.com" + href

                salary_raw = salary_el.inner_text().strip() if salary_el else ""
                # Only keep tokens that look like pay (contain $ or "hour"/"year").
                salary = salary_raw if (
                    "$" in salary_raw or "hour" in salary_raw.lower() or "year" in salary_raw.lower()
                ) else ""

                company = company_el.inner_text().strip() if company_el else ""
                # Dedupe: prefer URL path (the `?jk=...` Indeed job-key URL),
                # fall back to title+company for cards without an href.
                key = href.split("?")[0] if href else f"{title.lower()}|{company.lower()}"
                if key in seen_keys:
                    continue
                seen_keys.add(key)

                listings.append({
                    "title": title,
                    "company": company,
                    "location": (location_el.inner_text().strip() if location_el else ""),
                    "salary": salary,
                    "snippet": (desc_el.inner_text().strip() if desc_el else ""),
                    "url": href or "",
                    "query": query,
                })
            except Exception:
                continue

        # Optional detail-page fetch (off by default).
        # Each detail page costs ~3-5s and triggers Cloudflare more
        # aggressively than the search results page. Skipping it makes
        # a 5-job query go from ~35s to ~8s. The snippet is enough for
        # both display and match scoring.
        for listing in listings:
            if fetch_details and listing.get("url"):
                try:
                    detail = page.context.new_page()
                    detail.goto(listing["url"], wait_until="domcontentloaded", timeout=20000)
                    if self._is_blocked(detail):
                        self._wait_for_challenge(detail, timeout_s=60)
                    body = detail.query_selector("#jobDescriptionText")
                    listing["description"] = (
                        body.inner_text().strip()[:5000] if body else ""
                    )
                    if not listing.get("salary"):
                        salary_detail = detail.query_selector(
                            '[data-testid="jobsearch-OtherJobDetailsContainer"] [data-testid*="salary"], '
                            'div[class*="salary-snippet"]'
                        )
                        if salary_detail:
                            txt = salary_detail.inner_text().strip()
                            if "$" in txt or "hour" in txt.lower() or "year" in txt.lower():
                                listing["salary"] = txt.splitlines()[0][:80]
                    detail.close()
                except Exception:
                    listing["description"] = ""
            else:
                listing["description"] = ""

            # Resume-vs-description match score.
            text_to_score = listing.get("description") or listing.get("snippet", "")
            pct = self._match_percent(text_to_score) if text_to_score else None
            if pct is not None:
                listing["match_percent"] = pct

            # Per-listing cert overlap. Match against title + snippet + desc
            # so cert mentions in any visible field count.
            if self._resume_certs:
                from tools.resume_intel import cert_matches
                blob = " ".join(filter(None, [
                    listing.get("title", ""),
                    listing.get("company", ""),
                    listing.get("snippet", ""),
                    listing.get("description", ""),
                ]))
                matched = cert_matches(self._resume_certs, blob)
                if matched:
                    listing["cert_matches"] = matched

        return listings

    def _apply_one(self, page, listing, *, confirm_submit, pw_timeout) -> dict:
        url = listing.get("url")
        if not url:
            return {"status": "skipped", "reason": "no url"}
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except pw_timeout:
            return {"status": "error", "reason": "page timeout"}
        if self._is_blocked(page):
            if not self._wait_for_challenge(page, timeout_s=90):
                return {"status": "blocked", "reason": "captcha (timeout solving)"}

        # Easy Apply button text varies: "Apply now", "Easy Apply"
        easy_btn = page.query_selector(
            "button[id^='indeedApplyButton'], button:has-text('Easy Apply'), a:has-text('Easy Apply')"
        )
        if easy_btn is None:
            return {"status": "skipped", "reason": "no Easy Apply on this listing"}

        try:
            easy_btn.click(timeout=10000)
        except Exception as exc:
            return {"status": "error", "reason": f"could not open form: {exc}"}

        # Indeed Apply opens in either a same-tab iframe or a popover. Wait for
        # any input to appear so we know the form has rendered.
        try:
            page.wait_for_selector("input, select, textarea, button:has-text('Continue')", timeout=15000)
        except pw_timeout:
            return {"status": "error", "reason": "apply form did not load"}

        # Walk through the multi-step form using cooper's screener answers,
        # clicking Continue until we hit Review/Submit.
        for step in range(12):
            self._fill_visible_fields(page)
            cont = page.query_selector("button:has-text('Continue'), button:has-text('Next')")
            review = page.query_selector("button:has-text('Review your application')")
            submit = page.query_selector("button:has-text('Submit your application'), button:has-text('Submit application')")

            if submit:
                if confirm_submit:
                    try:
                        submit.click(timeout=10000)
                        page.wait_for_load_state("domcontentloaded", timeout=10000)
                        return {"status": "submitted", "step": step}
                    except Exception as exc:
                        return {"status": "error", "reason": f"submit click failed: {exc}"}
                return {"status": "stopped_before_submit", "step": step, "review_url": page.url}

            if review:
                try:
                    review.click(timeout=10000)
                except Exception:
                    pass
                continue

            if cont:
                try:
                    cont.click(timeout=10000)
                    page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    break
            else:
                break

        return {"status": "incomplete", "reason": "no submit button reached", "url": page.url}

    def _fill_visible_fields(self, page) -> None:
        """Best-effort fill of the visible form using cooper's defaults.

        Indeed screener inputs have varying labels; the matching is done
        case-insensitively on the surrounding label text.
        """
        try:
            labels = page.query_selector_all("label")
        except Exception:
            return

        for label in labels:
            try:
                txt = (label.inner_text() or "").lower()
            except Exception:
                continue

            value = self._answer_for_label(txt)
            if value is None:
                continue

            # Find the input the label points at.
            input_el = None
            for_attr = label.get_attribute("for")
            if for_attr:
                input_el = page.query_selector(f"#{for_attr}")
            if input_el is None:
                input_el = label.query_selector("input, select, textarea")
            if input_el is None:
                continue

            tag = (input_el.evaluate("el => el.tagName") or "").lower()
            try:
                if tag == "select":
                    input_el.select_option(label=value)
                elif (input_el.get_attribute("type") or "").lower() in ("radio", "checkbox"):
                    # Click the matching option in the same fieldset.
                    radios = page.query_selector_all(f"input[name='{input_el.get_attribute('name')}']")
                    for radio in radios:
                        rid = radio.get_attribute("id") or ""
                        rlabel = page.query_selector(f"label[for='{rid}']")
                        if rlabel and value.lower() in (rlabel.inner_text() or "").lower():
                            radio.check()
                            break
                else:
                    input_el.fill(value)
            except Exception:
                continue

    def _answer_for_label(self, label_text: str) -> str | None:
        if not label_text:
            return None
        d = COOPER_SCREENER_DEFAULTS
        rules = [
            (("years",), d["years_of_experience"]),
            (("start", "available"), d["earliest_start"]),
            (("citizen", "authorized to work"), d["us_citizen"]),
            (("clearance",), d["security_clearance"]),
            (("relocate",), d["willing_to_relocate"]),
            (("salary", "compensation", "pay rate"), d["salary_expectation"]),
        ]
        for keywords, value in rules:
            if all(any(k in label_text for k in [kw]) for kw in keywords):
                return value
        return None

    def _is_blocked(self, page) -> bool:
        """Detect an actual Cloudflare/captcha challenge page.

        Old version greped the whole HTML for "cloudflare", which gave a
        false positive on every normal Indeed page (Indeed loads scripts
        from cloudflare.com on every page). Now we look for markers that
        only appear on a genuine challenge interstitial:

          - URL contains /cdn-cgi/challenge-platform/
          - Document title is "Just a moment..." (Cloudflare's stock title)
          - <body> has a Cloudflare challenge container
          - Visible text contains the challenge prompt
        """
        try:
            url = (page.url or "").lower()
            if "/cdn-cgi/challenge-platform/" in url or "/__cf_chl_" in url:
                return True

            title = (page.title() or "").strip().lower()
            if title in {"just a moment...", "attention required! | cloudflare"}:
                return True

            # Look for visible challenge text in the rendered body, NOT raw HTML
            # (raw HTML matches CDN script tags). inner_text() returns only
            # rendered text the user would see.
            body = page.query_selector("body")
            if body is None:
                return False
            text = (body.inner_text() or "").lower()
            visible_markers = (
                "verify you are human",
                "checking your browser before accessing",
                "please complete the security check",
                "needs to review the security of your connection",
                "additional verification required",
            )
            return any(m in text for m in visible_markers)
        except Exception:
            return False

    def _wait_for_challenge(self, page, timeout_s: int = 60) -> bool:
        """If a real challenge is up, pause for the user to solve it.

        In headless mode there's nobody to click anything, so we bail
        immediately with a screenshot saved for diagnostics. Otherwise
        poll the page state for up to `timeout_s` seconds.
        """
        if not self._is_blocked(page):
            return True
        try:
            page.screenshot(path=str(RESULTS_DIR / "challenge.png"), full_page=True)
        except Exception:
            pass

        # Detect headless via the browser context's `headless` attribute on
        # the browser, or by checking that the window is realistically sized.
        try:
            is_headless = page.context.browser is None or page.evaluate(
                "() => !window.outerHeight"
            )
        except Exception:
            is_headless = False

        if is_headless:
            print("[indeed_apply] Cloudflare challenge detected (headless mode "
                  "— cannot solve interactively). Screenshot saved.")
            return False

        print("[indeed_apply] Cloudflare challenge detected. Solve it in the "
              f"browser window — waiting up to {timeout_s}s...")
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            time.sleep(2)
            if not self._is_blocked(page):
                print("[indeed_apply] Challenge cleared. Continuing.")
                return True
        return False
