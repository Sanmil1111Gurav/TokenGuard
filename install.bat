@echo off
REM ==============================================================================
REM TokenGuard 1-Command Installer for Antigravity & Cursor
REM ==============================================================================
SET "SCRIPT_DIR=%~dp0"
CD /D "%SCRIPT_DIR%"

IF EXIST ".venv\Scripts\python.exe" (
    SET "PY_CMD=.venv\Scripts\python.exe"
) ELSE (
    SET "PY_CMD=python"
)

%PY_CMD% install_plugin.py %*
IF ERRORLEVEL 1 (
    echo [ERROR] Installation failed.
    exit /b 1
)
