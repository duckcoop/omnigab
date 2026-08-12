# PR3: Test the agent loop

The highest-value untested surface in the repository. 29 KB, the heart
of the system, zero coverage.

---

```
Read AGENTS.md and docs/PLAN.md before doing anything. This is PR3.
PR2 (CI) must already be merged.

GOAL
`src/core/agent.py` is the tool-calling loop that everything runs
through, and it has no tests. Every parsing edge case in it is currently
verified by hoping. Cover it with a fake model, so no GGUF file is
needed.

TASK
1. Build a fake model harness in `tests/conftest.py`: something that
   satisfies whatever interface `Agent` expects from `ModelManager` and
   returns a scripted list of responses in order. Read `agent.py` and
   `core/model_manager.py` first to get the interface right. Do not
   change production code to make it testable unless you cannot avoid
   it, and if you cannot, say so before doing it.

2. Cover at minimum:

   `_extract_balanced_json(text, start_idx)`
   - nested braces
   - braces inside a JSON string value, e.g. {"q": "a { b"}
   - escaped quotes inside a string, e.g. {"q": "say \"hi\""}
   - unterminated JSON, returns (None, start_idx)
   - trailing text after the closing brace, returns the correct end
     index
   - malformed JSON that is brace-balanced but not parseable

   `TOOL_CALL_RE` and `TOOL_CALL_OPEN_RE`
   - a clean <tool_call>{...}</tool_call>
   - a call with prose before it (the prompt forbids this, but the
     parser must not break on it)
   - two calls in one response
   - an opening tag with no closing tag
   - a call whose arguments contain a > character

   Loop control
   - `MAX_TOOL_HOPS`: a fake model that emits a tool call forever must
     terminate at 4 hops and still return a coherent AgentTurn rather
     than looping or raising.
   - `MAX_OBSERVATION_CHARS`: a 20,000 character tool result is
     truncated to 12,000 and the resulting message is still well formed.
   - `max_history = 8`: history is trimmed and the trim does not orphan
     a tool result from its call.

   Failure paths
   - the model calls a tool name that is not in the registry
   - a tool's `run()` raises an exception
   - a tool returns something that is not JSON serializable
   In all three: caught, surfaced as a tool result, never a crash.

   Happy path
   - pure chat with no tool call returns the model text unchanged
   - one tool call, one result, one final answer produces the expected
     AgentTurn with tool_calls and tool_results populated

3. Add a coverage floor to the CI job, set to the number this PR
   actually achieves minus 3 points. Use `--cov-fail-under`.

NON-GOALS
- Do NOT refactor `agent.py`. Test what is there. Extraction of the
  system prompt is PR4.
- Do NOT fix bugs you find. Write each into docs/TODOS.md with a
  reproducing test marked `xfail`, so the bug is captured and visible
  without blocking this PR.
- No tests that need a model file or a network.

ACCEPTANCE
- `src/core/agent.py` coverage above 70 percent. Report the exact
  number.
- Every new test runs offline with no model file.
- CI fails when coverage drops below the new floor. Prove it by
  temporarily lowering a threshold locally, then restore.
- `flake8 src tests` clean.

REPORT
Exact coverage for agent.py before and after. Every bug you found,
with the xfail test that captures it. Any place you had to touch
production code to make testing possible, and why it was unavoidable.
```
