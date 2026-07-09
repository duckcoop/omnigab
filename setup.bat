@echo off
setlocal enabledelayedexpansion
title omnigab - Setup
cd /d "%~dp0"

echo.
echo  =============================================
echo    omnigab - One-Click Setup
echo  =============================================
echo.

:: -----------------------------------------------
:: 1. Find a REAL Python (skip the Microsoft Store alias stub)
:: -----------------------------------------------
:: The bare "python" command on Windows is often a Microsoft Store
:: placeholder that isn't real Python - running it just prints
:: "Python was not found... Microsoft Store" and exits. The old
:: detection grabbed that stub via "where python", so the version
:: check below failed even when real Python 3.12 was installed.
:: We now validate every candidate by actually running it, and we
:: prefer the py launcher, which never resolves to the stub.
set "PYTHON="

:: Prefer the py launcher with an explicit version (ignores the stub).
for %%V in (3.12 3.11 3.10 3.13 3) do (
    py -%%V -c "import sys" >nul 2>&1 && ( set "PYTHON=py -%%V" & goto :found_python )
)

:: Fall back to python / python3 on PATH, but only if they really run.
:: The Store stub prints no version, so it never passes this probe.
for %%P in (python python3) do (
    for /f "delims=" %%R in ('%%P -c "import sys; sys.stdout.write(str(sys.version_info[0]))" 2^>nul') do (
        if "%%R"=="3" ( set "PYTHON=%%P" & goto :found_python )
    )
)

:: Fall back to common install locations.
for /d %%D in ("C:\Users\%USERNAME%\AppData\Local\Python\pythoncore-3.*") do (
    if exist "%%D\python.exe" ( set "PYTHON=%%D\python.exe" & goto :found_python )
)
for /d %%D in ("C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python3*") do (
    if exist "%%D\python.exe" ( set "PYTHON=%%D\python.exe" & goto :found_python )
)
for /d %%D in ("C:\Python3*") do (
    if exist "%%D\python.exe" ( set "PYTHON=%%D\python.exe" & goto :found_python )
)

echo [ERROR] No real Python found on this machine.
echo         Install Python 3.12 from https://www.python.org/downloads/release/python-3128/
echo         and check "Add python.exe to PATH" during install, then rerun setup.bat.
echo.
echo         Tip: if typing "python" opens the Microsoft Store, turn off the alias at
echo         Settings ^> Apps ^> Advanced app settings ^> App execution aliases.
pause
exit /b 1

:found_python
echo [OK] Found Python: %PYTHON%
%PYTHON% --version

:: -----------------------------------------------
:: 2. Check Python version (warn, don't block)
:: -----------------------------------------------
:: Prebuilt CUDA wheels for llama-cpp-python target Python 3.10-3.12, so
:: those install cleanly. Other versions may fall back to CPU or need a
:: source build - we warn but no longer hard-block, so any Python runs.
%PYTHON% -c "import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,12) else 1)" 2>nul
if errorlevel 1 (
    echo.
    echo [WARNING] omnigab is tuned for Python 3.10-3.12.
    for /f "delims=" %%V in ('%PYTHON% -c "import sys; print(sys.version.split()[0])" 2^>nul') do echo           You are running Python %%V.
    echo           GPU/CUDA wheels for llama-cpp-python may be unavailable here,
    echo           so install could fall back to CPU or build from source.
    echo           For guaranteed GPU support, install Python 3.12 and rerun setup.
    echo.
) else (
    echo [OK] Python 3.10-3.12 confirmed.
)

:: -----------------------------------------------
:: 2. Virtual environment
:: -----------------------------------------------
echo.
if exist "venv\Scripts\activate.bat" (
    echo [OK] venv already exists.
) else (
    echo [SETUP] Creating venv...
    %PYTHON% -m venv venv
    if errorlevel 1 (
        echo [ERROR] venv creation failed.
        pause
        exit /b 1
    )
)
call venv\Scripts\activate.bat

:: -----------------------------------------------
:: 3. GPU detection (delegated to scripts/detect_gpu.py)
:: -----------------------------------------------
:: Python helper sidesteps cmd batch quirks (commas in nvidia-smi args,
:: stderr leaking through 2>nul before redirect parsing, etc.).
echo.
echo [SETUP] Detecting NVIDIA GPU...
set "GPU_PRESENT=0"
set "GPU_NAME="
set "VRAM_GB=0"

for /f "usebackq tokens=1,2,3 delims=|" %%A in (`%PYTHON% "%~dp0scripts\detect_gpu.py" 2^>nul`) do (
    set "GPU_PRESENT=%%A"
    set "GPU_NAME=%%B"
    set "VRAM_GB=%%C"
)

if "!GPU_PRESENT!"=="1" (
    echo [OK] NVIDIA GPU: !GPU_NAME!  ^(VRAM: !VRAM_GB! GB^)
) else (
    echo [INFO] No NVIDIA GPU detected. CPU-only.
)

:: -----------------------------------------------
:: 4. Install dependencies
:: -----------------------------------------------
:: llama-cpp-python install is delegated to scripts/install_llama_cpp.py.
:: That helper handles the GPU/CPU wheel cascade, CUDA runtime DLL install,
:: and post-install verification in one place. Keeping it in Python avoids
:: cmd batch nested-paren miscounts that bit us before.
echo.
echo [SETUP] Installing dependencies...
echo [SETUP] Updating pip to the latest version...
python -m pip install --upgrade pip

echo [SETUP] Installing llama-cpp-python ^(GPU/CPU wheel selected automatically^)...
python "%~dp0scripts\install_llama_cpp.py"
if errorlevel 1 (
    echo [ERROR] Could not install llama-cpp-python at all.
    pause
    exit /b 1
)

:: --- Step 4e: project requirements ---
echo.
echo [SETUP] Installing application dependencies: fastapi, uvicorn, sentence-transformers, faiss, etc.
pip install -r requirements.txt --no-cache-dir
if errorlevel 1 (
    echo [WARNING] Some packages had issues. Retrying with output...
    pip install -r requirements.txt --no-cache-dir
)

:: --- Step 4f: Playwright browser (used by the Indeed apply tool) ---
echo.
echo [SETUP] Installing Playwright Chromium browser...
python -m playwright install chromium 2>nul
if errorlevel 1 (
    echo [WARNING] Chromium install failed. The Indeed apply tool will not work
    echo           until you run:  venv\Scripts\python.exe -m playwright install chromium
) else (
    echo [OK] Playwright + Chromium ready.
)

echo.
echo [OK] Dependencies installed.

:: -----------------------------------------------
:: 5. Download default model
:: -----------------------------------------------
set "MODELS_DIR=%~dp0models"
set "GGUF_MODEL=%MODELS_DIR%\qwen2.5-1.5b-instruct-q4_k_m.gguf"

if not exist "%GGUF_MODEL%" (
    echo.
    echo [SETUP] Downloading default Qwen2.5-1.5B model ^(~1.1 GB^)...
    if not exist "%MODELS_DIR%" mkdir "%MODELS_DIR%"
    "%~dp0venv\Scripts\python.exe" -c "from huggingface_hub import hf_hub_download; hf_hub_download(repo_id='Qwen/Qwen2.5-1.5B-Instruct-GGUF', filename='qwen2.5-1.5b-instruct-q4_k_m.gguf', local_dir=r'%MODELS_DIR%')"
    if not exist "%GGUF_MODEL%" (
        echo [ERROR] Model download failed.
        pause
        exit /b 1
    )
)

:: -----------------------------------------------
:: 6. Build vector index if empty
:: -----------------------------------------------
if not exist "%~dp0vectorstore\faiss_index" (
    if exist "%~dp0data\docs" (
        echo.
        echo [SETUP] Building vector index from docs...
        python "%~dp0src\rag_agent.py" ingest 2>nul
    )
)

:: -----------------------------------------------
:: 7. Summary + launch
:: -----------------------------------------------
echo.
echo  =============================================
echo    omnigab setup complete!
if "!GPU_PRESENT!"=="1" (
    echo    GPU:  ENABLED  ^(!GPU_NAME!, VRAM: !VRAM_GB! GB^)
) else (
    echo    GPU:  CPU only
)
echo  =============================================
echo.

:: Flags:
::   --terminal    launch the CLI demo instead of the desktop UI
::   --no-launch   complete install verification only; do not start anything
::                 (handy when re-running setup to confirm dependencies)
if "%1"=="--no-launch" (
    echo Setup verified. Skipping launch ^(--no-launch^).
    echo Run omnigab.bat to start the app.
    pause
    exit /b 0
)

if "%1"=="--terminal" (
    python "%~dp0src\demo_ui.py"
) else (
    python "%~dp0desktop_app.py"
)

pause
