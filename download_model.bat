@echo off
setlocal

set "MODELS_DIR=%~dp0models"
set "GGUF_MODEL=%MODELS_DIR%\qwen2.5-1.5b-instruct-q4_k_m.gguf"

echo.
echo Local RAG Agent - Model Downloader
echo.

if exist "%GGUF_MODEL%" (
    echo Model already exists: qwen2.5-1.5b-instruct-q4_k_m.gguf
    echo Nothing to do.
    pause
    exit /b 0
)

echo Downloading Qwen2.5-1.5B-Instruct (Q4_K_M) ... ~1.1 GB
echo.

if not exist "%MODELS_DIR%" mkdir "%MODELS_DIR%"

if exist "%~dp0venv\Scripts\huggingface-cli.exe" (
    "%~dp0venv\Scripts\huggingface-cli.exe" download Qwen/Qwen2.5-1.5B-Instruct-GGUF qwen2.5-1.5b-instruct-q4_k_m.gguf --local-dir "%MODELS_DIR%"
) else (
    where huggingface-cli >nul 2>&1
    if errorlevel 1 (
        echo huggingface-cli not found. Installing...
        if exist "%~dp0venv\Scripts\pip.exe" (
            "%~dp0venv\Scripts\pip.exe" install huggingface-hub
            "%~dp0venv\Scripts\huggingface-cli.exe" download Qwen/Qwen2.5-1.5B-Instruct-GGUF qwen2.5-1.5b-instruct-q4_k_m.gguf --local-dir "%MODELS_DIR%"
        ) else (
            pip install huggingface-hub
            huggingface-cli download Qwen/Qwen2.5-1.5B-Instruct-GGUF qwen2.5-1.5b-instruct-q4_k_m.gguf --local-dir "%MODELS_DIR%"
        )
    ) else (
        huggingface-cli download Qwen/Qwen2.5-1.5B-Instruct-GGUF qwen2.5-1.5b-instruct-q4_k_m.gguf --local-dir "%MODELS_DIR%"
    )
)

echo.
if exist "%GGUF_MODEL%" (
    echo Done! Model downloaded successfully.
) else (
    echo Download may have failed. You can download it manually from:
    echo https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF
    echo Save qwen2.5-1.5b-instruct-q4_k_m.gguf into the models/ folder.
)
pause
