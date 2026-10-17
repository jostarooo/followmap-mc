@echo off
chcp 65001 >nul
cd /d "%~dp0"
title BlockLegend Auto-Fish Control
echo ================================================================
echo  BlockLegend auto-fish (fishauto) control
echo ================================================================
echo.
if not exist "D:\python\python.exe" (
  echo [X] Python not found: D:\python\python.exe
  pause
  exit /b 1
)
if not exist "%~dp0fishauto_ctl.py" (
  echo [X] fishauto_ctl.py missing next to this .bat
  pause
  exit /b 1
)
echo  WARNING: this makes the mod REALLY PRESS KEYS (left click / LShift).
echo  It only writes the vanilla KeyMapping fields, so it is equivalent to
echo  you pressing the key yourself - but it WILL act while you play.
echo.
echo  Emergency stop at any time:  fishauto_ctl.py stop   (or this .bat: stop)
echo.
pause
"D:\python\python.exe" "%~dp0fishauto_ctl.py" on
"D:\python\python.exe" "%~dp0fishauto_ctl.py" live
"D:\python\python.exe" "%~dp0fishauto_ctl.py" status %*
if "%~1"=="" pause
