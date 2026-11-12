@echo off
REM Dublu-click: permite python.exe prin "Acces controlat la foldere" (Windows Security).
REM Cere drepturi de administrator (fereastra UAC -> Da).
net session >nul 2>&1
if %errorlevel% neq 0 (
    powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
    exit /b
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\permite_python.ps1"
echo.
pause
