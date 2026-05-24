# push_omniagent.ps1 - finish the OmniAgent rebrand push from Windows
# Run from PowerShell:   powershell -ExecutionPolicy Bypass -File .\push_omniagent.ps1

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

Write-Host ""
Write-Host "=== OmniAgent push helper ===" -ForegroundColor Cyan
Write-Host ""

# 0. Clean any stale lockfile (only if no git process is running)
if (Test-Path ".git\index.lock") {
    $gitProc = Get-Process git -ErrorAction SilentlyContinue
    if ($gitProc) {
        Write-Host "git is running - refusing to clear index.lock. Close other git processes and rerun." -ForegroundColor Red
        exit 1
    }
    Remove-Item ".git\index.lock" -Force
    Write-Host "Cleared stale .git\index.lock" -ForegroundColor Yellow
}

# 1. Stage everything
Write-Host ""
Write-Host "Staging all changes (git add -A)..." -ForegroundColor Cyan
git add -A
if ($LASTEXITCODE -ne 0) { Write-Host "git add failed" -ForegroundColor Red; exit 1 }

# 2. Show what's about to be committed
Write-Host ""
Write-Host "=== About to commit ===" -ForegroundColor Cyan
git status --short

Write-Host ""
Write-Host "=== Sanity check: scanning staged files for private data ===" -ForegroundColor Cyan
$staged = git diff --cached --name-only
$leaks = $staged | Where-Object {
    # Resume documents (NOT source code that mentions "resume")
    $_ -match "^data/docs/.*[Rr]esume.*" -or
    $_ -match "^data/docs/.*\.(docx|pdf)$" -or
    # Local databases, profiles, run artifacts
    $_ -match "memory\.db$" -or
    $_ -match "^data/playwright_profile" -or
    $_ -match "^data/indeed_runs" -or
    $_ -match "^data/usajobs_runs" -or
    # Personal memory
    $_ -match "^user_memory\.json$" -or
    # Models and env
    $_ -match "\.gguf$" -or
    $_ -match "^venv/" -or
    $_ -match "^\.env$"
}
if ($leaks) {
    Write-Host "BLOCKED - these private/large files would be committed:" -ForegroundColor Red
    $leaks | ForEach-Object { Write-Host ("  " + $_) -ForegroundColor Red }
    Write-Host ""
    Write-Host "Add them to .gitignore and run:  git rm --cached <file>" -ForegroundColor Red
    exit 1
}
Write-Host "Clean - no private files staged." -ForegroundColor Green

# 3. Confirm before committing
Write-Host ""
$confirm = Read-Host "Proceed with commit + push to origin/main? (y/N)"
if ($confirm -ne "y" -and $confirm -ne "Y") {
    Write-Host "Aborted. Nothing committed or pushed." -ForegroundColor Yellow
    exit 0
}

# 4. Build commit message as an array then join (avoids here-string parse issues)
$msgLines = @(
    "feat: rebrand to OmniAgent, agent loop, USAJOBS tool, cert matching, GPU autotuning",
    "",
    "* Replace RAG-only pipeline with tool-calling Agent (src/core/agent.py)",
    "* Add tool catalog: rag_search, web_search, usajobs_search, memory_read/write, persistent_memory, open_in_browser, plus user-skill adapters",
    "* USAJOBS Playwright scraper with OPM series auto-injection, entry-level Pathways filter, and AI-focus mode for federally-designated AI roles",
    "* Resume cert extraction (Security+, Network+, CCNA, etc.) used to rank results",
    "* ModelManager with CUDA detect + hot-swap + per-model VRAM-aware context",
    "* Strict Python 3.12 enforcement, scripts/install_llama_cpp.py wheel cascade, scripts/install_cuda_dlls.py runtime DLL wiring",
    "* Async streaming via FastAPI SSE, markdown-rendering desktop UI with hyperlinks + tool-call display",
    "* Persistent SQLite memory layer with cross-session recall",
    "* Tool-calling capability badge in topbar (warns on small models)",
    "* Indeed scraping removed (Cloudflare unreliable); open_in_browser fallback added",
    "* New docs: README, SETUP_GUIDE; new tests; new scripts/deploy.py"
)
$msg = $msgLines -join "`n"

Write-Host ""
Write-Host "Committing..." -ForegroundColor Cyan
git commit -m $msg
if ($LASTEXITCODE -ne 0) { Write-Host "git commit failed" -ForegroundColor Red; exit 1 }

# 5. Push
Write-Host ""
Write-Host "Pushing to origin/main..." -ForegroundColor Cyan
git push origin main
if ($LASTEXITCODE -ne 0) { Write-Host "git push failed" -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "Done. Check https://github.com/duckcoop/local-rag-agent" -ForegroundColor Green
