"""Central agent: tool-calling loop. The LLM is the brain.

This replaces RAGAgent's rigid pipeline (always-retrieve →
always-verify → always-correct). The LLM sees a tool catalog and the
user message; it chooses what to do. For pure chat ("hi", "what's
2+2") it just answers. For doc lookups it calls `rag_search`. For
current-events lookups it calls `web_search`. For domain tasks it
calls a registered skill by name. The same loop drives both the
non-streaming `run()` path and the async SSE `stream()` path.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass, field
from typing import AsyncIterator

from core.model_manager import ModelManager
from core.tool_protocol import Tool, ToolCall, ToolResult
from security import audit_log, validate_query, ValidationError


SYSTEM_PROMPT = """You are omnigab, a local autonomous assistant. You have tools. \
You act by calling tools. You do not narrate intentions — you execute.

## What you are — answer questions about this accurately

You run entirely on the user's own computer. The model generating these words \
is a GGUF file loaded through llama.cpp on their hardware. There is no server, \
no account, and no API key. You were not trained by and are not hosted by \
OpenAI, Anthropic, or Google. Never claim to be ChatGPT, Claude, or Gemini.

State these facts confidently when asked about privacy or security:
  * Nothing typed here is uploaded anywhere. There is no cloud backend.
  * Documents added in the Docs tab are indexed into a vector store on this \
    machine and never leave it.
  * Memory is a local SQLite file on this machine.
  * The only network activity is user-initiated: web search, job board \
    lookups, CVE lookups, and downloading a model. Turn web search off and \
    the app works with no network at all.

Private and sensitive documents are precisely what this software is built \
for. Never advise the user to avoid adding personal, financial, medical, or \
confidential files, and never suggest the data would be safer elsewhere. \
That advice is false here and defeats the purpose of running locally. If the \
user asks whether their files are safe to add, the answer is yes, and the \
reason is that the files never leave their computer.

# The single most important rule
If the user asks you to DO something that requires a tool, your VERY FIRST tokens \
in the response must be `<tool_call>`. Do not write any prose first. Do not say \
"Sure, I'll do that" or "Let me find those" — that wastes tokens and the user \
sees nothing happen. Either you are answering from memory (pure chat) or you \
are calling a tool. There is no in-between.

# Tool-call format (strict)
<tool_call>{"name": "TOOL_NAME", "arguments": {"key": "value"}}</tool_call>

After the closing tag the system will execute the tool and feed you the result \
as a `[tool:TOOL_NAME]` message. Then you continue: either call another tool or \
write the final prose answer to the user.

# When to call which tool
- User mentions Space Force, USSF, federal, government, DoD, NSA, CIA, GS-grade, \
  USAJOBS, military, security clearance, or any agency-specific role:
    → call `usajobs_search`. Use SHORT generic keywords like "Cybersecurity", \
    "IT Specialist", "Network Administrator". DO NOT put cert names \
    (Security+, Network+, CCNA…) in the `query` field — federal postings are \
    indexed by OPM series code, not by cert, and including certs returns zero \
    results. The tool strips them automatically and auto-injects series 2210 \
    for IT/cyber queries.

    ALWAYS pass `entry_level=true` UNLESS the user explicitly asks for senior / \
    management / GS-12+ / "experienced" / "lead" roles, OR the request is about \
    AI/ML. Phrasing like "jobs I qualify for", "match my certs", "find me jobs", \
    "for me", "what could I apply to" all mean entry-level — pass \
    `entry_level=true`. The tool then returns Pathways postings \n    (Students / Recent Graduates) at any grade, merged with ordinary \n    postings at GS-09 and below.

    For AI/ML/artificial intelligence/machine learning/data science requests, \
    pass `ai_focus=true` and DO NOT pass `entry_level=true` (federal AI roles \
    are GS-12+; the entry-level filter would hide them). The tool will widen \
    the keyword to "Artificial Intelligence", force series 2210+1550, and \
    boost results whose title carries (AI), (AIML), or (ML). Phrasing like \
    "AI jobs", "experimental jobs", "cutting edge", "ML roles", "data science \
    positions" all mean ai_focus=true.
- User asks for general private-sector jobs ("help desk", "IT job", "software \
  engineer"), or asks to look beyond federal listings:
    → call `job_boards_search`. It returns live postings from Amazon Jobs, \
    RemoteOK, and any Greenhouse or Lever company board, AND prefilled search \
    links for LinkedIn, Handshake, and Indeed, which prohibit automated access \
    and are handed to the user's own browser instead. Pass `location` when the \
    user names one. Use `usajobs_search` for federal roles, and both when the \
    user wants a full picture. Reserve `open_in_browser` for when the user \
    explicitly asks to "just open" a site. Never call `open_in_browser` after \
    a job search has already returned results: the browser links are part of \
    that result and are shown to the user for you, and calling it opens a tab \
    on their desktop that they did not ask for.
- User asks to "just open" LinkedIn / Glassdoor / Indeed:
    → call `open_in_browser` with the appropriate `site` template.
- User asks about their files, docs, uploaded resume, IT runbooks:
    → call `rag_search` with their question as `query`.
- User asks about news, current events, "look up", "what's the latest":
    → call `web_search`.
- User says "remember", "save", "my name is", "I live in":
    → call `memory_write` OR `persistent_memory action=remember`.
- User refers to something they told you before, or asks "what do you know about me":
    → call `memory_read` or `persistent_memory action=search`.
- User mentions a CVE id (CVE-YYYY-NNNN), asks about a vulnerability,
  whether something is "actively exploited", or asks about the CISA KEV catalog:
    → call `cve_lookup`. Actions: 'cve' for NVD lookup, 'kev_search' for
    vendor/product, 'kev_recent' for last N days, 'is_in_kev' for quick membership.
- User asks for arithmetic, JSON/CSV manipulation, regex testing, hash
  computation, statistics, or any precise calculation that you should NOT
  guess at:
    -> call `python_eval` with a short snippet using print() for output.
    Sandbox is isolated and disposable — fine to use freely for computation,
    but DON'T use it for tasks the user wants persisted (memory_write for that).
- After a `usajobs_search` returns a result with `match_percent >= 85`:
    → proactively offer to draft a tailored federal resume for that posting.
    If the user says yes (or says "draft it", "make me a resume", etc.),
    call `draft_federal_resume` with the job's `url` from the search result.
    The tool returns a draft path under data/resume_drafts/.
- User states a STABLE preference or fact in passing (e.g. "I prefer remote-only
  jobs", "I'm a junior at UMD majoring in CS", "my certs are Sec+ and A+",
  "I'm targeting Maryland and DC"): proactively call
  `persistent_memory` with `action=remember` to save it. Do this even if the
  user didn't explicitly say "remember" — long-term memory is how the agent
  grows with the user. Brief observations should be saved as `category=fact`,
  workflow preferences as `category=preference`, behavior rules as
  `category=instruction`. Don't save chit-chat or single-turn questions.
- User asks a question you can answer from general knowledge ("what is 2+2", \
  "explain TLS"), OR a greeting/small talk:
    → answer directly, no tool call.

# Examples
User: hey
Assistant: Hi! What can I help with?

User: find me 5 entry level IT jobs
Assistant: <tool_call>{"name":"usajobs_search","arguments":{"query":"IT Specialist","entry_level":true,"max_jobs":5}}</tool_call>

User: find me Space Force cyber operations entry-level roles
Assistant: <tool_call>{"name":"usajobs_search","arguments":{"query":"Cybersecurity","entry_level":true,"max_jobs":10}}</tool_call>

User: federal IT specialist jobs in Austin TX
Assistant: <tool_call>{"name":"usajobs_search","arguments":{"query":"IT Specialist","location":"Austin, TX","entry_level":true}}</tool_call>

User: find AI jobs at usajobs
Assistant: <tool_call>{"name":"usajobs_search","arguments":{"query":"Artificial Intelligence","ai_focus":true,"max_jobs":10}}</tool_call>

User: look for experimental cutting edge ML positions
Assistant: <tool_call>{"name":"usajobs_search","arguments":{"query":"Machine Learning","ai_focus":true,"max_jobs":10}}</tool_call>

User: find me some help desk jobs in Austin
Assistant: <tool_call>{"name":"job_boards_search","arguments":{"query":"help desk","location":"Austin, TX"}}</tool_call>

User: can you look outside usajobs too
Assistant: <tool_call>{"name":"job_boards_search","arguments":{"query":"IT Specialist"}}</tool_call>

User: just open indeed for help desk jobs in Austin TX
Assistant: <tool_call>{"name":"open_in_browser","arguments":{"site":"indeed","query":"help desk","location":"Austin TX","days_ago":14}}</tool_call>

User: what does my AD doc say about password resets?
Assistant: <tool_call>{"name":"rag_search","arguments":{"query":"password reset Active Directory"}}</tool_call>

User: remember that my preferred location is Austin, TX
Assistant: <tool_call>{"name":"memory_write","arguments":{"action":"set","key":"location","value":"Austin, TX"}}</tool_call>

User: what's 17 * 23?
Assistant: 391.

# Hard rules
- Never describe what you will do — just do it.
- Never invent tools. Only call tools that appear in the catalog below.
- Never put extra text BEFORE a `<tool_call>` tag. Tool call must be the first thing.
- After the tool returns, the user wants the result presented clearly. Don't repeat the tool call.

# Presenting job-search results from `usajobs_search`
The tool returns a `results` list. Each item has: title, agency, location, \
salary, url, summary, description (full duties text), qualifications (full \
requirements text), series_code, status, match_percent, cert_matches \
(optional list of the user's certs that the listing mentions), ai_designated \
(true for federal AI-flagged roles).

## GROUNDING RULES — non-negotiable

You are reporting LIVE SCRAPED DATA. Every URL in the tool result has been \
verified to return HTTP 200 and the listing has been confirmed open on the \
live USAJOBS page. The tool already discarded dead links, closed postings, \
and off-series results before handing the list to you.

YOU MUST:
1. **Use ONLY the exact `url` string from each tool result.** Never construct, \
   shorten, modify, or guess a URL. Never write `[Apply](https://www.usajobs.gov/...)` \
   from memory. Copy the exact `url` field, character for character.
2. **Use ONLY the exact `title` from each tool result.** Do not paraphrase, \
   capitalize differently, or invent variants like "IT Specialist (Cyber)" \
   when the field says "IT SPECIALIST".
3. **Use ONLY the exact `agency`, `location`, `salary`, `grade` fields.** \
   If a field is empty or null, write "(not listed)" — do NOT guess based on \
   the agency name or job title.
4. **Never present a job that is not in the tool's `results` list.** If the \
   tool returned 3 results, you present 3. Padding with `[Job Title]` \
   placeholders or fabricated entries is forbidden.
5. **Never re-order or skip results unless they meet the curation rule below.**
6. The user can click any link you present. If you make one up, they see a \
   404 and you've broken the trust of the entire app.

## Evaluating fit — the most important section

`match_percent` is a coarse cosine similarity from the resume embedding. \
Treat it as ONE signal, not the verdict. The user's actual qualification \
profile is:
  * Active student in an IT degree program.
  * Holds CompTIA A+ and Security+ (and possibly Network+ / others).
  * Limited paid experience.

Read `qualifications` and `description` carefully. Apply these rules when \
deciding what to present and how to describe each role:

1. **Pathways / Recent Graduate / Student Trainee** roles satisfy the \
   "degree required" line via the user's active enrollment. Treat these as \
   STRONG matches even when `match_percent` is low. Federal Pathways was \
   built for exactly this profile.
2. An active **Security+** is worth roughly 2 years of relevant experience \
   for any role that lists IAT Level II / DoD 8570 / 8140 compliance, or \
   any cyber-leaning IT role. Lead with it.
3. An active **A+** covers most "help desk", "customer support", \
   "user support", and entry-level sysadmin postings.
4. Missing years-of-experience requirements are NOT a hard disqualifier \
   when the user has a relevant cert that the posting names. Federal \
   substitution rules (5 CFR 300, 5 CFR 338) let qualifying education + \
   certs substitute for general experience at GS-05 through GS-07.
5. Don't downgrade a role just because the user lacks a master's degree or \
   active TS/SCI — flag those as "requires clearance sponsorship" but \
   still present the role if everything else fits.

When you write the per-job blurb, lead with WHY it's a match: cite the \
specific cert or Pathways path that bridges the gap. Don't restate the \
job description.

## Curation
USAJOBS sometimes returns adjacent-category roles. The tool now strictly \
filters by series code, but if a clearly-unrelated title slips through \
(medical, therapist, custodial, clerical) AND `match_percent < 10` AND \
`cert_matches` is empty, OMIT it from the user-facing answer and note \
how many were skipped.

## Judging the results

Say which posting is the strongest fit and why, in plain prose, as your answer. Useful signals, in rough order:
  * the hiring path is student / recent graduate / Pathways, which for an     active student means strong eligibility
  * the posting names a cert the user holds (Security+, A+, Network+)
  * the gap that shows up across several of them, in one short clause:     missing years, missing clearance, grade too senior

Do NOT wrap that judgement in `<thinking>` tags. An earlier version of this prompt demanded a `<thinking>` block here, and the app renders anything inside those tags as dimmed reasoning rather than as an answer, so the judgement was greyed out and the user was left with no visible reply at all. Reasoning tags are for working, not for output.

## Format

Job search results are rendered for you.

When `usajobs_search` or `job_boards_search` returns, the posting list
(titles, agencies, match percentages, and apply links) is formatted
deterministically in Python and appended below your reply. That includes the
browser handoff links for the boards that prohibit automation, so those reach
the user without you writing them. Do NOT list the jobs yourself and do NOT
write any URLs. Write one or two sentences of useful commentary, for
example which posting is the strongest fit and why, or what gap shows up
across several of them. Then stop.

## When calling usajobs_search — location field

The `location` argument is sent directly to USAJOBS. Pass canonical
full forms ONLY:
  * "Washington, DC" — NOT "DC", "D.C.", "Wash", or "Washington"
  * "New York, NY" — NOT "NYC" or "NY"
  * "Los Angeles, CA" — NOT "LA"
  * Maryland-area users near DC: prefer `location=""` (nationwide) when
    asking for AI/ML federal roles, since most are negotiable or
    DC-metro by default anyway.

Truncating "Washington DC" to "Wash" zeroes out the search."""


from core import job_renderer


TOOL_CALL_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)
TOOL_CALL_OPEN_RE = re.compile(r"<tool_call>\s*(\{)", re.DOTALL)
MAX_TOOL_HOPS = 4
# Bumped 4000 -> 12000 because a usajobs_search result with 10-50 jobs
# easily exceeds 4000 chars even after slimming. Truncating mid-JSON
# was causing the model to lose track of fields (URLs, match_percent)
# and template-collapse the output (every job rendered with the first
# job's title). 12000 chars is ~3000 tokens — fits comfortably alongside
# the system prompt and history inside an 8192-token context.
MAX_OBSERVATION_CHARS = 12000

# Appended to the scratch when the hop budget runs out, so the model gets
# one turn to answer from what it already gathered.
#
# Sent with role "user" rather than "system" on purpose: chat templates
# vary in whether they accept a second system message mid-conversation,
# and several silently drop it, which would turn this into a no-op that is
# invisible until someone reads the rendered prompt.
#
# The last sentence is not decoration. A tool that fails and a tool that
# legitimately finds nothing both end with an empty result list, and the
# model reaching for the friendlier reading of that is how the app came to
# tell users there were no federal jobs while USAJOBS held several hundred.
FINAL_ANSWER_NUDGE = (
    "Your tool budget for this turn is spent. Do not call another tool. "
    "Answer now, using only the tool results above. If they did not "
    "produce what the user asked for, say so plainly, say what you did "
    "find, and suggest the next step. If a tool reported an error, report "
    "the error; never describe a failed search as one that found nothing."
)
# Every generation stops before this many trailing characters so a
# partially arrived "<tool_call>" tag is never shown to the user.
_TAG_HOLDBACK = len("<tool_call>")


def _extract_balanced_json(text: str, start_idx: int) -> tuple[dict | None, int]:
    """Walk braces from `start_idx` (must point at '{') and return the
    parsed JSON dict + index just past the closing brace. Tolerates
    strings containing braces. Returns (None, start_idx) on failure.
    """
    depth = 0
    in_string = False
    escape = False
    i = start_idx
    while i < len(text):
        ch = text[i]
        if escape:
            escape = False
        elif ch == "\\" and in_string:
            escape = True
        elif ch == '"':
            in_string = not in_string
        elif not in_string:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start_idx:i + 1]), i + 1
                    except json.JSONDecodeError:
                        return None, start_idx
        i += 1
    return None, start_idx


@dataclass
class AgentTurn:
    answer: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    tokens: int = 0
    tps: float = 0.0
    elapsed: float = 0.0
    model: str = ""


class Agent:
    """Tool-calling agent over a model + a tool registry."""

    def __init__(self, model_manager: ModelManager, tools: dict[str, Tool], memory,
                 persistent_memory=None):
        self.mm = model_manager
        self.tools = tools
        self.memory = memory
        # Optional SQLite-backed memory. When present, a snapshot is
        # injected into every turn so the model recalls facts across
        # sessions without an explicit tool call.
        self.persistent_memory = persistent_memory
        self.history: list[dict[str, str]] = []
        self.max_history = 8

    # ----- prompt assembly --------------------------------------------

    def _tool_catalog(self) -> str:
        if not self.tools:
            return "(no tools available)"
        lines = []
        for name, tool in self.tools.items():
            schema = json.dumps(tool.input_schema, separators=(",", ":"))
            lines.append(f"- {name}: {tool.description}\n  args: {schema}")
        return "\n".join(lines)

    def _build_messages(self, user_msg: str, scratch: list[dict]) -> list[dict]:
        system = SYSTEM_PROMPT

        # Tell the model which weights it is actually running, so "what model
        # are you" gets a true answer instead of a guess from training data.
        model_name = getattr(self.mm, "current_model_name", "") or ""
        if model_name:
            system += (f"\n\nThe model file you are running right now is "
                       f"`{model_name}`, loaded locally via llama.cpp. "
                       f"Give this name if asked which model you are.")

        system += "\n\nAvailable tools:\n" + self._tool_catalog()

        # User prefs from the legacy JSON store.
        try:
            extra_ctx = self.memory.build_prompt_context() if self.memory else ""
        except Exception:
            extra_ctx = ""
        if extra_ctx:
            system += "\n\nUser context:\n" + extra_ctx

        # Persistent SQLite memory snapshot — auto-injected so the model
        # remembers facts across sessions without an explicit tool call.
        if self.persistent_memory is not None:
            try:
                snap = self.persistent_memory.snapshot_for_prompt()
                if snap:
                    system += "\n\n" + snap
            except Exception:
                pass

        msgs: list[dict] = [{"role": "system", "content": system}]
        msgs.extend(self.history[-self.max_history:])
        msgs.append({"role": "user", "content": user_msg})
        msgs.extend(scratch)
        return msgs

    # ----- tool dispatch ---------------------------------------------

    def register_tool(self, tool: Tool) -> None:
        self.tools[tool.name] = tool

    def clear_history(self) -> None:
        self.history = []

    def _extract_tool_call(self, text: str) -> ToolCall | None:
        """Extract a tool call from model output.

        Accepts both the strict form (`<tool_call>...</tool_call>`) and
        the truncated form (`<tool_call>{...}` with the closing tag
        missing because the model stopped early). The truncated form is
        common: Qwen often treats the JSON's final `}` as a natural
        stopping point and never emits `</tool_call>`.
        """
        # Strict form first — cheapest match.
        m = TOOL_CALL_RE.search(text)
        if m:
            try:
                obj = json.loads(m.group(1))
            except (json.JSONDecodeError, TypeError):
                obj = None
            if isinstance(obj, dict):
                return self._tool_call_from_obj(obj)

        # Fallback: open tag without close tag. Walk braces.
        m_open = TOOL_CALL_OPEN_RE.search(text)
        if m_open:
            obj, _ = _extract_balanced_json(text, m_open.start(1))
            if isinstance(obj, dict):
                return self._tool_call_from_obj(obj)
        return None

    def _tool_call_from_obj(self, obj: dict) -> ToolCall | None:
        name = str(obj.get("name", "")).strip()
        if not name or name not in self.tools:
            return None
        args = obj.get("arguments") or {}
        if not isinstance(args, dict):
            args = {}
        return ToolCall(name=name, arguments=args)

    def _dispatch(self, call: ToolCall) -> ToolResult:
        tool = self.tools.get(call.name)
        if tool is None:
            return ToolResult(name=call.name, ok=False, output=None,
                              error=f"Unknown tool: {call.name}")
        try:
            output = tool.run(call.arguments)
            return ToolResult(name=call.name, ok=True, output=output)
        except Exception as exc:
            audit_log("tool.error", status="error", input_summary=call.name,
                      detail={"error": str(exc), "type": exc.__class__.__name__})
            return ToolResult(name=call.name, ok=False, output=None, error=str(exc))

    # Tools whose results are rendered deterministically in Python. The
    # model receives only a compact, URL-free digest of these, because it
    # never has to reproduce their fields.
    #
    # job_boards_search joined usajobs_search here because it emits URLs
    # too, and invariant I5 is about the model never writing one, not
    # about which board the posting came from. It needed no renderer work:
    # jobs.sources.posting() already normalises to the keys job_renderer
    # reads, which is what its docstring has always claimed and what
    # tests/test_job_boards_rendering.py now actually enforces.
    RENDERED_TOOLS = {"usajobs_search", "job_boards_search"}

    def _observation_payload(self, result: ToolResult) -> str:
        if (result.ok and result.name in self.RENDERED_TOOLS
                and isinstance(result.output, dict)):
            digest = job_renderer.summarize_for_model(result.output)
            if digest:
                # ~200 tokens instead of ~3000, and no URLs to copy wrong.
                return digest
        payload = {"ok": result.ok, "output": result.output, "error": result.error}
        text = json.dumps(payload, default=str, ensure_ascii=False)
        if len(text) > MAX_OBSERVATION_CHARS:
            text = text[:MAX_OBSERVATION_CHARS] + " …(truncated)"
        return text

    def _rendered_blocks(self, results: list[ToolResult]) -> str:
        """Deterministic markdown for the rendered tool results this turn.

        Repeated calls to the same tool are merged into one block and
        deduplicated by URL. A model that searches, reconsiders, and
        searches again used to get every result set rendered in full, so a
        single reply carried the same five postings twice in two different
        orders. Merging is better than keeping only the last, because two
        different queries against the same tool each contribute postings
        the other did not find.
        """
        merged: dict[str, dict] = {}
        for result in results:
            if not (result.ok and result.name in self.RENDERED_TOOLS
                    and isinstance(result.output, dict)):
                continue
            payload = result.output
            if result.name not in merged:
                # Copied, not aliased: the lists below are appended to, and
                # the tool's own result dict must not grow underneath it.
                first = dict(payload)
                first["results"] = list(payload.get("results") or [])
                first["handoffs"] = list(payload.get("handoffs") or [])
                merged[result.name] = first
                continue

            into = merged[result.name]
            seen = {job.get("url") for job in into["results"] if job.get("url")}
            for job in payload.get("results") or []:
                url = job.get("url")
                if url and url in seen:
                    continue
                if url:
                    seen.add(url)
                into["results"].append(job)

            handed = {h.get("url") for h in into["handoffs"] if h.get("url")}
            for handoff in payload.get("handoffs") or []:
                if handoff.get("url") not in handed:
                    handed.add(handoff.get("url"))
                    into["handoffs"].append(handoff)

            into["found"] = len(into["results"])

        blocks = [job_renderer.render_results(payload)
                  for payload in merged.values()]
        return "\n\n".join(block for block in blocks if block)

    # ----- running out of tool hops -----------------------------------

    def _closing_messages(self, user_msg: str, scratch: list[dict]) -> list[dict]:
        """Prompt for the final, tool-free pass after the budget is spent."""
        closing = list(scratch)
        closing.append({"role": "user", "content": FINAL_ANSWER_NUDGE})
        return self._build_messages(user_msg, closing)

    @staticmethod
    def _visible_answer(buffer: str) -> str:
        """Model output with reasoning tags normalized and any tool call cut.

        Splitting at the opening tag rather than stripping the pair matters
        here: the budget is spent, so a tool call in this buffer is never
        going to run, and everything after it is the model talking about
        work that will not happen.
        """
        return normalize_reasoning_tags(buffer).split("<tool_call>", 1)[0]

    def _final_answer(self, gen, user_msg: str, scratch: list[dict],
                      last_raw: str = "") -> str:
        """Answer built from the tool results, after the hops are exhausted.

        Without this the loop fell out of `for ... else` and the turn ended
        with whatever the model happened to say before its last tool call,
        which is usually a sentence announcing the call ("Let me try a
        broader keyword:"). The streaming path was worse: it emitted
        "[stopped: tool hop limit reached]" and no answer at all, so four
        successful tool calls could produce nothing a user could read.

        One extra generation is the cost. It buys a turn where the model
        can only summarise, which is exactly what is missing at this point.
        """
        try:
            prompt = gen.format_messages(self._closing_messages(user_msg, scratch))
            answer = _strip_tool_artifacts(
                self._visible_answer(gen.generate_raw(prompt))).strip()
        except Exception as exc:
            # A failed closing pass must not lose the turn. Fall back to
            # whatever the model last said rather than raising out of a
            # branch the caller reached by running normally.
            audit_log("agent.final_answer", status="error",
                      input_summary=user_msg, detail={"error": str(exc)})
            answer = ""
        if answer:
            return answer
        return (_strip_tool_artifacts(normalize_reasoning_tags(last_raw)).strip()
                or "(stopped: tool hop limit reached)")

    # ----- synchronous turn (tests, CLI) ------------------------------

    def run(self, user_msg: str) -> AgentTurn:
        user_msg = validate_query(user_msg)
        turn = AgentTurn(answer="", model=self.mm.current_model_name)
        t0 = time.time()
        scratch: list[dict] = []
        last_raw = ""

        gen = self.mm.generator
        if gen is None:
            turn.answer = "No model loaded."
            return turn

        for hop in range(MAX_TOOL_HOPS):
            messages = self._build_messages(user_msg, scratch)
            prompt = gen.format_messages(messages)
            raw = gen.generate_raw(prompt)
            last_raw = raw

            call = self._extract_tool_call(raw)
            if call is None:
                turn.answer = _strip_tool_artifacts(
                    normalize_reasoning_tags(raw)).strip()
                break

            turn.tool_calls.append(call)
            result = self._dispatch(call)
            turn.tool_results.append(result)

            scratch.append({"role": "assistant", "content": raw})
            scratch.append({
                "role": "tool",
                "name": call.name,
                "content": self._observation_payload(result),
            })
        else:
            turn.answer = self._final_answer(gen, user_msg, scratch, last_raw)

        rendered = self._rendered_blocks(turn.tool_results)
        if rendered:
            # The list itself is built from the verified tool output, not
            # transcribed by the model. Model prose (if any) sits above it.
            turn.answer = f"{turn.answer}\n\n{rendered}".strip()

        stats = gen.get_last_stats() if hasattr(gen, "get_last_stats") else {}
        turn.tokens = int(stats.get("tokens", 0))
        turn.tps = float(stats.get("tps", 0.0))
        turn.elapsed = round(time.time() - t0, 3)

        self.history.append({"role": "user", "content": user_msg})
        self.history.append({"role": "assistant", "content": turn.answer})
        self._trim_history()
        audit_log("agent.run", status="ok", input_summary=user_msg,
                  detail={"hops": len(turn.tool_calls), "tps": turn.tps})
        return turn

    # ----- async streaming turn (SSE endpoint) ------------------------

    async def stream(self, user_msg: str) -> AsyncIterator[dict]:
        try:
            user_msg = validate_query(user_msg)
        except ValidationError as exc:
            yield {"type": "error", "message": str(exc)}
            return

        gen = self.mm.generator
        if gen is None:
            yield {"type": "error", "message": "No model loaded."}
            return

        scratch: list[dict] = []
        stream_results: list[ToolResult] = []
        full_answer = ""
        t0 = time.time()

        for hop in range(MAX_TOOL_HOPS):
            messages = self._build_messages(user_msg, scratch)
            prompt = gen.format_messages(messages)

            buffer = ""
            visible = ""
            yielded_up_to = 0

            async for token in gen.stream_async(prompt):
                buffer += token
                # Normalized before anything reaches the UI, so a model that
                # thinks in <think> renders the same as one that thinks in
                # <thinking>. Safe on a partial buffer because the rewrite is
                # prefix-preserving; see normalize_reasoning_tags.
                visible = normalize_reasoning_tags(buffer)

                if "<tool_call>" in visible and "</tool_call>" not in visible:
                    head = visible.split("<tool_call>", 1)[0]
                    if len(head) > yielded_up_to:
                        delta = head[yielded_up_to:]
                        if delta:
                            yield {"type": "token", "text": delta}
                        yielded_up_to = len(head)
                    continue

                if "</tool_call>" in visible:
                    break

                if len(visible) > yielded_up_to:
                    delta = visible[yielded_up_to:]
                    if delta:
                        yield {"type": "token", "text": delta}
                    yielded_up_to = len(visible)

            # Tool-call extraction reads the raw buffer. The rewrite only
            # touches reasoning tags, but the parser should still see
            # exactly what the model emitted.
            call = self._extract_tool_call(buffer)
            if call is None:
                # Final answer for this turn.
                clean = _strip_tool_artifacts(visible)
                if len(clean) > yielded_up_to:
                    # Flush anything we held back (no-op if saw_call_start is False).
                    yield {"type": "token", "text": clean[yielded_up_to:]}
                full_answer = clean.strip()
                break

            yield {"type": "tool_start", "name": call.name, "arguments": call.arguments}
            result = await asyncio.to_thread(self._dispatch, call)
            stream_results.append(result)
            preview = self._observation_payload(result)
            yield {"type": "tool_end", "name": call.name, "ok": result.ok,
                   "preview": preview[:400]}

            scratch.append({"role": "assistant", "content": buffer})
            scratch.append({"role": "tool", "name": call.name, "content": preview})
        else:
            # Budget spent. Stream one tool-free pass so the user gets an
            # answer assembled from what the tools actually returned. This
            # branch used to emit the line below and stop, which meant four
            # successful tool calls could end the turn with no answer.
            buffer = ""
            yielded_up_to = 0
            try:
                prompt = gen.format_messages(
                    self._closing_messages(user_msg, scratch))
                async for token in gen.stream_async(prompt):
                    buffer += token
                    visible = self._visible_answer(buffer)
                    # Hold back the tail so a half-arrived "<tool_call>"
                    # never reaches the transcript. Whatever is held back
                    # is flushed below once the stream ends.
                    safe = visible[:-_TAG_HOLDBACK] if len(visible) > _TAG_HOLDBACK else ""
                    if len(safe) > yielded_up_to:
                        yield {"type": "token", "text": safe[yielded_up_to:]}
                        yielded_up_to = len(safe)
            except Exception as exc:
                audit_log("agent.final_answer", status="error",
                          input_summary=user_msg, detail={"error": str(exc)})
            visible = self._visible_answer(buffer)
            if len(visible) > yielded_up_to:
                yield {"type": "token", "text": visible[yielded_up_to:]}
            full_answer = _strip_tool_artifacts(visible).strip()
            if not full_answer:
                full_answer = "[stopped: tool hop limit reached]"
                yield {"type": "token", "text": "\n" + full_answer}

        rendered = self._rendered_blocks(stream_results)
        if rendered:
            block = f"\n\n{rendered}"
            yield {"type": "token", "text": block}
            full_answer = f"{full_answer}{block}".strip()

        stats = gen.get_last_stats() if hasattr(gen, "get_last_stats") else {}
        self.history.append({"role": "user", "content": user_msg})
        self.history.append({"role": "assistant", "content": full_answer or "(no answer)"})
        self._trim_history()

        audit_log("agent.stream", status="ok", input_summary=user_msg,
                  detail={"hops": len(scratch) // 2, "model": self.mm.current_model_name})

        yield {
            "type": "meta",
            "tokens": int(stats.get("tokens", 0)),
            "tps": float(stats.get("tps", 0.0)),
            "elapsed": round(time.time() - t0, 3),
            "model": self.mm.current_model_name,
            "history_len": len(self.history),
        }

    def _trim_history(self) -> None:
        max_msgs = self.max_history * 2  # user+assistant pairs
        if len(self.history) > max_msgs:
            self.history = self.history[-max_msgs:]


def _strip_tool_artifacts(text: str) -> str:
    """Remove any incomplete tool_call fragment from user-visible text."""
    return re.sub(r"<tool_call>.*", "", text, flags=re.DOTALL)


# Reasoning models emit their working in <think> tags natively. This app's
# own system prompt asks for <thinking>, and the desktop renderer already
# dims that spelling so reasoning is visible without looking like an
# answer. Rewriting one to the other is the whole fix: without it a model
# that thinks out loud prints raw tags and its internal monologue into the
# chat as ordinary text.
#
# Deliberately a rename rather than a strip. The reasoning is worth seeing,
# the existing UI already knows how to show it, and stripping would throw
# away the one signal that tells a user why an answer looks as it does.
#
# The rewrite is prefix-preserving, which is what makes it safe to apply to
# a partial buffer while streaming: every prefix of "<think>" is also a
# prefix of "<thinking>", so text already sent to the UI is never
# invalidated by a later token. test_reasoning_tags.py pins that property.
_REASONING_TAG_RE = re.compile(r"<(/?)think>")


def normalize_reasoning_tags(text: str) -> str:
    """Rewrite a model's native `<think>` tags to this app's `<thinking>`.

    Leaves `<thinking>` alone: the pattern requires the closing angle
    bracket immediately after "think", which `<thinking>` does not have.
    """
    if not text:
        return text
    return _REASONING_TAG_RE.sub(r"<\1thinking>", text)
