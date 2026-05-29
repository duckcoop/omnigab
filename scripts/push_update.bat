@echo off
echo === Pushing Hero README + Demo UI update ===

cd /d "%~dp0"

git add README.md src/demo_ui.py requirements.txt
git commit -m "feat: add Hero README, Rich terminal demo, and updated requirements"
git push origin main

echo.
echo === Update pushed ===
echo.
pause
