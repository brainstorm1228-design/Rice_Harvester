@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%install_agent.ps1" %*
if errorlevel 1 (
    echo.
    echo Installation finished with an error. Press any key to close.
    pause >nul
)
