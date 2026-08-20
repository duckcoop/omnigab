<#
.SYNOPSIS
    Downloads the default AI model for omnigab.
    Run this after installing dependencies if the model isn't in the models/ folder.

.USAGE
    .\download_model.ps1
#>

$ErrorActionPreference = "Stop"
$ModelsDir = Join-Path $PSScriptRoot "models"
$GgufModel = Join-Path $ModelsDir "Qwen_Qwen3.5-4B-Q4_K_M.gguf"

Write-Host ""
Write-Host "omnigab - Model Downloader" -ForegroundColor Cyan
Write-Host ""

if (Test-Path $GgufModel) {
    $sizeGB = [math]::Round((Get-Item $GgufModel).Length / 1GB, 2)
    Write-Host "Model already exists: Qwen_Qwen3.5-4B-Q4_K_M.gguf ($sizeGB GB)" -ForegroundColor Green
    Write-Host "Nothing to do." -ForegroundColor Green
    exit 0
}

Write-Host "Downloading Qwen3.5-4B (Q4_K_M) ... ~3 GB" -ForegroundColor Yellow
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
    & $hfCli download bartowski/Qwen_Qwen3.5-4B-GGUF `
        Qwen_Qwen3.5-4B-Q4_K_M.gguf `
        --local-dir $ModelsDir
} else {
    Write-Host "huggingface-cli not found. Installing huggingface-hub..." -ForegroundColor DarkYellow
    $venvPip = Join-Path $PSScriptRoot "venv\Scripts\pip.exe"
    if (Test-Path $venvPip) {
        & $venvPip install huggingface-hub
        $venvHf = Join-Path $PSScriptRoot "venv\Scripts\huggingface-cli.exe"
        & $venvHf download bartowski/Qwen_Qwen3.5-4B-GGUF `
            Qwen_Qwen3.5-4B-Q4_K_M.gguf `
            --local-dir $ModelsDir
    } else {
        pip install huggingface-hub
        huggingface-cli download bartowski/Qwen_Qwen3.5-4B-GGUF `
            Qwen_Qwen3.5-4B-Q4_K_M.gguf `
            --local-dir $ModelsDir
    }
}

Write-Host ""
if (Test-Path $GgufModel) {
    $sizeGB = [math]::Round((Get-Item $GgufModel).Length / 1GB, 2)
    Write-Host "Done! Model downloaded: $sizeGB GB" -ForegroundColor Green
} else {
    Write-Host "Download may have failed. You can download it manually from:" -ForegroundColor Red
    Write-Host "https://huggingface.co/bartowski/Qwen_Qwen3.5-4B-GGUF" -ForegroundColor Yellow
    Write-Host "Save Qwen_Qwen3.5-4B-Q4_K_M.gguf into the models/ folder." -ForegroundColor Yellow
}
