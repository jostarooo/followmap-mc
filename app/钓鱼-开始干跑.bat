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
echo  DRY RUN: the mod judges and logs the QTE but NEVER presses a key.
echo  Use this to verify the reflection binding works on your machine.
echo.
"D:\python\python.exe" "%~dp0fishauto_ctl.py" on
"D:\python\python.exe" "%~dp0fishauto_ctl.py" dry
"D:\python\python.exe" "%~dp0fishauto_ctl.py" status %*
if "%~1"=="" pause
