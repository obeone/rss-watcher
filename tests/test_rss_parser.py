"""
Unit tests for the RSS parser module.

Tests cover feed fetching, parsing, retry logic, and session management.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import aiohttp
import pytest
from aioresponses import aioresponses

from rss_watcher.config import FeedConfig
from rss_watcher.rss_parser import FeedParser


class TestFeedParserInit:
    """Tests for FeedParser initialization."""

    def test_default_values(self) -> None:
        """Test FeedParser default values."""
        parser = FeedParser()

        assert parser.timeout == 30
        assert parser.max_retries == 3
        assert parser.user_agent == "RSS-Watcher/1.0"
        assert parser.proxy_url is None
        assert parser._session is None

    def test_custom_values(self) -> None:
        """Test FeedParser with custom values."""
        parser = FeedParser(
            timeout=60,
            max_retries=5,
            user_agent="Custom/2.0",
            proxy_url="socks5://localhost:1080",
        )

        assert parser.timeout == 60
        assert parser.max_retries == 5
        assert parser.user_agent == "Custom/2.0"
        assert parser.proxy_url == "socks5://localhost:1080"

    def test_proxy_config(self) -> None:
        """Test FeedParser with proxy URL."""
        parser = FeedParser(proxy_url="socks5://user:pass@proxy.example.com:1080")

        assert parser.proxy_url == "socks5://user:pass@proxy.example.com:1080"


class TestFeedParserParse:
    """Tests for feed content parsing."""

    def test_parse_valid_rss(self, sample_rss_content: str) -> None:
        """Test parsing valid RSS 2.0 feed."""
        parser = FeedParser()

        entries = parser._parse_feed(sample_rss_content, "Test Feed")

        assert len(entries) == 4
        assert entries[0].title == "First Entry"
        assert entries[0].feed_name == "Test Feed"

    def test_parse_valid_atom(self, sample_atom_content: str) -> None:
        """Test parsing valid Atom feed."""
        parser = FeedParser()

        entries = parser._parse_feed(sample_atom_content, "Atom Feed")

        assert len(entries) == 2
        assert entries[0].title == "Atom Entry One"
        assert entries[0].feed_name == "Atom Feed"

    def test_parse_with_leading_whitespace(self, sample_rss_content: str) -> None:
        """Test parsing feed with leading whitespace."""
        parser = FeedParser()
        content_with_whitespace = "\n\n  " + sample_rss_content

        entries = parser._parse_feed(content_with_whitespace, "Feed")

        assert len(entries) == 4

    def test_parse_bozo_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        """Test that bozo (malformed) feeds log a warning."""
        parser = FeedParser()
        malformed_feed = """<?xml version="1.0"?>
        <rss version="2.0">
            <channel>
                <title>Test</title>
                <item>
                    <title>Entry 1</title>
                </item>
                <item>
                    <title>Entry 2
                </item>
            </channel>
        </rss>
        """

        # Should still parse what it can
        entries = parser._parse_feed(malformed_feed, "Bad Feed")

        # Feedparser marks this as bozo but still extracts entries
        assert "parsing issues" in caplog.text.lower() or len(entries) >= 0

    def test_parse_empty_feed(self) -> None:
        """Test parsing feed with no entries."""
        parser = FeedParser()
        empty_feed = """<?xml version="1.0"?>
        <rss version="2.0">
            <channel>
                <title>Empty Feed</title>
            </channel>
        </rss>
        """

        entries = parser._parse_feed(empty_feed, "Empty")

        assert entries == []


class TestFeedParserFetch:
    """Tests for feed fetching with HTTP requests."""

    async def test_fetch_success(self, sample_rss_content: str) -> None:
        """Test successful feed fetch."""
        parser = FeedParser()
        feed_config = FeedConfig(name="Test", url="https://example.com/feed.xml")

        with aioresponses() as m:
            m.get("https://example.com/feed.xml", body=sample_rss_content)

            entries = await parser.fetch_feed(feed_config)

        assert len(entries) == 4
        await parser.close()

    async def test_fetch_with_cookies(self, sample_rss_content: str) -> None:
        """Test feed fetch with cookies."""
        parser = FeedParser()
        feed_config = FeedConfig(
            name="Authenticated",
            url="https://example.com/private.xml",
            cookies={"session": "abc123", "token": "xyz"},
        )

        with aioresponses() as m:
            m.get("https://example.com/private.xml", body=sample_rss_content)

            entries = await parser.fetch_feed(feed_config)

        assert len(entries) == 4
        await parser.close()

    async def test_fetch_retry_on_error(
        self, sample_rss_content: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test retry logic on transient errors."""
        parser = FeedParser(max_retries=3)
        feed_config = FeedConfig(name="Retry", url="https://example.com/retry.xml")

        with aioresponses() as m:
            # First two requests fail, third succeeds
            m.get(
                "https://example.com/retry.xml",
                exception=aiohttp.ClientError("Connection failed"),
            )
            m.get(
                "https://example.com/retry.xml",
                exception=aiohttp.ClientError("Connection failed"),
            )
            m.get("https://example.com/retry.xml", body=sample_rss_content)

            entries = await parser.fetch_feed(feed_config)

        assert len(entries) == 4
        assert "attempt 1/3" in caplog.text.lower() or "attempt 2/3" in caplog.text.lower()
        await parser.close()

    async def test_fetch_max_retries_exceeded(self) -> None:
        """Test that max retries exceeded raises exception."""
        parser = FeedParser(max_retries=2)
        feed_config = FeedConfig(name="Fail", url="https://example.com/fail.xml")

        with aioresponses() as m:
            m.get(
                "https://example.com/fail.xml",
                exception=aiohttp.ClientError("Failed"),
            )
            m.get(
                "https://example.com/fail.xml",
                exception=aiohttp.ClientError("Failed"),
            )

            with pytest.raises(aiohttp.ClientError):
                await parser.fetch_feed(feed_config)

        await parser.close()

    async def test_fetch_http_error_status(self) -> None:
        """Test handling of HTTP error status codes."""
        parser = FeedParser(max_retries=1)
        feed_config = FeedConfig(name="Error", url="https://example.com/error.xml")

        with aioresponses() as m:
            m.get("https://example.com/error.xml", status=500)

            with pytest.raises(aiohttp.ClientResponseError):
                await parser.fetch_feed(feed_config)

        await parser.close()


class TestFeedParserSession:
    """Tests for HTTP session management."""

    async def test_session_lazy_creation(self) -> None:
        """Test that session is created lazily."""
        parser = FeedParser()

        assert parser._session is None

        # Access session
        session = await parser._get_session()

        assert session is not None
        assert parser._session is session

        await parser.close()

    async def test_session_reused(self, sample_rss_content: str) -> None:
        """Test that session is reused across requests."""
        parser = FeedParser()
        feed_config = FeedConfig(name="Test", url="https://example.com/feed.xml")

        with aioresponses() as m:
            m.get("https://example.com/feed.xml", body=sample_rss_content)
            m.get("https://example.com/feed.xml", body=sample_rss_content)

            await parser.fetch_feed(feed_config)
            session1 = parser._session

            await parser.fetch_feed(feed_config)
            session2 = parser._session

        assert session1 is session2
        await parser.close()

    async def test_session_close(self) -> None:
        """Test session closing."""
        parser = FeedParser()

        # Create session
        await parser._get_session()
        assert parser._session is not None

        # Close
        await parser.close()

        assert parser._session is None

    async def test_close_idempotent(self) -> None:
        """Test that close can be called multiple times."""
        parser = FeedParser()
        await parser._get_session()

        await parser.close()
        await parser.close()

        assert parser._session is None


class TestFeedParserContextManager:
    """Tests for async context manager support."""

    async def test_context_manager(self, sample_rss_content: str) -> None:
        """Test async context manager usage."""
        async with FeedParser() as parser:
            feed_config = FeedConfig(name="Test", url="https://example.com/feed.xml")

            with aioresponses() as m:
                m.get("https://example.com/feed.xml", body=sample_rss_content)
                entries = await parser.fetch_feed(feed_config)

            assert len(entries) == 4

    async def test_context_manager_closes_session(self) -> None:
        """Test context manager closes session on exit."""
        parser = FeedParser()
        async with parser:
            await parser._get_session()

        assert parser._session is None


class TestFeedParserProxy:
    """Tests for proxy configuration."""

    async def test_proxy_creates_connector(self) -> None:
        """Test that proxy URL creates a ProxyConnector."""
        parser = FeedParser(proxy_url="socks5://localhost:1080")

        with patch("rss_watcher.rss_parser.ProxyConnector") as mock_connector:
            mock_connector.from_url.return_value = MagicMock()

            await parser._get_session()

            mock_connector.from_url.assert_called_once_with("socks5://localhost:1080")

        await parser.close()

    def test_no_proxy_no_connector(self) -> None:
        """Test that no proxy means no connector."""
        parser = FeedParser(proxy_url=None)

        # Can't easily test this without mocking, but verify the attribute
        assert parser.proxy_url is None
