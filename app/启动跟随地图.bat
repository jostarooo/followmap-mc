@echo off
rem =====================================================================
rem  Fangkuai Chuanshuo - Follow Map (Scheme C) launcher
rem
rem  !!  THIS FILE MUST STAY 100 PERCENT PURE ASCII  !!
rem
rem  Why: cmd.exe reads a .bat file using the *console codepage* and moves
rem  a BYTE offset forward line by line.  A single line holding UTF-8
rem  Chinese makes that offset drift, so every following line loses its
rem  first characters ("rem" -> "em", "set" -> "et"), variables come out
rem  empty and the map window never opens.  Real observed failure:
rem      'em' is not recognized as an internal or external command
rem      [followmap] STARTUP FAILED  (because --size was blank)
rem
rem  So: all text here is English on purpose.  The map window itself
rem  renders Chinese fine (its own renderer, not the console).
rem
rem  After editing this file run:   python check_bats.py
rem =====================================================================
setlocal
cd /d "%~dp0"
chcp 65001 >nul 2>&1

rem ---- find a python. Order: this machine's fixed path -> PATH -> py launcher.
rem The py launcher (py.exe) is installed by python.org even when the box
rem "Add python.exe to PATH" is left unticked, so it is the best last resort.
rem None of the three candidates contains a space, so the call below leaves
rem %PY% unquoted on purpose (so that "py -3" works as a two-token command).
set "PY=D:\python\python.exe"
if not exist "%PY%" set "PY=python"
if not "%PY%"=="python" goto py_ready
where python >nul 2>&1
if not errorlevel 1 goto py_ready
where py >nul 2>&1
if not errorlevel 1 set "PY=py -3"
:py_ready

set "APPPY=%~dp0followmap\app.py"

rem ---- optional args:  [SIZE] [INTERVAL_MS] [LAYER] [extra args...] ----
set "SIZE=%~1"
if "%SIZE%"=="" set "SIZE=520"
set "INTERVAL=%~2"
if "%INTERVAL%"=="" set "INTERVAL=150"
set "LAYER=%~3"
if "%LAYER%"=="" set "LAYER=auto"

rem Shift past the three positional args, then collect anything else and
rem hand it straight to app.py (e.g. --selfclose 4  --dim null  --no-grid).
shift
shift
shift
set "EXTRA="
:collect_extra
if "%~1"=="" goto args_done
set "EXTRA=%EXTRA% %~1"
shift
goto collect_extra
:args_done

echo ============================================================
echo  Follow Map  size=%SIZE%  interval=%INTERVAL%ms  layer=%LAYER%
echo  python : %PY%
echo  script : %APPPY%
if not "%EXTRA%"=="" echo  extra  :%EXTRA%
echo ------------------------------------------------------------
echo  Drag = move   Wheel/z/x = zoom map   t = topmost   f = border
echo  g = grid   c = layer   n/p = dim   v = source   Esc = quit
echo  Resize window: + / - keys, 0 = reset, Ctrl+Wheel, or right-drag
echo  the bottom-right corner.
echo  r = cycle ruin alert (auto=sound+flash / sound / both=+shake / flag / off)
echo  Ruin alert: wizard / samurai / white-star ruins, fires only on
echo  newly loaded chunks.  Sound = 3 pings, no window shake by default
echo  (you watch the other screen).  Extra args can override, e.g.
echo  --ruin-alert both  --ruin-volume 2.0  --no-ruin.
echo ============================================================
echo.

if exist "%APPPY%" goto have_script
echo [followmap] ERROR: script not found: %APPPY%
echo [followmap] The 'followmap' folder must sit next to this .bat file.
set "RC=2"
goto failed

:have_script
if not "%SIZE%"=="" goto have_size
echo [followmap] ERROR: SIZE is empty - this launcher is probably corrupted.
echo [followmap] Fix: keep the file pure ASCII.  Verify with:
echo [followmap]      python check_bats.py
set "RC=3"
goto failed

:have_size
%PY% -u "%APPPY%" --size %SIZE% --interval %INTERVAL% --layer %LAYER% --source auto%EXTRA%
set "RC=%ERRORLEVEL%"
echo.
echo [followmap] exit code = %RC%
if "%RC%"=="0" goto done

echo.
echo [followmap] STARTUP FAILED (code %RC%). Read the messages above.
echo [followmap] Tip: run  diagnose.bat  for a step-by-step check.
pause

:done
endlocal
