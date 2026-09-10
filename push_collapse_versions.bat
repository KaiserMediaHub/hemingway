@echo off
cd /d "%~dp0"
echo Syntax-checking app.py, db.py, prompts.py (no Python changed, just checking nothing broke)...
python -c "import ast; [ast.parse(open(f).read()) for f in ['app.py','db.py','prompts.py']]; print('OK')" || goto :fail

echo.
echo Committing and pushing...
git add -A
git commit -m "Collapse Tone Profile version list behind a closed-by-default dropdown"
git push
echo.
echo Done. Now deploy on the server:
echo   1. ssh root@178.104.152.111
echo   2. cd /var/www/hemingway ^&^& git pull ^&^& systemctl restart hemingway
echo   3. systemctl status hemingway   (confirm "active (running)")
echo.
echo Then refresh Style ^& Voice in the browser -- versions should be
echo collapsed behind "Versions (N) -- click to show" by default.
pause >nul
goto :eof

:fail
echo.
echo SYNTAX CHECK FAILED. Not committing. Read the output above.
pause >nul
