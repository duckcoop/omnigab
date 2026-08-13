# PR1a: Make llama.cpp an optional dependency

Inserted after PR1, before PR2. PR0 found the blocker: `llama-cpp-python`
publishes an sdist only on PyPI, zero wheels, every platform. A bare
`pip install -e ".[dev]"` therefore attempts a source build needing CMake
and a C++ toolchain. CI on ubuntu and windows cannot do that inside a
five minute budget.

Two options existed. Adding `--extra-index-url https://abetlen.github.io/...`
to the workflow works, but it makes CI depend on one person's GitHub
Pages, and when that goes down CI goes red for reasons unrelated to the
code. The other option is better and is what this PR does.

**Do not fold this into PR2.** If the refactor and the workflow land in
one diff and CI goes green, you will not know which one did it.

**Effort: `xhigh`, plan mode.** Deep and careful, not wide. A workflow
would auto-approve edits across the import graph, which is the wrong
trade here.

---

```
Read AGENTS.md and docs/PLAN.md before doing anything. This is PR1a.
PR1 (pytest migration) is merged. PR2 (CI) has not started.

GOAL
Move llama-cpp-python out of the required dependency set, so the
package installs and the default test suite runs on a machine with no
GPU, no compiler, and no inference library.

This is not only a CI fix. AGENTS.md invariant I7 says tests must pass
with no GPU, no downloaded model, and no network. A repository where
importing src/extraction/gate.py requires a GPU inference library to be
installed does not really satisfy that, it just happens to work because
your venv has everything.

The verification gate, the extraction schema, the tool protocol, and
the job sources have no business needing llama.cpp to import. That is
the actual defect. CI is what exposed it.

TASK

0. FIRST, fix a pin bug from PR0 that is unrelated to llama.cpp but
   blocks the same CI job.

   `numpy>=2.5,<3.0` at pyproject.toml:31 is incompatible with
   `requires-python = ">=3.10,<3.13"` on the same file. Verified against
   PyPI:

     numpy 2.2.6  requires_python >=3.10   cp310 cp311 cp312 cp313
     numpy 2.3.0  requires_python >=3.11   cp311 cp312 cp313
     numpy 2.4.0  requires_python >=3.11   cp311 cp312 cp313 cp314
     numpy 2.5.0  requires_python >=3.12   cp312 cp313 cp314
     numpy 2.5.2  requires_python >=3.12   cp312 cp313 cp314

   numpy 2.5 dropped everything below 3.12, so the project is
   uninstallable on 3.10 and 3.11 today, on every platform. AGENTS.md
   section 5 and pyproject both claim 3.10 through 3.12.

   Change it to `numpy>=2.2,<3.0`. pip then resolves 2.2.6 on 3.10,
   2.4.x on 3.11, and 2.5.x on 3.12, which is the correct behavior for a
   floor.

   This is PR0's pinning method leaking: it anchored every floor to the
   version installed on a 3.12 machine. Check whether any OTHER pin in
   [project.dependencies] has the same problem, by resolving each one
   against 3.10, 3.11, and 3.12 rather than eyeballing it. Report what
   you find even if the answer is "only numpy".

1. In pyproject.toml, move `llama-cpp-python>=0.3,<0.4` out of
   [project.dependencies] and into a new optional extra. Name it
   `inference`. Keep the existing comment explaining why its lower
   bound is deliberately loose, because that reasoning is still true.

   Consider whether the three nvidia-*-cu12 Windows packages belong in
   the same extra. They exist to supply CUDA runtime DLLs for the
   llama-cpp-python CUDA wheel, so if llama.cpp is optional they
   arguably are too. Decide, and say why.

2. The import-laziness work is nearly done already. An audit found
   exactly one module-scope import:

     src/generator.py:30      from llama_cpp import Llama   <-- the only one

   These are already function-local and need no change:

     src/generator.py:94      from llama_cpp import GGML_TYPE_Q8_0
     src/generator.py:134     import llama_cpp as _lc
     src/core/model_manager.py:56    import llama_cpp
     src/core/model_manager.py:294   from generator import Generator
     src/rag_agent.py:61,64          from generator import Generator...

   Confirm this yourself rather than trusting it, then move only
   `generator.py:30` into the function that needs it.

3. The goal is that `import config`, `import extraction`,
   `import core.tool_protocol`, and the whole default pytest run all
   succeed with llama-cpp-python absent.

4. When the library IS missing and someone tries to load a model, the
   failure must be a clear message naming the fix, not a raw
   ImportError traceback. Something a user can act on:

     "Local inference is not installed. Run setup.bat, or
      pip install 'omnigab[inference]' with the CUDA wheel index."

   Route it through whatever error surface the app already uses for
   "no model loaded", so the desktop app and the web app both show
   something sensible. Read how ModelManager currently reports a
   missing model before inventing a new mechanism.

5. setup.bat must keep working unchanged for real users. It already
   installs llama-cpp-python first from abetlen's prebuilt CUDA wheel
   index via scripts/install_llama_cpp.py, before pip install -r
   requirements.txt runs, so the extra should not change what a user
   ends up with. Verify this rather than assuming it. If setup.bat
   needs a line changed so that the extra is requested explicitly, say
   exactly what you changed.

6. Update README.md's install section only if the user-facing steps
   actually changed.

7. Remove the "llama-cpp-python ships no wheels on PyPI" entry from
   docs/TODOS.md.

NON-GOALS
- Do NOT change how inference works, how models load, or how GPU
  offload is configured. This changes WHEN llama_cpp is imported, not
  what it does.
- Do NOT vendor, wrap, or abstract llama.cpp behind a new interface.
- Do NOT add a CPU fallback inference path.
- Do NOT write the CI workflow. That is PR2.

TESTS
- A test asserting that src/extraction, src/config, and
  src/core/tool_protocol import successfully when llama_cpp is
  unavailable. Simulate the absence rather than uninstalling: a
  conftest fixture that blocks the import via sys.meta_path or
  monkeypatches builtins __import__ to raise ImportError for
  'llama_cpp'.
- A test asserting the missing-library error message is the friendly
  one, not an ImportError.
- The full default pytest run must pass under that simulated absence.

ACCEPTANCE
- Prove it for real, not just with the simulation: create a fresh venv,
  run `pip install -e ".[dev]"` with NO extra index URL, confirm
  llama-cpp-python is not installed, and confirm `pytest` passes. Paste
  the pip output showing llama-cpp-python absent.
- Resolve the dependency set against Python 3.10, 3.11, AND 3.12, and
  show that all three succeed. Use `pip install --dry-run` with
  `--python-version` and `--only-binary=:all:` if you cannot create
  three real interpreters. This is the check that would have caught the
  numpy bug in PR0, so make it part of the record.
- `pip install -e ".[dev,inference]"` still resolves when the CUDA
  wheel index is supplied.
- Both entry points still start on your machine, where inference IS
  installed, with GPU offload working as before. Confirm CUDA
  initializes.
- `flake8 src tests` clean, `pytest` passes.

REPORT
Every module that imported llama_cpp at module scope, and where you
moved each one. Your decision on the nvidia-*-cu12 packages and the
reasoning. Whether setup.bat needed a change. The pip output proving a
clean install with no inference library. Anything that turned out to
depend on llama_cpp being importable that you did not expect.
```
