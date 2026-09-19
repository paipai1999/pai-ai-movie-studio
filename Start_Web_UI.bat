@echo off
chcp 65001 >nul
cd /d "%~dp0"
title AI Movie Recap Generator - Web UI Dashboard
color 0B

set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"

cls
echo ===============================================================================
echo            🎬  AI MOVIE RECAP GENERATOR - WEB UI DASHBOARD  🎬
echo ===============================================================================
echo.
echo [*] စနစ်စစ်ဆေးနေပါသည် / Checking Python environment...
"%PYTHON_EXE%" -c "import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)" >nul 2>&1
if errorlevel 1 (
    echo.
    echo ❌ [ERROR] Python 3.8+ or virtual environment (.venv) not found!
    echo    Please ensure python and virtual environment are installed.
    echo.
    pause
    exit /b 1
)

echo [*] Port 5000 စစ်ဆေးနေပါသည် / Checking Port 5000 availability...
"%PYTHON_EXE%" -c "import socket; s = socket.socket(); err = s.connect_ex(('127.0.0.1', 5000)); s.close(); exit(0 if err != 0 else 1)" >nul 2>&1
if errorlevel 1 (
    echo [!] Port 5000 is occupied by a previous session.
    echo [*] ယခင်ဖွင့်ထားသော session အဟောင်းကို ရှင်းလင်းနေပါသည် / Auto-clearing old session...
    "%PYTHON_EXE%" -c "import subprocess; subprocess.run(['powershell', '-Command', 'Get-NetTCPConnection -LocalPort 5000 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }'], capture_output=True)" >nul 2>&1
    timeout /t 1 /nobreak >nul
)

echo [*] Web Server စတင်ဖွင့်လှစ်နေပါသည် / Launching Web UI Server...
echo [*] Server အဆင်သင့်ဖြစ်ပါက Browser အလိုအလျောက် ပွင့်လာပါမည်...

:: Launch browser automatically as soon as server listens on port 5000
start /b "" "%PYTHON_EXE%" -c "import socket, time, webbrowser; [time.sleep(0.5) for _ in range(60) if not (socket.socket().connect_ex(('127.0.0.1', 5000)) == 0 and webbrowser.open('http://localhost:5000') or True and socket.socket().connect_ex(('127.0.0.1', 5000)) == 0)]" >nul 2>&1

echo.
echo ===============================================================================
echo  🌐 Dashboard Link : http://localhost:5000
echo  💡 Server ပိတ်ရန်  : Command window တွင် Ctrl + C ကို နှိပ်ပါ
echo ===============================================================================
echo.

"%PYTHON_EXE%" web_ui.py
if errorlevel 1 (
    echo.
    echo ❌ [!] Web UI Server ရပ်တန့်သွားပါသည် / Server stopped with an error code.
    echo.
    pause
)
