@echo off
cd /d "%~dp0"
echo Running new opener rotation tests...
python test_opener_rotation.py || goto :fail

echo.
echo Re-running Phase 1 tests (regression check)...
python test_tone_profile.py || goto :fail

echo.
echo Re-running Phase 2 tests (regression check)...
python test_tone_profile_phase2.py || goto :fail

echo.
echo Re-running Delta Analyzer tests (regression check)...
python test_delta_analyzer.py || goto :fail

echo.
echo Re-running Delta memory / leak-fix tests (regression check)...
python test_delta_memory.py || goto :fail

echo.
echo Syntax-checking app.py, db.py, prompts.py...
python -c "import ast; [ast.parse(open(f).read()) for f in ['app.py','db.py','prompts.py']]; print('OK')" || goto :fail

echo.
echo Committing and pushing...
git add -A
git commit -m "Phase 5: opener rotation (opener_shapes + recent/batch-aware anti-repetition) + opener library"
git push
echo.
echo Done. Now deploy on the server:
echo   1. ssh root@178.104.152.111
echo   2. cd /var/www/hemingway ^&^& git pull ^&^& systemctl restart hemingway
echo   3. systemctl status hemingway   (confirm "active (running)")
echo.
echo After that, run the Harris profile update script (see load_harris_opener_shapes.py)
echo over SSH to add the 25 opener shapes + consolidated voice rules as a new
echo PENDING version -- you'll review and activate it yourself in Style ^& Voice.
pause >nul
goto :eof

:fail
echo.
echo TESTS FAILED. Not committing. Read the output above.
pause >nul
