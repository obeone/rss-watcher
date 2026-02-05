"""
SimpleX Chat notification client.

Sends notifications to SimpleX Chat via the CLI WebSocket interface.
Requires the simplex-chat CLI to be running externally with -p <port> flag.
"""

import asyncio
import html
import json
import logging
import re
import uuid
from typing import Any

import websockets
from websockets.asyncio.client import ClientConnection
from websockets.exceptions import (
    ConnectionClosed,
    InvalidHandshake,
    InvalidURI,
)

from rss_watcher.config import SimpleXConfig
from rss_watcher.filters import RSSEntry

logger = logging.getLogger(__name__)

# Maximum message length for SimpleX (conservative estimate)
MAX_MESSAGE_LENGTH = 14000


class SimpleXNotifier:
    """
    SimpleX Chat notification client.

    Connects to a running simplex-chat CLI via WebSocket and sends
    messages to a pre-established contact.

    The simplex-chat CLI must be running externally with WebSocket
    server enabled, e.g.: simplex-chat -p 5225
    """

    def __init__(self, config: SimpleXConfig):
        """
        Initialize the SimpleX notifier.

        Parameters
        ----------
        config : SimpleXConfig
            SimpleX configuration with WebSocket URL and contact name.
        """
        self.config = config
        self._ws: ClientConnection | None = None
        self._pending_responses: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._receive_task: asyncio.Task | None = None
        self._rate_limit_delay = 0.5  # Seconds between messages
        self._connected = False

    async def _connect(self) -> bool:
        """
        Establish WebSocket connection to simplex-chat CLI.

        Returns
        -------
        bool
            True if connection was established successfully.
        """
        if self._ws is not None and self._connected:
            return True

        try:
            self._ws = await asyncio.wait_for(
                websockets.connect(self.config.websocket_url),
                timeout=self.config.connect_timeout,
            )
            self._connected = True
            logger.info(
                "Connected to SimpleX WebSocket at %s",
                self.config.websocket_url,
            )

            # Start background task to receive responses
            self._receive_task = asyncio.create_task(self._receive_loop())

            return True
        except TimeoutError:
            logger.error(
                "Timeout connecting to SimpleX WebSocket at %s",
                self.config.websocket_url,
            )
            return False
        except InvalidURI as e:
            logger.error("Invalid SimpleX WebSocket URL: %s", e)
            return False
        except InvalidHandshake as e:
            logger.error("SimpleX WebSocket handshake failed: %s", e)
            return False
        except OSError as e:
            logger.error("Failed to connect to SimpleX WebSocket: %s", e)
            return False

    async def _receive_loop(self) -> None:
        """Background task to receive and dispatch WebSocket responses."""
        if self._ws is None:
            return

        try:
            async for message in self._ws:
                try:
                    data = json.loads(message)
                    corr_id = data.get("corrId")

                    if corr_id and corr_id in self._pending_responses:
                        future = self._pending_responses.pop(corr_id)
                        if not future.done():
                            future.set_result(data)
                    else:
                        # Log async events without correlation ID
                        logger.debug("SimpleX async event: %s", data.get("resp", {}).get("type"))

                except json.JSONDecodeError:
                    logger.warning("Invalid JSON from SimpleX: %s", message[:100])

        except ConnectionClosed as e:
            logger.warning("SimpleX WebSocket connection closed: %s", e)
            self._connected = False
        except Exception as e:
            logger.error("Error in SimpleX receive loop: %s", e)
            self._connected = False

    async def _send_command(self, command: str) -> dict[str, Any] | None:
        """
        Send a command to simplex-chat and wait for response.

        Parameters
        ----------
        command : str
            The command to send (e.g., "@contact message").

        Returns
        -------
        dict | None
            Response data or None if failed.
        """
        if not await self._connect():
            return None

        if self._ws is None:
            return None

        corr_id = str(uuid.uuid4())
        request = json.dumps({"corrId": corr_id, "cmd": command})

        try:
            # Create future for response
            future: asyncio.Future[dict[str, Any]] = asyncio.get_event_loop().create_future()
            self._pending_responses[corr_id] = future

            # Send command
            await self._ws.send(request)
            logger.debug("Sent SimpleX command: %s", command[:100])

            # Wait for response with timeout
            try:
                response = await asyncio.wait_for(
                    future,
                    timeout=self.config.message_timeout,
                )
                return response
            except TimeoutError:
                logger.error("Timeout waiting for SimpleX response")
                self._pending_responses.pop(corr_id, None)
                return None

        except ConnectionClosed as e:
            logger.error("SimpleX connection closed while sending: %s", e)
            self._connected = False
            self._pending_responses.pop(corr_id, None)
            return None
        except Exception as e:
            logger.error("Error sending SimpleX command: %s", e)
            self._pending_responses.pop(corr_id, None)
            return None

    async def test_connection(self) -> bool:
        """
        Test the connection to SimpleX Chat.

        Sends a test command to verify the WebSocket is working
        and the CLI is responsive.

        Returns
        -------
        bool
            True if the connection is working.
        """
        if not await self._connect():
            return False

        # Send a simple command to test connectivity
        # Using "/u" (show user profile) as a harmless test command
        response = await self._send_command("/u")

        if response is not None:
            logger.info(
                "Connected to SimpleX Chat, will send to contact: %s",
                self.config.contact,
            )
            return True

        logger.error("Failed to verify SimpleX connection")
        return False

    async def send_entry(self, entry: RSSEntry) -> bool:
        """
        Send an RSS entry as a SimpleX message.

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

        # Format command for SimpleX: @contact message
        command = f"@{self.config.contact} {message}"

        try:
            response = await self._send_command(command)

            if response is None:
                logger.error("No response received from SimpleX")
                return False

            # Check response for success
            resp = response.get("resp", {})
            resp_type = resp.get("type", "")

            # Success responses include newChatItems for sent messages
            if resp_type == "newChatItems" or "chatItems" in resp:
                logger.info("Sent SimpleX notification for: %s", entry.title[:50])
                return True

            # Check for error responses
            if resp_type == "chatCmdError" or "error" in resp:
                error = resp.get("chatError", resp.get("error", "Unknown error"))
                logger.error("SimpleX error: %s", error)
                return False

            # Log unexpected response types but consider it success if not error
            logger.debug("SimpleX response type: %s", resp_type)
            return True

        except Exception as e:
            logger.error("Failed to send SimpleX notification: %s", e)
            return False

    def _format_entry(self, entry: RSSEntry) -> str:
        """
        Format an RSS entry as a SimpleX message.

        Uses Markdown-like formatting supported by SimpleX.

        Parameters
        ----------
        entry : RSSEntry
            The RSS entry to format.

        Returns
        -------
        str
            Formatted message string.
        """
        parts = []

        # Feed name (bold)
        parts.append(f"*[{entry.feed_name}]*")

        # Title with link
        title = entry.title if entry.title else "No title"
        if entry.link:
            parts.append(f"\n*{title}*")
            parts.append(f"\n{entry.link}")
        else:
            parts.append(f"\n*{title}*")

        # Author
        if entry.author:
            parts.append(f"\n_by {entry.author}_")

        # Categories
        if entry.categories:
            tags = " ".join(f"#{c.replace(' ', '_')}" for c in entry.categories[:5])
            parts.append(f"\n{tags}")

        # Content summary
        if entry.content:
            summary = self._clean_content(entry.content)
            # Limit summary length
            if len(summary) > 500:
                summary = summary[:497] + "..."
            parts.append(f"\n\n{summary}")

        message = "".join(parts)

        # Ensure message doesn't exceed SimpleX limit
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

    async def close(self) -> None:
        """Close the WebSocket connection and cleanup resources."""
        import contextlib

        # Cancel receive task
        if self._receive_task is not None:
            self._receive_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._receive_task
            self._receive_task = None

        # Cancel any pending responses
        for future in self._pending_responses.values():
            if not future.done():
                future.cancel()
        self._pending_responses.clear()

        # Close WebSocket
        if self._ws is not None:
            with contextlib.suppress(Exception):
                await self._ws.close()
            self._ws = None

        self._connected = False
        logger.debug("SimpleX client closed")
