"""Unit tests for the new clip_* submodules.

These verify that the refactor preserves the public surface of each module
and that submodule callers can use them directly without going through
``bookmark_clip``.
"""

from __future__ import annotations

import pytest


# ── clip_constants ────────────────────────────────────────────


class TestClipConstants:
    def test_image_thresholds_are_sane(self):
        from app.services.clip_constants import IMAGE_MIN_BYTES, IMAGE_MAX_BYTES

        assert 0 < IMAGE_MIN_BYTES < IMAGE_MAX_BYTES

    def test_image_extensions_lowercase_with_dots(self):
        from app.services.clip_constants import IMAGE_EXTENSIONS

        for ext in IMAGE_EXTENSIONS:
            assert ext.startswith(".")
            assert ext == ext.lower()

    def test_content_type_to_ext_known_types(self):
        from app.services.clip_constants import content_type_to_ext

        assert content_type_to_ext("image/jpeg") == ".jpg"
        assert content_type_to_ext("image/png") == ".png"
        assert content_type_to_ext("image/webp") == ".webp"
        assert content_type_to_ext("image/svg+xml") == ".svg"

    def test_content_type_to_ext_with_charset(self):
        from app.services.clip_constants import content_type_to_ext

        assert content_type_to_ext("image/png; charset=utf-8") == ".png"
        assert content_type_to_ext("IMAGE/JPEG") == ".jpg"

    def test_content_type_to_ext_unknown(self):
        from app.services.clip_constants import content_type_to_ext

        assert content_type_to_ext("text/html") == ""
        assert content_type_to_ext("") == ""


# ── clip_twitter ──────────────────────────────────────────────


class TestClipTwitter:
    @pytest.mark.parametrize(
        "url",
        [
            "https://twitter.com/jack/status/20",
            "https://x.com/elonmusk/status/123456789",
            "http://twitter.com/user/status/1",
            "https://x.com/User_With_Underscore/status/9876543210",
        ],
    )
    def test_is_twitter_url_positive(self, url):
        from app.services.clip_twitter import is_twitter_url

        assert is_twitter_url(url) is True

    @pytest.mark.parametrize(
        "url",
        [
            "https://example.com/",
            "https://twitter.com/jack",  # no /status/
            "https://x.com/explore",
            "",
            "https://t.co/shortlink",
        ],
    )
    def test_is_twitter_url_negative(self, url):
        from app.services.clip_twitter import is_twitter_url

        assert is_twitter_url(url) is False

    def test_extract_tweet_id_returns_username_and_id(self):
        from app.services.clip_twitter import extract_tweet_id

        assert extract_tweet_id("https://x.com/jack/status/20") == ("jack", "20")
        assert extract_tweet_id("https://twitter.com/foo/status/9999") == ("foo", "9999")

    def test_extract_tweet_id_returns_none_for_invalid(self):
        from app.services.clip_twitter import extract_tweet_id

        assert extract_tweet_id("https://example.com") is None
        assert extract_tweet_id("not a url") is None


# ── clip_content: sanitize_html ───────────────────────────────


class TestSanitizeHtml:
    def test_strips_scripts(self):
        from app.services.clip_content import sanitize_html

        html = '<p>safe</p><script>alert(1)</script><p>also safe</p>'
        result = sanitize_html(html)
        assert "alert" not in result
        assert "<script" not in result.lower()
        assert "safe" in result

    def test_strips_style_tags(self):
        from app.services.clip_content import sanitize_html

        result = sanitize_html("<style>body{display:none}</style><p>x</p>")
        assert "display" not in result
        assert "<p>x</p>" in result

    def test_strips_onclick_handlers(self):
        from app.services.clip_content import sanitize_html

        result = sanitize_html('<div onclick="alert(1)">x</div>')
        assert "onclick" not in result.lower()

    def test_strips_javascript_urls(self):
        from app.services.clip_content import sanitize_html

        result = sanitize_html('<a href="javascript:alert(1)">x</a>')
        assert "javascript:" not in result.lower()
        assert 'href="#"' in result

    def test_strips_buttons_and_svg(self):
        from app.services.clip_content import sanitize_html

        result = sanitize_html("<button>copy</button><svg>...</svg><p>keep</p>")
        assert "<button" not in result
        assert "<svg" not in result
        assert "keep" in result

    def test_keeps_youtube_iframe(self):
        from app.services.clip_content import sanitize_html

        result = sanitize_html(
            '<iframe src="https://youtube.com/embed/abc"></iframe><iframe src="https://evil.example.com"></iframe>'
        )
        assert "youtube.com" in result
        assert "evil.example.com" not in result


# ── clip_content: xml_to_html ─────────────────────────────────


class TestXmlToHtml:
    def test_converts_headings(self):
        from app.services.clip_content import xml_to_html

        result = xml_to_html('<doc><head rend="h2">Title</head></doc>')
        assert "<h2>Title</h2>" in result

    def test_converts_emphasis(self):
        from app.services.clip_content import xml_to_html

        result = xml_to_html('<doc><hi rend="bold">B</hi></doc>')
        assert "<strong>B</strong>" in result

    def test_converts_links(self):
        from app.services.clip_content import xml_to_html

        result = xml_to_html('<doc><ref target="https://e.com">link</ref></doc>')
        assert '<a href="https://e.com">link</a>' in result

    def test_converts_lists(self):
        from app.services.clip_content import xml_to_html

        result = xml_to_html("<doc><list><item>a</item><item>b</item></list></doc>")
        assert "<ul>" in result
        assert "<li>a</li>" in result
        assert "<li>b</li>" in result

    def test_deduplicates_graphics(self):
        from app.services.clip_content import xml_to_html

        xml = (
            '<doc>'
            '<graphic src="https://e.com/img.png" alt="x"/>'
            '<graphic src="https://e.com/img.png" alt="x"/>'
            "</doc>"
        )
        result = xml_to_html(xml)
        assert result.count("https://e.com/img.png") == 1


# ── clip_content: html_to_markdown ────────────────────────────


@pytest.mark.asyncio
class TestHtmlToMarkdown:
    async def test_basic_conversion(self):
        from app.services.clip_content import html_to_markdown

        md = await html_to_markdown("<h1>Hello</h1><p>world</p>")
        assert "Hello" in md
        assert "world" in md

    async def test_strips_excessive_blank_lines(self):
        from app.services.clip_content import html_to_markdown

        md = await html_to_markdown("<p>a</p><br><br><br><br><p>b</p>")
        # Should not contain 4+ consecutive newlines
        assert "\n\n\n\n" not in md


# ── clip_playwright: get_site_extractor ───────────────────────


class TestGetSiteExtractor:
    def test_zenn_scrap_returns_extractor(self):
        from app.services.clip_playwright import (
            extract_zenn_scrap,
            get_site_extractor,
        )

        fn = get_site_extractor("https://zenn.dev/foo/scraps/abc123")
        assert fn is extract_zenn_scrap

    def test_zenn_article_returns_none(self):
        from app.services.clip_playwright import get_site_extractor

        # Zenn articles (not scraps) use the default trafilatura path
        assert get_site_extractor("https://zenn.dev/foo/articles/abc") is None

    def test_other_domain_returns_none(self):
        from app.services.clip_playwright import get_site_extractor

        assert get_site_extractor("https://example.com/article") is None


# ── bookmark_clip: backwards-compat re-exports ────────────────


class TestBackwardsCompatibleAliases:
    def test_legacy_private_names_still_importable(self):
        from app.services import bookmark_clip

        # Names imported by existing tests must still resolve
        for name in (
            "_is_twitter_url",
            "_extract_tweet_id",
            "_xml_to_html",
            "_sanitize_html",
            "_extract_content",
            "_html_to_markdown",
            "_fetch_raw_html",
            "_clip_twitter",
            "_fetch_page",
            "_close_page_ref",
            "_process_images",
            "_get_site_extractor",
        ):
            assert hasattr(bookmark_clip, name), f"missing {name}"

    def test_legacy_aliases_point_to_submodules(self):
        from app.services import bookmark_clip
        from app.services.clip_content import sanitize_html, xml_to_html
        from app.services.clip_twitter import extract_tweet_id, is_twitter_url

        assert bookmark_clip._is_twitter_url is is_twitter_url
        assert bookmark_clip._extract_tweet_id is extract_tweet_id
        assert bookmark_clip._sanitize_html is sanitize_html
        assert bookmark_clip._xml_to_html is xml_to_html
