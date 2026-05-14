@echo off
setlocal enabledelayedexpansion

echo.
echo ============================================================
echo   Local RAG Agent - Windows Setup
echo ============================================================
echo.

REM -- Step 1: Check Python --
echo [1/6] Checking Python installation...
python --version >nul 2>&1
if errorlevel 1 (
    echo        ERROR: Python not found in PATH.
    echo        Install Python 3.10+ from https://www.python.org/downloads/
    echo        Make sure to check "Add Python to PATH" during install.
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo        Found: %%v

REM -- Step 2: Create virtual environment --
echo [2/6] Creating virtual environment...
if exist "venv" (
    echo        Existing venv found. Removing for a clean start...
    rmdir /s /q venv
)

python -m venv venv

if not exist "venv\Scripts\activate.bat" (
    echo        ERROR: venv creation failed.
    echo        Try: python -m ensurepip --upgrade
    pause
    exit /b 1
)
echo        venv created successfully.

REM -- Step 3: Upgrade pip --
echo [3/6] Upgrading pip...
venv\Scripts\python.exe -m pip install --upgrade pip setuptools wheel >nul 2>&1
echo        pip upgraded.

REM -- Step 4: Install dependencies --
echo [4/6] Installing dependencies from requirements.txt...
echo        This may take several minutes (PyTorch is large).
echo.
venv\Scripts\pip.exe install -r requirements.txt
if errorlevel 1 (
    echo.
    echo        ERROR: Dependency installation failed.
    echo        Check the output above for details.
    pause
    exit /b 1
)
echo.
echo        All dependencies installed.

REM -- Step 5: Verify llama-cpp-python --
echo [5/6] Verifying llama-cpp-python...
venv\Scripts\python.exe -c "import llama_cpp; print(f'       llama-cpp-python {llama_cpp.__version__} loaded successfully')"
if errorlevel 1 (
    echo        WARNING: llama-cpp-python import failed.
    echo        Try: venv\Scripts\pip.exe install llama-cpp-python --force-reinstall
)

REM -- Step 6: Check for GGUF model --
echo [6/6] Checking for GGUF model file...
if exist "models\qwen2.5-1.5b-instruct-q4_k_m.gguf" (
    echo        Model found: qwen2.5-1.5b-instruct-q4_k_m.gguf
) else (
    echo        Model NOT found. Downloading now...
    if not exist "models" mkdir models
    venv\Scripts\pip.exe install huggingface-hub >nul 2>&1
    venv\Scripts\huggingface-cli.exe download Qwen/Qwen2.5-1.5B-Instruct-GGUF qwen2.5-1.5b-instruct-q4_k_m.gguf --local-dir models/
    if exist "models\qwen2.5-1.5b-instruct-q4_k_m.gguf" (
        echo        Model downloaded successfully.
    ) else (
        echo        WARNING: Model download may have failed.
        echo        You can download it manually later (see README).
    )
)

echo.
echo ============================================================
echo   Setup Complete!
echo ============================================================
echo.
echo   To activate the environment:
echo     venv\Scripts\activate.bat
echo.
echo   To ingest your documents:
echo     cd src
echo     python rag_agent.py ingest
echo.
echo   To start querying:
echo     python rag_agent.py query
echo.
echo   To run the demo:
echo     python rag_agent.py demo
echo.
pause
