@echo off
cd /d "%~dp0"
echo Running Phase 1 tests (includes new deactivate tests)...
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
echo Re-running opener rotation tests (regression check)...
python test_opener_rotation.py || goto :fail

echo.
echo Syntax-checking app.py, db.py, prompts.py...
python -c "import ast; [ast.parse(open(f).read()) for f in ['app.py','db.py','prompts.py']]; print('OK')" || goto :fail

echo.
echo Committing and pushing...
git add -A
git commit -m "Add Tone Profile deactivate: one-click revert to the simple style_rules + reference-copy system per client, no history lost"
git push
echo.
echo Done. Deploy on the server:
echo   1. ssh root@178.104.152.111
echo   2. cd /var/www/hemingway ^&^& git pull ^&^& systemctl restart hemingway
echo   3. systemctl status hemingway   (confirm "active (running)")
echo.
echo Then in Hemingway: Harris Projects -^> Style ^& Voice -^> click
echo "Turn off Tone Profile for this context" under the active-version banner.
echo That's it -- no need to touch anything else. Generation will use Harris's
echo Style Rules box + Reference Copy uploads exactly like before Phase 1.
pause >nul
goto :eof

:fail
echo.
echo TESTS FAILED. Not committing. Read the output above.
pause >nul
