@echo off
setlocal enabledelayedexpansion
title Local RAG Agent - Setup
cd /d "%~dp0"

echo.
echo  =============================================
echo    Local RAG Agent - One-Click Setup
echo  =============================================
echo.

:: -----------------------------------------------
:: 1. Find Python
:: -----------------------------------------------
set "PYTHON="

:: Check common names on PATH
where python >nul 2>&1 && set "PYTHON=python" && goto :found_python
where python3 >nul 2>&1 && set "PYTHON=python3" && goto :found_python
where py >nul 2>&1 && set "PYTHON=py" && goto :found_python

:: Scan common install locations (handles any Python 3.x version)
for /d %%D in ("C:\Users\%USERNAME%\AppData\Local\Python\pythoncore-3.*") do (
    if exist "%%D\python.exe" (
        set "PYTHON=%%D\python.exe"
        goto :found_python
    )
)
for /d %%D in ("C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python3*") do (
    if exist "%%D\python.exe" (
        set "PYTHON=%%D\python.exe"
        goto :found_python
    )
)
for /d %%D in ("C:\Python3*") do (
    if exist "%%D\python.exe" (
        set "PYTHON=%%D\python.exe"
        goto :found_python
    )
)

echo [ERROR] Python not found. Please install Python 3.10+ from https://www.python.org
echo         Make sure to check "Add Python to PATH" during installation.
echo.
pause
exit /b 1

:found_python
echo [OK] Found Python: %PYTHON%

:: Verify it's Python 3.10+
%PYTHON% -c "import sys; assert sys.version_info >= (3, 10), f'Need 3.10+, got {sys.version}'" 2>nul
if errorlevel 1 (
    echo [ERROR] Python 3.10 or higher is required.
    %PYTHON% --version
    pause
    exit /b 1
)
%PYTHON% --version

:: -----------------------------------------------
:: 2. Create virtual environment (if needed)
:: -----------------------------------------------
echo.
if exist "venv\Scripts\activate.bat" (
    echo [OK] Virtual environment already exists.
) else (
    echo [SETUP] Creating virtual environment...
    %PYTHON% -m venv venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo [OK] Virtual environment created.
)

:: Activate it
call venv\Scripts\activate.bat

:: -----------------------------------------------
:: 3. Install dependencies
:: -----------------------------------------------
echo.
echo [SETUP] Installing dependencies (this may take a few minutes on first run)...
echo.

pip install --upgrade pip --quiet 2>nul

:: Install llama-cpp-python from pre-built wheels (avoids needing a C++ compiler)
echo [SETUP] Installing llama-cpp-python (pre-built wheel)...
pip install llama-cpp-python --prefer-binary --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu --quiet
if errorlevel 1 (
    echo [WARNING] Pre-built wheel not found for your Python version. Trying PyPI...
    pip install llama-cpp-python --prefer-binary --quiet
    if errorlevel 1 (
        echo [ERROR] llama-cpp-python failed to install.
        echo         This usually means your Python version is too new for pre-built wheels.
        echo         Install Python 3.12 from https://www.python.org and try again,
        echo         or install Visual Studio Build Tools for C++ compilation.
        pause
        exit /b 1
    )
)

:: Install remaining dependencies
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo.
    echo [WARNING] Some packages had issues. Retrying without --quiet...
    pip install -r requirements.txt
)

:: Make sure huggingface-hub is installed (needed for model download)
pip install huggingface-hub --quiet 2>nul

echo.
echo [OK] Dependencies installed.

:: -----------------------------------------------
:: 4. Download model (if needed)
:: -----------------------------------------------
set "MODELS_DIR=%~dp0models"
set "GGUF_MODEL=%MODELS_DIR%\qwen2.5-1.5b-instruct-q4_k_m.gguf"

if exist "%GGUF_MODEL%" (
    echo.
    echo [OK] Model already downloaded.
    goto :start_app
)

echo.
echo [SETUP] Downloading Qwen2.5-1.5B-Instruct model (~1.1 GB)...
echo         This is a one-time download. Please be patient.
echo.

if not exist "%MODELS_DIR%" mkdir "%MODELS_DIR%"

:: Use the venv's huggingface-cli directly (full path, no PATH issues)
"%~dp0venv\Scripts\huggingface-cli.exe" download Qwen/Qwen2.5-1.5B-Instruct-GGUF qwen2.5-1.5b-instruct-q4_k_m.gguf --local-dir "%MODELS_DIR%"

if exist "%GGUF_MODEL%" (
    echo.
    echo [OK] Model downloaded successfully!
) else (
    echo.
    echo [ERROR] Model download failed. This usually means a network issue.
    echo         You can retry by running this script again, or download manually:
    echo         https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF
    echo         Save qwen2.5-1.5b-instruct-q4_k_m.gguf into the models\ folder.
    echo.
    pause
    exit /b 1
)

:: -----------------------------------------------
:: 5. Ingest sample docs (if vectorstore is empty)
:: -----------------------------------------------
:start_app
if not exist "%~dp0vectorstore\faiss_index" (
    if exist "%~dp0data\docs" (
        echo.
        echo [SETUP] Building vector index from docs...
        python "%~dp0src\rag_agent.py" ingest 2>nul
        if exist "%~dp0vectorstore\faiss_index" (
            echo [OK] Vector index built.
        )
    )
)

:: -----------------------------------------------
:: 6. Launch the chat
:: -----------------------------------------------
echo.
echo  =============================================
echo    Setup complete! Launching chat...
echo  =============================================
echo.
echo   Web UI:      http://localhost:8000
echo   Terminal UI: Close this window and run start.bat --terminal
echo.

:: Check if user wants terminal mode
if "%1"=="--terminal" (
    python "%~dp0src\demo_ui.py"
) else (
    :: Default to web UI - open browser and start server
    start "" http://localhost:8000
    python "%~dp0src\web_app.py"
)

pause@echo off
setlocal enabledelayedexpansion
title Local RAG Agent - Setup
cd /d "%~dp0"

echo.
echo  =============================================
echo    Local RAG Agent - One-Click Setup
echo  =============================================
echo.

:: -----------------------------------------------
:: 1. Find Python
:: -----------------------------------------------
set "PYTHON="

:: Check common names on PATH
where python >nul 2>&1 && set "PYTHON=python" && goto :found_python
where python3 >nul 2>&1 && set "PYTHON=python3" && goto :found_python
where py >nul 2>&1 && set "PYTHON=py" && goto :found_python

:: Scan common install locations (handles any Python 3.x version)
for /d %%D in ("C:\Users\%USERNAME%\AppData\Local\Python\pythoncore-3.*") do (
    if exist "%%D\python.exe" (
        set "PYTHON=%%D\python.exe"
        goto :found_python
    )
)
for /d %%D in ("C:\Users\%USERNAME%\AppData\Local\Programs\Python\Python3*") do (
    if exist "%%D\python.exe" (
        set "PYTHON=%%D\python.exe"
        goto :found_python
    )
)
for /d %%D in ("C:\Python3*") do (
    if exist "%%D\python.exe" (
        set "PYTHON=%%D\python.exe"
        goto :found_python
    )
)

echo [ERROR] Python not found. Please install Python 3.10+ from https://www.python.org
echo         Make sure to check "Add Python to PATH" during installation.
echo.
pause
exit /b 1

:found_python
echo [OK] Found Python: %PYTHON%

:: Verify it's Python 3.10+
%PYTHON% -c "import sys; assert sys.version_info >= (3, 10), f'Need 3.10+, got {sys.version}'" 2>nul
if errorlevel 1 (
    echo [ERROR] Python 3.10 or higher is required.
    %PYTHON% --version
    pause
    exit /b 1
)
%PYTHON% --version

:: -----------------------------------------------
:: 2. Create virtual environment (if needed)
:: -----------------------------------------------
echo.
if exist "venv\Scripts\activate.bat" (
    echo [OK] Virtual environment already exists.
) else (
    echo [SETUP] Creating virtual environment...
    %PYTHON% -m venv venv
    if errorlevel 1 (
        echo [ERROR] Failed to create virtual environment.
        pause
        exit /b 1
    )
    echo [OK] Virtual environment created.
)

:: Activate it
call venv\Scripts\activate.bat

:: -----------------------------------------------
:: 3. Install dependencies
:: -----------------------------------------------
echo.
echo [SETUP] Installing dependencies (this may take a few minutes on first run)...
echo.

pip install --upgrade pip --quiet 2>nul
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo.
    echo [WARNING] Some packages had issues. Retrying without --quiet...
    pip install -r requirements.txt
)

:: Make sure huggingface-hub is installed (needed for model download)
pip install huggingface-hub --quiet 2>nul

echo.
echo [OK] Dependencies installed.

:: -----------------------------------------------
:: 4. Download model (if needed)
:: -----------------------------------------------
set "MODELS_DIR=%~dp0models"
set "GGUF_MODEL=%MODELS_DIR%\qwen2.5-1.5b-instruct-q4_k_m.gguf"

if exist "%GGUF_MODEL%" (
    echo.
    echo [OK] Model already downloaded.
    goto :start_app
)

echo.
echo [SETUP] Downloading Qwen2.5-1.5B-Instruct model (~1.1 GB)...
echo         This is a one-time download. Please be patient.
echo.

if not exist "%MODELS_DIR%" mkdir "%MODELS_DIR%"

:: Use the venv's huggingface-cli directly (full path, no PATH issues)
"%~dp0venv\Scripts\huggingface-cli.exe" download Qwen/Qwen2.5-1.5B-Instruct-GGUF qwen2.5-1.5b-instruct-q4_k_m.gguf --local-dir "%MODELS_DIR%"

if exist "%GGUF_MODEL%" (
    echo.
    echo [OK] Model downloaded successfully!
) else (
    echo.
    echo [ERROR] Model download failed. This usually means a network issue.
    echo         You can retry by running this script again, or download manually:
    echo         https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF
    echo         Save qwen2.5-1.5b-instruct-q4_k_m.gguf into the models\ folder.
    echo.
    pause
    exit /b 1
)

:: -----------------------------------------------
:: 5. Ingest sample docs (if vectorstore is empty)
:: -----------------------------------------------
:start_app
if not exist "%~dp0vectorstore\faiss_index" (
    if exist "%~dp0data\docs" (
        echo.
        echo [SETUP] Building vector index from docs...
        python "%~dp0src\rag_agent.py" ingest 2>nul
        if exist "%~dp0vectorstore\faiss_index" (
            echo [OK] Vector index built.
        )
    )
)

:: -----------------------------------------------
:: 6. Launch the chat
:: -----------------------------------------------
echo.
echo  =============================================
echo    Setup complete! Launching chat...
echo  =============================================
echo.
echo   Web UI:      http://localhost:8000
echo   Terminal UI: Close this window and run start.bat --terminal
echo.

:: Check if user wants terminal mode
if "%1"=="--terminal" (
    python "%~dp0src\demo_ui.py"
) else (
    :: Default to web UI - open browser and start server
    start "" http://localhost:8000
    python "%~dp0src\web_app.py"
)

pause
