@echo off
setlocal
cd /d "%~dp0"

set "PORT=8765"
if not "%~1"=="" set "PORT=%~1"

set "PY=%LOCALAPPDATA%\Microsoft\WindowsApps\python.exe"
if not exist "%PY%" (
    echo No se encontro python en: %PY%
    pause
    exit /b 1
)

echo ===================================================
echo  Cambio de Equipo FortiGate - servidor local
echo  URL: http://localhost:%PORT%
echo  (Cierra esta ventana para detener el servidor)
echo ===================================================
echo.

start "" "http://localhost:%PORT%"

"%PY%" server\app.py %PORT%

endlocal