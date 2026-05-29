"""Built-in tools exposed to the Agent loop."""

from __future__ import annotations

from pathlib import Path

from core.tool_protocol import Tool

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def build_default_toolset(*, embedder, store, web_search, memory,
                          generator_getter, skill_registry,
                          persistent_memory=None,
                          model_manager=None) -> dict[str, Tool]:
    """Construct the full built-in tool catalog plus skill adapters.

    Pass `generator_getter` (a callable returning the current Generator)
    instead of the generator itself so skill tools always pick up the
    live model after a hot swap.
    """
    from tools.rag_search import RagSearchTool
    from tools.web_search_tool import WebSearchTool
    from tools.memory_tools import MemoryReadTool, MemoryWriteTool
    # NOTE: IndeedApplyTool is INTENTIONALLY NOT REGISTERED. Indeed's Cloudflare
    # detection makes scraping unreliable and the tool was creating false
    # negatives. We still import its resume loader / cert extractor below to
    # keep the active-resume + cert pipeline working for usajobs_search.
    from tools.indeed_apply import IndeedApplyTool
    from tools.usajobs_search import UsaJobsSearchTool
    from tools.open_in_browser import OpenInBrowserTool
    from tools.cve_lookup import CveLookupTool
    from tools.python_eval import PythonEvalTool
    from tools.resume_drafter import ResumeDrafterTool
    from tools.skill_adapter import adapt_skill

    tools: dict[str, Tool] = {}

    rag = RagSearchTool(embedder=embedder, store=store)
    tools[rag.name] = rag

    if web_search is not None:
        ws = WebSearchTool(web_search=web_search)
        tools[ws.name] = ws

    mr = MemoryReadTool(memory=memory)
    mw = MemoryWriteTool(memory=memory)
    tools[mr.name] = mr
    tools[mw.name] = mw

    # IndeedApplyTool kept as a helper for its resume+cert plumbing, but NOT
    # exposed to the agent as a tool. The agent should never call indeed_apply.
    _indeed_helper = IndeedApplyTool(embedder=embedder)

    # USAJOBS uses the resume loader + cert extractor for ranking results.
    uj = UsaJobsSearchTool(
        embedder=embedder,
        resume_text_getter=_indeed_helper._load_resume,
        resume_certs_getter=_indeed_helper.resume_certs,
    )
    tools[uj.name] = uj

    # Cloudflare-proof fallback: opens URLs in the user's real browser.
    tools["open_in_browser"] = OpenInBrowserTool()

    # NIST NVD + CISA KEV cyber-intelligence tool.
    cve = CveLookupTool()
    tools[cve.name] = cve

    # Sandboxed Python execution (math, parsing, deterministic compute).
    pyeval = PythonEvalTool()
    tools[pyeval.name] = pyeval

    # Federal-resume drafter — uses live model + active resume + memory.
    # Passing model_manager lets the drafter hot-swap to a 7B for the
    # draft (~3-4× faster than the 14B) and swap back when done.
    drafter = ResumeDrafterTool(
        generator_getter=generator_getter,
        persistent_memory=persistent_memory,
        resume_text_getter=_indeed_helper._load_resume,
        model_manager=model_manager,
    )
    tools[drafter.name] = drafter

    if persistent_memory is not None:
        from tools.persistent_memory_tool import PersistentMemoryTool
        pmt = PersistentMemoryTool(persistent_memory=persistent_memory)
        tools[pmt.name] = pmt

    for skill in skill_registry.enabled_skills():
        try:
            tool = adapt_skill(
                skill,
                generator_getter=generator_getter,
                web_search=web_search,
                memory=memory,
            )
        except Exception as exc:
            print(f"[tools] Failed to adapt skill {skill.name}: {exc}")
            continue
        tools[tool.name] = tool

    return tools
