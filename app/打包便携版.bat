@echo off
rem Build a portable copy that can be handed to another computer.
rem PURE ASCII ON PURPOSE - cmd.exe parses a .bat by byte offset, so one UTF-8
rem Chinese line makes every following line lose its first characters.
rem Verify edits with:   python check_bats.py --run
setlocal
cd /d "%~dp0"
chcp 65001 >nul 2>&1

set "PY=D:\python\python.exe"
if not exist "%PY%" set "PY=python"

echo ============================================================
echo  Build portable package
echo  python : %PY%
echo  output : %~dp0..\dist\FollowMap-Portable
echo ------------------------------------------------------------
"%PY%" -u "%~dp0make_portable.py" %*
set "RC=%ERRORLEVEL%"
echo.
echo [pack] exit code = %RC%
if "%RC%"=="0" goto done
pause
:done
endlocal
