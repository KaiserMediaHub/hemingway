@echo off
cd /d "%~dp0"
echo Running memory tests (includes new leak-fix regression test)...
python test_delta_memory.py || goto :fail

echo.
echo Re-running Delta Analyzer tests (regression check)...
python test_delta_analyzer.py || goto :fail

echo.
echo Re-running Phase 1 tests (regression check)...
python test_tone_profile.py || goto :fail

echo.
echo Re-running Phase 2 tests (regression check)...
python test_tone_profile_phase2.py || goto :fail

echo.
echo Syntax-checking app.py, db.py, prompts.py...
python -c "import ast; [ast.parse(open(f).read()) for f in ['app.py','db.py','prompts.py']]; print('OK')" || goto :fail

echo.
echo Committing and pushing...
git add -A
git commit -m "Fix Delta Analyzer answer-leakage bug: regen call was being shown the current pair's own client edit as a 'follow this' example, causing verbatim repeats"
git push
echo.
echo Done. Press any key to close.
pause >nul
goto :eof

:fail
echo.
echo TESTS FAILED. Not committing. Read the output above.
pause >nul
