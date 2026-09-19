@echo off
chcp 65001 >nul
title Original Audio & Burmese Hardsub Studio Engine
color 0A

echo =====================================================================
echo    🎞️ ORIGINAL AUDIO & BURMESE HARDSUB STUDIO ENGINE
echo =====================================================================
echo    Features:
echo    [1] 100%% Original Audio Preserved (No TTS Overwrite / Full SFX)
echo    [2] Vision AI Hardcoded Subtitle Blur Box
echo    [3] Anti-Copyright Shields (1.02x Zoom/Crop + Color Grade + Mirror)
echo    [4] Faithful 1:1 Dialogue Translation (Male / Female / Child Personas)
echo    [5] Selectable Aspect Ratios (16:9 Landscape / 9:16 Vertical Reels / Both)
echo    [6] Selectable Resolutions (1080p Full HD / 720p HD)
echo =====================================================================
echo.

set "VENV_PYTHON=.venv\Scripts\python.exe"
if not exist "%VENV_PYTHON%" (
    set "VENV_PYTHON=python"
)

set /p "INPUT_URL=Enter Video Path or YouTube URL: "
if "%INPUT_URL%"=="" (
    echo [ERROR] No URL or file path provided.
    pause
    exit /b 1
)

echo.
echo Select Aspect Ratio / Format:
echo [1] Both 16:9 Landscape + 9:16 Vertical Reels (Default)
echo [2] 16:9 YouTube Landscape Only
echo [3] 9:16 Facebook Reels / TikTok Only
set /p "FMT_CHOICE=Choice [1-3, Enter for Both]: "

set "FMT=both"
if "%FMT_CHOICE%"=="2" set "FMT=16:9"
if "%FMT_CHOICE%"=="3" set "FMT=9:16"

echo.
echo Select Resolution:
echo [1] 1080p Full HD (Default)
echo [2] 720p Fast HD
set /p "RES_CHOICE=Choice [1-2, Enter for 1080p]: "

set "RES=1080p"
if "%RES_CHOICE%"=="2" set "RES=720p"

echo.
echo Select Subtitle Style Preset:
echo [1] Cinema Box (Netflix Black Box - Default)
echo [2] TikTok / Reels Pop (Yellow & Black)
echo [3] Classic Movie White (Drop Shadow)
echo [4] Cyber Cyan (Modern Blue)
echo [5] Thriller Crimson (Dark Red Box)
set /p "STYLE_CHOICE=Choice [1-5, Enter for Box Black]: "

set "STYLE=box_black"
if "%STYLE_CHOICE%"=="2" set "STYLE=yellow_pop"
if "%STYLE_CHOICE%"=="3" set "STYLE=white_stroke"
if "%STYLE_CHOICE%"=="4" set "STYLE=cyan_cyber"
if "%STYLE_CHOICE%"=="5" set "STYLE=crimson_box"

echo.
echo =====================================================================
echo [*] Starting Hardsub Studio Engine...
echo =====================================================================
echo.

"%VENV_PYTHON%" hardsub_engine.py "%INPUT_URL%" --format "%FMT%" --res "%RES%" --style "%STYLE%"

echo.
echo =====================================================================
echo [*] Engine Finished! Check the outputs/ folder.
echo =====================================================================
pause
