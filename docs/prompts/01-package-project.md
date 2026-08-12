# PR0: Package the project

Highest risk PR in the plan. Run it alone, verify both entry points
start, commit before moving on.

---

```
Read AGENTS.md and docs/PLAN.md before doing anything. This is PR0.

GOAL
Make this repository an installable Python package so that
`pip install -e ".[dev]"` works and no file ever needs
`sys.path.insert` again.

Right now `src/` is not a package. Every entry point does
`sys.path.insert(0, str(SRC))` and modules import each other as
top-level names: `from core.model_manager import ModelManager`,
`from security import audit_log`, `from tools.rag_search import
RagSearchTool`. Imports work by accident of the working directory.

TASK
1. Add a `pyproject.toml` at the repo root using setuptools.
   - Requires Python >=3.10,<3.13.
   - Configure the package discovery so the existing `src/` layout
     installs without renaming modules. Use whichever of `package-dir`
     or an explicit package list makes the smallest diff. Do NOT
     restructure the tree or rename modules in this PR.
   - Move every runtime dependency out of requirements.txt into
     `[project.dependencies]`, and PIN each one to a compatible release
     range (`~=` or `>=x.y,<x+1.0`). Right now they are all bare `>=`,
     which means a clone six months from now may not build. Resolve the
     current installed versions and pin against those.
   - Keep the Windows-only nvidia CUDA runtime packages behind their
     existing `platform_system == "Windows"` markers.
   - Add an optional `[project.optional-dependencies] dev` extra with
     pytest, pytest-cov, and flake8.
   - Keep `requirements.txt` as a thin file that installs the package,
     so `setup.bat` does not break.

2. Add a `[tool.pytest.ini_options]` section with:
   - `testpaths = ["tests"]`
   - markers `integration` (needs live network) and `model` (needs a
     real GGUF file on disk)
   - `addopts = "-m 'not integration and not model'"` so the default run
     is offline and model-free

3. Delete every `sys.path.insert` under `tests/` and fix the resulting
   imports. There are four: `test_gate.py` line 17, `test_omnigab.py`
   line 28, `test_usajobs.py` line 26, `evolution_benchmark.py` line 3.

4. Verify `setup.bat` still produces a working install. If it needs a
   line changed, change it and say exactly what you changed and why.

NON-GOALS
- Do not rename any module.
- Do not restructure directories.
- Do not change any behavior.
- Do not touch test contents beyond the import fix.
- Do not add a dependency that is not already installed and used.

ACCEPTANCE
- `pip install -e ".[dev]"` succeeds in a clean Python 3.11 venv.
- Both entry points still start: `desktop_app.py` and the FastAPI app in
  `src/web_app.py`. Verify this, do not assume it.
- `grep -rn "sys.path.insert" tests/` returns nothing.
- `python tests/test_gate.py` still passes (it has not been migrated
  yet, that is PR1).
- `flake8 src tests` is clean.

REPORT
State the exact pins you chose and how you resolved each version. List
anything in setup.bat you touched. If any import could not be fixed
without renaming a module, stop and tell me rather than renaming it.
```
