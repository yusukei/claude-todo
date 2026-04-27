"""Public install bootstrap endpoint: ``GET /install/{code}``.

Streams the PowerShell bootstrap script that downloads the supervisor
binary and runs ``--bootstrap <install_token>``. Mounted at the app
root (no ``/api/v1`` prefix) so the install URL stays short enough to
copy-paste reliably:

    https://todo.example.com/install/in_<hex32>

The endpoint is anonymous — the install_token in the URL is the only
secret. Validation is identical to :func:`exchange_install_token`
(must exist, not consumed, not expired); failures return 410 Gone with
a one-line PowerShell ``throw`` so a wrapping ``iex`` surfaces a clear
error instead of silently no-oping.
"""
from __future__ import annotations

import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Path
from fastapi.responses import PlainTextResponse

from ....core.config import settings
from ....models import InstallToken
from .workspaces._releases_util import find_latest_release

logger = logging.getLogger(__name__)

router = APIRouter()


def _backend_base_url() -> str:
    return (settings.BASE_URL or settings.FRONTEND_URL).rstrip("/") or "http://localhost:8000"


@router.get(
    "/install/{code}",
    response_class=PlainTextResponse,
    responses={
        200: {"content": {"text/plain": {}}},
        410: {"content": {"text/plain": {}}},
    },
)
async def install_bootstrap_script(
    code: str = Path(..., pattern=r"^in_[0-9a-f]{32}$"),
) -> PlainTextResponse:
    """Return the PowerShell script that bootstraps a new machine.

    The script:
      1. Downloads the latest stable supervisor binary (auth: install_token).
      2. Verifies SHA-256.
      3. Runs ``supervisor.exe --bootstrap <code>`` which exchanges the
         install_token for ``sv_`` / ``ta_`` tokens and writes config.toml.

    All values that depend on backend state (release URL + sha) are
    embedded at request time so the script is self-contained.
    """
    token = await InstallToken.find_one({"code": code})
    if not token:
        return _error_script("Install token not found or revoked.", code=410)
    if token.consumed_at is not None:
        return _error_script("Install token already consumed.", code=410)
    expires_utc = (
        token.expires_at if token.expires_at.tzinfo is not None
        else token.expires_at.replace(tzinfo=UTC)
    )
    if expires_utc <= datetime.now(UTC):
        return _error_script("Install token expired.", code=410)

    # We need the latest stable supervisor binary. ``find_latest_release``
    # only knows about agent releases; the supervisor side has its own
    # collection. Import lazily to avoid a circular dep.
    from ....models import SupervisorRelease

    # OS detection isn't possible here — the install URL is platform-
    # agnostic so the script picks at runtime. For now we ship the
    # win32-x64 stable supervisor; cross-platform installer support is
    # a Phase 4+ enhancement (the Rust supervisor itself already
    # cross-compiles).
    sv_release = await SupervisorRelease.find_one(
        {"os_type": "win32", "channel": "stable", "arch": "x64"},
        sort=[("created_at", -1)],
    )
    if not sv_release:
        return _error_script(
            "No SupervisorRelease for win32/stable/x64 yet. Upload one first.",
            code=503,
        )

    backend = _backend_base_url()
    sv_download_url = (
        f"{backend}/api/v1/workspaces/supervisor-releases/"
        f"{sv_release.id}/download"
    )

    script = _render_install_script(
        install_token=code,
        backend_url=backend,
        sv_download_url=sv_download_url,
        sv_sha256=sv_release.sha256,
        sv_version=sv_release.version,
    )
    return PlainTextResponse(content=script, media_type="text/plain; charset=utf-8")


def _error_script(message: str, *, code: int) -> PlainTextResponse:
    """Tiny PowerShell that prints + throws so ``iex`` surfaces it."""
    safe = message.replace("'", "''")
    body = (
        "$ErrorActionPreference = 'Stop'\n"
        f"Write-Error 'mcp-workspace install: {safe}'\n"
        f"throw '{safe}'\n"
    )
    return PlainTextResponse(
        content=body, status_code=code,
        media_type="text/plain; charset=utf-8",
    )


def _render_install_script(
    *,
    install_token: str,
    backend_url: str,
    sv_download_url: str,
    sv_sha256: str,
    sv_version: str,
) -> str:
    """Render the bootstrap PowerShell.

    Single ``@'…'@`` here-string with no curly-brace interpolation —
    we substitute via Python ``.format()`` so the literal ``$`` /
    ``{`` characters in the PowerShell don't need escaping. Anything
    that needs PowerShell variable expansion at runtime stays as
    ``$VarName`` in the template.
    """
    template = """\
# mcp-workspace supervisor bootstrap (auto-generated, install_token=in_…).
# Source: GET {backend_url}/install/{install_token}
# Supervisor release: v{sv_version}, sha256={sv_sha256}
$ErrorActionPreference = 'Stop'

$InstallToken         = '{install_token}'
$BackendUrl           = '{backend_url}'
$SupervisorDownloadUrl = '{sv_download_url}'
$SupervisorSha256      = '{sv_sha256}'

$BinDir  = Join-Path $env:LOCALAPPDATA 'mcp-workspace\\supervisor'
$ExePath = Join-Path $BinDir 'mcp-workspace-supervisor.exe'
New-Item -ItemType Directory -Force $BinDir | Out-Null

Write-Host '==> Stopping any prior supervisor / agent processes' -ForegroundColor Cyan
Get-Process mcp-workspace-supervisor -ErrorAction SilentlyContinue | Stop-Process -Force
Get-Process mcp-workspace-agent       -ErrorAction SilentlyContinue | Stop-Process -Force
Get-Process mcp-workspace-agent-rs    -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 2

Write-Host '==> Downloading supervisor binary' -ForegroundColor Cyan
$Headers = @{{ 'X-Install-Token' = $InstallToken }}
Invoke-WebRequest -Uri $SupervisorDownloadUrl -OutFile $ExePath `
    -Headers $Headers -UseBasicParsing | Out-Null

$Sha = (Get-FileHash $ExePath -Algorithm SHA256).Hash.ToLower()
if ($Sha -ne $SupervisorSha256) {{
    throw \"SHA-256 mismatch (expected $SupervisorSha256, got $Sha)\"
}}

Write-Host '==> Bootstrapping (exchanges install_token, writes config, registers task)' -ForegroundColor Cyan
& $ExePath --bootstrap $InstallToken --backend-url $BackendUrl
if ($LASTEXITCODE -ne 0) {{ throw \"supervisor --bootstrap failed (exit $LASTEXITCODE)\" }}

Write-Host ''
Write-Host '✓ Install complete.' -ForegroundColor Green
Write-Host 'Verify on operator side via list_remote_supervisors / list_remote_agents.'
"""
    return template.format(
        install_token=install_token,
        backend_url=backend_url,
        sv_download_url=sv_download_url,
        sv_sha256=sv_sha256,
        sv_version=sv_version,
    )
