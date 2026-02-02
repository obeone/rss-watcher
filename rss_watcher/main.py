"""
Main entry point for RSS Watcher.

Runs the main async loop that monitors feeds and sends notifications.
"""

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

import coloredlogs

from rss_watcher.config import FeedConfig, load_config
from rss_watcher.filters import EntryFilter, RSSEntry, filter_entries
from rss_watcher.rss_parser import FeedParser
from rss_watcher.storage import Storage
from rss_watcher.telegram import TelegramNotifier

logger = logging.getLogger(__name__)


class RSSWatcher:
    """
    Main RSS watcher application.

    Coordinates feed parsing, filtering, storage, and notifications.
    """

    def __init__(self, config_path: str | Path):
        """
        Initialize the RSS watcher.

        Parameters
        ----------
        config_path : str | Path
            Path to the YAML configuration file.
        """
        self.config = load_config(config_path)
        self.storage: Storage | None = None
        self.parser: FeedParser | None = None
        self.notifier: TelegramNotifier | None = None
        self._running = False
        self._tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        """Start the RSS watcher."""
        logger.info("Starting RSS Watcher")

        # Initialize components
        self.storage = Storage(self.config.storage.database_path)
        await self.storage.initialize()

        proxy_url = self.config.defaults.proxy
        if proxy_url:
            logger.info("Using proxy: %s", proxy_url.split("@")[-1])

        self.parser = FeedParser(
            timeout=self.config.defaults.request_timeout,
            max_retries=self.config.defaults.max_retries,
            proxy_url=proxy_url,
        )

        self.notifier = TelegramNotifier(self.config.telegram, proxy_url=proxy_url)

        # Test Telegram connection
        if not await self.notifier.test_connection():
            logger.error("Failed to connect to Telegram, exiting")
            await self.stop()
            sys.exit(1)

        self._running = True

        # Start feed watchers
        for feed in self.config.feeds:
            if feed.enabled:
                task = asyncio.create_task(self._watch_feed(feed))
                self._tasks.append(task)
                logger.info("Started watching feed: %s", feed.name)

        logger.info("RSS Watcher started with %d active feed(s)", len(self._tasks))

        # Wait for all tasks
        try:
            await asyncio.gather(*self._tasks)
        except asyncio.CancelledError:
            logger.info("Watcher tasks cancelled")

    async def stop(self) -> None:
        """Stop the RSS watcher gracefully."""
        logger.info("Stopping RSS Watcher")
        self._running = False

        # Cancel all tasks
        for task in self._tasks:
            task.cancel()

        # Wait for tasks to complete
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

        # Close components
        if self.parser:
            await self.parser.close()
        if self.storage:
            await self.storage.close()
        if self.notifier:
            await self.notifier.close()

        logger.info("RSS Watcher stopped")

    async def _watch_feed(self, feed: FeedConfig) -> None:
        """
        Watch a single feed continuously.

        Parameters
        ----------
        feed : FeedConfig
            Configuration for the feed to watch.
        """
        interval = feed.check_interval or self.config.defaults.check_interval

        while self._running:
            try:
                await self._check_feed(feed)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("Error checking feed '%s': %s", feed.name, e)

            # Wait for next check
            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                raise

    async def _check_feed(self, feed: FeedConfig) -> None:
        """
        Check a feed for new entries.

        Parameters
        ----------
        feed : FeedConfig
            Configuration for the feed to check.
        """
        if not self.parser or not self.storage or not self.notifier:
            raise RuntimeError("Components not initialized")

        logger.debug("Checking feed: %s", feed.name)

        # Check if this is the first run for this feed (persisted in DB)
        is_initialized = await self.storage.is_feed_initialized(feed.name)

        try:
            entries = await self.parser.fetch_feed(feed)
        except Exception as e:
            logger.warning("Failed to fetch feed '%s': %s", feed.name, e)
            return

        if not entries:
            logger.debug("No entries found in feed '%s'", feed.name)
            # Mark feed as initialized even if empty, to avoid re-checking
            if not is_initialized:
                await self.storage.mark_feed_initialized(feed.name)
            return

        # Apply filters
        filtered_entries = filter_entries(entries, feed.filters)

        # Find new entries
        new_entries: list[RSSEntry] = []
        for entry in filtered_entries:
            if not await self.storage.is_seen(entry.guid, feed.name):
                new_entries.append(entry)

        if not new_entries:
            logger.debug("No new entries in feed '%s'", feed.name)
            # Mark feed as initialized if not already
            if not is_initialized:
                await self.storage.mark_feed_initialized(feed.name)
            return

        logger.info(
            "Found %d new entr%s in '%s'",
            len(new_entries),
            "y" if len(new_entries) == 1 else "ies",
            feed.name,
        )

        if not is_initialized:
            # First time seeing this feed: mark entries as seen without notifying
            logger.info(
                "New feed detected: marking %d existing entries as seen for '%s'",
                len(new_entries),
                feed.name,
            )
            entries_to_mark = [
                (e.guid, feed.name, e.title, e.link) for e in new_entries
            ]
            await self.storage.mark_many_seen(entries_to_mark)
            await self.storage.mark_feed_initialized(feed.name)
            return

        # Send notifications for new entries
        for entry in new_entries:
            try:
                success = await self.notifier.send_entry(entry)
                if success:
                    await self.storage.mark_seen(
                        entry.guid,
                        feed.name,
                        entry.title,
                        entry.link,
                    )
            except Exception as e:
                logger.error("Failed to notify for entry '%s': %s", entry.title[:50], e)


def setup_logging(verbose: bool = False) -> None:
    """
    Configure application logging.

    Parameters
    ----------
    verbose : bool
        If True, set log level to DEBUG.
    """
    level = logging.DEBUG if verbose else logging.INFO

    coloredlogs.install(
        level=level,
        fmt="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Reduce noise from third-party libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="RSS feed watcher with Telegram notifications",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "-c",
        "--config",
        default="config.yaml",
        help="Path to configuration file",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    args = parser.parse_args()

    setup_logging(args.verbose)

    # Check config file exists
    config_path = Path(args.config)
    if not config_path.exists():
        logger.error("Configuration file not found: %s", config_path)
        sys.exit(1)

    watcher = RSSWatcher(config_path)

    # Setup signal handlers for graceful shutdown
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    def signal_handler():
        logger.info("Received shutdown signal")
        asyncio.create_task(watcher.stop())

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    try:
        loop.run_until_complete(watcher.start())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    finally:
        loop.run_until_complete(watcher.stop())
        loop.close()


if __name__ == "__main__":
    main()
