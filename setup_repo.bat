@echo off
echo === omnigab: GitHub repository bootstrap ===

cd /d "%~dp0"

:: Clean up corrupted .git if it exists
if exist ".git" (
    echo Removing old .git directory...
    rmdir /s /q .git
)

git init -b main
git config user.name "Cooper Preston"
git config user.email "cooperpreston43@gmail.com"

git add -A
git commit -m "feat: initial omnigab commit"

:: NOTE: update the URL below after you create / rename the GitHub repo.
git remote add origin https://github.com/duckcoop/omnigab.git
git push -u origin main

echo.
echo === Done! Repository pushed to GitHub ===
echo https://github.com/duckcoop/omnigab
echo.
pause
