"""The USAJOBS scraper's read of the live page, and how it fails.

This file exists because of a defect that ran undetected: USAJOBS moved
its result cards off the Tailwind utility classes the scraper matched on,
so `#search-results .bg-white.p-4` stopped matching anything. The scraper
kept working, found no cards, and returned `ok=True, found=0`. The agent
read that as "there are no jobs" and told the user so, while USAJOBS held
668 matching postings for the same query.

`tests/test_usajobs.py` could not catch it: its only assertion is
`result["ok"]`, and a scraper reading nothing at all reports ok. That is
the shape of the bug in one line. A zero is indistinguishable from a
truth unless something upstream refuses to produce it.

Two layers of cover here, matching the two ways this breaks.

* Unit, always run: `_scrape_integrity_error` must call selector drift a
  fault rather than an empty result. No network, no browser, so it holds
  under invariant I7 and runs on every push.
* Integration, opt in: the selectors are matched against the real page,
  because no offline test can notice that a website was redesigned. Run
  it with `pytest -m integration`.
"""

from __future__ import annotations

import pytest

from tools.usajobs_search import (
    CARD_TITLE_LINK,
    POSTING_LINK,
    RESULT_CARD,
    _scrape_integrity_error,
)

LIVE_SEARCH_URL = (
    "https://www.usajobs.gov/Search/Results?k=IT+Specialist&l=&dap=30"
    "&p=1&jc=2210"
)


# ------------------------------------------------------- the silent zero

def test_selector_drift_is_reported_as_a_fault():
    """Postings on the page but no cards matched is a scraper fault.

    This is the exact state the app was in: hundreds of postings present,
    zero cards recognised. It has to produce an error, because "0 jobs" is
    a claim about the world and the code has not confirmed it.
    """
    message = _scrape_integrity_error(
        card_count=0, posting_links=25, page_url=LIVE_SEARCH_URL)
    assert message is not None
    # The message has to name the selector to fix, or whoever reads it in
    # six months learns only that something is broken.
    assert RESULT_CARD in message
    assert "25" in message
    assert LIVE_SEARCH_URL in message


def test_a_genuinely_empty_search_is_not_a_fault():
    """No cards and no postings means the search really is empty.

    Without this half the check would turn every zero-result search into
    an error, which is the opposite failure and just as wrong.
    """
    assert _scrape_integrity_error(
        card_count=0, posting_links=0, page_url=LIVE_SEARCH_URL) is None


@pytest.mark.parametrize("cards,links", [(25, 25), (1, 40), (25, 0)])
def test_a_scrape_that_found_cards_is_never_a_fault(cards, links):
    assert _scrape_integrity_error(cards, links, LIVE_SEARCH_URL) is None


def test_posting_link_selector_is_independent_of_the_card_selector():
    """The check is only worth anything if the two selectors can't co-rot.

    POSTING_LINK keys off the /job/<id> href, which is what a posting is.
    If it were derived from RESULT_CARD, the same redesign would break
    both and the drift would go unnoticed exactly as before.
    """
    assert "/job/" in POSTING_LINK
    assert RESULT_CARD not in POSTING_LINK
    assert "page-section" not in POSTING_LINK


# ------------------------------------------------------------- live page

@pytest.fixture(scope="module")
def live_search_page():
    """The real USAJOBS result page in a headless browser, or a skip."""
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        try:
            browser = pw.chromium.launch(headless=True)
        except Exception as exc:                  # no browser installed
            pytest.skip(f"chromium unavailable: {exc}")
        page = browser.new_page()
        try:
            response = page.goto(LIVE_SEARCH_URL,
                                 wait_until="domcontentloaded", timeout=45000)
            if response is None or response.status != 200:
                pytest.skip(f"USAJOBS returned {response and response.status}")
            # The results are rendered client side; there is nothing in the
            # initial HTML to match against.
            page.wait_for_timeout(6000)
            yield page
        finally:
            browser.close()


@pytest.mark.integration
def test_result_card_selector_still_matches_the_live_page(live_search_page):
    """The assertion that would have caught this the day it broke.

    A query with 600+ open postings must yield cards. If this fails,
    USAJOBS has changed its markup again and RESULT_CARD needs updating,
    which is a five minute fix once you know that is the problem and a
    long confusing one when the only symptom is "no jobs found".
    """
    cards = live_search_page.locator(RESULT_CARD).count()
    assert cards > 0, (
        f"{RESULT_CARD!r} matched nothing on {LIVE_SEARCH_URL}. USAJOBS has "
        f"redesigned its result page; update RESULT_CARD in "
        f"src/tools/usajobs_search.py."
    )


@pytest.mark.integration
def test_card_titles_and_urls_are_still_extractable(live_search_page):
    """Matching a card is not enough; the title and href have to survive.

    _extract_card reads both out of the card, and a redesign that keeps
    the container but moves the heading would leave every stub without a
    url, which the scraper drops silently.
    """
    card = live_search_page.locator(RESULT_CARD).first
    link = card.locator(CARD_TITLE_LINK).first
    assert (link.inner_text() or "").strip()
    assert "/job/" in (link.get_attribute("href") or "")


@pytest.mark.integration
def test_the_integrity_check_stays_quiet_on_a_healthy_page(live_search_page):
    """End to end: real page, real selectors, no fault reported."""
    cards = live_search_page.locator(RESULT_CARD).count()
    links = live_search_page.locator(POSTING_LINK).count()
    assert _scrape_integrity_error(cards, links, LIVE_SEARCH_URL) is None
