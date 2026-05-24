# Prompt for Claude Code: Add Skill Learning + Security to omnigab

Paste everything below this line into Claude Code in VSCode.

---

Look at the existing RAG agent project in this folder. It currently does basic document retrieval and answer generation using a local Qwen model via llama-cpp-python, with FAISS vector search and a FastAPI backend.

I want to evolve this into a skill-learning agent with proper security. Here is what I mean by each.

## Skill Learning System

Add a plugin/skill architecture so the agent can acquire new capabilities over time without modifying core code. Specifically:

1. Create a `skills/` directory where each skill is a self-contained Python module with a standard interface (name, description, trigger conditions, execute function). Ship a few example skills: "summarize document", "compare two documents", "extract action items", "web search and cite".

2. Build a skill registry (`src/skill_registry.py`) that auto-discovers skills from the `skills/` folder on startup, maintains a manifest of available skills with their descriptions and trigger patterns, and exposes an API endpoint to list/enable/disable skills.

3. Add a skill router to the agent loop in `src/rag_agent.py`. Before doing a standard RAG retrieval, the agent should classify the user query against available skills and route to the appropriate skill if one matches. If no skill matches, fall back to standard RAG. The router should use the LLM itself to decide which skill to invoke based on the query and skill descriptions.

4. Add a skill creation endpoint or CLI command where a user can define a new skill by providing a name, description, a system prompt template, and optionally a Python function. Store these as JSON+Python in the `skills/` directory. The agent should be able to use newly created skills immediately without restart.

5. Implement skill memory: after a skill executes, store the result quality feedback (thumbs up/down from the user) in a SQLite database. Use this to rank skill suggestions over time. Skills that consistently get negative feedback get deprioritized.

## Security Hardening

Make the agent resistant to prompt injection and malicious input without breaking usability.

1. Sandboxed skill execution: skills should run in a restricted context. They should NOT be able to access the filesystem outside of `data/` and `skills/`, make network requests unless explicitly whitelisted in their manifest, modify other skills or core agent code, or access environment variables or system info.

2. Prompt injection defense: in `src/generator.py` and `src/rag_agent.py`, wrap all retrieved document chunks in clear delimiters like `[RETRIEVED DOCUMENT START]...[RETRIEVED DOCUMENT END]` and add a system prompt instruction telling the model to treat content inside those delimiters as reference data only, never as instructions. Strip any chat template tokens (`<|im_start|>`, `<|im_end|>`, `<|endoftext|>`, etc.) from retrieved chunks before they reach the model.

3. Input validation: add a validation layer for all user inputs. Query length limits, sanitize filenames on upload, validate URLs in web search against an allowlist of schemes (http/https only), and reject any input containing chat template tokens.

4. Localhost-only middleware for FastAPI: add middleware that rejects any request not originating from 127.0.0.1 or ::1. Add a simple bearer token check for write endpoints (token stored in a local `.env` file, generated on first run if not present).

5. Audit logging: log every skill invocation, document ingestion, and model switch to a structured JSON log file in `logs/audit.json` with timestamps, the action taken, input summary (truncated), and result status.

## Implementation Notes

Keep the existing file structure. Add new files rather than rewriting everything. The current entry points (`desktop_app.py`, `src/web_app.py`, `start.bat`, `RAG_Agent.bat`) should all still work. Use the existing venv and only add dependencies if absolutely necessary (prefer stdlib). If you add dependencies, update `requirements.txt` with pinned versions.

Start with the security hardening since it touches existing code, then build the skill system on top. Test each change by verifying the existing RAG query flow still works after your modifications.
