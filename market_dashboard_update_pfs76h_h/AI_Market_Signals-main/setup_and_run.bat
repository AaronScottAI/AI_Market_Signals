@echo off
REM One-click setup + launch for Market Signal Dashboard.
REM Double-click this file. First run sets everything up (takes a minute or
REM two); every run after that just launches the app in a few seconds.
REM Runs through cmd.exe, not PowerShell, so it isn't affected by
REM PowerShell's script execution policy.

cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo.
    echo Python wasn't found on this computer.
    echo Install Python 3.10 or newer from https://www.python.org/downloads/
    echo IMPORTANT: check "Add Python to PATH" during installation, then run this file again.
    echo.
    pause
    exit /b 1
)

if not exist ".venv" (
    echo Setting up Market Signal Dashboard for the first time...
    echo This installs everything into a local folder and only happens once.
    echo.
    python -m venv .venv
    call .venv\Scripts\activate.bat
    pip install -r requirements.txt
) else (
    call .venv\Scripts\activate.bat
)

echo.
echo Launching Market Signal Dashboard...
python main.py

if errorlevel 1 (
    echo.
    echo The app closed with an error - see above for details.
    pause
)
