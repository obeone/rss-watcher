"""
Unit tests for the Telegram notification module.

Tests cover message formatting, escaping, rate limiting, and sending.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram.error import RetryAfter, TelegramError

from rss_watcher.config import TelegramConfig
from rss_watcher.filters import RSSEntry
from rss_watcher.telegram import (
    MAX_CAPTION_LENGTH,
    MAX_MESSAGE_LENGTH,
    TelegramNotifier,
)


class TestTelegramInit:
    """Tests for TelegramNotifier initialization."""

    def test_basic_init(self, minimal_telegram_config: TelegramConfig) -> None:
        """Test basic TelegramNotifier initialization."""
        with patch("rss_watcher.telegram.Bot") as mock_bot_class:
            notifier = TelegramNotifier(minimal_telegram_config)

        assert notifier.config == minimal_telegram_config
        mock_bot_class.assert_called_once()

    def test_init_with_proxy(self, minimal_telegram_config: TelegramConfig) -> None:
        """Test TelegramNotifier initialization with proxy."""
        with patch("rss_watcher.telegram.Bot") as mock_bot_class:
            with patch("rss_watcher.telegram.HTTPXRequest") as mock_request:
                notifier = TelegramNotifier(
                    minimal_telegram_config,
                    proxy_url="socks5://localhost:1080",
                )

        mock_request.assert_called_once_with(proxy="socks5://localhost:1080")


class TestTelegramFormatting:
    """Tests for message formatting."""

    def test_format_html_basic(
        self, minimal_telegram_config: TelegramConfig, sample_rss_entry: RSSEntry
    ) -> None:
        """Test basic HTML formatting."""
        with patch("rss_watcher.telegram.Bot"):
            notifier = TelegramNotifier(minimal_telegram_config)

        message = notifier._format_html(sample_rss_entry)

        assert "<b>[Test Feed]</b>" in message
        assert 'href="https://example.com/test-entry"' in message
        assert "Test Entry Title" in message
        assert "<i>by Test Author</i>" in message

    def test_format_html_escape_special_chars(
        self, minimal_telegram_config: TelegramConfig
    ) -> None:
        """Test HTML escaping of special characters."""
        entry = RSSEntry(
            title="<script>alert('XSS')</script>",
            content="Test & more <content>",
            author="Author <special>",
            feed_name="Feed & News",
            link="https://example.com",
        )
        with patch("rss_watcher.telegram.Bot"):
            notifier = TelegramNotifier(minimal_telegram_config)

        message = notifier._format_html(entry)

        assert "&lt;script&gt;" in message
        assert "&amp;" in message
        assert "<script>" not in message

    def test_format_html_truncates_summary(
        self, minimal_telegram_config: TelegramConfig
    ) -> None:
        """Test HTML formatting truncates long summaries at 500 chars."""
        long_content = "A" * 1000
        entry = RSSEntry(
            title="Test",
            content=long_content,
            link="https://example.com",
            feed_name="Feed",
        )
        with patch("rss_watcher.telegram.Bot"):
            notifier = TelegramNotifier(minimal_telegram_config)

        message = notifier._format_html(entry)

        # Content should be truncated to ~500 chars with "..."
        assert "..." in message
        # Shouldn't contain all 1000 A's
        assert "A" * 600 not in message

    def test_format_html_respects_max_message_length(
        self, minimal_telegram_config: TelegramConfig
    ) -> None:
        """Test HTML formatting respects MAX_MESSAGE_LENGTH."""
        # Create entry that would exceed limit
        entry = RSSEntry(
            title="X" * 1000,
            content="Y" * 5000,
            link="https://example.com",
            feed_name="Feed",
        )
        with patch("rss_watcher.telegram.Bot"):
            notifier = TelegramNotifier(minimal_telegram_config)

        message = notifier._format_html(entry)

        assert len(message) <= MAX_MESSAGE_LENGTH
        assert message.endswith("...")

    def test_format_html_categories_as_hashtags(
        self, minimal_telegram_config: TelegramConfig
    ) -> None:
        """Test categories are formatted as hashtags."""
        entry = RSSEntry(
            title="Test",
            categories=["Tech News", "Python"],
            link="https://example.com",
            feed_name="Feed",
        )
        with patch("rss_watcher.telegram.Bot"):
            notifier = TelegramNotifier(minimal_telegram_config)

        message = notifier._format_html(entry)

        assert "#Tech_News" in message
        assert "#Python" in message

    def test_format_markdown_basic(
        self, minimal_telegram_config: TelegramConfig, sample_rss_entry: RSSEntry
    ) -> None:
        """Test basic Markdown formatting."""
        config = TelegramConfig(
            bot_token=minimal_telegram_config.bot_token,
            chat_id=minimal_telegram_config.chat_id,
            parse_mode="Markdown",
        )
        with patch("rss_watcher.telegram.Bot"):
            notifier = TelegramNotifier(config)

        message = notifier._format_markdown(sample_rss_entry)

        assert "*[Test Feed]*" in message
        assert "[Test Entry Title]" in message

    def test_format_markdown_escape(
        self, minimal_telegram_config: TelegramConfig
    ) -> None:
        """Test Markdown special character escaping."""
        entry = RSSEntry(
            title="Test *bold* and _italic_",
            content="",
            link="https://example.com",
            feed_name="Feed",
        )
        config = TelegramConfig(
            bot_token=minimal_telegram_config.bot_token,
            chat_id=minimal_telegram_config.chat_id,
            parse_mode="Markdown",
        )
        with patch("rss_watcher.telegram.Bot"):
            notifier = TelegramNotifier(config)

        message = notifier._format_markdown(entry)

        assert "\\*bold\\*" in message
        assert "\\_italic\\_" in message

    def test_format_no_title(self, minimal_telegram_config: TelegramConfig) -> None:
        """Test formatting entry without title."""
        entry = RSSEntry(
            title="",
            content="Content only",
            link="https://example.com",
            feed_name="Feed",
        )
        with patch("rss_watcher.telegram.Bot"):
            notifier = TelegramNotifier(minimal_telegram_config)

        message = notifier._format_html(entry)

        assert "No title" in message

    def test_format_no_link(self, minimal_telegram_config: TelegramConfig) -> None:
        """Test formatting entry without link."""
        entry = RSSEntry(
            title="Title Only",
            content="",
            link="",
            feed_name="Feed",
        )
        with patch("rss_watcher.telegram.Bot"):
            notifier = TelegramNotifier(minimal_telegram_config)

        message = notifier._format_html(entry)

        assert "<b>Title Only</b>" in message
        assert "href=" not in message


class TestCleanContent:
    """Tests for content cleaning."""

    def test_clean_html_tags(self, minimal_telegram_config: TelegramConfig) -> None:
        """Test HTML tag removal."""
        with patch("rss_watcher.telegram.Bot"):
            notifier = TelegramNotifier(minimal_telegram_config)

        content = "<p>Hello <strong>World</strong></p>"
        result = notifier._clean_content(content)

        assert result == "Hello World"

    def test_clean_html_entities(
        self, minimal_telegram_config: TelegramConfig
    ) -> None:
        """Test HTML entity decoding."""
        with patch("rss_watcher.telegram.Bot"):
            notifier = TelegramNotifier(minimal_telegram_config)

        content = "Test &amp; more &lt;stuff&gt;"
        result = notifier._clean_content(content)

        assert result == "Test & more <stuff>"

    def test_clean_whitespace(self, minimal_telegram_config: TelegramConfig) -> None:
        """Test whitespace normalization."""
        with patch("rss_watcher.telegram.Bot"):
            notifier = TelegramNotifier(minimal_telegram_config)

        content = "Hello\n\n\nWorld   with   spaces"
        result = notifier._clean_content(content)

        assert result == "Hello World with spaces"


class TestEscapeMarkdown:
    """Tests for Markdown escaping."""

    def test_escape_special_chars(
        self, minimal_telegram_config: TelegramConfig
    ) -> None:
        """Test escaping Markdown special characters."""
        with patch("rss_watcher.telegram.Bot"):
            notifier = TelegramNotifier(minimal_telegram_config)

        text = "Hello *world* and [link](url) plus `code`"
        result = notifier._escape_markdown(text)

        assert "\\*world\\*" in result
        assert "\\[link\\]" in result
        assert "\\`code\\`" in result

    def test_escape_normal_text(
        self, minimal_telegram_config: TelegramConfig
    ) -> None:
        """Test that normal text is not escaped."""
        with patch("rss_watcher.telegram.Bot"):
            notifier = TelegramNotifier(minimal_telegram_config)

        text = "Normal text without special chars"
        result = notifier._escape_markdown(text)

        assert result == text


class TestSendEntry:
    """Tests for sending single entries."""

    async def test_send_entry_success(
        self,
        minimal_telegram_config: TelegramConfig,
        sample_rss_entry: RSSEntry,
    ) -> None:
        """Test successful entry sending."""
        with patch("rss_watcher.telegram.Bot") as mock_bot_class:
            mock_bot = MagicMock()
            mock_bot.send_message = AsyncMock()
            mock_bot_class.return_value = mock_bot

            notifier = TelegramNotifier(minimal_telegram_config)
            result = await notifier.send_entry(sample_rss_entry)

        assert result is True
        mock_bot.send_message.assert_called_once()

    async def test_send_entry_error(
        self,
        minimal_telegram_config: TelegramConfig,
        sample_rss_entry: RSSEntry,
    ) -> None:
        """Test entry sending with error."""
        with patch("rss_watcher.telegram.Bot") as mock_bot_class:
            mock_bot = MagicMock()
            mock_bot.send_message = AsyncMock(
                side_effect=TelegramError("Send failed")
            )
            mock_bot_class.return_value = mock_bot

            notifier = TelegramNotifier(minimal_telegram_config)
            result = await notifier.send_entry(sample_rss_entry)

        assert result is False

    async def test_send_entry_rate_limit(
        self,
        minimal_telegram_config: TelegramConfig,
        sample_rss_entry: RSSEntry,
    ) -> None:
        """Test rate limit handling with retry."""
        with patch("rss_watcher.telegram.Bot") as mock_bot_class:
            mock_bot = MagicMock()
            # First call raises RetryAfter, second succeeds
            mock_bot.send_message = AsyncMock(
                side_effect=[RetryAfter(retry_after=1), None]
            )
            mock_bot_class.return_value = mock_bot

            notifier = TelegramNotifier(minimal_telegram_config)

            # Should succeed after retry
            with patch("asyncio.sleep", new_callable=AsyncMock):
                result = await notifier.send_entry(sample_rss_entry)

        assert result is True
        assert mock_bot.send_message.call_count == 2


class TestSendEntries:
    """Tests for sending multiple entries."""

    async def test_send_multiple_entries(
        self,
        minimal_telegram_config: TelegramConfig,
    ) -> None:
        """Test sending multiple entries."""
        entries = [
            RSSEntry(title=f"Entry {i}", feed_name="Feed", link=f"link{i}")
            for i in range(3)
        ]

        with patch("rss_watcher.telegram.Bot") as mock_bot_class:
            mock_bot = MagicMock()
            mock_bot.send_message = AsyncMock()
            mock_bot_class.return_value = mock_bot

            notifier = TelegramNotifier(minimal_telegram_config)

            with patch("asyncio.sleep", new_callable=AsyncMock):
                count = await notifier.send_entries(entries)

        assert count == 3
        assert mock_bot.send_message.call_count == 3

    async def test_send_entries_partial_failure(
        self,
        minimal_telegram_config: TelegramConfig,
    ) -> None:
        """Test partial failure when sending multiple entries."""
        entries = [
            RSSEntry(title=f"Entry {i}", feed_name="Feed", link=f"link{i}")
            for i in range(3)
        ]

        with patch("rss_watcher.telegram.Bot") as mock_bot_class:
            mock_bot = MagicMock()
            # Second call fails
            mock_bot.send_message = AsyncMock(
                side_effect=[None, TelegramError("Failed"), None]
            )
            mock_bot_class.return_value = mock_bot

            notifier = TelegramNotifier(minimal_telegram_config)

            with patch("asyncio.sleep", new_callable=AsyncMock):
                count = await notifier.send_entries(entries)

        assert count == 2


class TestConnection:
    """Tests for connection testing."""

    async def test_connection_success(
        self, minimal_telegram_config: TelegramConfig
    ) -> None:
        """Test successful connection test."""
        with patch("rss_watcher.telegram.Bot") as mock_bot_class:
            mock_bot = MagicMock()
            mock_me = MagicMock()
            mock_me.username = "test_bot"
            mock_bot.get_me = AsyncMock(return_value=mock_me)
            mock_bot_class.return_value = mock_bot

            notifier = TelegramNotifier(minimal_telegram_config)
            result = await notifier.test_connection()

        assert result is True
        mock_bot.get_me.assert_called_once()

    async def test_connection_failure(
        self, minimal_telegram_config: TelegramConfig
    ) -> None:
        """Test failed connection test."""
        with patch("rss_watcher.telegram.Bot") as mock_bot_class:
            mock_bot = MagicMock()
            mock_bot.get_me = AsyncMock(side_effect=TelegramError("Connection failed"))
            mock_bot_class.return_value = mock_bot

            notifier = TelegramNotifier(minimal_telegram_config)
            result = await notifier.test_connection()

        assert result is False


class TestTelegramClose:
    """Tests for notifier closing."""

    async def test_close_calls_shutdown(
        self, minimal_telegram_config: TelegramConfig
    ) -> None:
        """Test close calls bot shutdown."""
        with patch("rss_watcher.telegram.Bot") as mock_bot_class:
            mock_bot = MagicMock()
            mock_bot.shutdown = AsyncMock()
            mock_bot_class.return_value = mock_bot

            notifier = TelegramNotifier(minimal_telegram_config)
            await notifier.close()

        mock_bot.shutdown.assert_called_once()

    async def test_close_without_shutdown_method(
        self, minimal_telegram_config: TelegramConfig
    ) -> None:
        """Test close works when bot has no shutdown method."""
        with patch("rss_watcher.telegram.Bot") as mock_bot_class:
            mock_bot = MagicMock(spec=[])  # No shutdown attribute
            mock_bot_class.return_value = mock_bot

            notifier = TelegramNotifier(minimal_telegram_config)
            # Should not raise
            await notifier.close()


class TestTelegramParseMode:
    """Tests for parse mode selection."""

    async def test_html_parse_mode(
        self,
        minimal_telegram_config: TelegramConfig,
        sample_rss_entry: RSSEntry,
    ) -> None:
        """Test HTML parse mode is used."""
        from telegram.constants import ParseMode

        with patch("rss_watcher.telegram.Bot") as mock_bot_class:
            mock_bot = MagicMock()
            mock_bot.send_message = AsyncMock()
            mock_bot_class.return_value = mock_bot

            notifier = TelegramNotifier(minimal_telegram_config)
            await notifier.send_entry(sample_rss_entry)

        call_kwargs = mock_bot.send_message.call_args.kwargs
        assert call_kwargs["parse_mode"] == ParseMode.HTML

    async def test_markdown_parse_mode(
        self,
        sample_rss_entry: RSSEntry,
    ) -> None:
        """Test Markdown parse mode is used."""
        from telegram.constants import ParseMode

        config = TelegramConfig(
            bot_token="123:ABC",
            chat_id="-100123",
            parse_mode="Markdown",
        )

        with patch("rss_watcher.telegram.Bot") as mock_bot_class:
            mock_bot = MagicMock()
            mock_bot.send_message = AsyncMock()
            mock_bot_class.return_value = mock_bot

            notifier = TelegramNotifier(config)
            await notifier.send_entry(sample_rss_entry)

        call_kwargs = mock_bot.send_message.call_args.kwargs
        assert call_kwargs["parse_mode"] == ParseMode.MARKDOWN_V2
