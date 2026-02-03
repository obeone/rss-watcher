"""
Unit tests for the media download module.

Tests cover video URL extraction, filename handling, and downloads.
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

            mock_connector.from_url.assert_called_once_with("socks5://localhost:1080")

        await downloader.close()
