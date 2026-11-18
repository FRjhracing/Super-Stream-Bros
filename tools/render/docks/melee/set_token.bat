@echo off
rem Usage: set_token.bat                       saves the token as STARTGG_TOKEN (the normal case)
rem        set_token.bat STARTGG_TOKEN_STREAM2  saves it under another name, for a second dock on the
rem                                             same PC ("tokenVar" in that dock's dock_config.json)
title Super Stream Bros - start.gg token
set "VAR=%~1"
if "%VAR%"=="" set "VAR=STARTGG_TOKEN"
echo.
echo Paste your start.gg token below and press Enter.
echo (Get one at start.gg: profile picture ^> Developer Settings ^> Personal Access Tokens ^> Create new token.)
echo It is saved as a Windows user setting (%VAR%), not in any file. Don't share it.
echo.
set "TOKEN="
set /p TOKEN=Token:
if "%TOKEN%"=="" (
  echo Nothing entered; nothing changed.
  pause
  exit /b
)
setx %VAR% "%TOKEN%" >nul
set "TOKEN="
cls
echo Token saved as %VAR%. Close and reopen start_dock.bat if it was already running.
pause
