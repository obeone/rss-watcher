"""
Unit tests for the SimpleX Chat notification module.

Tests cover message formatting, WebSocket connection, and message sending.
"""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rss_watcher.config import SimpleXConfig
from rss_watcher.filters import RSSEntry
from rss_watcher.simplex import MAX_MESSAGE_LENGTH, SimpleXNotifier


@pytest.fixture
def minimal_simplex_config() -> SimpleXConfig:
    """Create a minimal valid SimpleX configuration."""
    return SimpleXConfig(
        websocket_url="ws://localhost:5225",
        contact="test-contact",
    )


@pytest.fixture
def sample_simplex_entry() -> RSSEntry:
    """Create a sample RSS entry for SimpleX testing."""
    return RSSEntry(
        title="Test Entry Title",
        content="This is the test entry content with some keywords.",
        link="https://example.com/test-entry",
        guid="https://example.com/test-entry",
        categories=["Technology", "Programming"],
        author="Test Author",
        published="2024-01-01T12:00:00Z",
        feed_name="Test Feed",
    )


class TestSimpleXInit:
    """Tests for SimpleXNotifier initialization."""

    def test_basic_init(self, minimal_simplex_config: SimpleXConfig) -> None:
        """Test basic SimpleXNotifier initialization."""
        notifier = SimpleXNotifier(minimal_simplex_config)

        assert notifier.config == minimal_simplex_config
        assert notifier._ws is None
        assert notifier._connected is False
        assert notifier._pending_responses == {}

    def test_init_with_custom_config(self) -> None:
        """Test SimpleXNotifier initialization with custom config."""
        config = SimpleXConfig(
            websocket_url="ws://192.168.1.100:5225",
            contact="my-contact",
            connect_timeout=30,
            message_timeout=60,
        )
        notifier = SimpleXNotifier(config)

        assert notifier.config.websocket_url == "ws://192.168.1.100:5225"
        assert notifier.config.contact == "my-contact"
        assert notifier.config.connect_timeout == 30
        assert notifier.config.message_timeout == 60


class TestSimpleXFormatting:
    """Tests for message formatting."""

    def test_format_basic_entry(
        self,
        minimal_simplex_config: SimpleXConfig,
        sample_simplex_entry: RSSEntry,
    ) -> None:
        """Test basic entry formatting."""
        notifier = SimpleXNotifier(minimal_simplex_config)

        message = notifier._format_entry(sample_simplex_entry)

        assert "*[Test Feed]*" in message
        assert "*Test Entry Title*" in message
        assert "https://example.com/test-entry" in message
        assert "_by Test Author_" in message

    def test_format_entry_with_categories(
        self,
        minimal_simplex_config: SimpleXConfig,
    ) -> None:
        """Test categories are formatted as hashtags."""
        entry = RSSEntry(
            title="Test",
            categories=["Tech News", "Python"],
            link="https://example.com",
            feed_name="Feed",
        )
        notifier = SimpleXNotifier(minimal_simplex_config)

        message = notifier._format_entry(entry)

        assert "#Tech_News" in message
        assert "#Python" in message

    def test_format_entry_no_link(
        self,
        minimal_simplex_config: SimpleXConfig,
    ) -> None:
        """Test formatting entry without link."""
        entry = RSSEntry(
            title="Title Only",
            content="",
            link="",
            feed_name="Feed",
        )
        notifier = SimpleXNotifier(minimal_simplex_config)

        message = notifier._format_entry(entry)

        assert "*Title Only*" in message
        assert "http" not in message

    def test_format_entry_no_title(
        self,
        minimal_simplex_config: SimpleXConfig,
    ) -> None:
        """Test formatting entry without title."""
        entry = RSSEntry(
            title="",
            content="Content only",
            link="https://example.com",
            feed_name="Feed",
        )
        notifier = SimpleXNotifier(minimal_simplex_config)

        message = notifier._format_entry(entry)

        assert "*No title*" in message

    def test_format_entry_truncates_content(
        self,
        minimal_simplex_config: SimpleXConfig,
    ) -> None:
        """Test that long content is truncated."""
        long_content = "A" * 1000
        entry = RSSEntry(
            title="Test",
            content=long_content,
            link="https://example.com",
            feed_name="Feed",
        )
        notifier = SimpleXNotifier(minimal_simplex_config)

        message = notifier._format_entry(entry)

        # Content should be truncated to ~500 chars with "..."
        assert "..." in message
        assert "A" * 600 not in message

    def test_format_entry_respects_max_length(
        self,
        minimal_simplex_config: SimpleXConfig,
    ) -> None:
        """Test message doesn't exceed MAX_MESSAGE_LENGTH."""
        entry = RSSEntry(
            title="X" * 1000,
            content="Y" * 20000,
            link="https://example.com",
            feed_name="Feed",
        )
        notifier = SimpleXNotifier(minimal_simplex_config)

        message = notifier._format_entry(entry)

        assert len(message) <= MAX_MESSAGE_LENGTH

    def test_format_entry_no_author(
        self,
        minimal_simplex_config: SimpleXConfig,
    ) -> None:
        """Test formatting entry without author."""
        entry = RSSEntry(
            title="Test",
            link="https://example.com",
            feed_name="Feed",
            author="",
        )
        notifier = SimpleXNotifier(minimal_simplex_config)

        message = notifier._format_entry(entry)

        assert "_by " not in message


class TestCleanContent:
    """Tests for content cleaning."""

    def test_clean_html_tags(self, minimal_simplex_config: SimpleXConfig) -> None:
        """Test HTML tag removal."""
        notifier = SimpleXNotifier(minimal_simplex_config)

        content = "<p>Hello <strong>World</strong></p>"
        result = notifier._clean_content(content)

        assert result == "Hello World"

    def test_clean_html_entities(
        self,
        minimal_simplex_config: SimpleXConfig,
    ) -> None:
        """Test HTML entity decoding."""
        notifier = SimpleXNotifier(minimal_simplex_config)

        content = "Test &amp; more &lt;stuff&gt;"
        result = notifier._clean_content(content)

        assert result == "Test & more <stuff>"

    def test_clean_whitespace(self, minimal_simplex_config: SimpleXConfig) -> None:
        """Test whitespace normalization."""
        notifier = SimpleXNotifier(minimal_simplex_config)

        content = "Hello\n\n\nWorld   with   spaces"
        result = notifier._clean_content(content)

        assert result == "Hello World with spaces"


class TestSimpleXConnection:
    """Tests for WebSocket connection handling."""

    async def test_connect_success(
        self,
        minimal_simplex_config: SimpleXConfig,
    ) -> None:
        """Test successful WebSocket connection."""
        mock_ws = AsyncMock()

        async def mock_aiter(self):
            while True:
                await asyncio.sleep(10)

        mock_ws.__aiter__ = mock_aiter

        with patch(
            "rss_watcher.simplex.websockets.connect", new_callable=AsyncMock
        ) as mock_connect:
            mock_connect.return_value = mock_ws

            notifier = SimpleXNotifier(minimal_simplex_config)
            result = await notifier._connect()

        assert result is True
        assert notifier._connected is True
        mock_connect.assert_called_once_with("ws://localhost:5225")

        # Cleanup
        await notifier.close()

    async def test_connect_timeout(
        self,
        minimal_simplex_config: SimpleXConfig,
    ) -> None:
        """Test connection timeout handling."""
        with patch(
            "rss_watcher.simplex.websockets.connect", new_callable=AsyncMock
        ) as mock_connect:
            mock_connect.side_effect = TimeoutError()

            notifier = SimpleXNotifier(minimal_simplex_config)
            result = await notifier._connect()

        assert result is False
        assert notifier._connected is False

    async def test_connect_invalid_uri(
        self,
        minimal_simplex_config: SimpleXConfig,
    ) -> None:
        """Test invalid URI error handling."""
        from websockets.exceptions import InvalidURI

        with patch(
            "rss_watcher.simplex.websockets.connect", new_callable=AsyncMock
        ) as mock_connect:
            mock_connect.side_effect = InvalidURI("invalid", "Bad URI")

            notifier = SimpleXNotifier(minimal_simplex_config)
            result = await notifier._connect()

        assert result is False

    async def test_connect_os_error(
        self,
        minimal_simplex_config: SimpleXConfig,
    ) -> None:
        """Test OS error handling (e.g., connection refused)."""
        with patch(
            "rss_watcher.simplex.websockets.connect", new_callable=AsyncMock
        ) as mock_connect:
            mock_connect.side_effect = OSError("Connection refused")

            notifier = SimpleXNotifier(minimal_simplex_config)
            result = await notifier._connect()

        assert result is False


class TestSimpleXTestConnection:
    """Tests for connection testing."""

    async def test_connection_success(
        self,
        minimal_simplex_config: SimpleXConfig,
    ) -> None:
        """Test successful connection test."""
        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()

        # Simulate response for /u command
        response_data = json.dumps(
            {"corrId": "test-id", "resp": {"type": "user", "user": {"displayName": "test"}}}
        )

        notifier = SimpleXNotifier(minimal_simplex_config)

        with patch(
            "rss_watcher.simplex.websockets.connect", new_callable=AsyncMock
        ) as mock_connect:
            mock_connect.return_value = mock_ws

            # Mock the receive loop to immediately return response
            async def mock_aiter(self):
                yield response_data
                while True:
                    await asyncio.sleep(10)

            mock_ws.__aiter__ = mock_aiter

            # Mock uuid to get predictable corrId
            with patch("rss_watcher.simplex.uuid.uuid4") as mock_uuid:
                mock_uuid.return_value = MagicMock()
                mock_uuid.return_value.__str__ = MagicMock(return_value="test-id")

                result = await notifier.test_connection()

        assert result is True
        await notifier.close()

    async def test_connection_failure(
        self,
        minimal_simplex_config: SimpleXConfig,
    ) -> None:
        """Test failed connection test."""
        with patch(
            "rss_watcher.simplex.websockets.connect", new_callable=AsyncMock
        ) as mock_connect:
            mock_connect.side_effect = OSError("Connection refused")

            notifier = SimpleXNotifier(minimal_simplex_config)
            result = await notifier.test_connection()

        assert result is False


class TestSimpleXSendEntry:
    """Tests for sending entries."""

    async def test_send_entry_success(
        self,
        minimal_simplex_config: SimpleXConfig,
        sample_simplex_entry: RSSEntry,
    ) -> None:
        """Test successful entry sending."""
        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()

        response_data = json.dumps(
            {"corrId": "test-id", "resp": {"type": "newChatItems", "chatItems": []}}
        )

        notifier = SimpleXNotifier(minimal_simplex_config)

        with patch(
            "rss_watcher.simplex.websockets.connect", new_callable=AsyncMock
        ) as mock_connect:
            mock_connect.return_value = mock_ws

            async def mock_aiter(self):
                yield response_data
                while True:
                    await asyncio.sleep(10)

            mock_ws.__aiter__ = mock_aiter

            with patch("rss_watcher.simplex.uuid.uuid4") as mock_uuid:
                mock_uuid.return_value = MagicMock()
                mock_uuid.return_value.__str__ = MagicMock(return_value="test-id")

                result = await notifier.send_entry(sample_simplex_entry)

        assert result is True

        # Verify the command was sent correctly
        call_args = mock_ws.send.call_args
        sent_data = json.loads(call_args[0][0])
        assert sent_data["corrId"] == "test-id"
        assert sent_data["cmd"].startswith("@test-contact ")

        await notifier.close()

    async def test_send_entry_error_response(
        self,
        minimal_simplex_config: SimpleXConfig,
        sample_simplex_entry: RSSEntry,
    ) -> None:
        """Test handling error response from SimpleX."""
        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()

        response_data = json.dumps(
            {
                "corrId": "test-id",
                "resp": {"type": "chatCmdError", "chatError": "Contact not found"},
            }
        )

        notifier = SimpleXNotifier(minimal_simplex_config)

        with patch(
            "rss_watcher.simplex.websockets.connect", new_callable=AsyncMock
        ) as mock_connect:
            mock_connect.return_value = mock_ws

            async def mock_aiter(self):
                yield response_data
                while True:
                    await asyncio.sleep(10)

            mock_ws.__aiter__ = mock_aiter

            with patch("rss_watcher.simplex.uuid.uuid4") as mock_uuid:
                mock_uuid.return_value = MagicMock()
                mock_uuid.return_value.__str__ = MagicMock(return_value="test-id")

                result = await notifier.send_entry(sample_simplex_entry)

        assert result is False
        await notifier.close()

    async def test_send_entry_timeout(
        self,
        minimal_simplex_config: SimpleXConfig,
        sample_simplex_entry: RSSEntry,
    ) -> None:
        """Test timeout waiting for response."""
        # Use short timeout for test
        config = SimpleXConfig(
            websocket_url="ws://localhost:5225",
            contact="test-contact",
            message_timeout=1,  # 1 second timeout
        )

        mock_ws = AsyncMock()
        mock_ws.send = AsyncMock()

        notifier = SimpleXNotifier(config)

        with patch(
            "rss_watcher.simplex.websockets.connect", new_callable=AsyncMock
        ) as mock_connect:
            mock_connect.return_value = mock_ws

            # Never yield any response to trigger timeout
            async def mock_aiter(self):
                while True:
                    await asyncio.sleep(10)

            mock_ws.__aiter__ = mock_aiter

            result = await notifier.send_entry(sample_simplex_entry)

        assert result is False
        await notifier.close()


class TestSimpleXClose:
    """Tests for notifier closing."""

    async def test_close_cleans_up(
        self,
        minimal_simplex_config: SimpleXConfig,
    ) -> None:
        """Test close properly cleans up resources."""
        mock_ws = AsyncMock()
        mock_ws.close = AsyncMock()

        notifier = SimpleXNotifier(minimal_simplex_config)

        with patch(
            "rss_watcher.simplex.websockets.connect", new_callable=AsyncMock
        ) as mock_connect:
            mock_connect.return_value = mock_ws

            async def mock_aiter(self):
                while True:
                    await asyncio.sleep(10)

            mock_ws.__aiter__ = mock_aiter

            await notifier._connect()

            # Add a pending response to test cleanup
            future = asyncio.get_event_loop().create_future()
            notifier._pending_responses["test-id"] = future

            await notifier.close()

        assert notifier._ws is None
        assert notifier._connected is False
        assert notifier._pending_responses == {}
        mock_ws.close.assert_called_once()

    async def test_close_when_not_connected(
        self,
        minimal_simplex_config: SimpleXConfig,
    ) -> None:
        """Test close works when never connected."""
        notifier = SimpleXNotifier(minimal_simplex_config)

        # Should not raise
        await notifier.close()

        assert notifier._ws is None
        assert notifier._connected is False


class TestSimpleXConfig:
    """Tests for SimpleX configuration validation."""

    def test_valid_config(self) -> None:
        """Test valid configuration."""
        config = SimpleXConfig(
            websocket_url="ws://localhost:5225",
            contact="my-contact",
        )

        assert config.websocket_url == "ws://localhost:5225"
        assert config.contact == "my-contact"
        assert config.connect_timeout == 10  # default
        assert config.message_timeout == 30  # default

    def test_empty_contact_raises(self) -> None:
        """Test empty contact raises validation error."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc_info:
            SimpleXConfig(
                websocket_url="ws://localhost:5225",
                contact="",
            )

        assert "Contact name cannot be empty" in str(exc_info.value)

    def test_whitespace_contact_raises(self) -> None:
        """Test whitespace-only contact raises validation error."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError) as exc_info:
            SimpleXConfig(
                websocket_url="ws://localhost:5225",
                contact="   ",
            )

        assert "Contact name cannot be empty" in str(exc_info.value)

    def test_custom_timeouts(self) -> None:
        """Test custom timeout values."""
        config = SimpleXConfig(
            websocket_url="ws://localhost:5225",
            contact="my-contact",
            connect_timeout=60,
            message_timeout=120,
        )

        assert config.connect_timeout == 60
        assert config.message_timeout == 120
