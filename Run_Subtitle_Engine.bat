@echo off
chcp 65001 >nul
title YouTube Video to Burmese Subtitle & Transcript Engine
color 0B

echo =====================================================================
echo    🎬 YOUTUBE VIDEO TO BURMESE SUBTITLE & TRANSCRIPT ENGINE
echo =====================================================================
echo    Features:
echo    [1] Download video & Extract 1:1 original timestamps
echo    [2] Multi-language detection & English intermediate translation
echo    [3] Natural spoken Burmese translation (စကားပြောဟန်)
echo    [4] Strict 100%% original timestamp preservation in .srt
echo    [5] Exports: 01_video, 02_orig_txt, 03_en_txt, 04_mm_txt, 05_mm_srt, 06_report
echo =====================================================================
echo.

set "VENV_PYTHON=.venv\Scripts\python.exe"
if not exist "%VENV_PYTHON%" (
    set "VENV_PYTHON=python"
)

set /p "INPUT_URL=Enter YouTube URL or Video File Path: "
if "%INPUT_URL%"=="" (
    echo [ERROR] No URL or file path provided.
    pause
    exit /b 1
)

set /p "PROJ_NAME=Enter Project Name (Optional, press Enter to auto-name): "

echo.
echo Select Source Language:
echo [1] Auto-detect (Default)
echo [2] English (en)
echo [3] Chinese (zh)
echo [4] Japanese (ja)
echo [5] Korean (ko)
echo [6] Thai (th)
set /p "LANG_CHOICE=Choice [1-6, Enter for Auto]: "

set "SRC_LANG=auto"
if "%LANG_CHOICE%"=="2" set "SRC_LANG=en"
if "%LANG_CHOICE%"=="3" set "SRC_LANG=zh"
if "%LANG_CHOICE%"=="4" set "SRC_LANG=ja"
if "%LANG_CHOICE%"=="5" set "SRC_LANG=ko"
if "%LANG_CHOICE%"=="6" set "SRC_LANG=th"

set "NAME_ARG="
if not "%PROJ_NAME%"=="" (
    set "NAME_ARG=--name "%PROJ_NAME%""
)

echo.
echo =====================================================================
echo [*] Starting Subtitle Engine...
echo =====================================================================
echo.

"%VENV_PYTHON%" subtitle_engine.py -i "%INPUT_URL%" %NAME_ARG% --source-lang "%SRC_LANG%"

echo.
echo =====================================================================
echo [*] Subtitle Engine execution finished. Check the outputs folder!
echo =====================================================================
pause
