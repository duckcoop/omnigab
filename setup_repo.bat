@echo off
echo === Setting up GitHub repository ===

cd /d "%~dp0"

:: Clean up corrupted .git if it exists
if exist ".git" (
    echo Removing old .git directory...
    rmdir /s /q .git
)

:: Initialize
git init -b main
git config user.name "Cooper Preston"
git config user.email "cooperpreston43@gmail.com"

:: Commit 1: Core pipeline
git add src/config.py src/embeddings.py src/generator.py src/ingest.py src/rag_agent.py src/vectorstore.py
git add data/docs/
git add requirements.txt README.md .gitignore LICENSE models/.gitkeep
git commit -m "feat: implement core RAG pipeline with GGUF support"

:: Commit 2: Verification layer
git add src/verifier.py
git commit -m "feat: add embedding-based verification layer for hallucination mitigation"

:: Commit 3: Evolution benchmarks
git add tests/ logs/ data/evolution/
git commit -m "docs: add evolution logs and benchmarking suite results"

:: Push to GitHub
git remote add origin https://github.com/duckcoop/local-rag-agent.git
git push -u origin main

echo.
echo === Done! Repository pushed to GitHub ===
echo https://github.com/duckcoop/local-rag-agent
echo.
pause
