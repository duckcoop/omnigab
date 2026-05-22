"""
Job Search Agent
================
Autonomous agent that searches Indeed for job listings matching a resume,
scores each job using the local LLM, and generates a PDF report of the
top matches.

Uses DuckDuckGo to find Indeed listings, scrapes job details, then
leverages the RAG pipeline's generator to evaluate fit.
"""

import re
import json
import time
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional

from config import MODELS_DIR, GGUF_MODEL_PATH, DOCS_DIR
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


@dataclass
class JobListing:
    """A scraped job listing with metadata."""
    title: str
    company: str
    location: str
    salary: str
    description: str
    url: str
    match_score: float = 0.0
    match_reason: str = ""

    def to_dict(self):
        return asdict(self)


def extract_resume_text(file_path: Path) -> str:
    """Extract text from a resume file (PDF, TXT, MD, DOCX)."""
    suffix = file_path.suffix.lower()

    if suffix == ".pdf":
        try:
            import fitz
            doc = fitz.open(str(file_path))
            text = "\n\n".join(page.get_text("text") for page in doc if page.get_text("text").strip())
            doc.close()
            return text
        except ImportError:
            return file_path.read_text(encoding="utf-8", errors="replace")

    elif suffix == ".docx":
        try:
            import zipfile
            import xml.etree.ElementTree as ET
            with zipfile.ZipFile(str(file_path)) as z:
                xml_content = z.read("word/document.xml")
            tree = ET.fromstring(xml_content)
            ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
            paragraphs = []
            for p in tree.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"):
                texts = [t.text for t in p.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t") if t.text]
                if texts:
                    paragraphs.append("".join(texts))
            return "\n".join(paragraphs)
        except Exception:
            return file_path.read_text(encoding="utf-8", errors="replace")

    else:
        return file_path.read_text(encoding="utf-8", errors="replace")


def find_resume_in_docs() -> Optional[Path]:
    """Look for a resume file in the docs directory."""
    if not DOCS_DIR.exists():
        return None
    docs_root = DOCS_DIR.resolve()
    resume_keywords = ["resume", "cv", "curriculum"]
    for file_path in DOCS_DIR.rglob("*"):
        if file_path.is_symlink():
            continue
        try:
            if not file_path.resolve().is_relative_to(docs_root):
                continue
        except OSError:
            continue
        if file_path.is_file():
            name_lower = file_path.stem.lower()
            if any(kw in name_lower for kw in resume_keywords):
                return file_path
    return None


def _scrape_job_page(url, timeout=8):
    """Scrape a job listing page for details."""
    if not HAS_SCRAPER:
        return None

    if not is_safe_url(url):
        return None

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        resp = requests.get(url, headers=headers, timeout=timeout, allow_redirects=False)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "iframe", "noscript"]):
            tag.decompose()

        main = soup.find("main") or soup.find("article") or soup.find("body")
        if not main:
            return None

        text = main.get_text(separator="\n", strip=True)
        text = re.sub(r"\n{3,}", "\n\n", text)

        if len(text) > 4000:
            text = text[:4000].rsplit("\n", 1)[0]

        return text if len(text) > 100 else None

    except Exception:
        return None


def search_jobs(query, location="", num_results=10):
    """
    Search for job listings using DuckDuckGo.
    Returns a list of raw search results with URLs and snippets.
    """
    if not HAS_DDG:
        return []

    search_query = f"site:indeed.com {query}"
    if location:
        search_query += f" {location}"

    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(search_query, max_results=num_results))
    except Exception as e:
        print(f"  Job search failed: {e}")
        return []

    return results


def parse_job_from_search(result, scraped_text=None):
    """Parse a job listing from search result + scraped page text."""
    title = result.get("title", "Unknown Position")
    body = result.get("body", "")
    url = result.get("href", "")

    # Try to extract company from title (Indeed format: "Job Title - Company Name")
    company = "Unknown Company"
    if " - " in title:
        parts = title.rsplit(" - ", 2)
        if len(parts) >= 2:
            title = parts[0].strip()
            company = parts[1].strip()
            # Remove "Indeed.com" or similar suffixes
            company = re.sub(r"\s*[-|]\s*(Indeed|Indeed\.com).*$", "", company).strip()

    # Try to extract location and salary from body/scraped text
    location = ""
    salary = ""
    description = scraped_text or body

    # Look for salary patterns
    salary_pattern = r"\$[\d,]+(?:\.\d{2})?\s*(?:[-–]\s*\$[\d,]+(?:\.\d{2})?)?\s*(?:per\s+(?:hour|year|month|week)|/\s*(?:hr|yr|mo|wk)|a\s+year|annually|hourly)?"
    salary_match = re.search(salary_pattern, description, re.IGNORECASE)
    if salary_match:
        salary = salary_match.group(0).strip()

    # Look for common location patterns
    loc_pattern = r"(?:in|location[:\s]+)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?,\s*[A-Z]{2})"
    loc_match = re.search(loc_pattern, description)
    if loc_match:
        location = loc_match.group(1).strip()

    return JobListing(
        title=title,
        company=company,
        location=location,
        salary=salary,
        description=description[:3000] if description else body,
        url=url,
    )


def score_job_with_llm(generator, job, resume_text):
    """
    Use the local LLM to score how well a job matches the resume.
    Returns a score (0-100) and a short explanation.
    """
    # Truncate resume and job description to fit context
    resume_short = resume_text[:1500] if len(resume_text) > 1500 else resume_text
    job_desc_short = job.description[:1500] if len(job.description) > 1500 else job.description

    prompt_context = f"""RESUME:
{resume_short}

JOB LISTING:
Title: {job.title}
Company: {job.company}
{f"Location: {job.location}" if job.location else ""}
{f"Salary: {job.salary}" if job.salary else ""}

Description:
{job_desc_short}"""

    question = "Rate this job match from 0 to 100. Reply with ONLY a number on the first line, then a one-sentence reason on the second line. Nothing else."

    try:
        response = generator.generate(
            question=question,
            context=prompt_context,
            temperature_override=0.1,
        )

        lines = response.strip().split("\n")
        score_text = re.search(r"(\d{1,3})", lines[0])
        score = int(score_text.group(1)) if score_text else 50
        score = min(100, max(0, score))

        reason = lines[1].strip() if len(lines) > 1 else "No explanation provided."
        reason = re.sub(r"^[-•*]\s*", "", reason)

        return score, reason

    except Exception as e:
        print(f"  Scoring failed for {job.title}: {e}")
        return 50, "Could not evaluate match."


class JobAgent:
    """Autonomous job search agent that finds and scores job listings."""

    def __init__(self, generator=None):
        self.generator = generator
        self.resume_text = ""
        self.resume_path = None
        self.jobs = []

    def load_resume(self, file_path: Optional[Path] = None):
        """Load resume from a file or auto-detect from docs folder."""
        if file_path and Path(file_path).exists():
            self.resume_path = Path(file_path)
        else:
            self.resume_path = find_resume_in_docs()

        if self.resume_path:
            self.resume_text = extract_resume_text(self.resume_path)
            print(f"Resume loaded: {self.resume_path.name} ({len(self.resume_text):,} chars)")
            return True
        else:
            print("No resume found. Add a file with 'resume' in the name to data/docs/")
            return False

    def set_resume_text(self, text):
        """Set resume text directly (for web UI uploads)."""
        self.resume_text = text
        self.resume_path = None
        print(f"Resume set from upload ({len(text):,} chars)")

    def search_and_score(self, job_title, location="", num_results=10, progress_callback=None):
        """
        Search for jobs, scrape details, and score each one against the resume.
        Returns sorted list of JobListing objects (best matches first).
        """
        if not self.resume_text:
            print("No resume loaded. Call load_resume() first.")
            return []

        # Step 1: Search
        if progress_callback:
            progress_callback("searching", 0, "Searching Indeed for jobs...")
        print(f"\nSearching: {job_title}" + (f" in {location}" if location else ""))
        raw_results = search_jobs(job_title, location, num_results)

        if not raw_results:
            print("No results found.")
            return []

        print(f"Found {len(raw_results)} listings. Scraping and scoring...\n")

        # Step 2: Scrape and parse each listing
        self.jobs = []
        for i, result in enumerate(raw_results):
            url = result.get("href", "")
            if progress_callback:
                progress_callback("scraping", i + 1, f"Scraping job {i + 1}/{len(raw_results)}...")

            scraped = _scrape_job_page(url) if url else None
            job = parse_job_from_search(result, scraped)
            self.jobs.append(job)

        # Step 3: Score each job with the LLM
        if self.generator:
            for i, job in enumerate(self.jobs):
                if progress_callback:
                    progress_callback("scoring", i + 1, f"AI scoring job {i + 1}/{len(self.jobs)}: {job.title[:40]}...")
                print(f"  Scoring [{i+1}/{len(self.jobs)}]: {job.title[:50]} at {job.company[:30]}")
                score, reason = score_job_with_llm(self.generator, job, self.resume_text)
                job.match_score = score
                job.match_reason = reason
                print(f"    Score: {score}/100 - {reason[:80]}")

        # Sort by score descending
        self.jobs.sort(key=lambda j: j.match_score, reverse=True)

        if progress_callback:
            progress_callback("done", len(self.jobs), "Complete!")

        return self.jobs

    def get_top_jobs(self, n=5):
        """Return the top N matched jobs."""
        return self.jobs[:n]

    def to_dict_list(self, n=5):
        """Return top N jobs as a list of dicts for JSON serialization."""
        return [j.to_dict() for j in self.jobs[:n]]


if __name__ == "__main__":
    print("=== Job Agent Test ===\n")

    # Test resume detection
    resume = find_resume_in_docs()
    if resume:
        print(f"Found resume: {resume}")
        text = extract_resume_text(resume)
        print(f"Resume length: {len(text):,} chars")
        print(f"Preview: {text[:200]}...")
    else:
        print("No resume found in docs folder.")

    # Test search (no LLM scoring in standalone test)
    if HAS_DDG:
        print("\nSearching for 'software engineer' jobs...")
        results = search_jobs("software engineer", "Frederick MD", 3)
        for r in results:
            print(f"  {r.get('title', 'N/A')}")
            print(f"  {r.get('href', 'N/A')}\n")
    else:
        print("\nddgs not installed, skipping search test.")
