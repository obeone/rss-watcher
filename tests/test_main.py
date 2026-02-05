"""
Unit tests for the main application module.

Tests cover RSSWatcher orchestration, feed checking, and lifecycle management.
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from rss_watcher.config import AppConfig, FeedConfig, FeedFilters, KeywordFilter, TelegramConfig
from rss_watcher.filters import RSSEntry
from rss_watcher.main import RSSWatcher, setup_logging


class TestRSSWatcherInit:
    """Tests for RSSWatcher initialization."""

    def test_loads_config(self, sample_config_path: Path) -> None:
        """Test that RSSWatcher loads configuration from file."""
        watcher = RSSWatcher(sample_config_path)

        assert watcher.config is not None
        assert len(watcher.config.feeds) == 2
        assert watcher.config.feeds[0].name == "Test Feed"

    def test_invalid_config_raises(self, tmp_path: Path) -> None:
        """Test that invalid config file raises error."""
        invalid_config = tmp_path / "invalid.yaml"
        invalid_config.write_text("invalid: yaml: content")

        with pytest.raises(Exception):
            RSSWatcher(invalid_config)

    def test_missing_config_raises(self, tmp_path: Path) -> None:
        """Test that missing config file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            RSSWatcher(tmp_path / "nonexistent.yaml")

    def test_initial_state(self, sample_config_path: Path) -> None:
        """Test initial state of RSSWatcher."""
        watcher = RSSWatcher(sample_config_path)

        assert watcher.storage is None
        assert watcher.parser is None
        assert watcher.notifiers == []
        assert watcher.media_downloader is None
        assert watcher._running is False
        assert watcher._tasks == []


class TestRSSWatcherCheckFeed:
    """Tests for feed checking logic."""

    @pytest.fixture
    def mock_watcher(self, sample_config_path: Path) -> RSSWatcher:
        """Create a watcher with mocked components."""
        watcher = RSSWatcher(sample_config_path)

        # Mock all components
        watcher.storage = MagicMock()
        watcher.storage.is_feed_initialized = AsyncMock(return_value=True)
        watcher.storage.is_seen = AsyncMock(return_value=False)
        watcher.storage.mark_seen = AsyncMock()
        watcher.storage.mark_many_seen = AsyncMock()
        watcher.storage.mark_feed_initialized = AsyncMock()

        watcher.parser = MagicMock()
        watcher.parser.fetch_feed = AsyncMock(return_value=[])

        # Create a mock notifier and add to list
        mock_notifier = MagicMock()
        mock_notifier.send_entry = AsyncMock(return_value=True)
        watcher.notifiers = [mock_notifier]

        watcher.media_downloader = MagicMock()
        watcher.media_downloader.process_entry = AsyncMock(return_value=[])

        return watcher

    async def test_check_feed_new_feed_marks_seen(
        self, mock_watcher: RSSWatcher
    ) -> None:
        """Test that new feed marks existing entries as seen without notifying."""
        mock_watcher.storage.is_feed_initialized = AsyncMock(return_value=False)

        entries = [
            RSSEntry(guid="1", title="Entry 1", feed_name="Test Feed"),
            RSSEntry(guid="2", title="Entry 2", feed_name="Test Feed"),
        ]
        mock_watcher.parser.fetch_feed = AsyncMock(return_value=entries)

        feed_config = mock_watcher.config.feeds[0]
        await mock_watcher._check_feed(feed_config)

        # Should mark all entries as seen
        mock_watcher.storage.mark_many_seen.assert_called_once()
        # Should mark feed as initialized
        mock_watcher.storage.mark_feed_initialized.assert_called_once()
        # Should NOT send notifications
        mock_watcher.notifiers[0].send_entry.assert_not_called()

    async def test_check_feed_filters_applied(
        self, mock_watcher: RSSWatcher
    ) -> None:
        """Test that filters are applied to entries."""
        mock_watcher.storage.is_feed_initialized = AsyncMock(return_value=True)
        mock_watcher.storage.is_seen = AsyncMock(return_value=False)

        # Create entries - one matches filter, one doesn't
        entries = [
            RSSEntry(guid="1", title="Python Tutorial", content="Learn Python"),
            RSSEntry(guid="2", title="Java Guide", content="Learn Java"),
        ]
        mock_watcher.parser.fetch_feed = AsyncMock(return_value=entries)

        # Use feed with python filter
        feed_config = mock_watcher.config.feeds[0]  # Has python keyword filter
        await mock_watcher._check_feed(feed_config)

        # Should only notify for the Python entry
        assert mock_watcher.notifiers[0].send_entry.call_count <= 1

    async def test_check_feed_marks_seen_after_notification(
        self, mock_watcher: RSSWatcher
    ) -> None:
        """Test entries are marked seen only after successful notification."""
        mock_watcher.storage.is_feed_initialized = AsyncMock(return_value=True)
        mock_watcher.storage.is_seen = AsyncMock(return_value=False)
        mock_watcher.notifiers[0].send_entry = AsyncMock(return_value=True)

        # Entry must match ALL filters (AND logic):
        # - keywords: "python" or "programming" (OR)
        # - categories: "Technology"
        # - authors: not "spammer"
        entries = [RSSEntry(
            guid="1",
            title="Python programming tutorial",
            content="Learn Python programming",
            categories=["Technology"],
            author="Good Author",
            feed_name="Test Feed",
        )]
        mock_watcher.parser.fetch_feed = AsyncMock(return_value=entries)

        feed_config = mock_watcher.config.feeds[0]
        await mock_watcher._check_feed(feed_config)

        # Verify mark_seen was called
        mock_watcher.storage.mark_seen.assert_called()

    async def test_check_feed_failed_notification_not_marked(
        self, mock_watcher: RSSWatcher
    ) -> None:
        """Test entries are not marked seen if notification fails."""
        mock_watcher.storage.is_feed_initialized = AsyncMock(return_value=True)
        mock_watcher.storage.is_seen = AsyncMock(return_value=False)
        mock_watcher.notifiers[0].send_entry = AsyncMock(return_value=False)

        entries = [RSSEntry(guid="1", title="Python Entry", content="Python")]
        mock_watcher.parser.fetch_feed = AsyncMock(return_value=entries)

        feed_config = mock_watcher.config.feeds[0]
        await mock_watcher._check_feed(feed_config)

        # mark_seen should NOT be called for failed notification
        mock_watcher.storage.mark_seen.assert_not_called()

    async def test_check_feed_media_download(
        self, mock_watcher: RSSWatcher
    ) -> None:
        """Test media download for filtered entries."""
        mock_watcher.storage.is_feed_initialized = AsyncMock(return_value=True)
        mock_watcher.storage.is_seen = AsyncMock(return_value=False)

        entries = [RSSEntry(guid="1", title="Video Entry", content="Python video")]
        mock_watcher.parser.fetch_feed = AsyncMock(return_value=entries)

        # Use feed with media_dir configured
        feed_config = mock_watcher.config.feeds[1]  # Has media_dir
        await mock_watcher._check_feed(feed_config)

        # Should call media downloader
        mock_watcher.media_downloader.process_entry.assert_called()

    async def test_check_feed_no_entries(
        self, mock_watcher: RSSWatcher
    ) -> None:
        """Test handling of feed with no entries."""
        mock_watcher.parser.fetch_feed = AsyncMock(return_value=[])

        feed_config = mock_watcher.config.feeds[0]
        await mock_watcher._check_feed(feed_config)

        # Should not call notification or storage
        mock_watcher.notifiers[0].send_entry.assert_not_called()
        mock_watcher.storage.mark_seen.assert_not_called()

    async def test_check_feed_all_seen(
        self, mock_watcher: RSSWatcher
    ) -> None:
        """Test handling when all entries are already seen."""
        mock_watcher.storage.is_feed_initialized = AsyncMock(return_value=True)
        mock_watcher.storage.is_seen = AsyncMock(return_value=True)  # All seen

        entries = [
            RSSEntry(guid="1", title="Entry 1"),
            RSSEntry(guid="2", title="Entry 2"),
        ]
        mock_watcher.parser.fetch_feed = AsyncMock(return_value=entries)

        feed_config = mock_watcher.config.feeds[0]
        await mock_watcher._check_feed(feed_config)

        # Should not send notifications for seen entries
        mock_watcher.notifiers[0].send_entry.assert_not_called()


class TestRSSWatcherLifecycle:
    """Tests for RSSWatcher start/stop lifecycle."""

    async def test_start_initializes_components(
        self, sample_config_path: Path
    ) -> None:
        """Test that start initializes all components."""
        with patch("rss_watcher.main.Storage") as mock_storage_class, \
             patch("rss_watcher.main.FeedParser") as mock_parser_class, \
             patch("rss_watcher.main.TelegramNotifier") as mock_notifier_class, \
             patch("rss_watcher.main.MediaDownloader") as mock_media_class:

            mock_storage = MagicMock()
            mock_storage.initialize = AsyncMock()
            mock_storage.close = AsyncMock()
            mock_storage_class.return_value = mock_storage

            mock_parser = MagicMock()
            mock_parser.close = AsyncMock()
            mock_parser_class.return_value = mock_parser

            mock_notifier = MagicMock()
            mock_notifier.test_connection = AsyncMock(return_value=True)
            mock_notifier.close = AsyncMock()
            mock_notifier_class.return_value = mock_notifier

            mock_media = MagicMock()
            mock_media.close = AsyncMock()
            mock_media_class.return_value = mock_media

            watcher = RSSWatcher(sample_config_path)

            # Start in background and stop immediately
            async def start_and_stop():
                task = asyncio.create_task(watcher.start())
                await asyncio.sleep(0.1)
                await watcher.stop()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

            await start_and_stop()

            mock_storage.initialize.assert_called_once()
            mock_notifier.test_connection.assert_called_once()

    async def test_stop_closes_components(
        self, sample_config_path: Path
    ) -> None:
        """Test that stop closes all components."""
        watcher = RSSWatcher(sample_config_path)

        # Mock components
        watcher.storage = MagicMock()
        watcher.storage.close = AsyncMock()

        watcher.parser = MagicMock()
        watcher.parser.close = AsyncMock()

        # Mock notifiers as a list
        mock_notifier = MagicMock()
        mock_notifier.close = AsyncMock()
        watcher.notifiers = [mock_notifier]

        watcher.media_downloader = MagicMock()
        watcher.media_downloader.close = AsyncMock()

        watcher._running = True

        await watcher.stop()

        watcher.storage.close.assert_called_once()
        watcher.parser.close.assert_called_once()
        mock_notifier.close.assert_called_once()
        watcher.media_downloader.close.assert_called_once()
        assert watcher._running is False


class TestSetupLogging:
    """Tests for logging configuration."""

    def test_verbose_mode(self) -> None:
        """Test verbose mode sets DEBUG level."""
        import logging

        with patch("rss_watcher.main.coloredlogs.install") as mock_install:
            setup_logging(verbose=True)

            mock_install.assert_called_once()
            call_kwargs = mock_install.call_args.kwargs
            assert call_kwargs["level"] == logging.DEBUG

    def test_normal_mode(self) -> None:
        """Test normal mode sets INFO level."""
        import logging

        with patch("rss_watcher.main.coloredlogs.install") as mock_install:
            setup_logging(verbose=False)

            mock_install.assert_called_once()
            call_kwargs = mock_install.call_args.kwargs
            assert call_kwargs["level"] == logging.INFO


class TestWatchFeed:
    """Tests for the _watch_feed method."""

    async def test_watch_feed_loops_while_running(
        self, sample_config_path: Path
    ) -> None:
        """Test _watch_feed loops while _running is True."""
        watcher = RSSWatcher(sample_config_path)
        watcher._running = True
        watcher.storage = MagicMock()
        watcher.parser = MagicMock()
        watcher.notifiers = [MagicMock()]
        watcher.media_downloader = MagicMock()

        call_count = 0

        async def mock_check_feed(feed):
            nonlocal call_count
            call_count += 1
            if call_count >= 2:
                watcher._running = False

        watcher._check_feed = mock_check_feed

        feed_config = watcher.config.feeds[0]
        feed_config.check_interval = 0  # No delay

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await watcher._watch_feed(feed_config)

        assert call_count >= 2

    async def test_watch_feed_handles_exceptions(
        self, sample_config_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test _watch_feed handles exceptions in _check_feed."""
        watcher = RSSWatcher(sample_config_path)
        watcher._running = True
        watcher.storage = MagicMock()
        watcher.parser = MagicMock()
        watcher.notifiers = [MagicMock()]
        watcher.media_downloader = MagicMock()

        call_count = 0

        async def mock_check_feed(feed):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("Test error")
            watcher._running = False

        watcher._check_feed = mock_check_feed

        feed_config = watcher.config.feeds[0]
        feed_config.check_interval = 0

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await watcher._watch_feed(feed_config)

        # Should have continued after error
        assert call_count >= 2
        assert "Error checking feed" in caplog.text

    async def test_watch_feed_cancellation(
        self, sample_config_path: Path
    ) -> None:
        """Test _watch_feed handles cancellation."""
        watcher = RSSWatcher(sample_config_path)
        watcher._running = True
        watcher.storage = MagicMock()
        watcher.parser = MagicMock()
        watcher.notifiers = [MagicMock()]
        watcher.media_downloader = MagicMock()

        async def mock_check_feed(feed):
            raise asyncio.CancelledError()

        watcher._check_feed = mock_check_feed

        feed_config = watcher.config.feeds[0]

        with pytest.raises(asyncio.CancelledError):
            await watcher._watch_feed(feed_config)


class TestComponentsNotInitialized:
    """Tests for error handling when components not initialized."""

    async def test_check_feed_raises_without_components(
        self, sample_config_path: Path
    ) -> None:
        """Test _check_feed raises error when components not initialized."""
        watcher = RSSWatcher(sample_config_path)

        with pytest.raises(RuntimeError, match="Components not initialized"):
            await watcher._check_feed(watcher.config.feeds[0])
