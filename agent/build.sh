#!/usr/bin/env bash
# ============================================================
#  MCP Todo Remote Workspace Agent — Unix build script
#
#  Builds a self-contained mcp-workspace-agent binary via
#  PyInstaller. Output: dist/mcp-workspace-agent
#
#  Prerequisites: uv (https://docs.astral.sh/uv/) on PATH
#
#  Usage:
#    ./build.sh           - normal build
#    ./build.sh --clean   - wipe build/ + dist/ first
# ============================================================
set -euo pipefail

# Always run from this script's directory.
cd "$(dirname "$0")"

if [[ "${1:-}" == "--clean" ]]; then
    echo "[build] Cleaning build artifacts..."
    rm -rf build dist
fi

echo "[build] Syncing dependencies (including dev tools)..."
uv sync --quiet

echo "[build] Running PyInstaller..."
uv run pyinstaller mcp-workspace-agent.spec --noconfirm --clean

if [[ -f dist/mcp-workspace-agent ]]; then
    size=$(stat -c%s dist/mcp-workspace-agent 2>/dev/null || stat -f%z dist/mcp-workspace-agent)
    echo
    echo "[build] Success: dist/mcp-workspace-agent"
    echo "[build] Size: ${size} bytes"
    echo
    echo "Run with:"
    echo "  ./dist/mcp-workspace-agent --url wss://your-server/api/v1/workspaces/agent/ws --token ta_xxx"
    echo "or:"
    echo "  ./dist/mcp-workspace-agent --config ~/.mcp-workspace/config.json"
else
    echo "[build] Build finished but output executable not found." >&2
    exit 1
fi
