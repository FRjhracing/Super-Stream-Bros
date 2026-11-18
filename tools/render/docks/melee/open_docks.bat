@echo off
rem Opens the Super Stream Bros dock pages in the default browser:
rem   Super Stream Bros - Home   http://127.0.0.1:8765/
rem   SSB:Full Bracket           http://127.0.0.1:8765/bracket
rem   SSB:Active Bracket         http://127.0.0.1:8765/active
rem Starts the dock server first (in its own window) if it isn't already running.
cd /d "%~dp0"
set "URL=http://127.0.0.1:8765"

curl.exe -s -o nul --max-time 2 "%URL%/" && goto open

echo Starting the dock server...
start "Super Stream Bros Dock Server" "%~dp0start_dock.bat"
for /l %%i in (1,1,30) do (
  timeout /t 1 /nobreak >nul
  curl.exe -s -o nul --max-time 2 "%URL%/" && goto open
)
echo The dock server didn't start. Check the "Super Stream Bros Dock Server" window for errors.
pause
exit /b 1

:open
start "" "%URL%/"
start "" "%URL%/bracket"
start "" "%URL%/active"
