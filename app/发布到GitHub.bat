@echo off
rem =====================================================================
rem  FollowMap -- publish the current version to GitHub
rem  target : https://github.com/jostarooo/followmap-mc   (private)
rem
rem  !!  THIS FILE MUST STAY 100 PERCENT PURE ASCII  !!
rem
rem  Why: cmd.exe reads a .bat using the *console codepage* and moves a
rem  BYTE offset forward line by line.  One line holding UTF-8 Chinese
rem  makes that offset drift, so every following line loses its first
rem  characters ("rem" -> "em", "set" -> "et"), variables come out empty
rem  and the script silently does the wrong thing.
rem  After editing this file run:   python check_bats.py --run
rem
rem  Usage:
rem     double click                       -> rebuild mod, commit, push
rem     "message" as arg 1                 -> same, with your own message
rem     --no-build as arg 1                -> skip rebuilding the mod jar
rem
rem  Token lookup order:  GH_TOKEN env var  ->  %USERPROFILE%\.followmap-gh-token
rem  Details in push_github.py.
rem =====================================================================
setlocal
cd /d "%~dp0"
chcp 65001 >nul 2>&1

rem ---- find a python (same order as the launcher .bat) ----
set "PY=D:\python\python.exe"
if not exist "%PY%" set "PY=python"
if not "%PY%"=="python" goto py_ready
where python >nul 2>&1
if not errorlevel 1 goto py_ready
where py >nul 2>&1
if not errorlevel 1 set "PY=py -3"
:py_ready

set "PUSH=%~dp0push_github.py"
set "BUILD=--build"
set "MSG="

:parse
if "%~1"=="" goto run
if /i "%~1"=="--no-build" goto no_build
set "MSG=%~1"
shift
goto parse

:no_build
set "BUILD="
shift
goto parse

:run
set "ARGS=--commit"
if not "%BUILD%"=="" set "ARGS=%ARGS% %BUILD%"
if not "%MSG%"=="" set "ARGS=%ARGS% --message "%MSG%""

echo ============================================================
echo  FollowMap  -^>  github.com/jostarooo/followmap-mc
echo  python : %PY%
echo  args   : %ARGS%
echo ------------------------------------------------------------
echo  Rebuilds the mod, commits local changes, uploads via API.
echo  Do NOT close this window until it prints "done".
echo ============================================================
echo.

if exist "%PUSH%" goto have_script
echo [X] script not found: %PUSH%
set "RC=2"
goto failed

:have_script
%PY% -u "%PUSH%" %ARGS%
set "RC=%ERRORLEVEL%"
echo.
if not "%RC%"=="0" goto failed
echo [ok] published.
goto done

:failed
echo [X] publish FAILED (exit code %RC%). Read the messages above.

:done
echo.
pause
endlocal
