@echo off
title Super Stream Bros Ultimate Dock
cd /d "%~dp0"
rem Find Python: the python.org installer's per-user folders first ("python" on PATH may be
rem the Microsoft Store stub), then the py launcher, then plain python.
for %%V in (314 313 312 311 310 39) do (
  if exist "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe" (
    "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe" dock_server.py
    goto done
  )
)
where py >nul 2>nul
if not errorlevel 1 (
  py -3 dock_server.py
  goto done
)
python dock_server.py
if errorlevel 9009 echo Python was not found. Install it from https://www.python.org/downloads/ (see SETUP.txt).
:done
pause
