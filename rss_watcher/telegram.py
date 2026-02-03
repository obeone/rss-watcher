"""
Telegram notification client.

Sends formatted notifications to Telegram using the Bot API.
"""

import asyncio
import html
import logging
import re

from telegram import Bot
from telegram.constants import ParseMode
from telegram.error import RetryAfter, TelegramError
from telegram.request import HTTPXRequest

from rss_watcher.config import TelegramConfig
from rss_watcher.filters import RSSEntry

logger = logging.getLogger(__name__)

# Maximum message length for Telegram
MAX_MESSAGE_LENGTH = 4096
MAX_CAPTION_LENGTH = 1024


class TelegramNotifier:
    """
    Telegram notification client.

    Sends formatted messages to a Telegram chat using a bot.
    Includes rate limiting and error handling.
    """

    def __init__(self, config: TelegramConfig, proxy_url: str | None = None):
        """
        Initialize the Telegram notifier.

        Parameters
        ----------
        config : TelegramConfig
            Telegram configuration with bot token and chat ID.
        proxy_url : str | None
            Optional SOCKS proxy URL (e.g., socks5://user:pass@host:port).
        """
        self.config = config

        request = None
        if proxy_url:
            request = HTTPXRequest(proxy=proxy_url)
            logger.debug("Telegram using proxy: %s", proxy_url.split("@")[-1])

        self._bot = Bot(token=config.bot_token, request=request)
        self._rate_limit_delay = 0.5  # Seconds between messages

    async def send_entry(self, entry: RSSEntry) -> bool:
        """
        Send an RSS entry as a Telegram message.

        Parameters
        ----------
        entry : RSSEntry
            The RSS entry to send.

        Returns
        -------
        bool
            True if the message was sent successfully.
        """
        message = self._format_entry(entry)

        try:
            await self._send_message(message)
            logger.info("Sent notification for: %s", entry.title[:50])
            return True
        except TelegramError as e:
            logger.error("Failed to send notification: %s", e)
            return False

    async def send_entries(self, entries: list[RSSEntry]) -> int:
        """
        Send multiple RSS entries as Telegram messages.

        Parameters
        ----------
        entries : list[RSSEntry]
            List of RSS entries to send.

        Returns
        -------
        int
            Number of successfully sent messages.
        """
        success_count = 0

        for entry in entries:
            if await self.send_entry(entry):
                success_count += 1
            # Rate limiting between messages
            await asyncio.sleep(self._rate_limit_delay)

        return success_count

    def _format_entry(self, entry: RSSEntry) -> str:
        """
        Format an RSS entry as a Telegram message.

        Parameters
        ----------
        entry : RSSEntry
            The RSS entry to format.

        Returns
        -------
        str
            Formatted message string.
        """
        if self.config.parse_mode == "HTML":
            return self._format_html(entry)
        else:
            return self._format_markdown(entry)

    def _format_html(self, entry: RSSEntry) -> str:
        """
        Format entry as HTML message.

        Parameters
        ----------
        entry : RSSEntry
            The RSS entry to format.

        Returns
        -------
        str
            HTML formatted message.
        """
        parts = []

        # Feed name
        parts.append(f"<b>[{html.escape(entry.feed_name)}]</b>")

        # Title with link
        title = html.escape(entry.title) if entry.title else "No title"
        if entry.link:
            parts.append(f'\n<b><a href="{html.escape(entry.link)}">{title}</a></b>')
        else:
            parts.append(f"\n<b>{title}</b>")

        # Author
        if entry.author:
            parts.append(f"\n<i>by {html.escape(entry.author)}</i>")

        # Categories
        if entry.categories:
            tags = " ".join(f"#{html.escape(c.replace(' ', '_'))}" for c in entry.categories[:5])
            parts.append(f"\n{tags}")

        # Content summary
        if entry.content:
            summary = self._clean_content(entry.content)
            # Limit summary length
            if len(summary) > 500:
                summary = summary[:497] + "..."
            parts.append(f"\n\n{html.escape(summary)}")

        message = "".join(parts)

        # Ensure message doesn't exceed Telegram limit
        if len(message) > MAX_MESSAGE_LENGTH:
            message = message[: MAX_MESSAGE_LENGTH - 3] + "..."

        return message

    def _format_markdown(self, entry: RSSEntry) -> str:
        """
        Format entry as Markdown message.

        Parameters
        ----------
        entry : RSSEntry
            The RSS entry to format.

        Returns
        -------
        str
            Markdown formatted message.
        """
        parts = []

        # Feed name
        parts.append(f"*[{self._escape_markdown(entry.feed_name)}]*")

        # Title with link
        title = self._escape_markdown(entry.title) if entry.title else "No title"
        if entry.link:
            parts.append(f"\n[{title}]({entry.link})")
        else:
            parts.append(f"\n*{title}*")

        # Author
        if entry.author:
            parts.append(f"\n_by {self._escape_markdown(entry.author)}_")

        # Categories
        if entry.categories:
            tags = " ".join(f"#{c.replace(' ', '_')}" for c in entry.categories[:5])
            parts.append(f"\n{self._escape_markdown(tags)}")

        # Content summary
        if entry.content:
            summary = self._clean_content(entry.content)
            if len(summary) > 500:
                summary = summary[:497] + "..."
            parts.append(f"\n\n{self._escape_markdown(summary)}")

        message = "".join(parts)

        if len(message) > MAX_MESSAGE_LENGTH:
            message = message[: MAX_MESSAGE_LENGTH - 3] + "..."

        return message

    def _clean_content(self, content: str) -> str:
        """
        Clean HTML content for display.

        Parameters
        ----------
        content : str
            Raw content possibly containing HTML.

        Returns
        -------
        str
            Cleaned plain text content.
        """
        # Remove HTML tags
        text = re.sub(r"<[^>]+>", "", content)
        # Decode HTML entities
        text = html.unescape(text)
        # Normalize whitespace
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _escape_markdown(self, text: str) -> str:
        """
        Escape special Markdown characters.

        Parameters
        ----------
        text : str
            Text to escape.

        Returns
        -------
        str
            Escaped text safe for Markdown.
        """
        escape_chars = r"_*[]()~`>#+-=|{}.!"
        return "".join(f"\\{c}" if c in escape_chars else c for c in text)

    async def _send_message(self, text: str) -> None:
        """
        Send a message with retry on rate limit.

        Parameters
        ----------
        text : str
            Message text to send.

        Raises
        ------
        TelegramError
            If the message could not be sent.
        """
        parse_mode = ParseMode.HTML if self.config.parse_mode == "HTML" else ParseMode.MARKDOWN_V2

        try:
            await self._bot.send_message(
                chat_id=self.config.chat_id,
                text=text,
                parse_mode=parse_mode,
                disable_web_page_preview=self.config.disable_web_page_preview,
            )
        except RetryAfter as e:
            logger.warning("Rate limited, waiting %d seconds", e.retry_after)
            await asyncio.sleep(e.retry_after)
            # Retry once
            await self._bot.send_message(
                chat_id=self.config.chat_id,
                text=text,
                parse_mode=parse_mode,
                disable_web_page_preview=self.config.disable_web_page_preview,
            )

    async def test_connection(self) -> bool:
        """
        Test the Telegram bot connection.

        Returns
        -------
        bool
            True if the connection is working.
        """
        try:
            me = await self._bot.get_me()
            logger.info("Connected to Telegram as @%s", me.username)
            return True
        except TelegramError as e:
            logger.error("Failed to connect to Telegram: %s", e)
            return False

    async def close(self) -> None:
        """Close the Telegram bot session."""
        if hasattr(self._bot, "shutdown"):
            await self._bot.shutdown()
        logger.debug("Telegram client closed")
