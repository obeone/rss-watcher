"""
Protocol definition for notification backends.

Defines the common interface that all notifiers must implement.
"""

from typing import Protocol, runtime_checkable

from rss_watcher.filters import RSSEntry


@runtime_checkable
class Notifier(Protocol):
    """
    Protocol defining the interface for notification backends.

    All notifiers (Telegram, SimpleX, etc.) must implement these methods
    to be compatible with the RSS Watcher notification system.

    The @runtime_checkable decorator allows using isinstance() checks
    against this protocol for structural typing validation.
    """

    async def test_connection(self) -> bool:
        """
        Test the connection to the notification backend.

        Returns
        -------
        bool
            True if the connection is working and messages can be sent.
        """
        ...

    async def send_entry(self, entry: RSSEntry) -> bool:
        """
        Send an RSS entry as a notification.

        Parameters
        ----------
        entry : RSSEntry
            The RSS entry to send.

        Returns
        -------
        bool
            True if the notification was sent successfully.
        """
        ...

    async def close(self) -> None:
        """
        Close the notifier and release any resources.

        This method should be called when shutting down the application
        to cleanly close connections and free resources.
        """
        ...
