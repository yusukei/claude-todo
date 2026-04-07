"""Shared constants and tiny helpers for the bookmark clipping pipeline."""

from __future__ import annotations

TIMEOUT_MS = 30_000
IMAGE_MIN_BYTES = 5 * 1024  # Skip images smaller than 5KB
IMAGE_MAX_BYTES = 10 * 1024 * 1024  # Skip images larger than 10MB
CLIP_CONTENT_MAX = 500 * 1024  # Truncate clip content at 500KB

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

IMAGE_EXTENSIONS = frozenset(
    {".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".avif", ".ico"}
)


def content_type_to_ext(content_type: str) -> str:
    """Map an HTTP Content-Type header value to a file extension.

    Returns an empty string when the content type is not a recognized image
    format. Callers should fall back to the URL extension or a default.
    """
    ct = content_type.lower().split(";")[0].strip()
    mapping = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/svg+xml": ".svg",
        "image/avif": ".avif",
        "image/x-icon": ".ico",
    }
    return mapping.get(ct, "")
