@echo off
setlocal
cd /d "%~dp0"

set "PYTHON=py -3"
where py >nul 2>nul
if errorlevel 1 set "PYTHON=python"

if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  %PYTHON% -m venv .venv
  if errorlevel 1 goto :error
)

call ".venv\Scripts\activate.bat"
if errorlevel 1 goto :error

echo Installing/updating requirements...
python -m pip install --disable-pip-version-check -q -r requirements.txt
if errorlevel 1 goto :error

echo Starting Kick Studio...
python app.py %*
if errorlevel 1 goto :error
goto :eof

:error
echo.
echo Kick Studio could not start. Check the messages above.
pause
exit /b 1
