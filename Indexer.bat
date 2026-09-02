@echo off
rem GClaude Indexer -- activates the local environment, starts the server
rem and opens the browser at the URL (phase 11). If the environment does
rem not exist yet on this machine, runs install.ps1 first.

setlocal

set "ROOT=%~dp0"
set "VENV=%LOCALAPPDATA%\GClaudeIndexer\venv"
set "URL=http://127.0.0.1:8000"

rem The project folder is synced by Google Drive -- never write
rem __pycache__ into it (section 11.1).
set "PYTHONDONTWRITEBYTECODE=1"

rem Optional (phase 15, task 3): "--cpu-sensor" asks the server to start the
rem elevated sensor helper, which is the only way to read CPU temperature
rem and power draw (LibreHardwareMonitor needs a kernel driver for those).
rem Without the flag nothing is elevated and nothing is asked -- this is the
rem default, and the desktop shortcut created by install.ps1 does not pass
rem it. The second shortcut, "GClaude Indexer (CPU sensor)", does.
rem
rem The flag does NOT elevate this script or the server: it only sets the
rem variable that makes the (unprivileged) server spawn one small
rem administrator child process whose whole job is reading five numbers.
rem Saying No to the UAC prompt leaves everything running exactly as it
rem does without the flag.
if /i "%~1"=="--cpu-sensor" (
    set "GCLAUDE_INDEXER_CPU_SENSOR=1"
    echo [Indexer] CPU sensor requested: Windows will ask for administrator
    echo [Indexer] for the sensor reader only. Saying No is fine -- the system
    echo [Indexer] opens anyway, just without CPU temperature and power.
)

if not exist "%VENV%\Scripts\activate.bat" (
    echo [Indexer] Environment not prepared on this machine yet.
    echo [Indexer] Running the installer ^(install.ps1^) first...
    powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%install.ps1"
    if errorlevel 1 (
        echo.
        echo [Indexer] The installer ran into a problem. See the messages above.
        pause
        exit /b 1
    )
)

rem Rebuild PATH from the registry before starting anything.
rem
rem install.ps1 adds Tesseract, Ghostscript and Ollama to the user's PATH
rem and broadcasts WM_SETTINGCHANGE, but Explorer frequently does not act
rem on it -- and this script was started by Explorer, so it inherits the
rem environment Explorer had when *it* started, from before the install.
rem That is why a fresh install appeared to need a reboot: the install was
rem complete, the variable just had not reached the running processes.
rem Reading it back from the registry costs one PowerShell startup and
rem removes the reboot. A failure here is not fatal -- gclaude_indexer's
rem tools.py resolves the same programs by absolute path (tools.json), so
rem this is the first of two independent fixes, not the only one.
for /f "usebackq delims=" %%P in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$m=[Environment]::GetEnvironmentVariable('Path','Machine'); $u=[Environment]::GetEnvironmentVariable('Path','User'); ($m,$u -ne '' -join ';')" 2^>nul`) do set "PATH=%%P"

call "%VENV%\Scripts\activate.bat"

rem pythonw.exe does not open a console window (version 1.0 -- explicit
rem user request: the server window stays suppressed). Use "python.exe"
rem here instead of "pythonw.exe" only if you need to see the server's
rem errors in the console while debugging.
echo [Indexer] Starting the GClaude Indexer server...
start "" /b "%VENV%\Scripts\pythonw.exe" "%ROOT%run_server.py"

timeout /t 2 /nobreak >nul

echo [Indexer] Opening %URL% in the browser...
start "" "%URL%"

endlocal
