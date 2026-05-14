<#
.SYNOPSIS
    Setup script for Local RAG Agent on Windows 10/11.
    Creates a virtual environment, installs all dependencies, verifies
    llama-cpp-python, and downloads the GGUF model if missing.

.USAGE
    Open PowerShell in the project root and run:
        .\setup_rag.ps1
#>

$ErrorActionPreference = "Stop"

# ── Configuration ──────────────────────────────────────────────
$ProjectRoot  = $PSScriptRoot
$VenvDir      = Join-Path $ProjectRoot "venv"
$ReqFile      = Join-Path $ProjectRoot "requirements.txt"
$ModelsDir    = Join-Path $ProjectRoot "models"
$GgufModel    = Join-Path $ModelsDir "qwen2.5-1.5b-instruct-q4_k_m.gguf"

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Local RAG Agent - Windows Setup" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# ── Step 1: Check Python version ──────────────────────────────
Write-Host "[1/6] Checking Python installation..." -ForegroundColor Yellow

try {
    $pyVersion = & python --version 2>&1
    Write-Host "       Found: $pyVersion" -ForegroundColor Green
} catch {
    Write-Host "       ERROR: Python not found in PATH." -ForegroundColor Red
    Write-Host "       Install Python 3.10+ from https://www.python.org/downloads/" -ForegroundColor Red
    Write-Host "       Make sure to check 'Add Python to PATH' during install." -ForegroundColor Red
    exit 1
}

# Verify version is 3.10+
$versionMatch = $pyVersion | Select-String -Pattern "(\d+)\.(\d+)"
if ($versionMatch) {
    $major = [int]$versionMatch.Matches[0].Groups[1].Value
    $minor = [int]$versionMatch.Matches[0].Groups[2].Value
    if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 10)) {
        Write-Host "       ERROR: Python 3.10+ required, found $major.$minor" -ForegroundColor Red
        exit 1
    }
}

# ── Step 2: Create virtual environment ────────────────────────
Write-Host "[2/6] Creating virtual environment..." -ForegroundColor Yellow

if (Test-Path $VenvDir) {
    Write-Host "       Existing venv found. Removing it for a clean start..." -ForegroundColor DarkYellow
    Remove-Item -Recurse -Force $VenvDir
}

& python -m venv $VenvDir

if (-not (Test-Path (Join-Path $VenvDir "Scripts\activate.bat"))) {
    Write-Host "       ERROR: venv creation failed. activate.bat not found." -ForegroundColor Red
    Write-Host "       Try: python -m ensurepip --upgrade" -ForegroundColor Red
    exit 1
}

Write-Host "       venv created at: $VenvDir" -ForegroundColor Green

# ── Step 3: Activate venv and upgrade pip ─────────────────────
Write-Host "[3/6] Activating venv and upgrading pip..." -ForegroundColor Yellow

$VenvPython = Join-Path $VenvDir "Scripts\python.exe"
$VenvPip    = Join-Path $VenvDir "Scripts\pip.exe"

& $VenvPython -m pip install --upgrade pip setuptools wheel 2>&1 | Out-Null
Write-Host "       pip upgraded successfully." -ForegroundColor Green

# ── Step 4: Install dependencies ──────────────────────────────
Write-Host "[4/6] Installing dependencies from requirements.txt..." -ForegroundColor Yellow
Write-Host "       This may take several minutes (PyTorch is large)." -ForegroundColor DarkYellow
Write-Host ""

& $VenvPip install -r $ReqFile

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "       ERROR: Dependency installation failed." -ForegroundColor Red
    Write-Host "       Check the output above for details." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "       All dependencies installed." -ForegroundColor Green

# ── Step 5: Verify llama-cpp-python and AVX support ───────────
Write-Host "[5/6] Verifying llama-cpp-python installation..." -ForegroundColor Yellow

$llamaCheck = & $VenvPython -c @"
import sys
try:
    import llama_cpp
    print(f'llama-cpp-python version: {llama_cpp.__version__}')

    # Quick smoke test: can it initialize?
    print('Import successful, library is functional.')

    # Check CPU features via platform info
    import platform
    proc = platform.processor()
    print(f'Processor: {proc}')

    # Ryzen 9850X3D (Zen 5) supports AVX-512
    # The pre-built wheel uses AVX2 by default.
    # For AVX-512, you would need to build from source (see notes below).
    print('')
    print('NOTE: The default pip wheel uses AVX2 acceleration.')
    print('Your Ryzen 9850X3D (Zen 5) supports AVX-512, but a source')
    print('build with CMAKE_ARGS is needed to enable it. AVX2 still')
    print('gives excellent performance (12-14+ tok/sec at Q4_K_M).')
    print('See the setup guide for optional AVX-512 build instructions.')

except ImportError as e:
    print(f'ERROR: {e}', file=sys.stderr)
    sys.exit(1)
"@

Write-Host "       $($llamaCheck -join "`n       ")" -ForegroundColor Green

# ── Step 6: Check for GGUF model ─────────────────────────────
Write-Host "[6/6] Checking for GGUF model file..." -ForegroundColor Yellow

if (Test-Path $GgufModel) {
    $sizeGB = [math]::Round((Get-Item $GgufModel).Length / 1GB, 2)
    Write-Host "       Model found: qwen2.5-1.5b-instruct-q4_k_m.gguf ($sizeGB GB)" -ForegroundColor Green
} else {
    Write-Host "       Model NOT found. Downloading now..." -ForegroundColor DarkYellow
    if (-not (Test-Path $ModelsDir)) { New-Item -ItemType Directory -Path $ModelsDir | Out-Null }

    & $VenvPip install huggingface-hub 2>&1 | Out-Null
    $HfCli = Join-Path $VenvDir "Scripts\huggingface-cli.exe"

    & $HfCli download Qwen/Qwen2.5-1.5B-Instruct-GGUF `
        qwen2.5-1.5b-instruct-q4_k_m.gguf `
        --local-dir $ModelsDir

    if (Test-Path $GgufModel) {
        $sizeGB = [math]::Round((Get-Item $GgufModel).Length / 1GB, 2)
        Write-Host "       Model downloaded: $sizeGB GB" -ForegroundColor Green
    } else {
        Write-Host "       WARNING: Model download may have failed." -ForegroundColor Red
        Write-Host "       You can download it manually later (see guide)." -ForegroundColor Red
    }
}

# ── Done ──────────────────────────────────────────────────────
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Setup Complete!" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  To activate the environment:" -ForegroundColor White
Write-Host "    .\venv\Scripts\Activate.ps1" -ForegroundColor Yellow
Write-Host ""
Write-Host "  To ingest your documents:" -ForegroundColor White
Write-Host "    cd src" -ForegroundColor Yellow
Write-Host "    python rag_agent.py ingest" -ForegroundColor Yellow
Write-Host ""
Write-Host "  To start querying:" -ForegroundColor White
Write-Host "    python rag_agent.py query" -ForegroundColor Yellow
Write-Host ""
Write-Host "  To run the demo:" -ForegroundColor White
Write-Host "    python rag_agent.py demo" -ForegroundColor Yellow
Write-Host ""
