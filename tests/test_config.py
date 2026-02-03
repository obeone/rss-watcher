"""
Unit tests for the configuration module.

Tests cover Pydantic model validation, environment variable substitution,
and YAML configuration loading.
"""

import os
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from rss_watcher.config import (
    AppConfig,
    DefaultsConfig,
    FeedConfig,
    FeedFilters,
    KeywordFilter,
    RegexFilter,
    StorageConfig,
    TelegramConfig,
    _substitute_env_vars,
    load_config,
)


class TestKeywordFilter:
    """Tests for KeywordFilter Pydantic model."""

    def test_default_values(self) -> None:
        """Test that KeywordFilter has correct default values."""
        filter_ = KeywordFilter()

        assert filter_.include == []
        assert filter_.exclude == []
        assert filter_.case_sensitive is False

    def test_custom_values(self) -> None:
        """Test KeywordFilter with custom values."""
        filter_ = KeywordFilter(
            include=["python", "rust"],
            exclude=["spam"],
            case_sensitive=True,
        )

        assert filter_.include == ["python", "rust"]
        assert filter_.exclude == ["spam"]
        assert filter_.case_sensitive is True

    def test_partial_values(self) -> None:
        """Test KeywordFilter with partial values."""
        filter_ = KeywordFilter(include=["test"])

        assert filter_.include == ["test"]
        assert filter_.exclude == []
        assert filter_.case_sensitive is False


class TestRegexFilter:
    """Tests for RegexFilter Pydantic model."""

    def test_default_none(self) -> None:
        """Test that RegexFilter defaults to None patterns."""
        filter_ = RegexFilter()

        assert filter_.title is None
        assert filter_.content is None

    def test_custom_patterns(self) -> None:
        """Test RegexFilter with custom patterns."""
        filter_ = RegexFilter(
            title=r"^Test.*$",
            content=r"Python|Rust",
        )

        assert filter_.title == r"^Test.*$"
        assert filter_.content == r"Python|Rust"

    def test_partial_patterns(self) -> None:
        """Test RegexFilter with only title pattern."""
        filter_ = RegexFilter(title=r"test")

        assert filter_.title == r"test"
        assert filter_.content is None


class TestFeedFilters:
    """Tests for FeedFilters Pydantic model."""

    def test_default_empty_filters(self) -> None:
        """Test that FeedFilters creates empty subfilters by default."""
        filters = FeedFilters()

        assert isinstance(filters.keywords, KeywordFilter)
        assert isinstance(filters.categories, KeywordFilter)
        assert isinstance(filters.authors, KeywordFilter)
        assert isinstance(filters.regex, RegexFilter)

    def test_custom_filters(self) -> None:
        """Test FeedFilters with custom subfilters."""
        filters = FeedFilters(
            keywords=KeywordFilter(include=["test"]),
            categories=KeywordFilter(exclude=["spam"]),
        )

        assert filters.keywords.include == ["test"]
        assert filters.categories.exclude == ["spam"]


class TestFeedConfig:
    """Tests for FeedConfig Pydantic model."""

    def test_minimal_feed(self) -> None:
        """Test FeedConfig with only required fields."""
        feed = FeedConfig(
            name="Test Feed",
            url="https://example.com/feed.xml",
        )

        assert feed.name == "Test Feed"
        assert feed.url == "https://example.com/feed.xml"
        assert feed.check_interval is None
        assert feed.enabled is True
        assert feed.cookies is None
        assert feed.media_dir is None
        assert feed.media_all_entries is None
        assert isinstance(feed.filters, FeedFilters)

    def test_full_feed(self) -> None:
        """Test FeedConfig with all fields specified."""
        feed = FeedConfig(
            name="Full Feed",
            url="https://example.com/full.xml",
            check_interval=600,
            enabled=False,
            cookies={"session": "abc123"},
            media_dir="/tmp/media",
            media_all_entries=True,
            filters=FeedFilters(keywords=KeywordFilter(include=["test"])),
        )

        assert feed.name == "Full Feed"
        assert feed.check_interval == 600
        assert feed.enabled is False
        assert feed.cookies == {"session": "abc123"}
        assert feed.media_dir == "/tmp/media"
        assert feed.media_all_entries is True
        assert feed.filters.keywords.include == ["test"]

    def test_feed_with_cookies(self) -> None:
        """Test FeedConfig with cookies dictionary."""
        feed = FeedConfig(
            name="Authenticated Feed",
            url="https://example.com/private.xml",
            cookies={"auth_token": "secret", "session_id": "12345"},
        )

        assert feed.cookies == {"auth_token": "secret", "session_id": "12345"}

    def test_feed_media_dir_empty_string(self) -> None:
        """Test FeedConfig with empty media_dir to disable downloads."""
        feed = FeedConfig(
            name="No Media Feed",
            url="https://example.com/feed.xml",
            media_dir="",
        )

        assert feed.media_dir == ""


class TestTelegramConfig:
    """Tests for TelegramConfig Pydantic model."""

    def test_valid_config(self) -> None:
        """Test TelegramConfig with valid values."""
        config = TelegramConfig(
            bot_token="1234567890:ABCdefGHIjklMNOpqrsTUVwxyz",
            chat_id="-1001234567890",
        )

        assert config.bot_token == "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz"
        assert config.chat_id == "-1001234567890"
        assert config.parse_mode == "HTML"
        assert config.disable_web_page_preview is False

    def test_empty_token_raises(self) -> None:
        """Test that empty bot token raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            TelegramConfig(bot_token="", chat_id="-1001234567890")

        assert "Field cannot be empty" in str(exc_info.value)

    def test_empty_chat_id_raises(self) -> None:
        """Test that empty chat_id raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            TelegramConfig(
                bot_token="1234567890:ABCdefGHIjklMNOpqrsTUVwxyz",
                chat_id="",
            )

        assert "Field cannot be empty" in str(exc_info.value)

    def test_whitespace_only_raises(self) -> None:
        """Test that whitespace-only values raise ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            TelegramConfig(
                bot_token="   ",
                chat_id="-1001234567890",
            )

        assert "Field cannot be empty" in str(exc_info.value)

    def test_custom_parse_mode(self) -> None:
        """Test TelegramConfig with Markdown parse mode."""
        config = TelegramConfig(
            bot_token="1234567890:ABCdefGHIjklMNOpqrsTUVwxyz",
            chat_id="-1001234567890",
            parse_mode="Markdown",
            disable_web_page_preview=True,
        )

        assert config.parse_mode == "Markdown"
        assert config.disable_web_page_preview is True


class TestDefaultsConfig:
    """Tests for DefaultsConfig Pydantic model."""

    def test_default_values(self) -> None:
        """Test DefaultsConfig default values."""
        config = DefaultsConfig()

        assert config.check_interval == 300
        assert config.request_timeout == 30
        assert config.max_retries == 3
        assert config.proxy is None
        assert config.media_dir is None
        assert config.media_all_entries is False

    def test_custom_values(self) -> None:
        """Test DefaultsConfig with custom values."""
        config = DefaultsConfig(
            check_interval=600,
            request_timeout=60,
            max_retries=5,
            proxy="socks5://localhost:1080",
            media_dir="/data/media",
            media_all_entries=True,
        )

        assert config.check_interval == 600
        assert config.request_timeout == 60
        assert config.max_retries == 5
        assert config.proxy == "socks5://localhost:1080"
        assert config.media_dir == "/data/media"
        assert config.media_all_entries is True


class TestStorageConfig:
    """Tests for StorageConfig Pydantic model."""

    def test_default_path(self) -> None:
        """Test StorageConfig default database path."""
        config = StorageConfig()

        assert config.database_path == "data/rss_watcher.db"

    def test_custom_path(self) -> None:
        """Test StorageConfig with custom path."""
        config = StorageConfig(database_path="/custom/path/db.sqlite")

        assert config.database_path == "/custom/path/db.sqlite"


class TestAppConfig:
    """Tests for AppConfig Pydantic model."""

    def test_empty_feeds_raises(self) -> None:
        """Test that AppConfig with empty feeds raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            AppConfig(
                telegram=TelegramConfig(
                    bot_token="1234567890:ABCdefGHIjklMNOpqrsTUVwxyz",
                    chat_id="-1001234567890",
                ),
                feeds=[],
            )

        assert "At least one feed must be configured" in str(exc_info.value)

    def test_minimal_valid(
        self, minimal_telegram_config: TelegramConfig, minimal_feed_config: FeedConfig
    ) -> None:
        """Test minimal valid AppConfig."""
        config = AppConfig(
            telegram=minimal_telegram_config,
            feeds=[minimal_feed_config],
        )

        assert config.telegram == minimal_telegram_config
        assert len(config.feeds) == 1
        assert isinstance(config.defaults, DefaultsConfig)
        assert isinstance(config.storage, StorageConfig)

    def test_full_valid(self, full_config_dict: dict[str, Any]) -> None:
        """Test fully configured AppConfig."""
        config = AppConfig.model_validate(full_config_dict)

        assert config.telegram.bot_token == "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz"
        assert config.defaults.check_interval == 600
        assert config.defaults.proxy == "socks5://localhost:1080"
        assert config.storage.database_path == "data/test.db"
        assert len(config.feeds) == 1

    def test_multiple_feeds(self, minimal_telegram_config: TelegramConfig) -> None:
        """Test AppConfig with multiple feeds."""
        feeds = [
            FeedConfig(name=f"Feed {i}", url=f"https://example.com/feed{i}.xml")
            for i in range(5)
        ]
        config = AppConfig(telegram=minimal_telegram_config, feeds=feeds)

        assert len(config.feeds) == 5


class TestEnvVarSubstitution:
    """Tests for environment variable substitution."""

    def test_simple_substitution(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test simple ${VAR} substitution."""
        monkeypatch.setenv("TEST_VAR", "test_value")

        result = _substitute_env_vars("${TEST_VAR}")

        assert result == "test_value"

    def test_default_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test ${VAR:-default} substitution when var is not set."""
        monkeypatch.delenv("NONEXISTENT_VAR", raising=False)

        result = _substitute_env_vars("${NONEXISTENT_VAR:-default_value}")

        assert result == "default_value"

    def test_default_value_not_used(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test ${VAR:-default} returns var value when set."""
        monkeypatch.setenv("EXISTING_VAR", "existing_value")

        result = _substitute_env_vars("${EXISTING_VAR:-default_value}")

        assert result == "existing_value"

    def test_missing_var_no_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that missing var without default returns original placeholder."""
        monkeypatch.delenv("MISSING_VAR", raising=False)

        result = _substitute_env_vars("${MISSING_VAR}")

        assert result == "${MISSING_VAR}"

    def test_nested_dict(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test substitution in nested dictionary."""
        monkeypatch.setenv("BOT_TOKEN", "secret_token")
        monkeypatch.setenv("CHAT_ID", "-100123")

        data = {
            "telegram": {
                "bot_token": "${BOT_TOKEN}",
                "chat_id": "${CHAT_ID}",
            }
        }

        result = _substitute_env_vars(data)

        assert result["telegram"]["bot_token"] == "secret_token"
        assert result["telegram"]["chat_id"] == "-100123"

    def test_lists(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test substitution in lists."""
        monkeypatch.setenv("URL1", "https://example1.com")
        monkeypatch.setenv("URL2", "https://example2.com")

        data = ["${URL1}", "${URL2}"]

        result = _substitute_env_vars(data)

        assert result == ["https://example1.com", "https://example2.com"]

    def test_non_string_passthrough(self) -> None:
        """Test that non-string values pass through unchanged."""
        data = {"number": 42, "boolean": True, "null": None}

        result = _substitute_env_vars(data)

        assert result == data

    def test_mixed_content(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test substitution in mixed string content."""
        monkeypatch.setenv("HOST", "example.com")

        result = _substitute_env_vars("https://${HOST}/feed.xml")

        assert result == "https://example.com/feed.xml"

    def test_empty_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test ${VAR:-} with empty default."""
        monkeypatch.delenv("EMPTY_DEFAULT_VAR", raising=False)

        result = _substitute_env_vars("${EMPTY_DEFAULT_VAR:-}")

        assert result == ""


class TestLoadConfig:
    """Tests for load_config function."""

    def test_file_not_found(self, tmp_path: Path) -> None:
        """Test that FileNotFoundError is raised for missing file."""
        with pytest.raises(FileNotFoundError) as exc_info:
            load_config(tmp_path / "nonexistent.yaml")

        assert "Configuration file not found" in str(exc_info.value)

    def test_empty_file(self, tmp_path: Path) -> None:
        """Test that ValueError is raised for empty config file."""
        config_file = tmp_path / "empty.yaml"
        config_file.write_text("")

        with pytest.raises(ValueError) as exc_info:
            load_config(config_file)

        assert "empty" in str(exc_info.value).lower()

    def test_invalid_yaml(self, tmp_path: Path) -> None:
        """Test that YAML error is raised for invalid YAML."""
        config_file = tmp_path / "invalid.yaml"
        config_file.write_text("invalid: yaml: content:\n  - bad indent")

        with pytest.raises(Exception):  # yaml.YAMLError
            load_config(config_file)

    def test_valid_config(self, sample_config_path: Path) -> None:
        """Test loading a valid configuration file."""
        config = load_config(sample_config_path)

        assert isinstance(config, AppConfig)
        assert config.telegram.bot_token == "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz"
        assert len(config.feeds) == 2
        assert config.feeds[0].name == "Test Feed"

    def test_config_with_env_vars(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test loading config with environment variable substitution."""
        monkeypatch.setenv("TEST_BOT_TOKEN", "env_token_123")
        monkeypatch.setenv("TEST_CHAT_ID", "-100999")

        config_content = """
telegram:
  bot_token: "${TEST_BOT_TOKEN}"
  chat_id: "${TEST_CHAT_ID}"
feeds:
  - name: "Test"
    url: "https://example.com/feed.xml"
"""
        config_file = tmp_path / "env_config.yaml"
        config_file.write_text(config_content)

        config = load_config(config_file)

        assert config.telegram.bot_token == "env_token_123"
        assert config.telegram.chat_id == "-100999"

    def test_config_path_as_string(self, sample_config_path: Path) -> None:
        """Test loading config with string path."""
        config = load_config(str(sample_config_path))

        assert isinstance(config, AppConfig)

    def test_validation_error_on_invalid_config(self, tmp_path: Path) -> None:
        """Test that ValidationError is raised for invalid config structure."""
        config_content = """
telegram:
  bot_token: ""
  chat_id: "-100"
feeds:
  - name: "Test"
    url: "https://example.com/feed.xml"
"""
        config_file = tmp_path / "invalid_token.yaml"
        config_file.write_text(config_content)

        with pytest.raises(ValidationError):
            load_config(config_file)
