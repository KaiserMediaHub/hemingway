@echo off
cd /d "%~dp0"
echo Running Phase 2 tests...
python test_tone_profile_phase2.py || goto :fail

echo.
echo Re-running Phase 1 tests (regression check)...
python test_tone_profile.py || goto :fail

echo.
echo Syntax-checking app.py, db.py, prompts.py...
python -c "import ast; [ast.parse(open(f).read()) for f in ['app.py','db.py','prompts.py']]; print('OK')" || goto :fail

echo.
echo Committing and pushing...
git add -A
git commit -m "Phase 2: wire active Tone Profile into generation prompts (replaces style_rules/reference_copy when active)"
git push
echo.
echo Done. Press any key to close.
pause >nul
goto :eof

:fail
echo.
echo TESTS FAILED. Not committing. Read the output above.
pause >nul
