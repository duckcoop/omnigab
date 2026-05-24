"""
Web Search Module
=================
Provides live web search and page scraping via DuckDuckGo to supplement
local document retrieval. Searches the web, fetches actual page content,
and returns results as Chunk objects for the RAG pipeline.

No API keys required.
"""

import time
import re

from ingest import Chunk
from url_safety import is_safe_url

try:
    from ddgs import DDGS
    HAS_DDG = True
except ImportError:
    try:
        from duckduckgo_search import DDGS
        HAS_DDG = True
    except ImportError:
        HAS_DDG = False

try:
    import requests
    from bs4 import BeautifulSoup
    HAS_SCRAPER = True
except ImportError:
    HAS_SCRAPER = False


def _scrape_page(url, timeout=5, max_chars=1500):
    """
    Fetch a URL and extract the main text content.
    Returns the cleaned text or None if it fails.
    """
    if not HAS_SCRAPER:
        return None

    if not is_safe_url(url):
        return None

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=False)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        # Remove scripts, styles, navs, footers, ads
        for tag in soup(["script", "style", "nav", "footer", "header",
                         "aside", "form", "iframe", "noscript"]):
            tag.decompose()

        # Try to find main content area first
        main = soup.find("main") or soup.find("article") or soup.find("body")
        if not main:
            return None

        text = main.get_text(separator=" ", strip=True)

        # Clean up whitespace
        text = re.sub(r"\s+", " ", text).strip()

        # Truncate to stay within context budget
        if len(text) > max_chars:
            text = text[:max_chars].rsplit(" ", 1)[0]

        # Skip if we got almost nothing useful
        if len(text) < 50:
            return None

        return text

    except Exception:
        return None


class WebSearchEngine:
    """DuckDuckGo web search with page scraping."""

    def __init__(self, max_results=3):
        self.max_results = max_results
        if not HAS_DDG:
            print("WARNING: ddgs not installed. Web search disabled.")
            print("  Install with: pip install ddgs")
        if not HAS_SCRAPER:
            print("WARNING: requests/beautifulsoup4 not installed. Page scraping disabled.")
            print("  Install with: pip install requests beautifulsoup4")

    def search(self, query, max_results=None):
        """
        Search the web, scrape page content, and return as (Chunk, score) tuples.

        For each search result:
        1. Get the URL and snippet from DuckDuckGo
        2. Fetch the actual page and extract text content
        3. Return the full page text (or snippet as fallback) as a Chunk

        Returns results in the same format as VectorStore.search().
        """
        if not HAS_DDG:
            return []

        n = max_results or self.max_results

        try:
            with DDGS() as ddgs:
                raw_results = list(ddgs.text(query, max_results=n))
        except Exception as e:
            print(f"  Web search failed: {e}")
            return []

        chunks = []
        for i, result in enumerate(raw_results):
            title = result.get("title", "")
            body = result.get("body", "")
            url = result.get("href", "")

            # Try to scrape the actual page content
            page_text = _scrape_page(url) if url else None

            if page_text:
                # Use scraped content with title for context
                text = f"{title}\n\n{page_text}"
                source_label = f"web: {url}"
            else:
                # Fall back to search snippet
                text = f"{title}\n{body}"
                source_label = f"web (snippet): {url}" if url else "web: search result"

            if url:
                text += f"\nSource: {url}"

            chunk = Chunk(
                text=text,
                source_file=source_label,
                chunk_index=i,
                start_char=0,
                end_char=len(text),
            )

            chunks.append((chunk, 0.50))

        return chunks

    def is_available(self):
        """Check if web search is functional."""
        return HAS_DDG


if __name__ == "__main__":
    print("=== Web Search + Scrape Test ===\n")
    engine = WebSearchEngine(max_results=2)

    if not engine.is_available():
        print("Install ddgs: pip install ddgs")
    else:
        query = "weather in Austin TX"
        print(f"Query: {query}\n")
        results = engine.search(query)
        for chunk, score in results:
            print(f"[{score:.2f}] {chunk.source_file}")
            print(f"  {chunk.text[:300]}")
            print()
