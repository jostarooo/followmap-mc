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
echo  The mod obeys ~/.fishauto/config.json and reloads it every second,
echo  so changes take effect WITHOUT restarting the game.
echo.
echo  Factory defaults are FULLY OFF: enabled=false, dry_run=true.
echo  Nothing happens until you turn it on AND set it live.
echo.
echo  Common commands (pass them to this .bat as arguments):
echo    status              show switches / config / install / log summary
echo    on | off            master switch
echo    dry | live          dry-run (record only) | really press keys
echo    stop | resume       emergency stop / resume
echo    speed 130           press cadence in ms (human: 100-300)
echo    hold 2              hold ticks for hold-type keys
echo    report [N]          summarise the last N games
echo    tail [N]            dump the last N log lines
echo.
"D:\python\python.exe" "%~dp0fishauto_ctl.py" %*
if "%~1"=="" pause
