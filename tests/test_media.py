"""
Unit tests for the media download module.

Tests cover video URL extraction, filename handling, downloads, and security.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from aioresponses import aioresponses

from rss_watcher.filters import RSSEntry
from rss_watcher.media import (
    VIDEO_MIME_TYPES,
    VIDEO_SRC_PATTERN,
    SOURCE_SRC_PATTERN,
    MediaDownloader,
    redact_proxy_url,
)


class TestExtractVideoUrlsFromHtml:
    """Tests for HTML video URL extraction."""

    def test_extract_video_src(self) -> None:
        """Test extracting video src attribute."""
        downloader = MediaDownloader()
        html = '<video src="https://example.com/video.mp4"></video>'

        urls = downloader.extract_video_urls_from_html(html)

        assert urls == ["https://example.com/video.mp4"]

    def test_extract_source_src(self) -> None:
        """Test extracting source src within video element."""
        downloader = MediaDownloader()
        html = '''
        <video>
            <source src="https://example.com/video.webm" type="video/webm">
            <source src="https://example.com/video.mp4" type="video/mp4">
        </video>
        '''

        urls = downloader.extract_video_urls_from_html(html)

        assert "https://example.com/video.webm" in urls
        assert "https://example.com/video.mp4" in urls

    def test_extract_no_duplicates(self) -> None:
        """Test that duplicate URLs are not included."""
        downloader = MediaDownloader()
        html = '''
        <video src="https://example.com/video.mp4">
            <source src="https://example.com/video.mp4">
        </video>
        '''

        urls = downloader.extract_video_urls_from_html(html)

        assert urls == ["https://example.com/video.mp4"]

    def test_extract_empty_html(self) -> None:
        """Test extraction from empty HTML."""
        downloader = MediaDownloader()

        urls = downloader.extract_video_urls_from_html("")

        assert urls == []

    def test_extract_no_videos(self) -> None:
        """Test extraction from HTML without videos."""
        downloader = MediaDownloader()
        html = '<p>Just some text</p><img src="image.jpg">'

        urls = downloader.extract_video_urls_from_html(html)

        assert urls == []

    def test_extract_case_insensitive(self) -> None:
        """Test case-insensitive tag matching."""
        downloader = MediaDownloader()
        html = '<VIDEO SRC="https://example.com/video.mp4"></VIDEO>'

        urls = downloader.extract_video_urls_from_html(html)

        assert urls == ["https://example.com/video.mp4"]


class TestExtractVideoUrlsFromEnclosures:
    """Tests for enclosure and media_content extraction."""

    def test_extract_video_enclosure(self) -> None:
        """Test extracting video from RSS enclosure."""
        downloader = MediaDownloader()
        raw_entry = {
            "enclosures": [
                {"href": "https://example.com/video.mp4", "type": "video/mp4"},
            ]
        }

        urls = downloader.extract_video_urls_from_enclosures(raw_entry)

        assert urls == ["https://example.com/video.mp4"]

    def test_extract_video_enclosure_with_url_key(self) -> None:
        """Test extracting video from enclosure with url key."""
        downloader = MediaDownloader()
        raw_entry = {
            "enclosures": [
                {"url": "https://example.com/video.mp4", "type": "video/mp4"},
            ]
        }

        urls = downloader.extract_video_urls_from_enclosures(raw_entry)

        assert urls == ["https://example.com/video.mp4"]

    def test_extract_media_content(self) -> None:
        """Test extracting video from media_content (Media RSS)."""
        downloader = MediaDownloader()
        raw_entry = {
            "media_content": [
                {"url": "https://example.com/media.mp4", "type": "video/mp4"},
            ]
        }

        urls = downloader.extract_video_urls_from_enclosures(raw_entry)

        assert urls == ["https://example.com/media.mp4"]

    def test_extract_media_content_by_medium(self) -> None:
        """Test extracting video by medium attribute."""
        downloader = MediaDownloader()
        raw_entry = {
            "media_content": [
                {"url": "https://example.com/media.mp4", "medium": "video"},
            ]
        }

        urls = downloader.extract_video_urls_from_enclosures(raw_entry)

        assert urls == ["https://example.com/media.mp4"]

    def test_ignore_non_video_enclosure(self) -> None:
        """Test that non-video enclosures are ignored."""
        downloader = MediaDownloader()
        raw_entry = {
            "enclosures": [
                {"href": "https://example.com/audio.mp3", "type": "audio/mpeg"},
                {"href": "https://example.com/image.jpg", "type": "image/jpeg"},
            ]
        }

        urls = downloader.extract_video_urls_from_enclosures(raw_entry)

        assert urls == []

    def test_extract_mixed_sources(self) -> None:
        """Test extraction from both enclosures and media_content."""
        downloader = MediaDownloader()
        raw_entry = {
            "enclosures": [
                {"href": "https://example.com/enc.mp4", "type": "video/mp4"},
            ],
            "media_content": [
                {"url": "https://example.com/media.mp4", "type": "video/mp4"},
            ],
        }

        urls = downloader.extract_video_urls_from_enclosures(raw_entry)

        assert "https://example.com/enc.mp4" in urls
        assert "https://example.com/media.mp4" in urls


class TestFilename:
    """Tests for filename extraction and sanitization."""

    def test_extract_filename_from_url(self) -> None:
        """Test filename extraction from URL."""
        downloader = MediaDownloader()

        filename = downloader._extract_filename_from_url(
            "https://example.com/path/to/video.mp4"
        )

        assert filename == "video.mp4"

    def test_extract_filename_with_query_string(self) -> None:
        """Test filename extraction ignores query string."""
        downloader = MediaDownloader()

        filename = downloader._extract_filename_from_url(
            "https://example.com/video.mp4?token=abc"
        )

        assert filename == "video.mp4"

    def test_extract_filename_url_encoded(self) -> None:
        """Test filename extraction with URL encoding."""
        downloader = MediaDownloader()

        filename = downloader._extract_filename_from_url(
            "https://example.com/my%20video.mp4"
        )

        assert filename == "my video.mp4"

    def test_extract_filename_missing_generates_hash(self) -> None:
        """Test filename generation when URL has no filename."""
        downloader = MediaDownloader()

        filename = downloader._extract_filename_from_url("https://example.com/")

        assert filename.startswith("video_")

    def test_sanitize_filename_removes_unsafe_chars(self) -> None:
        """Test filename sanitization removes unsafe characters."""
        downloader = MediaDownloader()

        sanitized = downloader._sanitize_filename('file<>:"/\\|?*.mp4')

        assert "<" not in sanitized
        assert ">" not in sanitized
        assert ":" not in sanitized
        assert '"' not in sanitized
        assert "\\" not in sanitized
        assert "|" not in sanitized
        assert "?" not in sanitized
        assert "*" not in sanitized

    def test_sanitize_filename_strips_spaces_dots(self) -> None:
        """Test filename sanitization strips leading/trailing spaces and dots."""
        downloader = MediaDownloader()

        sanitized = downloader._sanitize_filename("  ..video..  ")

        assert not sanitized.startswith(" ")
        assert not sanitized.startswith(".")
        assert not sanitized.endswith(" ")
        assert not sanitized.endswith(".")

    def test_sanitize_filename_length_limit(self) -> None:
        """Test filename sanitization limits length to 200 characters."""
        downloader = MediaDownloader()
        long_name = "a" * 250 + ".mp4"

        sanitized = downloader._sanitize_filename(long_name)

        assert len(sanitized) <= 200
        assert sanitized.endswith(".mp4")

    def test_sanitize_filename_empty_returns_default(self) -> None:
        """Test sanitization of empty filename returns default."""
        downloader = MediaDownloader()

        sanitized = downloader._sanitize_filename("...")

        assert sanitized == "video"

    def test_sanitize_feed_name(self) -> None:
        """Test feed name sanitization for directory use."""
        downloader = MediaDownloader()

        sanitized = downloader._sanitize_feed_name('My Feed: "Special"')

        assert ":" not in sanitized
        assert '"' not in sanitized


class TestDownload:
    """Tests for video download functionality."""

    async def test_download_success(self, tmp_media_dir: Path) -> None:
        """Test successful video download."""
        downloader = MediaDownloader()
        video_content = b"fake video content"

        with aioresponses() as m:
            m.get(
                "https://example.com/video.mp4",
                body=video_content,
                headers={"Content-Type": "video/mp4"},
            )

            result = await downloader.download_video(
                "https://example.com/video.mp4",
                "Test Feed",
                str(tmp_media_dir),
            )

        assert result is not None
        assert result.exists()
        assert result.read_bytes() == video_content
        await downloader.close()

    async def test_download_creates_feed_directory(self, tmp_media_dir: Path) -> None:
        """Test download creates feed-specific directory."""
        downloader = MediaDownloader()

        with aioresponses() as m:
            m.get("https://example.com/video.mp4", body=b"content")

            result = await downloader.download_video(
                "https://example.com/video.mp4",
                "My Feed",
                str(tmp_media_dir),
            )

        assert result is not None
        assert "My_Feed" in str(result.parent) or "My Feed" in str(result.parent)
        await downloader.close()

    async def test_download_http_error(
        self, tmp_media_dir: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test download handles HTTP errors gracefully."""
        downloader = MediaDownloader()

        with aioresponses() as m:
            m.get("https://example.com/video.mp4", status=404)

            result = await downloader.download_video(
                "https://example.com/video.mp4",
                "Test Feed",
                str(tmp_media_dir),
            )

        assert result is None
        assert "failed to download" in caplog.text.lower()
        await downloader.close()

    async def test_download_network_error(
        self, tmp_media_dir: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test download handles network errors gracefully."""
        downloader = MediaDownloader()

        with aioresponses() as m:
            m.get(
                "https://example.com/video.mp4",
                exception=aiohttp.ClientError("Network error"),
            )

            result = await downloader.download_video(
                "https://example.com/video.mp4",
                "Test Feed",
                str(tmp_media_dir),
            )

        assert result is None
        await downloader.close()

    async def test_download_cleanup_partial_file(self, tmp_media_dir: Path) -> None:
        """Test partial file cleanup on download failure."""
        downloader = MediaDownloader()

        with aioresponses() as m:
            # This will fail mid-download
            m.get(
                "https://example.com/video.mp4",
                exception=aiohttp.ClientError("Connection reset"),
            )

            result = await downloader.download_video(
                "https://example.com/video.mp4",
                "Test Feed",
                str(tmp_media_dir),
            )

        assert result is None
        # No partial files should remain
        feed_dir = tmp_media_dir / "Test_Feed"
        if feed_dir.exists():
            assert list(feed_dir.iterdir()) == []
        await downloader.close()

    async def test_download_timestamped_filename(self, tmp_media_dir: Path) -> None:
        """Test downloaded file has timestamp prefix."""
        downloader = MediaDownloader()

        with aioresponses() as m:
            m.get("https://example.com/video.mp4", body=b"content")

            result = await downloader.download_video(
                "https://example.com/video.mp4",
                "Feed",
                str(tmp_media_dir),
            )

        assert result is not None
        # Filename should have timestamp format: YYYYMMDD_HHMMSS_video.mp4
        assert "_video.mp4" in result.name
        assert result.name[0:8].isdigit()  # Date part
        await downloader.close()


class TestProcessEntry:
    """Tests for processing RSS entries for media."""

    async def test_process_entry_extracts_and_downloads(
        self, tmp_media_dir: Path, sample_rss_entry_with_video: RSSEntry
    ) -> None:
        """Test process_entry extracts URLs and downloads videos."""
        downloader = MediaDownloader()

        with aioresponses() as m:
            # Mock all three video sources
            m.get("https://example.com/video.mp4", body=b"html video")
            m.get("https://example.com/enclosure.mp4", body=b"enclosure video")
            m.get("https://example.com/media.mp4", body=b"media video")

            results = await downloader.process_entry(
                sample_rss_entry_with_video,
                str(tmp_media_dir),
            )

        # Should download from HTML, enclosure, and media_content
        assert len(results) == 3
        assert all(r.exists() for r in results)
        await downloader.close()

    async def test_process_entry_no_videos(
        self, tmp_media_dir: Path, sample_rss_entry: RSSEntry
    ) -> None:
        """Test process_entry with entry containing no videos."""
        # Use entry without video content
        entry = RSSEntry(
            title="No Video",
            content="Just text content",
            raw={},
        )
        downloader = MediaDownloader()

        results = await downloader.process_entry(entry, str(tmp_media_dir))

        assert results == []
        await downloader.close()

    async def test_process_entry_combines_sources_no_duplicates(
        self, tmp_media_dir: Path
    ) -> None:
        """Test process_entry deduplicates URLs from different sources."""
        entry = RSSEntry(
            title="Test",
            content='<video src="https://example.com/same.mp4"></video>',
            raw={
                "enclosures": [
                    {"href": "https://example.com/same.mp4", "type": "video/mp4"},
                ],
            },
        )
        downloader = MediaDownloader()

        with aioresponses() as m:
            m.get("https://example.com/same.mp4", body=b"video")

            results = await downloader.process_entry(entry, str(tmp_media_dir))

        # Should only download once despite being in both HTML and enclosure
        assert len(results) == 1
        await downloader.close()


class TestMediaDownloaderSession:
    """Tests for HTTP session management."""

    async def test_session_lazy_creation(self) -> None:
        """Test that session is created lazily."""
        downloader = MediaDownloader()

        assert downloader._session is None

        session = await downloader._get_session()

        assert session is not None
        await downloader.close()

    async def test_session_reused(self, tmp_media_dir: Path) -> None:
        """Test that session is reused across downloads."""
        downloader = MediaDownloader()

        with aioresponses() as m:
            m.get("https://example.com/v1.mp4", body=b"1")
            m.get("https://example.com/v2.mp4", body=b"2")

            await downloader.download_video(
                "https://example.com/v1.mp4", "Feed", str(tmp_media_dir)
            )
            session1 = downloader._session

            await downloader.download_video(
                "https://example.com/v2.mp4", "Feed", str(tmp_media_dir)
            )
            session2 = downloader._session

        assert session1 is session2
        await downloader.close()

    async def test_close_session(self) -> None:
        """Test session closing."""
        downloader = MediaDownloader()
        await downloader._get_session()

        await downloader.close()

        assert downloader._session is None

    async def test_context_manager(self, tmp_media_dir: Path) -> None:
        """Test async context manager."""
        async with MediaDownloader() as downloader:
            with aioresponses() as m:
                m.get("https://example.com/video.mp4", body=b"content")

                result = await downloader.download_video(
                    "https://example.com/video.mp4",
                    "Feed",
                    str(tmp_media_dir),
                )

                assert result is not None


class TestMediaDownloaderProxy:
    """Tests for proxy configuration."""

    async def test_proxy_creates_connector(self) -> None:
        """Test that proxy URL creates a ProxyConnector."""
        downloader = MediaDownloader(proxy_url="socks5://localhost:1080")

        with patch("rss_watcher.media.ProxyConnector") as mock_connector:
            mock_connector.from_url.return_value = MagicMock()

            await downloader._get_session()

            # Verify ProxyConnector.from_url was called (with ssl parameter)
            mock_connector.from_url.assert_called_once()
            call_args = mock_connector.from_url.call_args
            assert call_args[0][0] == "socks5://localhost:1080"

        await downloader.close()


class TestSSRFProtection:
    """Tests for SSRF protection in media downloads."""

    def test_validate_url_allows_http(self) -> None:
        """Test that http:// URLs are allowed."""
        downloader = MediaDownloader()
        assert downloader._validate_url("http://example.com/video.mp4") is True

    def test_validate_url_allows_https(self) -> None:
        """Test that https:// URLs are allowed."""
        downloader = MediaDownloader()
        assert downloader._validate_url("https://example.com/video.mp4") is True

    def test_validate_url_blocks_file(self) -> None:
        """Test that file:// URLs are blocked."""
        downloader = MediaDownloader()
        assert downloader._validate_url("file:///etc/passwd") is False

    def test_validate_url_blocks_ftp(self) -> None:
        """Test that ftp:// URLs are blocked."""
        downloader = MediaDownloader()
        assert downloader._validate_url("ftp://example.com/video.mp4") is False

    def test_validate_url_blocks_gopher(self) -> None:
        """Test that gopher:// URLs are blocked."""
        downloader = MediaDownloader()
        assert downloader._validate_url("gopher://example.com/") is False

    def test_validate_url_blocks_data(self) -> None:
        """Test that data: URLs are blocked."""
        downloader = MediaDownloader()
        assert downloader._validate_url("data:video/mp4;base64,AAAA") is False

    def test_validate_url_blocks_no_host(self) -> None:
        """Test that URLs without host are blocked."""
        downloader = MediaDownloader()
        assert downloader._validate_url("http:///path/to/file") is False

    async def test_download_blocked_url_returns_none(
        self, tmp_media_dir: Path
    ) -> None:
        """Test that downloading a blocked URL returns None."""
        downloader = MediaDownloader()

        result = await downloader.download_video(
            "file:///etc/passwd",
            "Test Feed",
            str(tmp_media_dir),
        )

        assert result is None
        await downloader.close()


class TestPathTraversalProtection:
    """Tests for path traversal protection in media downloads."""

    def test_validate_path_within_base_valid(self, tmp_media_dir: Path) -> None:
        """Test valid path within base directory."""
        downloader = MediaDownloader()
        base_dir = tmp_media_dir
        target = base_dir / "feed" / "video.mp4"

        assert downloader._validate_path_within_base(base_dir, target) is True

    def test_validate_path_within_base_traversal(self, tmp_media_dir: Path) -> None:
        """Test path traversal attempt is blocked."""
        downloader = MediaDownloader()
        base_dir = tmp_media_dir
        target = base_dir / ".." / "etc" / "passwd"

        # The resolved path will be outside base_dir
        assert downloader._validate_path_within_base(base_dir, target) is False

    def test_validate_path_within_base_absolute_escape(self, tmp_media_dir: Path) -> None:
        """Test absolute path escape attempt is blocked."""
        downloader = MediaDownloader()
        base_dir = tmp_media_dir
        target = Path("/etc/passwd")

        assert downloader._validate_path_within_base(base_dir, target) is False


class TestDownloadSizeLimits:
    """Tests for download size limit enforcement."""

    async def test_download_within_size_limit(self, tmp_media_dir: Path) -> None:
        """Test download proceeds when within size limit."""
        max_size = 1024 * 1024  # 1 MB
        downloader = MediaDownloader(max_download_size=max_size)
        small_content = b"x" * 1000

        with aioresponses() as m:
            m.get(
                "https://example.com/small.mp4",
                body=small_content,
                headers={"Content-Length": str(len(small_content))},
            )

            result = await downloader.download_video(
                "https://example.com/small.mp4",
                "Test Feed",
                str(tmp_media_dir),
            )

        assert result is not None
        assert result.exists()
        await downloader.close()

    async def test_download_exceeds_content_length(
        self, tmp_media_dir: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test download blocked when Content-Length exceeds limit."""
        max_size = 1024  # 1 KB
        downloader = MediaDownloader(max_download_size=max_size)

        with aioresponses() as m:
            m.get(
                "https://example.com/large.mp4",
                body=b"",  # Body doesn't matter, Content-Length is checked first
                headers={"Content-Length": str(10 * 1024 * 1024)},  # 10 MB
            )

            result = await downloader.download_video(
                "https://example.com/large.mp4",
                "Test Feed",
                str(tmp_media_dir),
            )

        assert result is None
        assert "too large" in caplog.text.lower()
        await downloader.close()

    async def test_download_exceeds_limit_during_streaming(
        self, tmp_media_dir: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test download stopped when actual size exceeds limit during streaming."""
        max_size = 100
        downloader = MediaDownloader(max_download_size=max_size)
        # Large content but no Content-Length header
        large_content = b"x" * 500

        with aioresponses() as m:
            m.get(
                "https://example.com/streaming.mp4",
                body=large_content,
                # No Content-Length header, so streaming check kicks in
            )

            result = await downloader.download_video(
                "https://example.com/streaming.mp4",
                "Test Feed",
                str(tmp_media_dir),
            )

        assert result is None
        assert "exceeded" in caplog.text.lower()
        # Verify partial file is cleaned up
        feed_dir = tmp_media_dir / "Test_Feed"
        if feed_dir.exists():
            assert len(list(feed_dir.iterdir())) == 0
        await downloader.close()


class TestProxyUrlRedaction:
    """Tests for proxy URL credential redaction."""

    def test_redact_url_with_password(self) -> None:
        """Test password is redacted from proxy URL."""
        url = "socks5://user:secretpassword@proxy.example.com:1080"
        redacted = redact_proxy_url(url)

        assert "secretpassword" not in redacted
        assert "****" in redacted
        assert "user" in redacted
        assert "proxy.example.com" in redacted
        assert "1080" in redacted

    def test_redact_url_without_password(self) -> None:
        """Test URL without password is returned unchanged."""
        url = "socks5://proxy.example.com:1080"
        redacted = redact_proxy_url(url)

        assert redacted == url

    def test_redact_url_with_username_only(self) -> None:
        """Test URL with username but no password is returned unchanged."""
        url = "socks5://user@proxy.example.com:1080"
        redacted = redact_proxy_url(url)

        # No password means no redaction needed
        assert "user@" in redacted

    def test_redact_malformed_url(self) -> None:
        """Test malformed URL returns safe fallback."""
        url = "not-a-valid-url-at-all:::"
        redacted = redact_proxy_url(url)

        # Should return original or fallback, not crash
        assert redacted is not None
