# PR0a: Get flake8 to zero

Inserted after PR0. Run this **before** PR1, not before PR2.

PR0 discovered that `flake8 src tests` has never been clean: 63 findings
at HEAD, none of them introduced by PR0. That makes `verify.bat`
unusable and makes the definition of done in AGENTS.md section 7 a rule
nobody can satisfy. PR1 is a large diff, and landing it on a red
baseline means you cannot tell new lint from old.

**Effort: `ultracode`.** Wide and mechanical, one agent per file. Four
of the findings are not mechanical and are called out below.

---

```
Read AGENTS.md and docs/PLAN.md before doing anything. This is PR0a.
PR0 (packaging) is merged. PR1 has not started.

GOAL
`flake8 src tests` must exit 0. It currently reports 63 findings, none
of them introduced by PR0, and docs/TODOS.md already has the writeup
under "flake8 src tests is not clean, and never has been".

Until this lands, verify.bat cannot pass and AGENTS.md section 7 states
a definition of done that has never been achievable.

THE SHAPE OF THE WORK
Verified breakdown across the worst files:

  E127  continuation line over-indented for visual indent   ~22
  F401  imported but unused                                 ~14
  E266  too many leading # for a block comment              ~6
  F811  redefinition of unused name                          3
  W391  blank line at end of file                            1
  F841  local variable assigned but never used               1

Concentrated in src/tools/usajobs_search.py (26), src/job_agent.py (5),
src/demo_ui.py (5), src/tools/resume_intel.py (3), src/rag_agent.py (3),
src/config.py (2), tests/test_omnigab.py (2), src/jobs/sources.py (1).
Run flake8 yourself for the current full list rather than trusting these
counts.

FOUR FINDINGS THAT ARE NOT MECHANICAL
Do not batch these with the rest. Investigate each, then report what you
found.

1. src/tools/usajobs_search.py:29 F811 redefinition of 'json' from :26
2. src/tools/usajobs_search.py:30 F811 redefinition of 'os' from :27
3. src/tools/usajobs_search.py:33 F811 redefinition of 'time' from :28

   Three modules imported twice within eight lines. Before deleting the
   duplicates, check whether the second block sits inside a try/except,
   a conditional, or a different scope, in which case deleting it
   changes behavior. Read the surrounding lines.

4. src/job_agent.py:77 F841 local variable 'ns' assigned but never used

   An assigned-and-unused local is often a real bug: someone meant to
   use the value. Do NOT just delete the assignment. Read the function,
   work out what 'ns' was for, and tell me whether the right fix is
   deleting the line or using the variable. If you are not sure, delete
   nothing and report it.

TASK
1. Fix every mechanical finding. E127, E266, W391, and the genuinely
   unused F401 imports.
2. For each F401, confirm the import really is unused before removing
   it. An import can exist to register a side effect or to re-export a
   name. Note that .flake8 already carries
   `per-file-ignores = __init__.py: F401`, so re-exports in package
   __init__ files are excluded and anything F401 flags outside those is
   more likely to be genuinely dead.
3. Handle the four findings above individually, per the instructions.
4. Do NOT add `# noqa` to silence anything. Do NOT loosen `.flake8` by
   adding codes to extend-ignore. The point is a clean baseline, not a
   quiet one.
5. Remove the "flake8 src tests is not clean" entry from
   docs/TODOS.md.
6. Update AGENTS.md section 3 "Known structural problems" to drop the
   red-flake8 bullet if one is present there.

NON-GOALS
- Do NOT change behavior. This is a lint pass.
- Do NOT reformat code that flake8 is not complaining about. No black,
  no autopep8 across the whole tree, no line reflowing for taste.
- Do NOT rename anything.
- Do NOT touch test logic. Two findings are in tests/test_omnigab.py;
  fix the lint only, and leave the assertions alone for PR1.
- Do NOT start PR1.

ACCEPTANCE
- `flake8 src tests` exits 0.
- `python tests/test_gate.py` still reports 20 passed, 0 failed.
- Both entry points still start: desktop_app.py opens its window, and
  the FastAPI app in src/web_app.py answers on /api/status. Verify
  this, do not assume it, because removing an "unused" import that had
  a side effect is exactly the way a lint pass breaks an app.
- The diff contains no behavior change you cannot justify in one
  sentence.

REPORT
What you found for each of the four non-mechanical findings, especially
'ns' in job_agent.py. Any F401 you decided NOT to remove and why. Any
place a lint fix required a judgment call. The finding count before and
after.
```
