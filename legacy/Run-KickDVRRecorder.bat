@echo off
title Kick Studio
setlocal
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0KickDVRRecorder.ps1"
if errorlevel 1 (
  echo.
  echo Kick Studio closed with an error.
  pause
)
endlocal
