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

The script is deliberately **stdlib-only** — upload uses ``urllib`` with
a hand-rolled multipart encoder so release tooling has zero extra
dependencies (important for agents deployed into tight environments).

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
    """Update ``self_update.py`` and ``pyproject.toml`` in-place.

    Idempotent: if both files already carry ``new_version`` it's a no-op
    and the function returns without raising. Missing ``__version__`` /
    ``version`` lines are still a hard error so typos don't go silent.
    """
    current = read_current_version()
    if current == new_version:
        print(f"[release] version already at {new_version}; skipping bump")
        return

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


def _build_multipart(
    fields: dict[str, str],
    file_field: str,
    file_path: Path,
    mime_type: str = "application/octet-stream",
) -> tuple[bytes, str]:
    """Hand-rolled ``multipart/form-data`` encoder (stdlib-only upload)."""
    import secrets
    import uuid

    boundary = f"----mcpRelease{uuid.uuid4().hex}{secrets.token_hex(4)}"
    crlf = b"\r\n"
    body = bytearray()
    for name, value in fields.items():
        body += f"--{boundary}".encode() + crlf
        body += (
            f'Content-Disposition: form-data; name="{name}"'.encode() + crlf + crlf
        )
        body += value.encode("utf-8") + crlf
    body += f"--{boundary}".encode() + crlf
    body += (
        f'Content-Disposition: form-data; name="{file_field}"; '
        f'filename="{file_path.name}"'
    ).encode() + crlf
    body += f"Content-Type: {mime_type}".encode() + crlf + crlf
    body += file_path.read_bytes() + crlf
    body += f"--{boundary}--".encode() + crlf
    return bytes(body), boundary


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
    """POST the binary to ``/api/v1/workspaces/releases`` (stdlib only)."""
    import json as _json
    import urllib.error
    import urllib.request

    url = f"{base_url.rstrip('/')}/api/v1/workspaces/releases"
    print(f"[release] POST {url} (version={version}, channel={channel})")

    fields = {
        "version": version,
        "os_type": os_type,
        "channel": channel,
        "arch": arch,
        "release_notes": notes,
    }
    body, boundary = _build_multipart(fields, "file", exe_path)
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "X-API-Key": api_key,
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(body)),
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            status = resp.status
            payload = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        status = e.code
        payload = (e.read() or b"").decode("utf-8", errors="replace")
    except urllib.error.URLError as e:
        raise SystemExit(f"upload failed: {e.reason}") from e

    if status == 401:
        raise SystemExit(
            "upload rejected: 401 Unauthorized. Check MCP_TODO_ADMIN_API_KEY."
        )
    if status == 403:
        raise SystemExit(
            "upload rejected: 403 Forbidden. "
            "The API key's owner must have is_admin=True."
        )
    if status == 409:
        raise SystemExit(
            f"upload rejected: 409 Conflict (version {version} already exists). "
            "Bump --version or delete the existing release first."
        )
    if status < 200 or status >= 300:
        raise SystemExit(f"upload failed: HTTP {status} {payload[:500]}")
    try:
        result = _json.loads(payload)
    except _json.JSONDecodeError:
        raise SystemExit(f"upload returned non-JSON: {payload[:500]}")
    print(f"[release] uploaded: {result}")
    return result


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
