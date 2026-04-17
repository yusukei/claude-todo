"""End-to-end agent release helper.

Builds ``dist/mcp-workspace-agent.exe`` via ``build.bat`` (Windows) or
``build.sh`` (POSIX), then uploads it to the backend's
``/api/v1/workspaces/releases`` endpoint using an admin-owned MCP API
key.

Intended to replace the historical "bump version → run build → log into
admin UI → drag-and-drop upload" dance with a single command:

    python agent/release.py \\
        --version 0.4.0 \\
        --channel stable \\
        --base-url https://todo.example.com \\
        --api-key $MCP_TODO_ADMIN_KEY \\
        --notes "shell routing + bash detection"

Environment variable fallbacks:

    MCP_TODO_BASE_URL       → --base-url
    MCP_TODO_ADMIN_API_KEY  → --api-key

The script is deliberately dependency-light (stdlib only on the happy
path; ``requests`` is imported lazily for the upload step so operators
who just want to ``--build-only`` don't need extra packages).

Exit codes:
    0  success (build + optional upload)
    1  build failed / upload rejected / auth failure
    2  bad arguments
"""

from __future__ import annotations

import argparse
import os
import platform
import re
import subprocess
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent
VERSION_FILE = AGENT_DIR / "self_update.py"
PYPROJECT = AGENT_DIR / "pyproject.toml"
DIST_EXE = AGENT_DIR / "dist" / "mcp-workspace-agent.exe"

VERSION_RE = re.compile(r'__version__\s*=\s*"([^"]+)"')
PYPROJECT_VERSION_RE = re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE)


def read_current_version() -> str:
    m = VERSION_RE.search(VERSION_FILE.read_text(encoding="utf-8"))
    if not m:
        raise RuntimeError(f"__version__ not found in {VERSION_FILE}")
    return m.group(1)


def bump_version(new_version: str) -> None:
    """Update ``self_update.py`` and ``pyproject.toml`` in-place."""
    sv = VERSION_FILE.read_text(encoding="utf-8")
    sv_new = VERSION_RE.sub(f'__version__ = "{new_version}"', sv, count=1)
    if sv == sv_new:
        raise RuntimeError("self_update.py was unchanged; version regex missed")
    VERSION_FILE.write_text(sv_new, encoding="utf-8")

    py = PYPROJECT.read_text(encoding="utf-8")
    py_new = PYPROJECT_VERSION_RE.sub(f'version = "{new_version}"', py, count=1)
    if py == py_new:
        raise RuntimeError("pyproject.toml was unchanged; version regex missed")
    PYPROJECT.write_text(py_new, encoding="utf-8")
    print(f"[release] bumped version → {new_version}")


def build_agent(clean: bool = True) -> Path:
    """Run build.bat / build.sh and return the produced exe path."""
    is_windows = platform.system().lower().startswith("win")
    if is_windows:
        cmd = [str(AGENT_DIR / "build.bat")]
        if clean:
            cmd.append("--clean")
        print(f"[release] running {' '.join(cmd)}")
        result = subprocess.run(cmd, cwd=AGENT_DIR, shell=True)
    else:
        cmd = ["bash", str(AGENT_DIR / "build.sh")]
        if clean:
            cmd.append("--clean")
        print(f"[release] running {' '.join(cmd)}")
        result = subprocess.run(cmd, cwd=AGENT_DIR)
    if result.returncode != 0:
        raise RuntimeError(f"build failed (exit {result.returncode})")
    if not DIST_EXE.exists():
        raise RuntimeError(f"build reported success but {DIST_EXE} missing")
    size_mb = DIST_EXE.stat().st_size / (1024 * 1024)
    print(f"[release] built {DIST_EXE} ({size_mb:.1f} MB)")
    return DIST_EXE


def upload_release(
    *,
    exe_path: Path,
    version: str,
    base_url: str,
    api_key: str,
    os_type: str = "win32",
    channel: str = "stable",
    arch: str = "x64",
    notes: str = "",
) -> dict:
    """POST the binary to ``/api/v1/workspaces/releases``."""
    # Lazy import so --build-only flows don't need requests installed.
    try:
        import requests  # type: ignore
    except ImportError as e:
        raise SystemExit(
            "requests is required for upload. "
            "Install with `pip install requests` or pass --build-only."
        ) from e

    url = f"{base_url.rstrip('/')}/api/v1/workspaces/releases"
    print(f"[release] POST {url} (version={version}, channel={channel})")

    with open(exe_path, "rb") as f:
        files = {"file": (exe_path.name, f, "application/octet-stream")}
        data = {
            "version": version,
            "os_type": os_type,
            "channel": channel,
            "arch": arch,
            "release_notes": notes,
        }
        resp = requests.post(
            url, headers={"X-API-Key": api_key}, data=data, files=files,
            timeout=120,
        )

    if resp.status_code == 401:
        raise SystemExit(
            "upload rejected: 401 Unauthorized. Check MCP_TODO_ADMIN_API_KEY."
        )
    if resp.status_code == 403:
        raise SystemExit(
            "upload rejected: 403 Forbidden. "
            "The API key's owner must have is_admin=True."
        )
    if resp.status_code == 409:
        raise SystemExit(
            f"upload rejected: 409 Conflict (version {version} already exists). "
            "Bump --version or delete the existing release first."
        )
    if not resp.ok:
        raise SystemExit(
            f"upload failed: {resp.status_code} {resp.text[:500]}"
        )
    print(f"[release] uploaded: {resp.json()}")
    return resp.json()


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Build and upload an agent release.",
    )
    p.add_argument(
        "--version",
        help="New semver to set (e.g. 0.4.1). Omit to reuse the current version.",
    )
    p.add_argument(
        "--base-url",
        default=os.environ.get("MCP_TODO_BASE_URL"),
        help="Backend URL (default: $MCP_TODO_BASE_URL)",
    )
    p.add_argument(
        "--api-key",
        default=os.environ.get("MCP_TODO_ADMIN_API_KEY"),
        help="Admin-owned MCP API key (default: $MCP_TODO_ADMIN_API_KEY)",
    )
    p.add_argument("--channel", default="stable", choices=("stable", "beta", "canary"))
    p.add_argument("--os-type", default="win32", choices=("win32", "darwin", "linux"))
    p.add_argument("--arch", default="x64", choices=("x64", "arm64"))
    p.add_argument("--notes", default="", help="Release notes.")
    p.add_argument(
        "--no-clean",
        action="store_true",
        help="Skip cleaning build/ + dist/ before PyInstaller.",
    )
    p.add_argument(
        "--build-only",
        action="store_true",
        help="Stop after build; do not upload (requests not needed).",
    )
    p.add_argument(
        "--skip-build",
        action="store_true",
        help="Reuse existing dist/mcp-workspace-agent.exe (faster retries).",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)

    # 1. Version bump (only if the caller asked for a specific version).
    version = args.version
    if version:
        if not re.match(r"^\d+\.\d+\.\d+(?:[.-][0-9A-Za-z.-]+)?$", version):
            print(f"[release] invalid version: {version}", file=sys.stderr)
            return 2
        bump_version(version)
    else:
        version = read_current_version()
        print(f"[release] reusing current version {version}")

    # 2. Build (unless explicitly skipped).
    if not args.skip_build:
        try:
            build_agent(clean=not args.no_clean)
        except Exception as e:
            print(f"[release] build error: {e}", file=sys.stderr)
            return 1
    elif not DIST_EXE.exists():
        print(
            f"[release] --skip-build set but {DIST_EXE} missing", file=sys.stderr,
        )
        return 1

    # 3. Upload (unless --build-only).
    if args.build_only:
        print("[release] --build-only: skipping upload")
        return 0

    if not args.base_url or not args.api_key:
        print(
            "[release] --base-url and --api-key (or MCP_TODO_BASE_URL / "
            "MCP_TODO_ADMIN_API_KEY env vars) are required for upload. "
            "Pass --build-only to build without uploading.",
            file=sys.stderr,
        )
        return 2

    try:
        upload_release(
            exe_path=DIST_EXE,
            version=version,
            base_url=args.base_url,
            api_key=args.api_key,
            os_type=args.os_type,
            channel=args.channel,
            arch=args.arch,
            notes=args.notes,
        )
    except SystemExit as e:
        print(f"[release] {e}", file=sys.stderr)
        return 1
    print("[release] done ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
