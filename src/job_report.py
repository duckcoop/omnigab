"""
Job Report Generator
====================
Generates a clean PDF report of job search results with match scores
and explanations. Uses FPDF2 for PDF creation (no external dependencies
beyond pip install fpdf2).
"""

import re
from pathlib import Path
from datetime import datetime

try:
    from fpdf import FPDF
    HAS_FPDF = True
except ImportError:
    HAS_FPDF = False


class JobReportPDF(FPDF):
    """Custom PDF class for job search reports."""

    def header(self):
        self.set_font("Helvetica", "B", 16)
        self.cell(0, 10, "Job Search Results", align="C", new_x="LMARGIN", new_y="NEXT")
        self.set_font("Helvetica", "", 9)
        self.set_text_color(120, 120, 120)
        self.cell(0, 6, f"Generated {datetime.now().strftime('%B %d, %Y at %I:%M %p')}", align="C", new_x="LMARGIN", new_y="NEXT")
        self.set_text_color(0, 0, 0)
        self.ln(4)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}}", align="C")


def _clean_text(text):
    """Remove non-printable characters that FPDF can't handle."""
    if not text:
        return ""
    text = text.encode("ascii", errors="replace").decode("ascii")
    text = re.sub(r"[^\x20-\x7E\n\r\t]", "", text)
    return text.strip()


def _score_color(score):
    """Return RGB color based on match score."""
    if score >= 80:
        return (34, 139, 34)    # green
    elif score >= 60:
        return (218, 165, 32)   # gold
    elif score >= 40:
        return (255, 140, 0)    # orange
    else:
        return (178, 34, 34)    # red


def generate_job_report(jobs, search_query="", location="", output_path=None):
    """
    Generate a PDF report of job search results.

    Args:
        jobs: List of JobListing objects (from job_agent.py)
        search_query: The search query used
        location: The location searched
        output_path: Where to save the PDF. Defaults to project root/job_results.pdf

    Returns:
        Path to the generated PDF file
    """
    if not HAS_FPDF:
        raise ImportError("fpdf2 is required for PDF generation. Install with: pip install fpdf2")

    if output_path is None:
        output_path = Path(__file__).parent.parent / "job_results.pdf"
    else:
        output_path = Path(output_path)

    pdf = JobReportPDF()
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()

    # Search summary
    pdf.set_font("Helvetica", "", 10)
    search_info = f"Search: {search_query}"
    if location:
        search_info += f" in {location}"
    search_info += f"  |  {len(jobs)} results scored"
    pdf.set_text_color(80, 80, 80)
    pdf.cell(0, 8, _clean_text(search_info), align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(6)

    # Divider line
    pdf.set_draw_color(200, 200, 200)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(6)

    for i, job in enumerate(jobs):
        # Check if we need a new page (at least 60mm needed for a job entry)
        if pdf.get_y() > 240:
            pdf.add_page()

        # Job number and score badge
        score = int(job.match_score)
        r, g, b = _score_color(score)

        # Score badge
        pdf.set_font("Helvetica", "B", 22)
        pdf.set_text_color(r, g, b)
        badge_text = f"{score}"
        pdf.cell(20, 12, badge_text, new_x="END")

        # Job title
        pdf.set_font("Helvetica", "B", 13)
        pdf.set_text_color(0, 0, 0)
        title_clean = _clean_text(job.title) if job.title else "Untitled Position"
        pdf.cell(0, 12, f"  {title_clean[:70]}", new_x="LMARGIN", new_y="NEXT")

        # Company and location line
        pdf.set_x(pdf.l_margin + 22)
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(60, 60, 60)
        info_parts = []
        if job.company and job.company != "Unknown Company":
            info_parts.append(_clean_text(job.company))
        if job.location:
            info_parts.append(_clean_text(job.location))
        if job.salary:
            info_parts.append(_clean_text(job.salary))
        if info_parts:
            pdf.cell(0, 6, "  ".join(info_parts), new_x="LMARGIN", new_y="NEXT")

        # Match reason
        if job.match_reason and job.match_reason != "No explanation provided.":
            pdf.set_x(pdf.l_margin + 22)
            pdf.set_font("Helvetica", "I", 9)
            pdf.set_text_color(80, 80, 80)
            reason = _clean_text(job.match_reason)[:200]
            pdf.multi_cell(0, 5, reason, new_x="LMARGIN", new_y="NEXT")

        # URL
        if job.url:
            pdf.set_x(pdf.l_margin + 22)
            pdf.set_font("Helvetica", "", 8)
            pdf.set_text_color(0, 102, 204)
            url_clean = _clean_text(job.url)[:100]
            pdf.cell(0, 5, url_clean, new_x="LMARGIN", new_y="NEXT", link=job.url)

        # Spacing between jobs
        pdf.ln(8)

        # Light divider between jobs (not after the last one)
        if i < len(jobs) - 1:
            pdf.set_draw_color(220, 220, 220)
            pdf.line(pdf.l_margin + 20, pdf.get_y() - 3, pdf.w - pdf.r_margin, pdf.get_y() - 3)

    # Save
    output_path.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(output_path))
    print(f"PDF report saved: {output_path}")
    return output_path


if __name__ == "__main__":
    from job_agent import JobListing

    print("=== Job Report Test ===\n")

    sample_jobs = [
        JobListing("Senior Python Developer", "Acme Corp", "Frederick, MD",
                    "$120,000 - $150,000/year", "Build backend services...",
                    "https://indeed.com/example1", 92, "Strong Python match with backend experience."),
        JobListing("IT Support Specialist", "Tech Solutions Inc", "Remote",
                    "$55,000 - $70,000/year", "Provide technical support...",
                    "https://indeed.com/example2", 74, "IT experience aligns but looking for more senior role."),
        JobListing("Data Analyst", "DataCo", "Baltimore, MD",
                    "$80,000/year", "Analyze datasets...",
                    "https://indeed.com/example3", 45, "Some skill overlap but different career focus."),
    ]

    path = generate_job_report(sample_jobs, "Python Developer", "Maryland")
    print(f"Report at: {path}")
