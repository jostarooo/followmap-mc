@echo off
chcp 65001 >nul
cd /d "%~dp0"
title BlockLegend Mouse Link Self-Test
echo ================================================================
echo  Mouse link self-test - click the mouse a few times
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
echo  This tells you WHICH source caught your click:
echo    Raw Input   = hardware level (external mouse usually)
echo    polling     = driver-synthesised (touchpad tap usually)
echo  It exits as soon as one full click is seen (or after 30s).
echo  Read-only: no cursor grab, no injection, no blocking.
echo.
"D:\python\python.exe" "%~dp0fishkey.py" --mousetest 30 %*
if "%~1"=="" pause
