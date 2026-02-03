"""
Shared fixtures for RSS Watcher tests.

Provides common test fixtures for use across all test modules.
"""

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from rss_watcher.config import (
    AppConfig,
    FeedConfig,
    FeedFilters,
    KeywordFilter,
    RegexFilter,
    TelegramConfig,
)
from rss_watcher.filters import RSSEntry
from rss_watcher.storage import Storage


# Path to test fixtures directory
FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    """Return path to fixtures directory."""
    return FIXTURES_DIR


@pytest.fixture
def sample_rss_path(fixtures_dir: Path) -> Path:
    """Return path to sample RSS feed file."""
    return fixtures_dir / "sample_rss.xml"


@pytest.fixture
def sample_atom_path(fixtures_dir: Path) -> Path:
    """Return path to sample Atom feed file."""
    return fixtures_dir / "sample_atom.xml"


@pytest.fixture
def sample_config_path(fixtures_dir: Path) -> Path:
    """Return path to sample config file."""
    return fixtures_dir / "sample_config.yaml"


@pytest.fixture
def sample_rss_content(sample_rss_path: Path) -> str:
    """Return contents of sample RSS feed."""
    return sample_rss_path.read_text()


@pytest.fixture
def sample_atom_content(sample_atom_path: Path) -> str:
    """Return contents of sample Atom feed."""
    return sample_atom_path.read_text()


@pytest.fixture
def sample_rss_entry() -> RSSEntry:
    """
    Create a sample RSS entry for testing.

    Returns
    -------
    RSSEntry
        A fully populated RSS entry instance.
    """
    return RSSEntry(
        title="Test Entry Title",
        content="This is the test entry content with some keywords like Python.",
        link="https://example.com/test-entry",
        guid="https://example.com/test-entry",
        categories=["Technology", "Programming"],
        author="Test Author",
        published="2024-01-01T12:00:00Z",
        feed_name="Test Feed",
        raw={
            "title": "Test Entry Title",
            "link": "https://example.com/test-entry",
            "id": "https://example.com/test-entry",
        },
    )


@pytest.fixture
def sample_rss_entry_with_video() -> RSSEntry:
    """
    Create a sample RSS entry with embedded video for testing.

    Returns
    -------
    RSSEntry
        An RSS entry with video content and enclosures.
    """
    return RSSEntry(
        title="Entry with Video",
        content='<p>Watch this video:</p><video src="https://example.com/video.mp4"></video>',
        link="https://example.com/video-entry",
        guid="https://example.com/video-entry",
        categories=["Media"],
        author="Video Author",
        published="2024-01-01T12:00:00Z",
        feed_name="Test Feed",
        raw={
            "title": "Entry with Video",
            "link": "https://example.com/video-entry",
            "id": "https://example.com/video-entry",
            "enclosures": [
                {"href": "https://example.com/enclosure.mp4", "type": "video/mp4"},
            ],
            "media_content": [
                {"url": "https://example.com/media.mp4", "type": "video/mp4"},
            ],
        },
    )


@pytest.fixture
def empty_keyword_filter() -> KeywordFilter:
    """Create an empty keyword filter."""
    return KeywordFilter()


@pytest.fixture
def sample_keyword_filter() -> KeywordFilter:
    """
    Create a keyword filter with sample includes/excludes.

    Returns
    -------
    KeywordFilter
        A filter with Python/programming includes and spam exclude.
    """
    return KeywordFilter(
        include=["python", "programming"],
        exclude=["spam", "advertisement"],
        case_sensitive=False,
    )


@pytest.fixture
def sample_regex_filter() -> RegexFilter:
    """
    Create a regex filter with sample patterns.

    Returns
    -------
    RegexFilter
        A filter with title and content regex patterns.
    """
    return RegexFilter(
        title=r"^Test.*$",
        content=r"Python",
    )


@pytest.fixture
def empty_feed_filters() -> FeedFilters:
    """Create empty feed filters."""
    return FeedFilters()


@pytest.fixture
def sample_feed_filters(
    sample_keyword_filter: KeywordFilter, sample_regex_filter: RegexFilter
) -> FeedFilters:
    """
    Create sample feed filters with keywords and regex.

    Returns
    -------
    FeedFilters
        Fully configured feed filters.
    """
    return FeedFilters(
        keywords=sample_keyword_filter,
        categories=KeywordFilter(include=["Technology"], exclude=["Spam"]),
        authors=KeywordFilter(include=[], exclude=["spammer"]),
        regex=sample_regex_filter,
    )


@pytest.fixture
def minimal_telegram_config() -> TelegramConfig:
    """Create a minimal valid Telegram configuration."""
    return TelegramConfig(
        bot_token="1234567890:ABCdefGHIjklMNOpqrsTUVwxyz",
        chat_id="-1001234567890",
    )


@pytest.fixture
def minimal_feed_config() -> FeedConfig:
    """Create a minimal valid feed configuration."""
    return FeedConfig(
        name="Test Feed",
        url="https://example.com/feed.xml",
    )


@pytest.fixture
def full_feed_config() -> FeedConfig:
    """Create a fully configured feed."""
    return FeedConfig(
        name="Full Test Feed",
        url="https://example.com/full-feed.xml",
        check_interval=600,
        enabled=True,
        cookies={"session": "abc123"},
        media_dir="/tmp/media",
        media_all_entries=True,
        filters=FeedFilters(
            keywords=KeywordFilter(include=["test"], exclude=["spam"]),
        ),
    )


@pytest.fixture
def minimal_config_dict() -> dict[str, Any]:
    """
    Create a minimal valid configuration dictionary.

    Returns
    -------
    dict
        Configuration dictionary that can be used to create AppConfig.
    """
    return {
        "telegram": {
            "bot_token": "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz",
            "chat_id": "-1001234567890",
        },
        "feeds": [
            {
                "name": "Test Feed",
                "url": "https://example.com/feed.xml",
            }
        ],
    }


@pytest.fixture
def full_config_dict(minimal_config_dict: dict[str, Any]) -> dict[str, Any]:
    """
    Create a fully configured configuration dictionary.

    Returns
    -------
    dict
        Complete configuration dictionary with all options.
    """
    config = minimal_config_dict.copy()
    config["defaults"] = {
        "check_interval": 600,
        "request_timeout": 60,
        "max_retries": 5,
        "proxy": "socks5://localhost:1080",
        "media_dir": "/tmp/media",
        "media_all_entries": True,
    }
    config["storage"] = {
        "database_path": "data/test.db",
    }
    config["feeds"][0]["filters"] = {
        "keywords": {"include": ["python"], "exclude": ["spam"]},
        "categories": {"include": ["Tech"]},
    }
    return config


@pytest.fixture
def minimal_app_config(minimal_telegram_config: TelegramConfig) -> AppConfig:
    """Create a minimal valid app configuration."""
    return AppConfig(
        telegram=minimal_telegram_config,
        feeds=[FeedConfig(name="Test Feed", url="https://example.com/feed.xml")],
    )


@pytest_asyncio.fixture
async def in_memory_storage() -> AsyncGenerator[Storage, None]:
    """
    Create an in-memory SQLite storage for testing.

    Yields
    ------
    Storage
        An initialized in-memory storage instance.
    """
    storage = Storage(":memory:")
    await storage.initialize()
    yield storage
    await storage.close()


@pytest.fixture
def tmp_media_dir(tmp_path: Path) -> Path:
    """
    Create a temporary directory for media downloads.

    Returns
    -------
    Path
        Path to temporary media directory.
    """
    media_dir = tmp_path / "media"
    media_dir.mkdir()
    return media_dir


@pytest.fixture
def mock_aiohttp_response() -> MagicMock:
    """
    Create a mock aiohttp response.

    Returns
    -------
    MagicMock
        A mock response object with common attributes.
    """
    response = MagicMock()
    response.status = 200
    response.raise_for_status = MagicMock()
    response.text = AsyncMock(return_value="<rss></rss>")
    response.headers = {"Content-Type": "text/xml"}
    return response


@pytest.fixture
def mock_telegram_bot() -> MagicMock:
    """
    Create a mock Telegram bot.

    Returns
    -------
    MagicMock
        A mock Bot instance with common methods mocked.
    """
    bot = MagicMock()
    bot.send_message = AsyncMock()
    bot.get_me = AsyncMock(return_value=MagicMock(username="test_bot"))
    bot.shutdown = AsyncMock()
    return bot


@pytest.fixture
def feedparser_entry() -> dict[str, Any]:
    """
    Create a sample feedparser entry dictionary.

    Returns
    -------
    dict
        A dictionary mimicking feedparser entry structure.
    """
    return {
        "title": "Test Entry",
        "link": "https://example.com/entry",
        "id": "https://example.com/entry",
        "summary": "This is a test summary",
        "content": [{"value": "This is the full content"}],
        "author": "Test Author",
        "tags": [{"term": "Category1"}, {"term": "Category2"}],
        "published": "2024-01-01T12:00:00Z",
    }
