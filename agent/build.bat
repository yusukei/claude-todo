@echo off
REM ============================================================
REM  MCP Todo Remote Workspace Agent — Windows build script
REM
REM  Builds a self-contained mcp-workspace-agent.exe via PyInstaller.
REM  Output: dist\mcp-workspace-agent.exe
REM
REM  Prerequisites: uv (https://docs.astral.sh/uv/) on PATH
REM
REM  Usage:
REM    build.bat            - normal build
REM    build.bat --clean    - wipe build/ + dist/ first
REM ============================================================
setlocal

REM Always run from this script's directory so relative paths work
REM regardless of where the user invoked the .bat from.
cd /d "%~dp0"

if /i "%~1"=="--clean" (
    echo [build] Cleaning build artifacts...
    if exist build rmdir /s /q build
    if exist dist rmdir /s /q dist
)

echo [build] Syncing dependencies (including dev tools)...
uv sync --quiet
if errorlevel 1 (
    echo [build] uv sync failed.
    exit /b 1
)

echo [build] Running PyInstaller...
uv run pyinstaller mcp-workspace-agent.spec --noconfirm --clean
if errorlevel 1 (
    echo [build] PyInstaller failed.
    exit /b 1
)

if exist dist\mcp-workspace-agent.exe (
    echo.
    echo [build] Success: dist\mcp-workspace-agent.exe
    for %%I in (dist\mcp-workspace-agent.exe) do echo [build] Size: %%~zI bytes
    echo.
    echo Run with:
    echo   dist\mcp-workspace-agent.exe --url wss://your-server/api/v1/workspaces/agent/ws --token ta_xxx
    echo or:
    echo   dist\mcp-workspace-agent.exe --config "%%USERPROFILE%%\.mcp-workspace\config.json"
) else (
    echo [build] Build finished but output executable not found.
    exit /b 1
)

endlocal
exit /b 0
