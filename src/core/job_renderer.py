"""Deterministic rendering of job search results.

Why this module exists
----------------------
The agent used to hand the raw usajobs_search JSON to the language model
and instruct it, in ~1500 tokens of system prompt, to copy each job's URL
"byte for byte" into a markdown list.

That approach fails for two reasons:

1. Small quantized models cannot reliably transcribe long unique URLs.
   Under any context pressure they template collapse (reuse job 1's URL
   for every job) or invent plausible looking URLs that 404. The tool
   layer already HTTP verifies every URL and discards dead ones, so every
   dead link the user saw was invented during rendering, not fetched.

2. It wastes context. See the budget note in agent.py.

The data is already structured and already verified. Formatting structured
data is a job for code, not for a language model. This module renders the
list; the model only writes the short prose comment above it.

Every URL emitted here comes from the tool result dict, so a link can only
appear if the tool actually fetched it and got HTTP 200.
"""

from __future__ import annotations

from typing import Any


def _clean(value: Any, fallback: str) -> str:
    """Normalize a possibly missing/blank field to display text."""
    if value is None:
        return fallback
    text = str(value).strip()
    return text or fallback


def _join(values: Any) -> str:
    """Render a list field as a comma separated string, or '' if empty."""
    if not values:
        return ""
    if isinstance(values, str):
        return values.strip()
    return ", ".join(str(v).strip() for v in values if str(v).strip())


def _source_errors(errors: Any) -> str:
    """Name the boards that failed, so a partial result reads as partial.

    search_many keeps going when one board is down and records the failure
    rather than raising. That is the right behaviour, and it is only honest
    if the failure reaches the user instead of looking like a thin result.
    """
    if not errors:
        return ""
    names = _join([e.get("source") for e in errors if isinstance(e, dict)])
    if not names:
        return ""
    return f"These sources failed and returned nothing: {names}."


def _fit_line(job: dict) -> str:
    """The headline verdict: a band and the facts behind it.

    This replaced a "Match: 20%" line computed from embedding similarity
    between the resume and the job text. Two postings scored 20% and 29%,
    and the real difference between them was that the user could apply to
    one and not the other, which similarity cannot see and a percentage
    implies it measured. The band claims only what its inputs support and
    shows them.
    """
    band = _clean(job.get("fit"), "")
    if not band:
        return ""
    reasons = job.get("fit_reasons") or []
    if reasons:
        return f"{band} · " + " · ".join(str(r) for r in reasons)
    return band


def _relevance_line(job: dict) -> str:
    """The old similarity number, kept but labelled as what it is.

    Useful as a rough topical signal, misleading as a fit score. Naming it
    "relevance" and saying it is text overlap stops it being read as an
    answer to "should I apply".
    """
    raw = job.get("match_percent")
    series = _clean(job.get("series_code"), "")
    parts = []
    if raw is not None:
        parts.append(f"Relevance: {raw}% resume text overlap")
    # Series codes are a federal concept. Printing "Series ?" on an Amazon
    # posting is noise, so the segment is omitted when absent.
    if series:
        parts.append(f"Series {series}")
    return " · ".join(parts)


def _gap_line(job: dict) -> str:
    """Summarize what the user is missing for this posting. '' if nothing."""
    segments = []
    certs = _join(job.get("missing_certs"))
    if certs:
        segments.append(f"certs {certs}")
    clearance = _clean(job.get("missing_clearance"), "")
    if clearance:
        segments.append(f"clearance {clearance}")
    skills = _join(job.get("missing_skills"))
    if skills:
        segments.append(f"skills {skills}")
    return "Gap: " + "  ·  ".join(segments) if segments else ""


def render_job(job: dict, index: int) -> str:
    """Render one job posting as a markdown block."""
    title = _clean(job.get("title"), "(untitled posting)")
    agency = _clean(job.get("agency"), "(agency not listed)")
    location = _clean(job.get("location"), "(anywhere)")
    salary = _clean(job.get("salary"), "(salary not listed)")

    lines = [
        f"**{index}. {title}**",
        f"{agency} · {location} · {salary}",
    ]
    # Fit first, because it is the answer to the question the user asked.
    # Relevance sits under it, labelled, for the cases where topical
    # closeness is still worth knowing.
    for line in (_fit_line(job), _relevance_line(job)):
        if line:
            lines.append(line)

    certs = _join(job.get("cert_matches"))
    if certs:
        lines.append(f"Certs matched: {certs}")

    gap = _gap_line(job)
    if gap:
        lines.append(gap)

    url = _clean(job.get("url"), "")
    if url:
        labels = {
            "amazon": "View on Amazon Jobs",
            "remoteok": "View on RemoteOK",
            "greenhouse": "View posting",
            "lever": "View posting",
        }
        label = labels.get(job.get("source"), "Apply on USAJOBS")
        lines.append(f"[{label}]({url})")
    else:
        # Should not happen: the tool discards entries without a live URL.
        lines.append("(no verified link available)")

    return "\n".join(lines)


def render_results(payload: dict, limit: int = 10) -> str:
    """Render a full usajobs_search result payload as markdown.

    `payload` is the dict the tool returns. Returns '' when the payload
    holds no renderable results, which signals the caller to fall back to
    normal model output.
    """
    if not isinstance(payload, dict) or not payload.get("ok"):
        return ""

    results = payload.get("results") or []
    handoffs_only = payload.get("handoffs") or []
    if not results and not handoffs_only:
        return ""

    blocks = [render_job(job, i) for i, job in enumerate(results[:limit], 1)]
    body = "\n\n".join(blocks)

    found = payload.get("found", len(results))
    location = _clean(payload.get("location"), "(anywhere)")
    header = f"Found {found} open postings · {location}"

    shown = min(limit, len(results))
    footer_bits = []
    if found > shown:
        footer_bits.append(f"Showing the top {shown}.")

    discarded = payload.get("dead_links_discarded") or []
    closed = payload.get("closed_listings_discarded") or 0
    dropped = len(discarded) if isinstance(discarded, list) else int(discarded or 0)
    if dropped:
        footer_bits.append(f"{dropped} dead link(s) discarded.")
    if closed:
        footer_bits.append(f"{closed} closed posting(s) discarded.")
    # Only claim verification when the source actually performed it.
    # usajobs_search fetches every URL; the public board APIs do not.
    if payload.get("verification"):
        footer_bits.append("Every link above returned HTTP 200 when checked.")

    # A board that was down is why the list is short. Saying so beats
    # letting a partial result pass for the whole picture.
    source_errors = _source_errors(payload.get("errors"))
    if source_errors:
        footer_bits.append(source_errors)

    # Postings the user cannot apply to are dropped, never silently. A
    # shorter list with no explanation is the same failure as a zero with
    # no explanation.
    hidden = payload.get("hidden_ineligible") or []
    if hidden:
        footer_bits.append(
            f"{len(hidden)} posting(s) hidden: you cannot apply "
            f"({hidden[0].get('reason', 'restricted audience')}).")

    # Boards that prohibit automation return a prefilled search link
    # instead of listings. Surfacing them here is the whole point: the
    # user still gets to those results, just in their own browser.
    handoff_block = ""
    handoffs = payload.get("handoffs") or []
    if handoffs:
        lines = ["Search these in your browser (they block automated access):"]
        for h in handoffs:
            label = h.get("label") or h.get("source", "board")
            url = h.get("url", "")
            if url:
                lines.append(f"- [{label}]({url})")
        handoff_block = "\n\n" + "\n".join(lines)

    footer = " ".join(footer_bits)
    footer_block = f"\n\n_{footer}_" if footer else ""
    return f"{header}\n\n{body}{handoff_block}{footer_block}"


def summarize_for_model(payload: dict, limit: int = 10) -> str:
    """A compact, URL free digest of the results for the model to comment on.

    The model never sees the URLs, so it cannot copy them wrong and it
    cannot invent them. It gets just enough to write a sentence or two of
    useful commentary, at roughly a tenth of the token cost of the full
    JSON payload.
    """
    if not isinstance(payload, dict) or not payload.get("ok"):
        return ""

    results = payload.get("results") or []
    handoffs = payload.get("handoffs") or []
    errors = payload.get("errors") or []

    if not results:
        # "No postings" is the wrong summary when the search produced
        # browser handoff links, because those links ARE the result for
        # LinkedIn, Handshake and Indeed. Telling the model nothing was
        # found makes it say so, while the rendered block below its reply
        # is busy showing the user three places to look.
        notes = ["No postings came back from the boards that allow "
                 "automated search."]
        if handoffs:
            names = _join([h.get("label") or h.get("source") for h in handoffs])
            notes.append(f"Browser search links were produced for {names}, "
                         f"and are shown to the user below your reply.")
        if errors:
            notes.append(_source_errors(errors))
        return " ".join(notes)

    lines = [f"{payload.get('found', len(results))} open postings found."]
    for i, job in enumerate(results[:limit], 1):
        title = _clean(job.get("title"), "untitled")
        agency = _clean(job.get("agency"), "unknown agency")
        # Fit, not the similarity score. The model repeats whatever the
        # digest tells it, and it used to be handed "29% match" for a
        # vacancy the user was not allowed to apply for.
        band = _clean(job.get("fit"), "")
        reasons = job.get("fit_reasons") or []
        if band:
            note = band + (": " + "; ".join(str(r) for r in reasons)
                           if reasons else "")
        else:
            raw = job.get("match_percent")
            note = "unscored" if raw is None else f"{raw}% text relevance"
        certs = _join(job.get("cert_matches"))
        cert_note = f", certs matched: {certs}" if certs else ""
        lines.append(f"{i}. {title} at {agency} - {note}{cert_note}")

    hidden = payload.get("hidden_ineligible") or []
    if hidden:
        lines.append(f"{len(hidden)} further posting(s) were hidden because "
                     f"the user cannot apply to them; say so if it matters.")
    return "\n".join(lines)
