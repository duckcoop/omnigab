from skill_base import Skill, SkillContext, SkillResult


def _execute(ctx: SkillContext) -> SkillResult:
    if ctx.web_search is None:
        return SkillResult(answer="Web search is not available for this skill.")
    results = ctx.web_search.search(ctx.query, max_results=3)
    chunks = []
    citations = []
    for chunk, score in results:
        chunks.append(chunk.text)
        citations.append({
            "source": chunk.source_file,
            "score": round(float(score), 4),
        })
    if not chunks:
        return SkillResult(answer="No web results were available.", citations=[])
    if ctx.generator is None:
        answer = "\n\n".join(chunks)
    else:
        answer = ctx.generator.generate(
            "Answer this using the web results and cite the source URLs: " + ctx.query,
            "\n\n".join(chunks),
            user_context=(
                "You are a web-search citation skill. Use only the web results in context. "
                "Include concise citations inline using the source URL labels."
            ),
        )
    sources = [
        {"file": item["source"], "chunk": i, "score": item["score"], "preview": chunks[i][:100] + "..."}
        for i, item in enumerate(citations)
    ]
    return SkillResult(answer=answer, sources=sources, citations=citations)


SKILL = Skill(
    name="web_search_and_cite",
    description="Search the web and cite results.",
    execute=_execute,
    triggers=["web search", "search the web", "latest", "cite"],
    network_allowlist=["duckduckgo.com", "ddg.gg", "html.duckduckgo.com", "lite.duckduckgo.com"],
    requires_retrieval=False,
)
