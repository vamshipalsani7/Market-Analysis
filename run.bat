@echo off
REM ============================================================
REM   India Market Pulse - double-click launcher (Windows)
REM ============================================================
cd /d "%~dp0"
title India Market Pulse

echo.
echo   Starting India Market Pulse...
echo.

REM --- find Python ---
where python >nul 2>&1
if %errorlevel%==0 (
    set "PY=python"
) else (
    where py >nul 2>&1
    if %errorlevel%==0 (
        set "PY=py"
    ) else (
        echo   [!] Python was not found on this PC.
        echo       Install it from https://www.python.org/downloads/
        echo       During setup, tick "Add Python to PATH".
        echo.
        pause
        exit /b 1
    )
)

REM --- install dependency the first time (quiet, user scope) ---
echo   Checking data library (one-time setup on first run)...
%PY% -m pip install --quiet --disable-pip-version-check --user -r requirements.txt

REM --- open the browser, then start the server ---
start "" http://localhost:8765
echo.
echo   The dashboard is opening in your browser.
echo   Keep THIS window open while you use the tool.
echo   Close it (or press Ctrl+C) to stop.
echo.
%PY% server.py 8765

pause
