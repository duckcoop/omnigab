from skill_base import Skill, SkillContext, SkillResult


def _execute(ctx: SkillContext) -> SkillResult:
    if ctx.generator is None:
        return SkillResult(answer="Generator unavailable.")
    context = "\n\n".join(c.get("text", "") for c in ctx.retrieved_chunks)
    prompt = "Summarize this document content for the user query: " + ctx.query
    answer = ctx.generator.generate(
        prompt,
        context,
        user_context=(
            "You are a document summarization skill. Use only retrieved content. "
            "Return a compact summary with key points and any notable caveats."
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
    return SkillResult(answer=answer, sources=sources)


SKILL = Skill(
    name="summarize_document",
    description="Summarize retrieved document chunks.",
    execute=_execute,
    triggers=["summarize", "summary", "tl;dr", "overview"],
)
