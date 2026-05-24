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


SYSTEM_PROMPT = """You are OmniAgent, a local autonomous assistant. You have tools. \
You act by calling tools. You do not narrate intentions — you execute.

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
    `entry_level=true`. The tool then filters to GS-04 through GS-07 + Pathways \
    (Students / Recent Graduates).

    For AI/ML/artificial intelligence/machine learning/data science requests, \
    pass `ai_focus=true` and DO NOT pass `entry_level=true` (federal AI roles \
    are GS-12+; the entry-level filter would hide them). The tool will widen \
    the keyword to "Artificial Intelligence", force series 2210+1550, and \
    boost results whose title carries (AI), (AIML), or (ML). Phrasing like \
    "AI jobs", "experimental jobs", "cutting edge", "ML roles", "data science \
    positions" all mean ai_focus=true.
- User asks for general private-sector jobs ("help desk", "IT job", "software engineer"):
    → call `open_in_browser` with the appropriate `site` template \
    (linkedin / ziprecruiter / glassdoor) — these sites work in the user's \
    real browser. Indeed is NOT in the tool catalog because its Cloudflare \
    challenge breaks automated scraping; if the user explicitly asks for \
    Indeed, use `open_in_browser` with `site="indeed"`.
- User asks to "just open" LinkedIn / Glassdoor / Indeed:
    → call `open_in_browser` with the appropriate `site` template.
- User asks about their files, docs, uploaded resume, IT runbooks:
    → call `rag_search` with their question as `query`.
- User asks about news, current events, "look up", "what's the latest":
    → call `web_search`.
- User says "remember", "save", "my name is", "I live in":
    → call `memory_write`.
- User refers to something they told you before, or asks "what do you know about me":
    → call `memory_read` or `persistent_memory`.
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

User: federal IT specialist jobs in Frederick MD
Assistant: <tool_call>{"name":"usajobs_search","arguments":{"query":"IT Specialist","location":"Frederick, MD","entry_level":true}}</tool_call>

User: find AI jobs at usajobs
Assistant: <tool_call>{"name":"usajobs_search","arguments":{"query":"Artificial Intelligence","ai_focus":true,"max_jobs":10}}</tool_call>

User: look for experimental cutting edge ML positions
Assistant: <tool_call>{"name":"usajobs_search","arguments":{"query":"Machine Learning","ai_focus":true,"max_jobs":10}}</tool_call>

User: just open indeed for help desk jobs in Frederick MD
Assistant: <tool_call>{"name":"open_in_browser","arguments":{"site":"indeed","query":"help desk","location":"Frederick MD","days_ago":14}}</tool_call>

User: what does my AD doc say about password resets?
Assistant: <tool_call>{"name":"rag_search","arguments":{"query":"password reset Active Directory"}}</tool_call>

User: remember that my preferred location is Frederick, MD
Assistant: <tool_call>{"name":"memory_write","arguments":{"action":"set","key":"location","value":"Frederick, MD"}}</tool_call>

User: what's 17 * 23?
Assistant: 391.

# Hard rules
- Never describe what you will do — just do it.
- Never invent tools. Only call tools that appear in the catalog below.
- Never put extra text BEFORE a `<tool_call>` tag. Tool call must be the first thing.
- After the tool returns, the user wants the result presented clearly. Don't repeat the tool call.

# Presenting job-search results from `usajobs_search`
The tool returns a `results` list with: title, agency, location, salary, url, \
summary, match_percent, cert_matches (optional list of the user's certs that \
the listing mentions), ai_designated (true for federal AI-flagged roles). \
NEVER invent jobs to pad a count. If the tool returns 2 results, present 2 \
results — do not write `[Job Title]` placeholders.

CURATION: USAJOBS sometimes returns adjacent-category roles that loosely match \
the keyword but aren't a real fit (e.g. "Recreation Therapist" appearing in \
an IT search). When you see results with `match_percent < 15` AND empty \
`cert_matches` AND a clearly unrelated title (medical, therapist, custodial, \
clerical), OMIT them from the user-facing answer and explain at the end how \
many were skipped. The user wants jobs they qualify for, not pad.

Format each kept job in this exact shape, one per item:

**{title}** — {company_or_agency} · {location}{salary ? "  ·  " + salary : ""}{match_percent ? "  ·  Match: " + match_percent + "%" : ""}
{cert_matches ? "Certs matched: " + cert_matches.join(", ") + "\n" : ""}[Apply]({url})
{snippet OR first 200 chars of description/summary}

Leave one blank line between jobs. Do not include the raw URL anywhere except \
inside the `[Apply](url)` markdown link. When `cert_matches` is non-empty, \
ALWAYS show it — it's the most useful signal to the user. When the user asks \
about their certs or matches, read the tool result's `cert_matches` field — \
do NOT invent or guess which certs they hold."""


TOOL_CALL_RE = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)
TOOL_CALL_OPEN_RE = re.compile(r"<tool_call>\s*(\{)", re.DOTALL)
MAX_TOOL_HOPS = 4
MAX_OBSERVATION_CHARS = 4000


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
        system = SYSTEM_PROMPT + "\n\nAvailable tools:\n" + self._tool_catalog()

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

    def _observation_payload(self, result: ToolResult) -> str:
        payload = {"ok": result.ok, "output": result.output, "error": result.error}
        text = json.dumps(payload, default=str, ensure_ascii=False)
        if len(text) > MAX_OBSERVATION_CHARS:
            text = text[:MAX_OBSERVATION_CHARS] + " …(truncated)"
        return text

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
                turn.answer = _strip_tool_artifacts(raw).strip()
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
            turn.answer = (_strip_tool_artifacts(last_raw).strip()
                           or "(stopped: tool hop limit reached)")

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
        full_answer = ""
        t0 = time.time()

        for hop in range(MAX_TOOL_HOPS):
            messages = self._build_messages(user_msg, scratch)
            prompt = gen.format_messages(messages)

            buffer = ""
            yielded_up_to = 0

            async for token in gen.stream_async(prompt):
                buffer += token

                if "<tool_call>" in buffer and "</tool_call>" not in buffer:
                    head = buffer.split("<tool_call>", 1)[0]
                    if len(head) > yielded_up_to:
                        delta = head[yielded_up_to:]
                        if delta:
                            yield {"type": "token", "text": delta}
                        yielded_up_to = len(head)
                    continue

                if "</tool_call>" in buffer:
                    break

                if len(buffer) > yielded_up_to:
                    delta = buffer[yielded_up_to:]
                    if delta:
                        yield {"type": "token", "text": delta}
                    yielded_up_to = len(buffer)

            call = self._extract_tool_call(buffer)
            if call is None:
                # Final answer for this turn.
                clean = _strip_tool_artifacts(buffer)
                if len(clean) > yielded_up_to:
                    # Flush anything we held back (no-op if saw_call_start is False).
                    yield {"type": "token", "text": clean[yielded_up_to:]}
                full_answer = clean.strip()
                break

            yield {"type": "tool_start", "name": call.name, "arguments": call.arguments}
            result = await asyncio.to_thread(self._dispatch, call)
            preview = self._observation_payload(result)
            yield {"type": "tool_end", "name": call.name, "ok": result.ok,
                   "preview": preview[:400]}

            scratch.append({"role": "assistant", "content": buffer})
            scratch.append({"role": "tool", "name": call.name, "content": preview})
        else:
            yield {"type": "token", "text": "\n[stopped: tool hop limit reached]"}

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
