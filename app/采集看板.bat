@echo off
chcp 65001 >nul
cd /d "%~dp0"
title BlockLegend Fishing Dashboard
echo ================================================================
echo  BlockLegend fishing dashboard - per-minigame sample counts
echo ================================================================
echo.
if not exist "D:\python\python.exe" (
  echo [X] Python not found: D:\python\python.exe
  pause
  exit /b 1
)
if not exist "%~dp0fishviz.py" (
  echo [X] fishviz.py missing next to this .bat
  pause
  exit /b 1
)
echo  Tips:
echo    --watch 5   keep refreshing (page reloads itself)
echo    --verbose   also dump every episode in the console
echo.
"D:\python\python.exe" "%~dp0fishviz.py" --watch 5 --open %*
if "%~1"=="" pause
