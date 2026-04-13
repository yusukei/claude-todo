"""Web clipping pipeline orchestrator.

This module is intentionally thin: the heavy lifting now lives in dedicated
submodules so each piece can be tested and reasoned about in isolation.

- ``clip_constants``  — shared constants and ``content_type_to_ext``
- ``clip_content``    — trafilatura, sanitization, XML→HTML, HTML→Markdown
- ``clip_images``     — image download and URL rewriting
- ``clip_playwright`` — Playwright fetch, metadata, site-specific extractors
- ``clip_twitter``    — Twitter/X-only clip path (FxTwitter / oEmbed / syndication)

For backwards compatibility with existing tests and callers, the legacy
private helper names (``_xml_to_html``, ``_sanitize_html``, ``_is_twitter_url``,
``_extract_tweet_id``, ``_html_to_markdown``, ``_extract_content``,
``_fetch_raw_html``) are re-exported below.
"""

from __future__ import annotations

import asyncio
import html as _html_mod
import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

from ..core.config import settings
from ..models.bookmark import Bookmark, ClipStatus
from .clip_constants import CLIP_CONTENT_MAX
from .clip_content import (
    extract_content as _extract_content_impl,
    html_to_markdown as _html_to_markdown_impl,
    sanitize_html as _sanitize_html_impl,
    xml_to_html as _xml_to_html_impl,
)
from .clip_images import process_images as _process_images_impl
from .clip_playwright import (
    close_page_ref as _close_page_ref_impl,
    fetch_page as _fetch_page_impl,
    fetch_raw_html as _fetch_raw_html_impl,
    get_site_extractor as _get_site_extractor_impl,
)
from .clip_twitter import (
    clip_twitter as _clip_twitter_impl,
    extract_tweet_id as _extract_tweet_id_impl,
    is_twitter_url as _is_twitter_url_impl,
)

if TYPE_CHECKING:
    from .clip_playwright import BrowserPool

logger = logging.getLogger(__name__)


# ── Public entry point ────────────────────────────────────────


async def clip_bookmark(
    bookmark: Bookmark,
    *,
    browser_pool: BrowserPool | None = None,
) -> None:
    """Run the full clipping pipeline for a bookmark.

    1. Update status to processing
    2. For Twitter/X: route to clip_twitter
    3. Otherwise:
       - pre-fetch raw HTML (preserve embeds)
       - launch Playwright, capture screenshot + metadata
       - try site-specific extractor
       - fall back to trafilatura → Markdown
       - download images and rewrite URLs
       - update bookmark with results

    Args:
        bookmark: The bookmark document to clip.
        browser_pool: Optional BrowserPool for reusing a shared browser.
            When provided, pages are created from the pool instead of
            launching a new browser per clip.
    """
    bookmark.clip_status = ClipStatus.processing
    bookmark.clip_error = ""
    await bookmark.save_updated()

    # Twitter/X: bypass Playwright entirely
    if _is_twitter_url_impl(bookmark.url):
        try:
            await _clip_twitter_impl(bookmark, _log_and_publish)
            return
        except Exception as e:
            logger.exception("Twitter clip failed for bookmark %s", bookmark.id)
            bookmark.clip_status = ClipStatus.failed
            bookmark.clip_error = str(e)[:500]
            await bookmark.save_updated()
            return

    page_ref = None
    _used_pool = False
    try:
        # Pre-fetch raw HTML (before JS execution) to preserve Twitter/YouTube embeds
        raw_html = await _fetch_raw_html_impl(bookmark.url)

        # Use pool if available, otherwise standalone browser
        if browser_pool is not None:
            html, page_url, metadata, screenshot_bytes, page_ref = (
                await browser_pool.fetch_page(bookmark.url)
            )
            _used_pool = True
        else:
            html, page_url, metadata, screenshot_bytes, page_ref = (
                await _fetch_page_impl(bookmark.url)
            )

        # Update metadata if not already set
        if not bookmark.metadata.meta_title and metadata.meta_title:
            bookmark.metadata = metadata
        if bookmark.title == bookmark.url and metadata.meta_title:
            bookmark.title = metadata.meta_title

        # Save thumbnail
        asset_dir = Path(settings.BOOKMARK_ASSETS_DIR) / str(bookmark.id)
        asset_dir.mkdir(parents=True, exist_ok=True)

        if screenshot_bytes:
            thumb_path = asset_dir / "thumb.jpg"
            await asyncio.to_thread(thumb_path.write_bytes, screenshot_bytes)
            bookmark.thumbnail_path = "thumb.jpg"

        # Check for site-specific extraction
        site_extractor = _get_site_extractor_impl(page_url)

        if site_extractor and page_ref:
            site_html = await site_extractor(page_ref, page_url)
            if site_html:
                if _used_pool:
                    await browser_pool.release_page(page_ref)
                else:
                    await _close_page_ref_impl(page_ref)
                page_ref = None
                site_html = _sanitize_html_impl(site_html)
                processed_html, local_images = await _process_images_impl(
                    site_html, page_url, str(bookmark.id), asset_dir,
                )
                bookmark.clip_content = processed_html
                bookmark.clip_markdown = await _html_to_markdown_impl(processed_html)
                bookmark.local_images = local_images
                bookmark.clip_status = ClipStatus.done
                await bookmark.save_updated()
                _log_and_publish(bookmark)
                return

        # Close Playwright before trafilatura (no longer needed)
        if _used_pool:
            await browser_pool.release_page(page_ref)
        else:
            await _close_page_ref_impl(page_ref)
        page_ref = None

        # Default: trafilatura extraction → always Markdown
        source_html = raw_html or html

        # Replace Twitter blockquotes with placeholders that trafilatura will preserve.
        # This keeps tweet URLs at their original position in the article.
        _tweet_placeholders: dict[str, dict[str, str]] = {}
        _tweet_counter = [0]

        def _replace_tweet(m: re.Match) -> str:
            block = m.group(1)
            url_match = re.search(
                r'href="(https?://(?:twitter\.com|x\.com)/\w+/status/\d+)',
                block,
            )
            if not url_match:
                return ""
            url = re.sub(r"\?.*$", "", url_match.group(1))

            # Extract tweet text, author, date from the original blockquote
            text_parts = re.findall(r"<p[^>]*>(.*?)</p>", block, re.DOTALL)
            tweet_text = "\n".join(
                re.sub(r"<[^>]+>", "", p).strip() for p in text_parts
            ).strip()
            author_match = re.search(r"(?:&mdash;|—)\s*(.+?)(?:<a|$)", block)
            author = (
                re.sub(r"<[^>]+>", "", author_match.group(1)).strip()
                if author_match
                else ""
            )
            date_match = re.search(r"<a[^>]*>([^<]*\d{4}[^<]*)</a>\s*$", block.strip())
            date_str = date_match.group(1).strip() if date_match else ""

            _tweet_counter[0] += 1
            placeholder = f"TWEETPLACEHOLDER{_tweet_counter[0]}"
            _tweet_placeholders[placeholder] = {
                "url": url,
                "text": tweet_text,
                "author": author,
                "date": date_str,
            }
            return f"<p>{placeholder}</p>"

        source_html = re.sub(
            r'<blockquote[^>]*class="twitter-tweet"[^>]*>(.*?)</blockquote>',
            _replace_tweet,
            source_html,
            flags=re.DOTALL | re.IGNORECASE,
        )

        # Extract YouTube video IDs and their surrounding text (for position matching)
        _yt_embeds: list[dict[str, str]] = []
        _yt_seen: set[str] = set()

        for pattern in [
            r"<figure[^>]*>.*?(?:youtube\.com/embed/|youtu\.be/)([\w-]+).*?</figure>",
            r"<iframe[^>]*(?:youtube\.com/embed/|youtu\.be/)([\w-]+)[^>]*>.*?</iframe>",
        ]:
            for m in re.finditer(pattern, source_html, flags=re.DOTALL | re.IGNORECASE):
                vid = m.group(1)
                if vid in _yt_seen:
                    continue
                _yt_seen.add(vid)
                # Find text AFTER the embed for position matching
                after_raw = source_html[m.end() : m.end() + 2000]
                after_raw = re.sub(
                    r"<script[^>]*>.*?</script>",
                    "",
                    after_raw,
                    flags=re.DOTALL | re.IGNORECASE,
                )
                after_raw = re.sub(
                    r"<style[^>]*>.*?</style>",
                    "",
                    after_raw,
                    flags=re.DOTALL | re.IGNORECASE,
                )
                after_plain = re.sub(r"<[^>]+>", "\n", after_raw)
                after_lines = [
                    line.strip() for line in after_plain.split("\n") if len(line.strip()) > 8
                ]
                after_snippet = after_lines[0][:30] if after_lines else ""
                _yt_embeds.append({"vid": vid, "after": after_snippet})

        extracted_html = await _extract_content_impl(source_html, page_url)
        if not extracted_html:
            bookmark.clip_status = ClipStatus.failed
            bookmark.clip_error = "No article content could be extracted"
            await bookmark.save_updated()
            return

        processed_html, local_images = await _process_images_impl(
            extracted_html, page_url, str(bookmark.id), asset_dir,
        )
        md_content = await _html_to_markdown_impl(processed_html)

        # Replace placeholders with tweet embed markers (at correct positions)
        for placeholder, info in _tweet_placeholders.items():
            text = info["text"].replace("|", "｜").replace("\n", " ")
            author = info["author"].replace("|", "｜")
            date = info["date"].replace("|", "｜")
            marker = f'<!--tweet:{info["url"]}|{author}|{date}|{text}-->'
            md_content = md_content.replace(placeholder, marker)

        # Insert YouTube markers at correct positions using text AFTER the embed
        for yt in _yt_embeds:
            marker = f'\n\n<!--youtube:{yt["vid"]}-->\n\n'
            snippet = yt.get("after", "")
            if snippet and len(snippet) > 5:
                decoded = _html_mod.unescape(snippet)
                escaped = re.escape(decoded[:20])
                match = re.search(escaped, md_content)
                if match:
                    before_region = md_content[: match.start()]
                    last_newline = before_region.rfind("\n")
                    insert_pos = last_newline + 1 if last_newline >= 0 else 0
                    md_content = md_content[:insert_pos] + marker + md_content[insert_pos:]
                    continue
            md_content += marker

        if len(md_content.encode("utf-8")) > CLIP_CONTENT_MAX:
            md_content = md_content[:CLIP_CONTENT_MAX] + "\n\n...(truncated)"

        bookmark.clip_content = md_content
        bookmark.clip_markdown = md_content
        bookmark.local_images = local_images
        bookmark.clip_status = ClipStatus.done
        await bookmark.save_updated()

        _log_and_publish(bookmark)

    except Exception as e:
        logger.exception("Clip failed for bookmark %s", bookmark.id)
        bookmark.clip_status = ClipStatus.failed
        bookmark.clip_error = str(e)[:500]
        await bookmark.save_updated()
    finally:
        if page_ref is not None:
            if _used_pool and browser_pool is not None:
                await browser_pool.release_page(page_ref)
            else:
                await _close_page_ref_impl(page_ref)


def _log_and_publish(bookmark: Bookmark) -> None:
    """Log and publish SSE event for a completed clip."""
    logger.info("Clipped bookmark %s: %s", bookmark.id, bookmark.url)
    try:
        from .events import publish_event

        asyncio.ensure_future(
            publish_event(
                str(bookmark.id),
                "bookmark:clipped",
                {"bookmark_id": str(bookmark.id), "status": "done"},
            )
        )
    except Exception:
        logger.warning("Failed to publish clip event for bookmark %s", bookmark.id, exc_info=True)


# ── Backwards-compatible private aliases ──────────────────────
# Existing tests and other modules import these underscore-prefixed names.
# Keep them as thin shims that delegate to the new submodule implementations.

_is_twitter_url = _is_twitter_url_impl
_extract_tweet_id = _extract_tweet_id_impl
_clip_twitter = _clip_twitter_impl
_xml_to_html = _xml_to_html_impl
_sanitize_html = _sanitize_html_impl
_extract_content = _extract_content_impl
_html_to_markdown = _html_to_markdown_impl
_fetch_raw_html = _fetch_raw_html_impl
_fetch_page = _fetch_page_impl
_close_page_ref = _close_page_ref_impl
_process_images = _process_images_impl
_get_site_extractor = _get_site_extractor_impl


__all__ = [
    "clip_bookmark",
]
