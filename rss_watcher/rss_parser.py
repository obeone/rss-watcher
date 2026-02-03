"""
RSS/Atom feed parsing module.

Handles fetching and parsing RSS/Atom feeds using feedparser
with async HTTP requests.
"""

import logging
from typing import Any

import aiohttp
import feedparser
from aiohttp_socks import ProxyConnector

from rss_watcher.config import FeedConfig
from rss_watcher.filters import RSSEntry

logger = logging.getLogger(__name__)


class FeedParser:
    """
    Async RSS/Atom feed parser.

    Fetches feeds using aiohttp and parses them with feedparser.
    """

    def __init__(
        self,
        timeout: int = 30,
        max_retries: int = 3,
        user_agent: str = "RSS-Watcher/1.0",
        proxy_url: str | None = None,
    ):
        """
        Initialize the feed parser.

        Parameters
        ----------
        timeout : int
            HTTP request timeout in seconds.
        max_retries : int
            Maximum number of retries for failed requests.
        user_agent : str
            User-Agent header for HTTP requests.
        proxy_url : str | None
            Optional SOCKS proxy URL (e.g., socks5://user:pass@host:port).
        """
        self.timeout = timeout
        self.max_retries = max_retries
        self.user_agent = user_agent
        self.proxy_url = proxy_url
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create the HTTP session."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.timeout)
            headers = {"User-Agent": self.user_agent}

            connector = None
            if self.proxy_url:
                connector = ProxyConnector.from_url(self.proxy_url)
                logger.debug("Using proxy: %s", self.proxy_url.split("@")[-1])

            self._session = aiohttp.ClientSession(
                timeout=timeout, headers=headers, connector=connector
            )
        return self._session

    async def fetch_feed(self, feed_config: FeedConfig) -> list[RSSEntry]:
        """
        Fetch and parse an RSS/Atom feed.

        Parameters
        ----------
        feed_config : FeedConfig
            Configuration for the feed to fetch.

        Returns
        -------
        list[RSSEntry]
            List of parsed entries from the feed.

        Raises
        ------
        aiohttp.ClientError
            If the HTTP request fails after all retries.
        """
        session = await self._get_session()
        last_error: Exception | None = None

        for attempt in range(1, self.max_retries + 1):
            try:
                logger.debug(
                    "Fetching feed '%s' (attempt %d/%d)%s",
                    feed_config.name,
                    attempt,
                    self.max_retries,
                    " with cookies" if feed_config.cookies else "",
                )

                async with session.get(feed_config.url, cookies=feed_config.cookies) as response:
                    response.raise_for_status()
                    content = await response.text()

                entries = self._parse_feed(content, feed_config.name)
                logger.info(
                    "Fetched %d entries from '%s'",
                    len(entries),
                    feed_config.name,
                )
                return entries

            except aiohttp.ClientError as e:
                last_error = e
                logger.warning(
                    "Failed to fetch feed '%s' (attempt %d/%d): %s",
                    feed_config.name,
                    attempt,
                    self.max_retries,
                    e,
                )
                if attempt < self.max_retries:
                    continue

        # All retries failed
        logger.error(
            "Failed to fetch feed '%s' after %d attempts",
            feed_config.name,
            self.max_retries,
        )
        raise last_error or RuntimeError("Unknown error fetching feed")

    def _parse_feed(self, content: str, feed_name: str) -> list[RSSEntry]:
        """
        Parse feed content into RSSEntry objects.

        Parameters
        ----------
        content : str
            Raw feed XML/content.
        feed_name : str
            Name of the feed for logging and entry metadata.

        Returns
        -------
        list[RSSEntry]
            List of parsed entries.
        """
        # Strip leading whitespace - some servers return content with
        # leading newlines which breaks XML declaration parsing
        content = content.lstrip()
        parsed: Any = feedparser.parse(content)

        if parsed.bozo and parsed.bozo_exception:
            logger.warning(
                "Feed '%s' has parsing issues: %s",
                feed_name,
                parsed.bozo_exception,
            )

        entries = []
        for entry in parsed.entries:
            try:
                rss_entry = RSSEntry.from_feedparser(entry, feed_name)
                entries.append(rss_entry)
            except Exception as e:
                logger.warning(
                    "Failed to parse entry in feed '%s': %s",
                    feed_name,
                    e,
                )
                continue

        return entries

    async def close(self) -> None:
        """Close the HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
            logger.debug("HTTP session closed")

    async def __aenter__(self) -> "FeedParser":
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.close()
