"""Image downloading and URL rewriting for clipped HTML content."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

from .clip_constants import (
    IMAGE_EXTENSIONS,
    IMAGE_MAX_BYTES,
    IMAGE_MIN_BYTES,
    USER_AGENT,
    content_type_to_ext,
)

logger = logging.getLogger(__name__)


async def process_images(
    html: str,
    page_url: str,
    bookmark_id: str,
    asset_dir: Path,
) -> tuple[str, dict[str, str]]:
    """Download images referenced in HTML and rewrite URLs to local paths.

    Returns (processed_html, {original_url: local_filename}).
    """
    local_images: dict[str, str] = {}
    # Match both <img src="..."> and markdown ![...](...)
    img_urls: list[str] = re.findall(r"<img[^>]+src=[\"']([^\"']+)[\"']", html)
    img_urls += re.findall(r"!\[[^\]]*\]\(([^)]+)\)", html)

    if not img_urls:
        return html, local_images

    # Deduplicate
    unique_urls = list(dict.fromkeys(img_urls))

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=15.0,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        for img_url in unique_urls:
            try:
                abs_url = (
                    img_url
                    if img_url.startswith(("http://", "https://"))
                    else urljoin(page_url, img_url)
                )

                # Validate URL
                parsed = urlparse(abs_url)
                if parsed.scheme not in ("http", "https"):
                    continue

                resp = await client.get(abs_url)
                resp.raise_for_status()

                content = resp.content
                if len(content) < IMAGE_MIN_BYTES or len(content) > IMAGE_MAX_BYTES:
                    continue

                # Determine extension from content-type or URL
                ct = resp.headers.get("content-type", "")
                ext = content_type_to_ext(ct)
                if not ext:
                    url_ext = Path(parsed.path).suffix.lower()
                    ext = url_ext if url_ext in IMAGE_EXTENSIONS else ".jpg"

                # Hash-based filename
                file_hash = hashlib.sha256(content).hexdigest()[:16]
                filename = f"{file_hash}{ext}"
                filepath = asset_dir / filename

                await asyncio.to_thread(filepath.write_bytes, content)
                local_images[img_url] = filename

                # Rewrite URL in HTML
                local_api_url = f"/api/v1/bookmark-assets/{bookmark_id}/{filename}"
                html = html.replace(img_url, local_api_url)

            except Exception:
                logger.debug("Failed to download image: %s", img_url, exc_info=True)
                continue

    return html, local_images
