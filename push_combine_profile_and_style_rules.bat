@echo off
cd /d "%~dp0"
echo Running Phase 2 tests (includes updated precedence-v2 tests)...
python test_tone_profile_phase2.py || goto :fail

echo.
echo Re-running Phase 1 tests (regression check)...
python test_tone_profile.py || goto :fail

echo.
echo Re-running Delta Analyzer tests (regression check -- still works, just hidden in UI)...
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
git commit -m "Precedence v2: combine active Tone Profile (voice baseline) with client Style Rules doc (explicit corrections) instead of either/or. Hide Delta Analyzer card in UI (retired, not deleted)."
git push
echo.
echo Done. Deploy on the server:
echo   1. ssh root@178.104.152.111
echo   2. cd /var/www/hemingway ^&^& git pull ^&^& systemctl restart hemingway
echo   3. systemctl status hemingway   (confirm "active (running)")
echo.
echo Then in Hemingway, Harris Projects -^> Style ^& Voice:
echo   - Open "Versions (N) -- click to show" and find v1 (source_type
echo     "transcript", no change summary -- that's the original long-form
echo     interview synthesis, before any of tonight's opener-shape additions).
echo   - Click "Activate" on v1.
echo   - Your existing Style Rules text box and uploaded Reference Copy docs
echo     stay exactly as they are -- they now combine with v1 automatically,
echo     with your Style Rules winning on any conflict.
echo   - The Delta Analyzer card is now collapsed/hidden by default -- nothing
echo     was deleted, it is just out of the way.
pause >nul
goto :eof

:fail
echo.
echo TESTS FAILED. Not committing. Read the output above.
pause >nul
