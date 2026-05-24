from skill_base import Skill, SkillContext, SkillResult


def _execute(ctx: SkillContext) -> SkillResult:
    if ctx.generator is None:
        return SkillResult(answer="Generator unavailable.")
    context = "\n\n".join(c.get("text", "") for c in ctx.retrieved_chunks)
    answer = ctx.generator.generate(
        "Extract action items for: " + ctx.query,
        context,
        user_context=(
            "You are an action-item extraction skill. Return only actions grounded in the retrieved content. "
            "Use bullets with action, owner, due date, and source when available. If none exist, say so."
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
    name="extract_action_items",
    description="Extract action items from retrieved text.",
    execute=_execute,
    triggers=["action items", "todo", "tasks", "next steps"],
)
