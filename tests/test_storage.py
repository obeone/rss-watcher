"""
Unit tests for the storage module.

Tests cover async SQLite operations, seen entry tracking,
feed initialization state, and cleanup functions.
"""

from pathlib import Path

import pytest

from rss_watcher.storage import Storage


class TestStorageInit:
    """Tests for Storage initialization."""

    async def test_creates_db_file(self, tmp_path: Path) -> None:
        """Test that initialize creates the database file."""
        db_path = tmp_path / "data" / "test.db"
        storage = Storage(db_path)

        await storage.initialize()

        assert db_path.exists()
        await storage.close()

    async def test_creates_parent_directories(self, tmp_path: Path) -> None:
        """Test that initialize creates parent directories."""
        db_path = tmp_path / "nested" / "deep" / "test.db"
        storage = Storage(db_path)

        await storage.initialize()

        assert db_path.parent.exists()
        await storage.close()

    async def test_creates_tables(self, in_memory_storage: Storage) -> None:
        """Test that initialize creates required tables."""
        # Check seen_entries table exists by querying it
        cursor = await in_memory_storage._connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='seen_entries'"
        )
        result = await cursor.fetchone()
        assert result is not None
        assert result[0] == "seen_entries"

    async def test_creates_feed_state_table(self, in_memory_storage: Storage) -> None:
        """Test that initialize creates feed_state table."""
        cursor = await in_memory_storage._connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='feed_state'"
        )
        result = await cursor.fetchone()
        assert result is not None
        assert result[0] == "feed_state"

    async def test_creates_index(self, in_memory_storage: Storage) -> None:
        """Test that initialize creates the guid_feed index."""
        cursor = await in_memory_storage._connection.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_guid_feed'"
        )
        result = await cursor.fetchone()
        assert result is not None

    async def test_in_memory_database(self) -> None:
        """Test that :memory: database works correctly."""
        storage = Storage(":memory:")
        await storage.initialize()

        # Should work without creating any files
        assert await storage.get_seen_count() == 0

        await storage.close()


class TestStorageSeenEntries:
    """Tests for seen entry tracking."""

    async def test_is_seen_returns_false_for_new(
        self, in_memory_storage: Storage
    ) -> None:
        """Test is_seen returns False for new entries."""
        result = await in_memory_storage.is_seen("guid123", "test_feed")

        assert result is False

    async def test_mark_seen_then_is_seen(self, in_memory_storage: Storage) -> None:
        """Test marking entry as seen makes is_seen return True."""
        await in_memory_storage.mark_seen(
            guid="guid123",
            feed_name="test_feed",
            title="Test Title",
            link="https://example.com",
        )

        result = await in_memory_storage.is_seen("guid123", "test_feed")

        assert result is True

    async def test_duplicate_insert_ignored(self, in_memory_storage: Storage) -> None:
        """Test that duplicate entries are silently ignored."""
        await in_memory_storage.mark_seen("guid123", "test_feed", "Title 1", "link1")
        await in_memory_storage.mark_seen("guid123", "test_feed", "Title 2", "link2")

        # Should still only be one entry
        count = await in_memory_storage.get_seen_count()
        assert count == 1

    async def test_same_guid_different_feeds(self, in_memory_storage: Storage) -> None:
        """Test that same GUID in different feeds are tracked separately."""
        await in_memory_storage.mark_seen("guid123", "feed_a")
        await in_memory_storage.mark_seen("guid123", "feed_b")

        assert await in_memory_storage.is_seen("guid123", "feed_a") is True
        assert await in_memory_storage.is_seen("guid123", "feed_b") is True
        assert await in_memory_storage.get_seen_count() == 2

    async def test_seen_entry_stores_metadata(self, in_memory_storage: Storage) -> None:
        """Test that seen entries store title and link."""
        await in_memory_storage.mark_seen(
            guid="guid123",
            feed_name="test_feed",
            title="Test Title",
            link="https://example.com/entry",
        )

        cursor = await in_memory_storage._connection.execute(
            "SELECT title, link FROM seen_entries WHERE guid = ?",
            ("guid123",),
        )
        result = await cursor.fetchone()

        assert result[0] == "Test Title"
        assert result[1] == "https://example.com/entry"


class TestStorageFeedState:
    """Tests for feed initialization state tracking."""

    async def test_is_initialized_returns_false_for_new(
        self, in_memory_storage: Storage
    ) -> None:
        """Test is_feed_initialized returns False for new feeds."""
        result = await in_memory_storage.is_feed_initialized("new_feed")

        assert result is False

    async def test_mark_initialized(self, in_memory_storage: Storage) -> None:
        """Test marking feed as initialized."""
        await in_memory_storage.mark_feed_initialized("test_feed")

        result = await in_memory_storage.is_feed_initialized("test_feed")

        assert result is True

    async def test_mark_initialized_idempotent(
        self, in_memory_storage: Storage
    ) -> None:
        """Test that marking as initialized twice doesn't raise error."""
        await in_memory_storage.mark_feed_initialized("test_feed")
        await in_memory_storage.mark_feed_initialized("test_feed")

        assert await in_memory_storage.is_feed_initialized("test_feed") is True

    async def test_multiple_feeds_initialized(
        self, in_memory_storage: Storage
    ) -> None:
        """Test tracking multiple feeds' initialization state."""
        await in_memory_storage.mark_feed_initialized("feed_a")
        await in_memory_storage.mark_feed_initialized("feed_b")

        assert await in_memory_storage.is_feed_initialized("feed_a") is True
        assert await in_memory_storage.is_feed_initialized("feed_b") is True
        assert await in_memory_storage.is_feed_initialized("feed_c") is False


class TestStorageBulk:
    """Tests for bulk storage operations."""

    async def test_mark_many_seen(self, in_memory_storage: Storage) -> None:
        """Test marking multiple entries as seen at once."""
        entries = [
            ("guid1", "feed", "Title 1", "link1"),
            ("guid2", "feed", "Title 2", "link2"),
            ("guid3", "feed", "Title 3", "link3"),
        ]

        await in_memory_storage.mark_many_seen(entries)

        assert await in_memory_storage.is_seen("guid1", "feed") is True
        assert await in_memory_storage.is_seen("guid2", "feed") is True
        assert await in_memory_storage.is_seen("guid3", "feed") is True

    async def test_mark_many_seen_empty_list(self, in_memory_storage: Storage) -> None:
        """Test mark_many_seen with empty list doesn't raise."""
        await in_memory_storage.mark_many_seen([])

        assert await in_memory_storage.get_seen_count() == 0

    async def test_mark_many_seen_with_duplicates(
        self, in_memory_storage: Storage
    ) -> None:
        """Test mark_many_seen handles duplicates gracefully."""
        entries = [
            ("guid1", "feed", "Title 1", "link1"),
            ("guid1", "feed", "Title 1 Dup", "link1"),  # Duplicate
            ("guid2", "feed", "Title 2", "link2"),
        ]

        await in_memory_storage.mark_many_seen(entries)

        assert await in_memory_storage.get_seen_count() == 2

    async def test_get_seen_count_all(self, in_memory_storage: Storage) -> None:
        """Test get_seen_count returns total count."""
        entries = [
            ("guid1", "feed_a", "T1", "l1"),
            ("guid2", "feed_a", "T2", "l2"),
            ("guid3", "feed_b", "T3", "l3"),
        ]
        await in_memory_storage.mark_many_seen(entries)

        count = await in_memory_storage.get_seen_count()

        assert count == 3

    async def test_get_seen_count_by_feed(self, in_memory_storage: Storage) -> None:
        """Test get_seen_count with feed filter."""
        entries = [
            ("guid1", "feed_a", "T1", "l1"),
            ("guid2", "feed_a", "T2", "l2"),
            ("guid3", "feed_b", "T3", "l3"),
        ]
        await in_memory_storage.mark_many_seen(entries)

        count_a = await in_memory_storage.get_seen_count("feed_a")
        count_b = await in_memory_storage.get_seen_count("feed_b")

        assert count_a == 2
        assert count_b == 1


class TestStorageCleanup:
    """Tests for storage cleanup operations."""

    async def test_cleanup_old_entries(self, in_memory_storage: Storage) -> None:
        """Test cleanup_old_entries removes old entries."""
        # Insert an entry with old timestamp directly
        await in_memory_storage._connection.execute(
            """
            INSERT INTO seen_entries (guid, feed_name, title, link, seen_at)
            VALUES (?, ?, ?, ?, datetime('now', '-60 days'))
            """,
            ("old_guid", "feed", "Old Title", "old_link"),
        )
        await in_memory_storage._connection.commit()

        # Insert a recent entry normally
        await in_memory_storage.mark_seen("new_guid", "feed", "New Title", "new_link")

        # Cleanup entries older than 30 days
        deleted = await in_memory_storage.cleanup_old_entries(days=30)

        assert deleted == 1
        assert await in_memory_storage.is_seen("old_guid", "feed") is False
        assert await in_memory_storage.is_seen("new_guid", "feed") is True

    async def test_cleanup_no_old_entries(self, in_memory_storage: Storage) -> None:
        """Test cleanup returns 0 when no old entries exist."""
        await in_memory_storage.mark_seen("guid1", "feed")

        deleted = await in_memory_storage.cleanup_old_entries(days=30)

        assert deleted == 0
        assert await in_memory_storage.get_seen_count() == 1

    async def test_cleanup_custom_days(self, in_memory_storage: Storage) -> None:
        """Test cleanup with custom days parameter."""
        # Insert entry from 10 days ago
        await in_memory_storage._connection.execute(
            """
            INSERT INTO seen_entries (guid, feed_name, title, link, seen_at)
            VALUES (?, ?, ?, ?, datetime('now', '-10 days'))
            """,
            ("ten_days_old", "feed", "Title", "link"),
        )
        await in_memory_storage._connection.commit()

        # Cleanup entries older than 7 days
        deleted = await in_memory_storage.cleanup_old_entries(days=7)

        assert deleted == 1


class TestStorageNotInitialized:
    """Tests for operations on uninitialized storage."""

    async def test_is_seen_raises_runtime_error(self) -> None:
        """Test is_seen raises RuntimeError when not initialized."""
        storage = Storage(":memory:")

        with pytest.raises(RuntimeError, match="Database not initialized"):
            await storage.is_seen("guid", "feed")

    async def test_mark_seen_raises_runtime_error(self) -> None:
        """Test mark_seen raises RuntimeError when not initialized."""
        storage = Storage(":memory:")

        with pytest.raises(RuntimeError, match="Database not initialized"):
            await storage.mark_seen("guid", "feed")

    async def test_mark_many_seen_raises_runtime_error(self) -> None:
        """Test mark_many_seen raises RuntimeError when not initialized."""
        storage = Storage(":memory:")

        with pytest.raises(RuntimeError, match="Database not initialized"):
            await storage.mark_many_seen([("guid", "feed", "t", "l")])

    async def test_is_feed_initialized_raises_runtime_error(self) -> None:
        """Test is_feed_initialized raises RuntimeError when not initialized."""
        storage = Storage(":memory:")

        with pytest.raises(RuntimeError, match="Database not initialized"):
            await storage.is_feed_initialized("feed")

    async def test_get_seen_count_raises_runtime_error(self) -> None:
        """Test get_seen_count raises RuntimeError when not initialized."""
        storage = Storage(":memory:")

        with pytest.raises(RuntimeError, match="Database not initialized"):
            await storage.get_seen_count()


class TestStorageContextManager:
    """Tests for async context manager support."""

    async def test_context_manager_initializes(self) -> None:
        """Test async context manager initializes storage."""
        async with Storage(":memory:") as storage:
            # Should be able to use storage
            await storage.mark_seen("guid", "feed")
            assert await storage.is_seen("guid", "feed") is True

    async def test_context_manager_closes(self) -> None:
        """Test async context manager closes storage on exit."""
        storage = Storage(":memory:")
        async with storage:
            pass

        # Connection should be closed
        assert storage._connection is None

    async def test_close_idempotent(self, in_memory_storage: Storage) -> None:
        """Test close can be called multiple times safely."""
        await in_memory_storage.close()
        await in_memory_storage.close()

        assert in_memory_storage._connection is None
