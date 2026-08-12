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
echo  1/2  flake8
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
echo  2/2  pytest
echo ============================================================
"%PY%" -m pytest --cov=src --cov-report=term-missing
set PYTEST_RC=%ERRORLEVEL%

REM Exit 5 means pytest collected no tests. That is the expected state
REM until PR1 lands, because none of the four files under tests/ define
REM a test_ function yet. Warn rather than fail, so this gate is usable
REM during PR0a. Delete this branch once PR1 is merged, so that "no
REM tests collected" goes back to being a real failure.
if "%PYTEST_RC%"=="5" (
    echo.
    echo [verify] WARNING: pytest collected no tests. Expected until PR1.
    goto :green
)
if not "%PYTEST_RC%"=="0" (
    echo.
    echo [verify] FAILED: pytest ^(exit %PYTEST_RC%^)
    exit /b 1
)

:green
echo.
echo ============================================================
echo  ALL GREEN
echo ============================================================
exit /b 0
