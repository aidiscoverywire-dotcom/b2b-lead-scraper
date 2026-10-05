@echo off
REM =====================================================================
REM  LeadScraper — Reset Password (double-click, no commands to type)
REM  Works with the source folder. For the installed app, use the
REM  "Reset Password" shortcut in the Start Menu instead.
REM =====================================================================
title LeadScraper - Reset Password
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo.
    echo  Python nahi mila. https://python.org se Python install karo
    echo  ("Add python to PATH" tick zaroor karna), phir dobara chalao.
    echo.
    pause
    exit /b 1
)

REM Installed app ka database use karo agar mojood hai
if exist "%APPDATA%\LeadScraper\data\leadscraper.db" (
    set DATA_DIR=%APPDATA%\LeadScraper\data
)

echo.
python reset_password.py
echo.
pause
