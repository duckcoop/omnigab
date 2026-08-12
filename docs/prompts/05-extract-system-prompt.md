# PR4: Extract and de-conflict the system prompt

There is a live contradiction in the prompt right now. This PR moves the
prompt into files and removes exactly one thing.

---

```
Read AGENTS.md and docs/PLAN.md before doing anything. This is PR4.
PR3 (agent loop tests) must already be merged.

GOAL
`SYSTEM_PROMPT` in `src/core/agent.py` is roughly 5,000 words of
product logic stored as a module-level string constant. It cannot be
diffed usefully, cannot be versioned independently, and mixes
job-search specifics into the core agent loop. It also contains a
contradiction that is actively degrading small-model behavior.

THE CONTRADICTION
The prompt contains a section whose markdown heading begins with
"## Format" and ends with "REQUIRED four lines per job". Search for the
string "REQUIRED four lines per job" to find it.

Immediately after that section, the prompt says:

  "Job search results are rendered for you. When usajobs_search
   returns, the posting list ... is formatted deterministically in
   Python and appended below your reply. Do NOT list the jobs yourself
   and do NOT write any URLs."

Both are in the live prompt at the same time. The second one is
correct: `src/core/job_renderer.py` owns that output, and invariant I5
in AGENTS.md says the model never emits a URL. The four-line format
section is dead instruction left over from before the renderer existed.

TASK
1. Create `src/prompts/` containing:
   - `system.md`: the core identity, the tool-call format, the hard
     rules, the what-you-are section. Everything that applies
     regardless of which tools are registered.
   - `jobs.md`: everything specific to `usajobs_search`,
     `open_in_browser`, `draft_federal_resume`, and job result
     presentation.

2. Load them at runtime and compose. `jobs.md` is appended only when at
   least one job tool is present in the registry. Read
   `src/tools/__init__.py` `build_default_toolset` to see how the
   registry is built.

   Files must be packaged correctly so they still resolve after
   `pip install -e .`. Use `importlib.resources`, not a path relative to
   `__file__`, and make sure `pyproject.toml` includes them as package
   data.

3. Delete the "REQUIRED four lines per job" section entirely, from its
   "## Format" heading through to the line immediately before the "Job
   search results are rendered for you" paragraph. Delete nothing else.

4. Add tests:
   - The assembled prompt for a registry with no job tools does not
     contain the string "usajobs" (case insensitive).
   - The assembled prompt never contains the substring "https://".
   - The assembled prompt contains no instruction to write a URL.
   - Prompt files load correctly from an installed package, not just
     from the source tree.

NON-GOALS
- Do NOT rewrite the prompt's substance. Move it, split it, delete the
  one contradictory section. Nothing else.
- Do NOT reword instructions to sound better.
- Do NOT change tool descriptions or the tool catalog.

Moving files and rewriting behavior in the same diff makes any
regression impossible to attribute. That is the entire reason this PR
is scoped so tightly.

ACCEPTANCE
- `src/core/agent.py` is roughly 250 lines shorter.
- The prompt files are plain markdown, readable on GitHub.
- All four tests above pass.
- Behavior check: run these five queries against the same model before
  and after, and record both outputs in the PR description.
    1. "hey"
    2. "what's 17 * 23"
    3. "find me 5 entry level IT jobs"
    4. "what does my resume say about certifications"
    5. "is CVE-2024-3094 in the KEV catalog"
  Any difference other than the removed four-line format is a
  regression. Report it rather than accepting it.
- `pytest` and `flake8 src tests` clean.

REPORT
Line count of agent.py before and after. The five before/after outputs.
Confirmation that only the one section was deleted, with the deleted
text quoted so I can check.
```
