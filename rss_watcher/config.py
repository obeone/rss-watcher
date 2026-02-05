"""
Configuration management for RSS Watcher.

Handles loading and validation of YAML configuration files
with support for environment variable substitution.
"""

import logging
import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

logger = logging.getLogger(__name__)


class KeywordFilter(BaseModel):
    """
    Keyword-based filtering configuration.

    Attributes
    ----------
    include : list[str]
        Keywords that must be present (OR logic).
    exclude : list[str]
        Keywords that must not be present.
    case_sensitive : bool
        Whether matching is case-sensitive.
    """

    include: list[str] = Field(default_factory=list)
    exclude: list[str] = Field(default_factory=list)
    case_sensitive: bool = False


class RegexFilter(BaseModel):
    """
    Regex-based filtering configuration.

    Attributes
    ----------
    title : str | None
        Regex pattern to match against entry title.
    content : str | None
        Regex pattern to match against entry content.
    """

    title: str | None = None
    content: str | None = None


class FeedFilters(BaseModel):
    """
    Combined filters for a feed.

    Attributes
    ----------
    keywords : KeywordFilter
        Keyword-based filters for title and content.
    categories : KeywordFilter
        Category/tag-based filters.
    authors : KeywordFilter
        Author-based filters.
    regex : RegexFilter
        Regex-based filters.
    """

    keywords: KeywordFilter = Field(default_factory=KeywordFilter)
    categories: KeywordFilter = Field(default_factory=KeywordFilter)
    authors: KeywordFilter = Field(default_factory=KeywordFilter)
    regex: RegexFilter = Field(default_factory=RegexFilter)


class FeedConfig(BaseModel):
    """
    Configuration for a single RSS feed.

    Attributes
    ----------
    name : str
        Human-readable name for the feed.
    url : str
        URL of the RSS/Atom feed.
    check_interval : int | None
        Override for check interval in seconds.
    filters : FeedFilters
        Filtering rules for this feed.
    enabled : bool
        Whether this feed is active.
    cookies : dict[str, str] | None
        Optional cookies to send with HTTP requests.
    media_dir : str | None
        Override for media download directory. Set to empty string to disable.
    media_all_entries : bool | None
        Override for downloading media from all entries vs filtered only.
    """

    name: str
    url: str
    check_interval: int | None = None
    filters: FeedFilters = Field(default_factory=FeedFilters)
    enabled: bool = True
    cookies: dict[str, str] | None = None
    media_dir: str | None = None
    media_all_entries: bool | None = None


class TelegramConfig(BaseModel):
    """
    Telegram bot configuration.

    Attributes
    ----------
    bot_token : str
        Telegram Bot API token.
    chat_id : str
        Target chat ID for notifications.
    parse_mode : str
        Message parse mode (HTML or Markdown).
    disable_web_page_preview : bool
        Whether to disable link previews.
    """

    bot_token: str
    chat_id: str
    parse_mode: str = "HTML"
    disable_web_page_preview: bool = False

    @field_validator("bot_token", "chat_id")
    @classmethod
    def check_not_empty(cls, v: str) -> str:
        """Validate that required fields are not empty."""
        if not v or not v.strip():
            raise ValueError("Field cannot be empty")
        return v


class SimpleXConfig(BaseModel):
    """
    SimpleX Chat notification configuration.

    Requires the simplex-chat CLI to be running externally with WebSocket
    server enabled (e.g., simplex-chat -p 5225).

    Attributes
    ----------
    websocket_url : str
        WebSocket URL for the simplex-chat CLI server.
    contact : str
        Name of the SimpleX contact to send messages to.
        Must be a pre-established contact in the simplex-chat client.
    connect_timeout : int
        Timeout in seconds for establishing WebSocket connection.
    message_timeout : int
        Timeout in seconds for waiting for message acknowledgment.
    """

    websocket_url: str = "ws://localhost:5225"
    contact: str
    connect_timeout: int = 10
    message_timeout: int = 30

    @field_validator("contact")
    @classmethod
    def check_contact_not_empty(cls, v: str) -> str:
        """Validate that contact name is not empty."""
        if not v or not v.strip():
            raise ValueError("Contact name cannot be empty")
        return v


class DefaultsConfig(BaseModel):
    """
    Default settings for all feeds.

    Attributes
    ----------
    check_interval : int
        Default interval between feed checks in seconds.
    request_timeout : int
        HTTP request timeout in seconds.
    max_retries : int
        Maximum number of retries for failed requests.
    proxy : str | None
        Optional SOCKS proxy URL (e.g., socks5://user:pass@host:port).
    media_dir : str | None
        Directory to save downloaded media files. None disables media download.
    media_all_entries : bool
        If True, download media from all entries, not just filtered ones.
    """

    check_interval: int = 300
    request_timeout: int = 30
    max_retries: int = 3
    proxy: str | None = None
    media_dir: str | None = None
    media_all_entries: bool = False


class StorageConfig(BaseModel):
    """
    Storage configuration for persistence.

    Attributes
    ----------
    database_path : str
        Path to SQLite database file.
    """

    database_path: str = "data/rss_watcher.db"


class AppConfig(BaseModel):
    """
    Root application configuration.

    Attributes
    ----------
    telegram : TelegramConfig | None
        Telegram bot settings (optional if simplex is configured).
    simplex : SimpleXConfig | None
        SimpleX Chat settings (optional if telegram is configured).
    defaults : DefaultsConfig
        Default settings for feeds.
    storage : StorageConfig
        Storage settings.
    feeds : list[FeedConfig]
        List of RSS feeds to monitor.
    """

    telegram: TelegramConfig | None = None
    simplex: SimpleXConfig | None = None
    defaults: DefaultsConfig = Field(default_factory=DefaultsConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    feeds: list[FeedConfig] = Field(default_factory=list)

    @field_validator("feeds")
    @classmethod
    def check_feeds_not_empty(cls, v: list[FeedConfig]) -> list[FeedConfig]:
        """Validate that at least one feed is configured."""
        if not v:
            raise ValueError("At least one feed must be configured")
        return v

    @model_validator(mode="after")
    def check_at_least_one_notifier(self) -> "AppConfig":
        """Validate that at least one notifier is configured."""
        if self.telegram is None and self.simplex is None:
            raise ValueError(
                "At least one notifier must be configured (telegram or simplex)"
            )
        return self


def _substitute_env_vars(value: Any) -> Any:
    """
    Recursively substitute environment variables in configuration values.

    Supports ${VAR_NAME} and ${VAR_NAME:-default} syntax.

    Parameters
    ----------
    value : Any
        The value to process.

    Returns
    -------
    Any
        The value with environment variables substituted.
    """
    if isinstance(value, str):
        # Pattern matches ${VAR} or ${VAR:-default}
        pattern = r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}"

        def replacer(match: re.Match) -> str:
            var_name = match.group(1)
            default = match.group(2)
            env_value = os.environ.get(var_name)
            if env_value is not None:
                return env_value
            if default is not None:
                return default
            logger.warning(
                "Environment variable '%s' not set and no default provided",
                var_name,
            )
            return match.group(0)

        return re.sub(pattern, replacer, value)
    elif isinstance(value, dict):
        return {k: _substitute_env_vars(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_substitute_env_vars(item) for item in value]
    return value


def load_config(config_path: str | Path) -> AppConfig:
    """
    Load and validate configuration from a YAML file.

    Parameters
    ----------
    config_path : str | Path
        Path to the YAML configuration file.

    Returns
    -------
    AppConfig
        Validated application configuration.

    Raises
    ------
    FileNotFoundError
        If the configuration file does not exist.
    yaml.YAMLError
        If the YAML is invalid.
    pydantic.ValidationError
        If the configuration is invalid.
    """
    config_path = Path(config_path)

    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    logger.info("Loading configuration from %s", config_path)

    with open(config_path, encoding="utf-8") as f:
        raw_config = yaml.safe_load(f)

    if raw_config is None:
        raise ValueError("Configuration file is empty")

    # Substitute environment variables
    processed_config = _substitute_env_vars(raw_config)

    # Validate and return
    config = AppConfig.model_validate(processed_config)

    logger.info(
        "Configuration loaded successfully: %d feed(s) configured",
        len(config.feeds),
    )

    return config
