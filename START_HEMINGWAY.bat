@echo off
title Hemingway - Kaiser Media Group
cd /d "%~dp0"

echo.
echo ============================================
echo  HEMINGWAY - Starting up
echo ============================================
echo.

where python >nul 2>nul
if errorlevel 1 goto NoPython

if exist ".env" goto SkipEnvSetup

echo First-time setup detected.
echo Creating your .env file from the template...
copy ".env.example" ".env" >nul
echo.
echo ============================================
echo  ACTION NEEDED
echo ============================================
echo.
echo Notepad will open your .env file.
echo Please fill in these three values:
echo.
echo   ANTHROPIC_API_KEY  - your Anthropic API key
echo   TEAM_PASSWORD      - the password to log in with
echo   SESSION_SECRET     - any random string of letters and numbers
echo.
echo Save the file, then close Notepad, then come back here.
echo.
pause
notepad ".env"
echo.
echo Once you have saved and closed Notepad, press any key to continue...
pause >nul

:SkipEnvSetup

if exist ".venv" goto SkipVenv

echo.
echo Creating Python virtual environment...
python -m venv .venv

:SkipVenv

echo.
echo Installing required packages...
call .venv\Scripts\pip install -r requirements.txt --quiet
if errorlevel 1 goto InstallFailed

echo.
echo ============================================
echo  Starting Hemingway...
echo ============================================
echo.
echo Once you see "Hemingway running on port 3000" below,
echo open your browser and go to: http://localhost:3000
echo.
echo Leave this window open while you use the app.
echo Close this window to stop Hemingway.
echo.

start "" cmd /c "timeout /t 3 >nul & start http://localhost:3000"
call .venv\Scripts\python app.py
goto End

:NoPython
echo ERROR: Python is not installed on this computer.
echo.
echo Please go to https://python.org, download Python 3.11 or newer,
echo install it (check "Add to PATH"), then double-click this file again.
echo.
pause
exit /b

:InstallFailed
echo.
echo Something went wrong during install. Scroll up to see
echo the error, or send it to Claude for help.
echo.
pause
exit /b

:End
pause
