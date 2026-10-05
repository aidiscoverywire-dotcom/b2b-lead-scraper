@echo off
REM =====================================================================
REM  B2B AI Lead Scraper v6.2 — Windows build script
REM  Produces: installer\windows\Output\Setup_LeadScraper_v6_2.exe
REM
REM  Requirements (one-time setup):
REM    1. Python 3.12+  — https://python.org  (tick "Add to PATH")
REM    2. Inno Setup 6  — https://jrsoftware.org/isdl.php  (free)
REM    3. Node.js 20+   — https://nodejs.org  (for frontend build)
REM    4. WebView2 Runtime — pre-installed on Win10/11. If missing, the app
REM       still works: it opens in the default browser instead of a native window.
REM =====================================================================
setlocal
cd /d "%~dp0\..\.."

echo.
echo  ==^> Step 1/6: Python check
python --version >nul 2>&1
if errorlevel 1 (
    echo  ERROR: Python not found. Install from https://python.org
    pause & exit /b 1
)

echo.
echo  ==^> Step 2/6: Build frontend (React) — always rebuilt so code changes take effect
if exist "frontend\dist" rmdir /s /q "frontend\dist"
cd frontend
call npm install --silent
call npm run build
if errorlevel 1 ( echo  ERROR: frontend build failed. & pause & exit /b 1 )
cd ..

echo.
echo  ==^> Step 3/6: Python dependencies + pywebview
if not exist ".venv-win" python -m venv .venv-win
call .venv-win\Scripts\activate.bat
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r backend\requirements.txt pyinstaller pywebview
if errorlevel 1 ( echo  ERROR: pip install failed. & pause & exit /b 1 )

echo.
echo  ==^> Step 4/6: PyInstaller — build LeadScraper.exe
rmdir /s /q build 2>nul
rmdir /s /q dist  2>nul
pyinstaller --noconfirm installer\windows\app.spec
if errorlevel 1 ( echo  ERROR: PyInstaller failed. See above. & pause & exit /b 1 )
echo  Built: dist\LeadScraper\LeadScraper.exe

echo.
echo  ==^> Step 5/6: PyInstaller — build ResetPassword.exe (password recovery tool)
pyinstaller --noconfirm installer\windows\reset_password.spec
if errorlevel 1 ( echo  ERROR: ResetPassword build failed. See above. & pause & exit /b 1 )
REM onefile spec -> dist\ResetPassword.exe (self-contained, no _internal folder)
copy /y "dist\ResetPassword.exe" "dist\LeadScraper\ResetPassword.exe" >nul
if errorlevel 1 ( echo  ERROR: could not copy ResetPassword.exe. & pause & exit /b 1 )
echo  Built: dist\LeadScraper\ResetPassword.exe

echo.
echo  ==^> Step 6/6: Inno Setup installer
if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" goto :have_iscc
if exist "C:\Program Files\Inno Setup 6\ISCC.exe"       goto :have_iscc64
echo  Inno Setup not found — exe is ready at dist\LeadScraper\LeadScraper.exe
echo  Install Inno Setup to generate the Setup_*.exe installer.
pause & exit /b 0
:have_iscc
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" "installer\windows\setup.iss"
goto :iscc_done
:have_iscc64
"C:\Program Files\Inno Setup 6\ISCC.exe" "installer\windows\setup.iss"
:iscc_done
if errorlevel 1 ( echo  ERROR: Inno Setup failed. & pause & exit /b 1 )

echo.
echo =====================================================================
echo  SUCCESS!  installer\windows\Output\Setup_LeadScraper_v6_2.exe
echo  Buyers: double-click Setup file → Next → Finish. Done.
echo =====================================================================
pause
