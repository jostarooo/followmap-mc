@echo off
rem Silent launcher (no console window).  PURE ASCII ON PURPOSE - cmd.exe
rem parses a .bat by byte offset, so a single UTF-8 Chinese line makes the
rem following lines lose their first characters and the map never opens.
rem If anything goes wrong use the main launcher instead, so you can read
rem the error.  Verify edits with:   python check_bats.py --run
setlocal
cd /d "%~dp0"
set "PYW=D:\python\pythonw.exe"
if not exist "%PYW%" set "PYW=D:\python\python.exe"
if not exist "%PYW%" set "PYW=pythonw"
rem Fallbacks (see the main launcher for the reasoning): PATH, then the py
rem launcher - pyw.exe lands in C:\Windows even when "Add to PATH" is unticked.
if not "%PYW%"=="pythonw" goto pyw_ready
where pythonw >nul 2>&1
if not errorlevel 1 goto pyw_ready
where pyw >nul 2>&1
if not errorlevel 1 set "PYW=pyw -3"
:pyw_ready

set "APPPY=%~dp0followmap\app.py"
if exist "%APPPY%" goto have_script
echo [followmap] ERROR: script not found: %APPPY%
echo [followmap] The 'followmap' folder must sit next to this .bat file.
echo [followmap] Use the main launcher to see the full message.
pause
exit /b 2

:have_script
rem  optional args:  [SIZE] [extra args for app.py ...]
set "SIZE=%~1"
if "%SIZE%"=="" set "SIZE=520"
shift
set "EXTRA="
:collect_extra
if "%~1"=="" goto run
set "EXTRA=%EXTRA% %~1"
shift
goto collect_extra

:run
rem 150ms redraw keeps up with fast travel; see the main launcher note.
start "" %PYW% "%APPPY%" --size %SIZE% --interval 150 --layer auto --source auto%EXTRA%
endlocal
