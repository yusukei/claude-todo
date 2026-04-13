"""Playwright page fetching, metadata extraction, site-specific extractors,
and a reusable BrowserPool for concurrent clipping.
"""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import urljoin, urlparse

import httpx

from ..models.bookmark import BookmarkMetadata
from .clip_constants import TIMEOUT_MS, USER_AGENT

logger = logging.getLogger(__name__)


# ── Raw HTML pre-fetch ────────────────────────────────────────


async def fetch_raw_html(url: str) -> str | None:
    """Fetch raw HTML via httpx (no JS execution). Used to preserve embeds."""
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=15.0,
            headers={"User-Agent": USER_AGENT},
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            return resp.text
    except Exception:
        return None


# ── Playwright fetch (standalone, one browser per call) ───────


async def fetch_page(
    url: str,
) -> tuple[str, str, BookmarkMetadata, bytes | None, object | None]:
    """Fetch page using Playwright.

    Returns (full_html, final_url, metadata, screenshot_bytes, page_ref).
    page_ref is a Playwright page object for site-specific extractors to use.
    The caller must call close_page_ref(page_ref) when done.
    Note: The browser/context are kept alive via _clip_cleanup stored on the ref.
    """
    from playwright.async_api import async_playwright

    pw = await async_playwright().__aenter__()
    browser = None
    context = None
    page = None
    try:
        browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1280, "height": 800},
            locale="ja-JP",
        )
        page = await context.new_page()

        # Store cleanup references early so they can be freed on any failure
        page._clip_cleanup = (context, browser, pw)  # type: ignore[attr-defined]

        try:
            await page.goto(url, wait_until="networkidle", timeout=TIMEOUT_MS)
        except Exception:
            # Some pages never reach networkidle; try domcontentloaded
            await page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT_MS)

        final_url = page.url
        meta = await extract_page_metadata(page, final_url)
        screenshot = await page.screenshot(type="jpeg", quality=80)
        html = await page.content()

        return html, final_url, meta, screenshot, page
    except Exception:
        # Clean up resources on failure before propagating
        if page and hasattr(page, "_clip_cleanup"):
            await close_page_ref(page)
        else:
            # page wasn't created or cleanup not set — close manually
            if context:
                try:
                    await context.close()
                except Exception:
                    logger.debug("Failed to close Playwright context", exc_info=True)
            if browser:
                try:
                    await browser.close()
                except Exception:
                    logger.debug("Failed to close Playwright browser", exc_info=True)
            try:
                await pw.__aexit__(None, None, None)
            except Exception:
                logger.debug("Failed to exit Playwright", exc_info=True)
        raise


async def close_page_ref(page_ref: object | None) -> None:
    """Clean up Playwright resources from fetch_page."""
    if page_ref is None:
        return
    try:
        cleanup = getattr(page_ref, "_clip_cleanup", None)
        if cleanup:
            context, browser, pw = cleanup
            await context.close()
            await browser.close()
            await pw.__aexit__(None, None, None)
    except Exception:
        logger.debug("Failed to clean up Playwright page_ref", exc_info=True)


async def extract_page_metadata(page, url: str) -> BookmarkMetadata:
    """Extract metadata from a Playwright page."""
    try:
        data = await page.evaluate(
            """() => {
            const getMeta = (name) => {
                const el = document.querySelector(`meta[property="${name}"], meta[name="${name}"]`);
                return el ? el.getAttribute('content') || '' : '';
            };
            const getLink = (rel) => {
                const el = document.querySelector(`link[rel*="${rel}"]`);
                return el ? el.getAttribute('href') || '' : '';
            };
            return {
                title: document.title || '',
                og_title: getMeta('og:title'),
                og_description: getMeta('og:description'),
                description: getMeta('description'),
                og_image: getMeta('og:image'),
                site_name: getMeta('og:site_name'),
                author: getMeta('author') || getMeta('article:author'),
                published: getMeta('article:published_time'),
                favicon: getLink('icon'),
            };
        }"""
        )

        favicon = data.get("favicon", "")
        if favicon and not favicon.startswith(("http://", "https://")):
            favicon = urljoin(url, favicon)

        return BookmarkMetadata(
            meta_title=data.get("og_title") or data.get("title", ""),
            meta_description=data.get("og_description") or data.get("description", ""),
            favicon_url=favicon,
            og_image_url=data.get("og_image", ""),
            site_name=data.get("site_name", ""),
            author=data.get("author", ""),
            published_date=data.get("published") or None,
        )
    except Exception:
        return BookmarkMetadata()


# ── Site-specific extractors ──────────────────────────────────


def get_site_extractor(url: str):
    """Return a site-specific extractor function for the URL, or None."""
    domain = urlparse(url).hostname or ""

    if domain in ("zenn.dev", "www.zenn.dev") and "/scraps/" in url:
        return extract_zenn_scrap

    return None


async def extract_zenn_scrap(page, url: str) -> str | None:
    """Extract Zenn scrap thread as structured HTML with comment cards."""
    try:
        result = await page.evaluate(
            """() => {
            const items = document.querySelectorAll('[class*="ScrapThread_item"]');
            if (!items.length) return null;

            let html = '';
            items.forEach(item => {
                const article = item.querySelector('article');
                if (!article) return;

                // User info
                const avatarImg = article.querySelector('[class*="ThreadHeader"] img');
                const userName = article.querySelector('[class*="userName"]');
                const dateEl = article.querySelector('[class*="dateContainer"]');

                const avatar = avatarImg ? avatarImg.src : '';
                const name = userName ? userName.textContent.trim() : '';
                const date = dateEl ? dateEl.textContent.trim() : '';

                // Content (the znc div)
                const content = article.querySelector('[class*="content"] .znc');
                const contentHtml = content ? content.innerHTML : '';

                if (!contentHtml.trim()) return;

                html += '<div class="clip-comment-card">';
                html += '<div class="clip-comment-header">';
                if (avatar) html += '<img class="clip-avatar" src="' + avatar + '" alt="' + name + '" />';
                if (name) html += '<strong>' + name + '</strong>';
                if (date) html += '<span class="clip-date">' + date + '</span>';
                html += '</div>';
                html += '<div class="clip-comment-body">' + contentHtml + '</div>';
                html += '</div>';
            });

            return html || null;
        }"""
        )
        return result
    except Exception:
        logger.warning("Zenn scrap extraction failed for %s", url, exc_info=True)
        return None


# ── BrowserPool for concurrent clipping ───────────────────────


class BrowserPool:
    """Persistent Playwright browser with concurrent page support.

    Instead of launching a new browser per clip (expensive), this pool
    maintains a single browser + context and creates lightweight pages
    on demand, bounded by a semaphore.

    Usage::

        pool = BrowserPool(max_pages=3)
        html, url, meta, screenshot, page = await pool.fetch_page("https://...")
        # ... use page for site-specific extraction ...
        await pool.release_page(page)
        # on shutdown:
        await pool.shutdown()
    """

    def __init__(self, max_pages: int = 3) -> None:
        self._max_pages = max_pages
        self._semaphore = asyncio.Semaphore(max_pages)
        self._pw = None
        self._browser = None
        self._context = None
        self._lock = asyncio.Lock()
        self._closed = False

    async def _ensure_browser(self) -> None:
        """Lazily initialise the browser and context (thread-safe)."""
        if self._browser is not None and self._context is not None:
            return
        async with self._lock:
            # Double-check after acquiring lock
            if self._browser is not None and self._context is not None:
                return
            from playwright.async_api import async_playwright

            self._pw = await async_playwright().__aenter__()
            self._browser = await self._pw.chromium.launch(headless=True)
            self._context = await self._browser.new_context(
                user_agent=USER_AGENT,
                viewport={"width": 1280, "height": 800},
                locale="ja-JP",
            )
            logger.info("BrowserPool: browser initialised (max_pages=%d)", self._max_pages)

    async def fetch_page(
        self, url: str,
    ) -> tuple[str, str, BookmarkMetadata, bytes | None, object | None]:
        """Fetch a page using a pooled browser.

        Returns the same tuple as the standalone ``fetch_page``.
        The caller MUST call ``release_page(page)`` when done.
        """
        await self._semaphore.acquire()
        page = None
        try:
            await self._ensure_browser()
            if self._context is None:
                raise RuntimeError("BrowserPool: context not available")

            page = await self._context.new_page()

            try:
                await page.goto(url, wait_until="networkidle", timeout=TIMEOUT_MS)
            except Exception:
                await page.goto(url, wait_until="domcontentloaded", timeout=TIMEOUT_MS)

            final_url = page.url
            meta = await extract_page_metadata(page, final_url)
            screenshot = await page.screenshot(type="jpeg", quality=80)
            html = await page.content()

            # Tag the page so release_page knows it came from the pool
            page._from_pool = True  # type: ignore[attr-defined]
            return html, final_url, meta, screenshot, page
        except Exception:
            # On failure, close the page and release the semaphore
            if page:
                try:
                    await page.close()
                except Exception:
                    logger.debug("BrowserPool: failed to close page on error", exc_info=True)
            self._semaphore.release()
            # If the browser itself crashed, reset it so the next call
            # gets a fresh one.
            await self._reset_if_crashed()
            raise

    async def release_page(self, page: object | None) -> None:
        """Close a page and release the semaphore slot."""
        if page is None:
            return
        try:
            await page.close()  # type: ignore[union-attr]
        except Exception:
            logger.debug("BrowserPool: failed to close page", exc_info=True)
            # Browser may have crashed — reset for next call
            await self._reset_if_crashed()
        finally:
            self._semaphore.release()

    async def _reset_if_crashed(self) -> None:
        """Reset browser/context if the browser process has died."""
        async with self._lock:
            if self._browser is None:
                return
            try:
                # Quick health check: if connected, the browser is fine
                if self._browser.is_connected():
                    return
            except Exception:
                pass
            logger.warning("BrowserPool: browser crashed, resetting")
            await self._close_internal()

    async def _close_internal(self) -> None:
        """Close browser resources without acquiring the lock."""
        if self._context:
            try:
                await self._context.close()
            except Exception:
                pass
            self._context = None
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._pw:
            try:
                await self._pw.__aexit__(None, None, None)
            except Exception:
                pass
            self._pw = None

    async def shutdown(self) -> None:
        """Shut down the pool and release all Playwright resources."""
        self._closed = True
        async with self._lock:
            await self._close_internal()
        logger.info("BrowserPool: shut down")
