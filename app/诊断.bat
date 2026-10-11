@echo off
rem Step-by-step diagnostic. Pure ASCII on purpose (see main launcher).
setlocal
cd /d "%~dp0"
set "PY_CHCP="
chcp 65001 >nul 2>&1
set "PY=D:\python\python.exe"
if not exist "%PY%" set "PY=python"
rem Fallbacks (see the main launcher): PATH, then the py launcher.
if not "%PY%"=="python" goto py_ready
where python >nul 2>&1
if not errorlevel 1 goto py_ready
where py >nul 2>&1
if not errorlevel 1 set "PY=py -3"
:py_ready

%PY% -u "%~dp0diagnose.py"
echo.
echo [diagnose] exit code = %ERRORLEVEL%
pause
endlocal
