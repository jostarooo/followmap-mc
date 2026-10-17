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
echo  Creating ~/.fishauto/STOP - the mod stops pressing keys immediately
echo  (it keeps logging). Remove with:  fishauto_ctl.py resume
echo.
"D:\python\python.exe" "%~dp0fishauto_ctl.py" stop
"D:\python\python.exe" "%~dp0fishauto_ctl.py" status %*
if "%~1"=="" pause
