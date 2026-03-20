@echo off
setlocal
set "PORT=8765"
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
  set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
) else (
  set "PYTHON_EXE=python"
)

for /f "tokens=5" %%P in ('netstat -ano ^| findstr ":%PORT%" ^| findstr "LISTENING"') do (
  echo Local reader is already running on port %PORT%.
  start "" "http://127.0.0.1:%PORT%/?v=20260320-live3"
  exit /b 0
)

echo Starting Daily Paper Reader local server on port %PORT%...
start "DPR Local Server" "%PYTHON_EXE%" -m http.server %PORT%
timeout /t 2 >nul
start "" "http://127.0.0.1:%PORT%/?v=20260320-live3"
exit /b 0
