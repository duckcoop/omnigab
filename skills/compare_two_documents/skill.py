from skill_base import Skill, SkillContext, SkillResult


def _execute(ctx: SkillContext) -> SkillResult:
    if ctx.generator is None:
        return SkillResult(answer="Generator unavailable.")
    grouped = {}
    for chunk in ctx.retrieved_chunks:
        source = chunk.get("source") or "unknown"
        grouped.setdefault(source, []).append(chunk.get("text", ""))
    sections = []
    for source, texts in grouped.items():
        sections.append("SOURCE: {}\n{}".format(source, "\n\n".join(texts[:3])))
    context = "\n\n".join(sections)
    prompt = (
        "Compare the documents relevant to this request: {}\n\n"
        "Return similarities, differences, conflicts, and recommended next steps if the documents disagree."
    ).format(ctx.query)
    answer = ctx.generator.generate(
        prompt,
        context,
        user_context=(
            "You are a document comparison skill. Use only retrieved content. "
            "Be explicit about which source supports each important distinction."
        ),
    )
    sources = [
        {
            "file": c.get("source"),
            "chunk": c.get("chunk_index"),
            "score": c.get("score"),
            "preview": (c.get("text") or "")[:100] + "...",
        }
        for c in ctx.retrieved_chunks
    ]
    return SkillResult(answer=answer, sources=sources, metadata={"source_count": len(grouped)})


SKILL = Skill(
    name="compare_two_documents",
    description="Compare retrieved documents.",
    execute=_execute,
    triggers=["compare", "difference", "versus", "contrast"],
)
