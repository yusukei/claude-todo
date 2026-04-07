"""HTML/XML content extraction, sanitization, and Markdown conversion.

Pure(-ish) text-processing helpers for the bookmark clipping pipeline.
No Playwright, no DB, no network — just trafilatura + regex + markdownify.
"""

from __future__ import annotations

import asyncio
import logging
import re

logger = logging.getLogger(__name__)


# ── HTML sanitization ─────────────────────────────────────────


def sanitize_html(html: str) -> str:
    """Remove dangerous elements/attributes and UI decorations from HTML."""
    # Remove <script> and <style> tags with content
    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)

    # Remove event handler attributes (onclick, onerror, onload, etc.)
    html = re.sub(r"\s+on\w+\s*=\s*[\"'][^\"']*[\"']", "", html, flags=re.IGNORECASE)
    html = re.sub(r"\s+on\w+\s*=\s*\S+", "", html, flags=re.IGNORECASE)

    # Remove javascript: URLs
    html = re.sub(
        r"href\s*=\s*[\"']javascript:[^\"']*[\"']",
        'href="#"',
        html,
        flags=re.IGNORECASE,
    )

    # Remove <iframe> (except youtube/vimeo)
    html = re.sub(
        r"<iframe(?![^>]*(?:youtube|vimeo))[^>]*>.*?</iframe>",
        "",
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )

    # Remove UI decoration images (copy buttons, icons, etc.) — typically small SVGs
    html = re.sub(
        r"<img[^>]+src=[\"'][^\"']*(?:copy-icon|wrap-icon|toggle-|button-|icon[-_])[^\"']*[\"'][^>]*/?>",
        "",
        html,
        flags=re.IGNORECASE,
    )

    # Remove <button> elements (copy buttons, action buttons from original site)
    html = re.sub(r"<button[^>]*>.*?</button>", "", html, flags=re.DOTALL | re.IGNORECASE)

    # Remove <svg> elements (inline icons)
    html = re.sub(r"<svg[^>]*>.*?</svg>", "", html, flags=re.DOTALL | re.IGNORECASE)

    # Remove <input>, <select>, <textarea>, <form>
    html = re.sub(
        r"<(?:input|select|textarea|form)[^>]*(?:>.*?</(?:select|textarea|form)>|/?>)",
        "",
        html,
        flags=re.DOTALL | re.IGNORECASE,
    )

    return html


# ── trafilatura → HTML ────────────────────────────────────────


async def extract_content(html: str, url: str) -> str | None:
    """Extract article content from HTML using trafilatura.

    trafilatura's HTML output drops images, so we use the XML output
    and convert it to simple HTML with <graphic> → <img> replacement.
    """
    try:
        import trafilatura

        result_xml = await asyncio.to_thread(
            trafilatura.extract,
            html,
            url=url,
            output_format="xml",
            include_images=True,
            include_links=True,
            include_tables=True,
            favor_recall=True,
        )

        if not result_xml:
            return None

        return xml_to_html(result_xml)
    except Exception:
        logger.warning("trafilatura extraction failed for %s", url, exc_info=True)
        return None


def xml_to_html(xml: str) -> str:
    """Convert trafilatura XML output to simple HTML.

    Handles: <p>, <head rend="h2">, <hi rend="bold|italic">,
    <ref target="...">, <graphic src="..." alt="..."/>,
    <list><item>, <lb/>, <row><cell> (tables).
    """
    out: list[str] = []  # noqa: F841 (kept for future use)

    # Remove the XML declaration and <doc> wrapper
    body = re.sub(r"<\?xml[^>]*\?>\s*", "", xml)
    body = re.sub(r"<doc[^>]*>", "", body)
    body = re.sub(r"</doc>", "", body)

    # Convert <graphic> to <img>, skipping duplicates (keep first occurrence)
    _seen_srcs: set[str] = set()

    def _graphic_to_img(m: re.Match) -> str:
        src = m.group(1)
        if src in _seen_srcs:
            return ""  # skip duplicate
        _seen_srcs.add(src)
        alt = m.group(2) or ""
        return f'<p><img src="{src}" alt="{alt}" /></p>'

    body = re.sub(
        r"<graphic\s+src=[\"']([^\"']+)[\"'](?:\s+alt=[\"']([^\"']*)[\"'])?[^/]*/?>",
        _graphic_to_img,
        body,
    )

    # Convert <head rend="h2"> etc to headings
    body = re.sub(r'<head\s+rend="h(\d+)">', r"<h\1>", body)
    body = re.sub(r"<head>", "<h2>", body)
    body = re.sub(r"</head>", lambda m: "</h2>", body)
    # Fix closing tags for headings
    for i in range(1, 7):
        body = re.sub(f"<h{i}>([^<]*)</h2>", f"<h{i}>\\1</h{i}>", body)

    # Convert <hi rend="bold"> → <strong>, <hi rend="italic"> → <em>
    body = re.sub(r'<hi\s+rend="bold">', "<strong>", body)
    body = re.sub(r'<hi\s+rend="italic">', "<em>", body)
    body = re.sub(r"<hi[^>]*>", "<strong>", body)  # fallback
    body = re.sub(r"</hi>", "</strong>", body)

    # Convert <ref target="url">text</ref> → <a href="url">text</a>
    body = re.sub(r"<ref\s+target=[\"']([^\"']+)[\"']>", r'<a href="\1">', body)
    body = re.sub(r"</ref>", "</a>", body)

    # Convert <lb/> → <br>
    body = re.sub(r"<lb\s*/>", "<br>", body)

    # Convert <list><item> → <ul><li>
    body = body.replace("<list>", "<ul>").replace("</list>", "</ul>")
    body = body.replace("<item>", "<li>").replace("</item>", "</li>")

    # Convert <table><row><cell> → <table><tr><td>
    body = body.replace("<row>", "<tr>").replace("</row>", "</tr>")
    body = body.replace("<cell>", "<td>").replace("</cell>", "</td>")
    body = re.sub(r"<table[^>]*>", "<table>", body)

    # Convert <quote> → <blockquote>
    body = body.replace("<quote>", "<blockquote>").replace("</quote>", "</blockquote>")

    # Remove remaining XML-only tags
    body = re.sub(r"</?(?:main|comments)[^>]*>", "", body)

    return body.strip()


# ── HTML → Markdown ───────────────────────────────────────────


async def html_to_markdown(html: str) -> str:
    """Convert HTML to Markdown using markdownify."""
    try:
        from markdownify import markdownify

        md = await asyncio.to_thread(
            markdownify,
            html,
            heading_style="ATX",
            bullets="-",
            strip=["script", "style"],
        )
        # Clean up excessive whitespace
        md = re.sub(r"\n{3,}", "\n\n", md)
        return md.strip()
    except Exception:
        logger.warning("markdownify conversion failed", exc_info=True)
        return html
