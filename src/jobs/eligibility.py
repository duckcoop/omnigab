"""Who a federal posting is actually open to, and whether that includes you.

Why this exists
---------------
`usajobs_search` ranked postings by `match_percent`, a cosine similarity
between the user's resume embedding and the job text. That measures how
much vocabulary the two share, which is not the question anybody is asking.

Measured on one real result set for an IT student holding Security+:

    IT SPECIALIST (SYSADMIN), NH-3/4       29%   <- ranked best
    IT Specialist (Network), NH-3          29%
    IT Cybersecurity Specialist,
      CES Recent Graduate                  20%   <- ranked worse

The 29% posting is open to "Federal employees - Competitive service". The
user is not a federal employee, so he cannot apply to it at all. The 20%
posting is open to "Recent graduates", which is exactly what he is. The
ranking was close to inverted, because a senior sysadmin listing shares
more IT nouns with an IT resume than an HR-worded Pathways listing does.

Eligibility is not a similarity problem. It is a set membership problem,
and USAJOBS states the answer in plain text on every posting under the
heading "This job is open to". The tool was already downloading that page
and discarding the section.

The vocabulary below is USAJOBS' own fixed list of hiring paths, so this
is matching against a closed set rather than guessing at free text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# Canonical key -> the labels USAJOBS prints for it. Order matters: the
# longest label is tried first so "Federal employees - Competitive service"
# is not swallowed by a bare "Federal employees" prefix.
HIRING_PATHS: dict[str, tuple[str, ...]] = {
    "public": ("The public", "Open to the public"),
    "federal_competitive": ("Federal employees - Competitive service",),
    "federal_excepted": ("Federal employees - Excepted service",),
    "internal_agency": ("Internal to an agency",
                        "Internal to the agency"),
    "career_transition": ("Career transition (CTAP, ICTAP, RPL)",
                          "Career transition"),
    "students": ("Students",),
    "recent_graduates": ("Recent graduates",),
    "veterans": ("Veterans",),
    "military_spouses": ("Military spouses",),
    "disability": ("Individuals with disabilities",),
    "native_americans": ("Native Americans",),
    "peace_corps": ("Peace Corps & AmeriCorps Vista",
                    "Peace Corps and AmeriCorps Vista", "Peace Corps"),
    "family_overseas": ("Family of overseas employees",),
    "land_management": ("Land & base management", "Land and base management"),
    "national_guard": ("National Guard & reserves",
                       "National Guard and reserves"),
    "special_authorities": ("Special authorities",),
    "senior_executives": ("Senior executives",),
}

# Paths that an applicant either holds or does not, with no route in for
# somebody outside them. A posting open ONLY to these, for a user who has
# none of them, is a dead end rather than a long shot, so it is dropped.
HARD_PATHS = frozenset({
    "federal_competitive",
    "federal_excepted",
    "internal_agency",
    "career_transition",
    "senior_executives",
})

# Human-readable reasons, used verbatim in the rendered output so the user
# is told why a posting was hidden rather than just given a shorter list.
PATH_LABELS = {key: labels[0] for key, labels in HIRING_PATHS.items()}

_SECTION_HEADING = "this job is open to"

# Headings that live in the same block but name no audience. "Help" is a
# tooltip trigger; the clarification is the agency's own free-text note.
_NOT_A_PATH = frozenset({"help", "clarification from the agency"})


def _normalise(label: str) -> str:
    """Fold a printed label to a comparison key.

    USAJOBS is inconsistent about the ampersand: the same path renders as
    "National Guard & reserves" in one place and "National Guard and
    reserves" in another.
    """
    text = label.strip().lower().replace("&", "and")
    return re.sub(r"\s+", " ", text)


_LABEL_TO_KEY = {
    _normalise(label): key
    for key, labels in HIRING_PATHS.items()
    for label in labels
}
# Longest first, so "federal employees - competitive service" is never
# shadowed by a shorter label contained inside it.
_ORDERED = sorted(_LABEL_TO_KEY.items(), key=lambda pair: -len(pair[0]))


def paths_from_headings(headings: list[str]) -> list[str]:
    """Canonical keys for a list of printed heading texts, order stable.

    Exact label matching, because the block is a list of headings from a
    closed vocabulary rather than prose. An unrecognised heading is
    ignored rather than guessed at.
    """
    found: set[str] = set()
    for heading in headings or []:
        key = _LABEL_TO_KEY.get(_normalise(heading))
        if key is not None:
            found.add(key)
    return [key for key in HIRING_PATHS if key in found]


def paths_from_text(section_text: str) -> list[str]:
    """Fallback for when the headings cannot be read.

    Substring matching over the block's text, longest label first with each
    hit blanked out so a long label cannot also register as a short one
    nested inside it. Only ever applied to the block itself: run over a
    whole posting it would find "Veterans" thirty times in prose that has
    nothing to do with who may apply.
    """
    if not section_text:
        return []
    working = _normalise(section_text)
    found: set[str] = set()
    for label, key in _ORDERED:
        if label in working:
            found.add(key)
            working = working.replace(label, " ")
    return [key for key in HIRING_PATHS if key in found]


def hiring_path_block(soup):
    """The element holding the audience headings, or None.

    Walks up from the "This job is open to" heading until it reaches an
    ancestor that actually contains sub-headings. The nearest enclosing div
    is a layout wrapper around the heading alone, with the audiences in a
    sibling, so stopping at the first parent finds a block naming nobody.
    """
    try:
        headings = soup.find_all(["h1", "h2", "h3"])
    except Exception:
        return None
    for heading in headings:
        try:
            if _normalise(heading.get_text(" ", strip=True)) != _SECTION_HEADING:
                continue
            node = heading.parent
            for _ in range(6):
                if node is None:
                    break
                subs = [h for h in node.find_all(["h3", "h4"])
                        if h is not heading]
                if subs:
                    return node
                node = node.parent
        except Exception:
            continue
    return None


def extract_hiring_paths(soup) -> list[str]:
    """Hiring paths a posting is open to, read from its detail page.

    Structure first: inside the block, each audience is its own `h3`, which
    is a closed list to match against exactly. The text fallback exists
    because this markup has already been rewritten once during this
    project's life, and a section that cannot be read has to degrade to
    "unknown" rather than to "open to nobody".
    """
    block = hiring_path_block(soup)
    if block is None:
        return []
    try:
        headings = [node.get_text(" ", strip=True)
                    for node in block.find_all(["h3", "h4"])]
    except Exception:
        headings = []
    headings = [h for h in headings if _normalise(h) not in _NOT_A_PATH]

    keys = paths_from_headings(headings)
    if keys:
        return keys
    try:
        return paths_from_text(block.get_text(" ", strip=True)[:2000])
    except Exception:
        return []


@dataclass
class Eligibility:
    """The verdict for one posting against one user profile."""

    verdict: str                       # "eligible" | "conditional" | "blocked"
    matched: list[str] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)
    reason: str = ""

    @property
    def blocked(self) -> bool:
        return self.verdict == "blocked"


def assess(job_paths: list[str], profile: set[str]) -> Eligibility:
    """Whether a posting is open to somebody with `profile`.

    Three verdicts rather than two, for the same reason the extraction gate
    has three: collapsing "I am not sure" into either yes or no forces the
    tool to either hide a job the user could have got, or to pad the list
    with dead ends. Both are the complaint this module exists to answer.

      eligible     the posting names a path the user holds
      conditional  no overlap, but the paths involved are ones an outsider
                   sometimes has a route into, so it is shown and marked
      blocked      the posting is open only to paths that are membership
                   facts the user does not have, so it is dropped

    A posting whose section could not be parsed is `conditional`, never
    `blocked`. Hiding a job because a page failed to parse is the same
    mistake as reporting zero results because a selector broke.
    """
    paths = list(job_paths or [])
    if not paths:
        return Eligibility("conditional", [], [],
                           "USAJOBS did not say who this is open to")

    matched = [key for key in paths if key in profile]
    if matched:
        return Eligibility(
            "eligible", matched, paths,
            "open to " + ", ".join(PATH_LABELS[key].lower() for key in matched))

    if all(key in HARD_PATHS for key in paths):
        return Eligibility(
            "blocked", [], paths,
            "open only to " + ", ".join(PATH_LABELS[key].lower()
                                        for key in paths))

    # Name every audience, not only the ones the user might pursue. Listing
    # the soft paths alone reads as "open to veterans", when the posting is
    # really a federal-employee vacancy that also takes veterans.
    return Eligibility(
        "conditional", [], paths,
        "open to " + ", ".join(PATH_LABELS[key].lower() for key in paths)
        + ", none of which you have claimed")
