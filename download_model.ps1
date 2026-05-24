<#
.SYNOPSIS
    Downloads the default AI model for omnigab.
    Run this after installing dependencies if the model isn't in the models/ folder.

.USAGE
    .\download_model.ps1
#>

$ErrorActionPreference = "Stop"
$ModelsDir = Join-Path $PSScriptRoot "models"
$GgufModel = Join-Path $ModelsDir "qwen2.5-1.5b-instruct-q4_k_m.gguf"

Write-Host ""
Write-Host "omnigab - Model Downloader" -ForegroundColor Cyan
Write-Host ""

if (Test-Path $GgufModel) {
    $sizeGB = [math]::Round((Get-Item $GgufModel).Length / 1GB, 2)
    Write-Host "Model already exists: qwen2.5-1.5b-instruct-q4_k_m.gguf ($sizeGB GB)" -ForegroundColor Green
    Write-Host "Nothing to do." -ForegroundColor Green
    exit 0
}

Write-Host "Downloading Qwen2.5-1.5B-Instruct (Q4_K_M) ... ~1.1 GB" -ForegroundColor Yellow
Write-Host ""

if (-not (Test-Path $ModelsDir)) { New-Item -ItemType Directory -Path $ModelsDir | Out-Null }

# Check if huggingface-cli is available
$hfCli = $null
$venvHf = Join-Path $PSScriptRoot "venv\Scripts\huggingface-cli.exe"
if (Test-Path $venvHf) {
    $hfCli = $venvHf
} else {
    try { $null = Get-Command huggingface-cli -ErrorAction Stop; $hfCli = "huggingface-cli" } catch {}
}

if ($hfCli) {
    & $hfCli download Qwen/Qwen2.5-1.5B-Instruct-GGUF `
        qwen2.5-1.5b-instruct-q4_k_m.gguf `
        --local-dir $ModelsDir
} else {
    Write-Host "huggingface-cli not found. Installing huggingface-hub..." -ForegroundColor DarkYellow
    $venvPip = Join-Path $PSScriptRoot "venv\Scripts\pip.exe"
    if (Test-Path $venvPip) {
        & $venvPip install huggingface-hub
        $venvHf = Join-Path $PSScriptRoot "venv\Scripts\huggingface-cli.exe"
        & $venvHf download Qwen/Qwen2.5-1.5B-Instruct-GGUF `
            qwen2.5-1.5b-instruct-q4_k_m.gguf `
            --local-dir $ModelsDir
    } else {
        pip install huggingface-hub
        huggingface-cli download Qwen/Qwen2.5-1.5B-Instruct-GGUF `
            qwen2.5-1.5b-instruct-q4_k_m.gguf `
            --local-dir $ModelsDir
    }
}

Write-Host ""
if (Test-Path $GgufModel) {
    $sizeGB = [math]::Round((Get-Item $GgufModel).Length / 1GB, 2)
    Write-Host "Done! Model downloaded: $sizeGB GB" -ForegroundColor Green
} else {
    Write-Host "Download may have failed. You can download it manually from:" -ForegroundColor Red
    Write-Host "https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF" -ForegroundColor Yellow
    Write-Host "Save qwen2.5-1.5b-instruct-q4_k_m.gguf into the models/ folder." -ForegroundColor Yellow
}
