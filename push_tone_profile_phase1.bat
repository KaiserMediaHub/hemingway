@echo off
cd /d "%~dp0"
echo Running tone-profile tests (only test file that's Windows-compatible)...
python test_tone_profile.py || goto :fail

echo.
echo Syntax-checking app.py, db.py, prompts.py...
python -c "import ast; [ast.parse(open(f).read()) for f in ['app.py','db.py','prompts.py']]; print('OK')" || goto :fail

echo.
echo Committing and pushing...
git add -A
git commit -m "Add Tone Profile Phase 1: versioned voice profiles per client/context (inert -- not wired to generation yet)"
git push
echo.
echo Done. Press any key to close this window.
pause >nul
goto :eof

:fail
echo.
echo TESTS FAILED. Not committing. Read the output above.
pause >nul
