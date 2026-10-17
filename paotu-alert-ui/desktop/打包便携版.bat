@echo off
rem Build the portable package (exe + launchers + docs) into ..\dist\PaotuAlert-Portable
rem PURE ASCII ON PURPOSE - cmd.exe parses a .bat by byte offset, so one UTF-8
rem Chinese line makes every following line lose its first characters.
setlocal
cd /d "%~dp0"
chcp 65001 >nul 2>&1

set "PY=D:\python\python.exe"
if not exist "%PY%" set "PY=python"

echo ============================================================
echo  Build portable package
echo  python : %PY%
echo  output : %~dp0..\dist\PaotuAlert-Portable
echo ------------------------------------------------------------
"%PY%" -u "%~dp0make_portable.py" %*
set "RC=%ERRORLEVEL%"
echo.
echo [portable] exit code = %RC%
if "%RC%"=="0" goto done
pause
:done
endlocal
