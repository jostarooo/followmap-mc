@echo off
chcp 65001 >nul
cd /d "%~dp0"
title BlockLegend Fishing Collector - channel B + live dashboard
echo ================================================================
echo  BlockLegend fishing collector: channel B capture + live dashboard
echo ================================================================
echo.
if not exist "D:\python\python.exe" (
  echo [X] Python not found: D:\python\python.exe
  pause
  exit /b 1
)
if not exist "%~dp0fishkey.py" (
  echo [X] fishkey.py missing next to this .bat
  pause
  exit /b 1
)
if not exist "%~dp0fishviz.py" (
  echo [X] fishviz.py missing next to this .bat
  pause
  exit /b 1
)
echo  Channel B (key/mouse marks) runs in THIS window; the live
echo  dashboard opens in a second window and refreshes itself.
echo  Close this window or press Ctrl+C to stop capturing.
echo.
start "FishViz Dashboard" "D:\python\python.exe" "%~dp0fishviz.py" --watch 5 --open
timeout /t 1 /nobreak >nul
"D:\python\python.exe" "%~dp0fishkey.py" %*
if "%~1"=="" pause
