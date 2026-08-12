# Task prompts

One file per pull request. Paste the fenced block into Claude Code,
starting a fresh session for each one.

## How to run a task

1. Open Claude Code in the repo root so it picks up `AGENTS.md`.
2. Set the effort level for this PR. See the table below, and the fuller
   explanation in `SETUP.md`.
3. Shift+Tab into plan mode. Let it read and propose before it writes.
4. Paste the prompt.
5. Read the plan. If it wants to touch files outside the stated scope,
   say no and make it explain why it thinks it needs them.
6. Approve, then let it work.
7. Before you accept, run `verify.bat` yourself. Do not take the agent's
   word for it. Agents report success on failing test suites more often
   than you would like.

## Effort per PR

| PR | Setting |
|---|---|
| PR0 packaging | `high`, plan mode, no workflow |
| PR0a flake8 to zero | `ultracode` |
| PR1 pytest migration | `ultracode` |
| PR1a optional inference | `xhigh`, plan mode |
| PR2 CI | `ultracode` |
| PR3 agent loop tests | `ultracode` |
| PR4 prompt extraction | `high`, plan mode |
| PR5 page-indexed PDF | `high` or `xhigh` |
| PR6 constrained decoding | `xhigh` |
| PR7 rubric and corpus | `high` plus `ultrathink` in the prompt |
| PR8 eval harness | `xhigh` |
| PR9 smoke test | `high` |

Ultracode when the work is wide, `xhigh` when the work is deep, `high`
when it is neither. `high` is the default, so PRs marked `high` need no
change.

PR0 is deliberately not a workflow. Workflow subagents run in
`acceptEdits` mode and auto-approve their own file edits regardless of
your session's permission mode, and PR0 is the one change where a wrong
move breaks both entry points.

## Order

`PR0, PR0a, PR1, PR1a, PR2, PR3, PR4` is Phase 1 and should run in
order. PR0a and PR1a were added after PR0 surfaced two blockers that
were not visible from the outside:

- **PR0a** exists because `flake8 src tests` has never been clean. 63
  pre-existing findings make `verify.bat` unusable and make the
  definition of done in AGENTS.md unsatisfiable. It goes before PR1 so
  PR1's large diff lands on a clean baseline.
- **PR1a** exists because `llama-cpp-python` ships no wheels on PyPI,
  so CI cannot install the package without a source build. It goes
  before PR2 so CI is green on its first run rather than its fifth.

`PR5, PR6, PR7, PR8` is Phase 2. PR5 only depends on PR1, so you can
start it as soon as pytest exists if you want to interleave.

`PR9` needs PR6.

Optional, unscheduled: PR0 also flagged that the flat layout installs 22
loose top-level module names into site-packages (`config`, `security`,
`generator`, `verifier`, and so on). Nothing collides today because the
app owns its venv. The fix is an `omnigab.` namespace across roughly 45
files, best done after PR1 when the test suite can prove nothing broke.
It is written up in `docs/TODOS.md`. Lowest priority of the three,
because nothing is broken today.

## One session per PR

Do not run two of these in one session. Context rot is real: twenty tool
calls in, the agent has forgotten the non-goals and starts "improving"
things you did not ask about. `/clear` between PRs, or open a new tab.
A fresh session re-reads `AGENTS.md` and starts clean.

## Files

| File | PR |
|---|---|
| `01-package-project.md` | PR0 (done) |
| `01a-flake8-to-zero.md` | PR0a |
| `02-pytest-migration.md` | PR1 |
| `02a-optional-inference.md` | PR1a |
| `03-continuous-integration.md` | PR2 |
| `04-agent-loop-tests.md` | PR3 |
| `05-extract-system-prompt.md` | PR4 |
| `06-page-indexed-pdf.md` | PR5 |
| `07-constrained-decoding.md` | PR6 |
| `08-rubric-and-corpus.md` | PR7 |
| `09-eval-harness.md` | PR8 |
| `10-smoke-test.md` | PR9 |
