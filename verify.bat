@echo off
REM Quality gate. Run this yourself before accepting any agent PR.
REM Never take the agent's word that tests pass.
REM
REM Exit code 0 means the task is done. Anything else means it is not,
REM whatever the summary said.

setlocal

set PY=venv\Scripts\python.exe
if not exist "%PY%" (
    echo [verify] venv\Scripts\python.exe not found. Run setup.bat first.
    exit /b 2
)

echo.
echo ============================================================
echo  1/3  flake8
echo ============================================================
"%PY%" -m flake8 src tests
if errorlevel 1 (
    echo.
    echo [verify] FAILED: flake8
    exit /b 1
)
echo [verify] flake8 clean

echo.
echo ============================================================
echo  2/3  pyflakes ^(whole repo^)
echo ============================================================
REM The full ruleset runs on src and tests only, because desktop_app.py
REM and scripts/ still carry cosmetic findings. The pyflakes subset is the
REM bug half of flake8 (undefined names, unused imports, redefinitions)
REM and the whole repo passes it, so gate on it everywhere. This is what
REM would have caught the two handlers that raised NameError instead of
REM showing the user an error.
"%PY%" -m flake8 --select=F src tests scripts desktop_app.py
if errorlevel 1 (
    echo.
    echo [verify] FAILED: pyflakes
    exit /b 1
)
echo [verify] pyflakes clean

echo.
echo ============================================================
echo  3/3  pytest
echo ============================================================
"%PY%" -m pytest --cov=src --cov-report=term-missing
set PYTEST_RC=%ERRORLEVEL%

REM Any non-zero code is a failure, including 5 (no tests collected).
REM PR1 tolerated 5 while tests/ held no test_ function; now that the
REM suite is real, "collected nothing" means collection broke.
if not "%PYTEST_RC%"=="0" (
    echo.
    echo [verify] FAILED: pytest ^(exit %PYTEST_RC%^)
    exit /b 1
)

echo.
echo ============================================================
echo  ALL GREEN
echo ============================================================
exit /b 0
