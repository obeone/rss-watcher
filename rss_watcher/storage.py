"""
SQLite storage for tracking seen RSS entries.

Provides async database operations to persist entry state
and avoid duplicate notifications after restarts.
"""

import logging
from datetime import datetime, timezone
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)


class Storage:
    """
    Async SQLite storage for seen RSS entries.

    Stores entry GUIDs with metadata to track which entries
    have already been processed and notified.
    """

    def __init__(self, database_path: str | Path):
        """
        Initialize storage with database path.

        Parameters
        ----------
        database_path : str | Path
            Path to the SQLite database file.
        """
        self.database_path = Path(database_path)
        self._connection: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        """
        Initialize the database connection and create tables.

        Creates the database file and parent directories if they don't exist.
        """
        # Ensure parent directory exists
        self.database_path.parent.mkdir(parents=True, exist_ok=True)

        logger.info("Initializing database at %s", self.database_path)

        self._connection = await aiosqlite.connect(self.database_path)
        await self._create_tables()

    async def _create_tables(self) -> None:
        """Create database tables if they don't exist."""
        if self._connection is None:
            raise RuntimeError("Database not initialized")

        await self._connection.execute("""
            CREATE TABLE IF NOT EXISTS seen_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guid TEXT NOT NULL,
                feed_name TEXT NOT NULL,
                title TEXT,
                link TEXT,
                seen_at TEXT NOT NULL,
                UNIQUE(guid, feed_name)
            )
        """)

        # Create index for faster lookups
        await self._connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_guid_feed
            ON seen_entries (guid, feed_name)
        """)

        # Table to track initialized feeds (for first-run detection)
        await self._connection.execute("""
            CREATE TABLE IF NOT EXISTS feed_state (
                feed_name TEXT PRIMARY KEY,
                initialized_at TEXT NOT NULL
            )
        """)

        await self._connection.commit()
        logger.debug("Database tables created/verified")

    async def is_seen(self, guid: str, feed_name: str) -> bool:
        """
        Check if an entry has already been seen.

        Parameters
        ----------
        guid : str
            Unique identifier of the entry.
        feed_name : str
            Name of the feed the entry belongs to.

        Returns
        -------
        bool
            True if the entry has been seen before.
        """
        if self._connection is None:
            raise RuntimeError("Database not initialized")

        cursor = await self._connection.execute(
            "SELECT 1 FROM seen_entries WHERE guid = ? AND feed_name = ?",
            (guid, feed_name),
        )
        result = await cursor.fetchone()
        return result is not None

    async def is_feed_initialized(self, feed_name: str) -> bool:
        """
        Check if a feed has been initialized (first-run completed).

        Parameters
        ----------
        feed_name : str
            Name of the feed to check.

        Returns
        -------
        bool
            True if the feed has been initialized before.
        """
        if self._connection is None:
            raise RuntimeError("Database not initialized")

        cursor = await self._connection.execute(
            "SELECT 1 FROM feed_state WHERE feed_name = ?",
            (feed_name,),
        )
        result = await cursor.fetchone()
        return result is not None

    async def mark_feed_initialized(self, feed_name: str) -> None:
        """
        Mark a feed as initialized (first-run completed).

        Parameters
        ----------
        feed_name : str
            Name of the feed to mark as initialized.
        """
        if self._connection is None:
            raise RuntimeError("Database not initialized")

        now = datetime.now(timezone.utc).isoformat()

        await self._connection.execute(
            """
            INSERT OR IGNORE INTO feed_state (feed_name, initialized_at)
            VALUES (?, ?)
            """,
            (feed_name, now),
        )
        await self._connection.commit()
        logger.debug("Marked feed as initialized: %s", feed_name)

    async def mark_seen(
        self,
        guid: str,
        feed_name: str,
        title: str = "",
        link: str = "",
    ) -> None:
        """
        Mark an entry as seen.

        Parameters
        ----------
        guid : str
            Unique identifier of the entry.
        feed_name : str
            Name of the feed the entry belongs to.
        title : str
            Entry title for reference.
        link : str
            Entry link for reference.
        """
        if self._connection is None:
            raise RuntimeError("Database not initialized")

        now = datetime.now(timezone.utc).isoformat()

        await self._connection.execute(
            """
            INSERT OR IGNORE INTO seen_entries (guid, feed_name, title, link, seen_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (guid, feed_name, title, link, now),
        )
        await self._connection.commit()
        logger.debug("Marked entry as seen: %s", guid[:50])

    async def mark_many_seen(
        self,
        entries: list[tuple[str, str, str, str]],
    ) -> None:
        """
        Mark multiple entries as seen in a single transaction.

        Parameters
        ----------
        entries : list[tuple[str, str, str, str]]
            List of (guid, feed_name, title, link) tuples.
        """
        if self._connection is None:
            raise RuntimeError("Database not initialized")

        now = datetime.now(timezone.utc).isoformat()

        await self._connection.executemany(
            """
            INSERT OR IGNORE INTO seen_entries (guid, feed_name, title, link, seen_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            [(guid, feed_name, title, link, now) for guid, feed_name, title, link in entries],
        )
        await self._connection.commit()
        logger.debug("Marked %d entries as seen", len(entries))

    async def get_seen_count(self, feed_name: str | None = None) -> int:
        """
        Get the count of seen entries.

        Parameters
        ----------
        feed_name : str | None
            If provided, count only entries from this feed.

        Returns
        -------
        int
            Number of seen entries.
        """
        if self._connection is None:
            raise RuntimeError("Database not initialized")

        if feed_name:
            cursor = await self._connection.execute(
                "SELECT COUNT(*) FROM seen_entries WHERE feed_name = ?",
                (feed_name,),
            )
        else:
            cursor = await self._connection.execute("SELECT COUNT(*) FROM seen_entries")

        result = await cursor.fetchone()
        return result[0] if result else 0

    async def cleanup_old_entries(self, days: int = 30) -> int:
        """
        Remove entries older than specified days.

        Parameters
        ----------
        days : int
            Remove entries older than this many days.

        Returns
        -------
        int
            Number of entries removed.
        """
        if self._connection is None:
            raise RuntimeError("Database not initialized")

        cursor = await self._connection.execute(
            """
            DELETE FROM seen_entries
            WHERE seen_at < datetime('now', ?)
            """,
            (f"-{days} days",),
        )
        await self._connection.commit()

        deleted = cursor.rowcount
        if deleted > 0:
            logger.info("Cleaned up %d old entries", deleted)

        return deleted

    async def close(self) -> None:
        """Close the database connection."""
        if self._connection:
            await self._connection.close()
            self._connection = None
            logger.debug("Database connection closed")

    async def __aenter__(self) -> "Storage":
        """Async context manager entry."""
        await self.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.close()
