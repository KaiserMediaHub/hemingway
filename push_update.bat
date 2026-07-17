@echo off
cd /d "%~dp0"
echo Working in: %cd%
echo.

git add .
git commit -m "Task #10: wire global anti-AI style doc into prompts.py"
git push

echo.
echo DONE. Scroll up and check for any red error text.
pause
