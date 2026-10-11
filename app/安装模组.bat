@echo off
cd /d "%~dp0"
set PY=D:\python\python.exe
if not exist "%PY%" set PY=python
"%PY%" build_mod.py --mc 1.20.4
echo.
pause
