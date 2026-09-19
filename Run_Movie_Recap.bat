@echo off
chcp 65001 >nul
cd /d "%~dp0"
title AI Movie Recap Generator - Windows Launcher
color 0B
set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"

:MENU
cls
echo ===============================================================================
echo            🎬  AI MOVIE RECAP GENERATOR - 100%% FREE LOCAL PIPELINE  🎬
echo ===============================================================================
echo.
echo    [1] 🚀 Auto-Process All Videos in "movies/" Folder (Batch Mode)
echo    [2] 🔗 Process a Single YouTube / TikTok URL or Video File Path
echo    [3] ⚡ Force Re-Process All Videos in "movies/" (Ignore Completed)
echo    [4] 🌐 Launch Interactive Web UI (Graphical Dashboard)
echo    [5] 🗑️  Open Cleanup Utility (Delete Old Outputs or Source Videos)
echo    [6] 🎞️ Launch Hardsub Studio (Original Audio + Anti-Copyright Shields)
echo    [7] 📝 Launch Subtitle & Transcript Studio (YouTube to Burmese Subs)
echo    [0] ❌ Exit
echo.
echo ===============================================================================
set /p choice="👉 Select an option [0-7]: "

if "%choice%"=="1" goto BATCH
if "%choice%"=="2" goto SINGLE
if "%choice%"=="3" goto FORCE
if "%choice%"=="4" goto WEBUI
if "%choice%"=="5" goto CLEAN
if "%choice%"=="6" goto HARDSUB
if "%choice%"=="7" goto SUBTITLE
if "%choice%"=="0" goto EXIT
goto MENU

:BATCH
cls
echo ===============================================================================
echo 🚀 STARTING BATCH RECAP GENERATION FOR ALL VIDEOS IN "movies/" FOLDER...
echo ===============================================================================
"%PYTHON_EXE%" main.py --batch
echo.
echo ===============================================================================
echo ✅ Batch Processing Complete! Press any key to return to menu...
pause >nul
goto MENU

:SINGLE
cls
echo ===============================================================================
echo 🔗 PASTE YOUTUBE/TIKTOK URL OR LOCAL VIDEO FILE PATH BELOW:
echo ===============================================================================
echo Tip: For YouTube links, paste full link (e.g., https://www.youtube.com/watch?v=...)
echo.
set "input_src="
set /p "input_src=👉 Input URL or File Path: "
setlocal EnableDelayedExpansion
if not defined input_src (
    endlocal
    goto MENU
)
cls
echo ===============================================================================
echo 🎬 PROCESSING: !input_src!
echo ===============================================================================
"%PYTHON_EXE%" main.py "!input_src!"
endlocal
echo.
echo ===============================================================================
echo ✅ Processing Complete! Press any key to return to menu...
pause >nul
goto MENU

:FORCE
cls
echo ===============================================================================
echo ⚡ FORCE RE-PROCESSING ALL VIDEOS IN "movies/" FOLDER...
echo ===============================================================================
"%PYTHON_EXE%" main.py --batch --force
echo.
echo ===============================================================================
echo ✅ Force Batch Processing Complete! Press any key to return to menu...
pause >nul
goto MENU

:WEBUI
cls
echo ===============================================================================
echo 🌐 STARTING GRAPHICAL WEB UI SERVER...
echo ===============================================================================
echo Open your web browser and go to: http://localhost:5000
echo Press Ctrl+C in this window to stop the web server.
echo.
start http://localhost:5000
"%PYTHON_EXE%" web_ui.py
pause
goto MENU

:CLEAN
cls
"%PYTHON_EXE%" main.py --clean
pause
goto MENU

:HARDSUB
cls
call "%~dp0Run_Hardsub_Engine.bat"
goto MENU

:SUBTITLE
cls
call "%~dp0Run_Subtitle_Engine.bat"
goto MENU

:EXIT
exit
