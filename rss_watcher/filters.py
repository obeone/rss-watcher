"""
Filtering system for RSS entries.

Provides combinable filters for keywords, categories, authors, and regex patterns.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from rss_watcher.config import FeedFilters, KeywordFilter, RegexFilter

logger = logging.getLogger(__name__)


@dataclass
class RSSEntry:
    """
    Normalized RSS/Atom entry for filtering.

    Attributes
    ----------
    title : str
        Entry title.
    content : str
        Entry content/summary.
    link : str
        Entry URL.
    guid : str
        Unique identifier for the entry.
    categories : list[str]
        Entry categories/tags.
    author : str
        Entry author name.
    published : str
        Publication date string.
    feed_name : str
        Name of the source feed.
    raw : dict
        Original feedparser entry data.
    """

    title: str = ""
    content: str = ""
    link: str = ""
    guid: str = ""
    categories: list[str] = field(default_factory=list)
    author: str = ""
    published: str = ""
    feed_name: str = ""
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_feedparser(cls, entry: Any, feed_name: str = "") -> "RSSEntry":
        """
        Create an RSSEntry from a feedparser entry.

        Parameters
        ----------
        entry : Any
            A feedparser entry object.
        feed_name : str
            Name of the source feed.

        Returns
        -------
        RSSEntry
            Normalized entry instance.
        """
        # Extract content, preferring content over summary
        content = ""
        if hasattr(entry, "content") and entry.content:
            content = entry.content[0].get("value", "")
        elif hasattr(entry, "summary"):
            content = entry.summary or ""

        # Extract categories
        categories = []
        if hasattr(entry, "tags"):
            categories = [tag.get("term", "") for tag in entry.tags if tag.get("term")]

        # Extract author
        author = ""
        if hasattr(entry, "author"):
            author = entry.author or ""
        elif hasattr(entry, "author_detail"):
            author = entry.author_detail.get("name", "")

        # Get unique identifier
        guid = entry.get("id", "") or entry.get("link", "")

        return cls(
            title=entry.get("title", ""),
            content=content,
            link=entry.get("link", ""),
            guid=guid,
            categories=categories,
            author=author,
            published=entry.get("published", ""),
            feed_name=feed_name,
            raw=dict(entry),
        )


class EntryFilter:
    """
    Combinable filter for RSS entries.

    Applies keyword, category, author, and regex filters to entries.
    All filter types must pass for an entry to be accepted (AND logic).
    Within each filter type, include rules use OR logic.
    """

    def __init__(self, filters: FeedFilters):
        """
        Initialize the filter with configuration.

        Parameters
        ----------
        filters : FeedFilters
            Filter configuration to apply.
        """
        self.filters = filters
        self._compiled_regex: dict[str, re.Pattern | None] = {}
        self._compile_regex_patterns()

    def _compile_regex_patterns(self) -> None:
        """Compile regex patterns for efficiency."""
        regex = self.filters.regex

        if regex.title:
            try:
                self._compiled_regex["title"] = re.compile(regex.title, re.IGNORECASE)
            except re.error as e:
                logger.error("Invalid title regex pattern '%s': %s", regex.title, e)
                self._compiled_regex["title"] = None

        if regex.content:
            try:
                self._compiled_regex["content"] = re.compile(regex.content, re.IGNORECASE)
            except re.error as e:
                logger.error("Invalid content regex pattern '%s': %s", regex.content, e)
                self._compiled_regex["content"] = None

    def matches(self, entry: RSSEntry) -> bool:
        """
        Check if an entry passes all filters.

        Parameters
        ----------
        entry : RSSEntry
            The entry to check.

        Returns
        -------
        bool
            True if the entry passes all filters.
        """
        checks = [
            self._check_keywords(entry),
            self._check_categories(entry),
            self._check_authors(entry),
            self._check_regex(entry),
        ]

        result = all(checks)

        if result:
            logger.debug("Entry '%s' passed all filters", entry.title[:50])
        else:
            logger.debug("Entry '%s' filtered out", entry.title[:50])

        return result

    def _check_keywords(self, entry: RSSEntry) -> bool:
        """
        Check keyword filters against title and content.

        Parameters
        ----------
        entry : RSSEntry
            The entry to check.

        Returns
        -------
        bool
            True if the entry passes keyword filters.
        """
        keyword_filter = self.filters.keywords

        # If no keywords configured, pass
        if not keyword_filter.include and not keyword_filter.exclude:
            return True

        text = f"{entry.title} {entry.content}"
        if not keyword_filter.case_sensitive:
            text = text.lower()

        # Check exclude keywords first (any match = reject)
        for keyword in keyword_filter.exclude:
            check_keyword = keyword if keyword_filter.case_sensitive else keyword.lower()
            if check_keyword in text:
                logger.debug("Entry rejected: contains excluded keyword '%s'", keyword)
                return False

        # Check include keywords (any match = accept, if configured)
        if keyword_filter.include:
            for keyword in keyword_filter.include:
                check_keyword = keyword if keyword_filter.case_sensitive else keyword.lower()
                if check_keyword in text:
                    return True
            logger.debug("Entry rejected: no included keywords found")
            return False

        return True

    def _check_categories(self, entry: RSSEntry) -> bool:
        """
        Check category filters.

        Parameters
        ----------
        entry : RSSEntry
            The entry to check.

        Returns
        -------
        bool
            True if the entry passes category filters.
        """
        category_filter = self.filters.categories

        # If no category filters configured, pass
        if not category_filter.include and not category_filter.exclude:
            return True

        entry_categories = entry.categories
        if not category_filter.case_sensitive:
            entry_categories = [c.lower() for c in entry_categories]

        # Check exclude categories
        for category in category_filter.exclude:
            check_cat = category if category_filter.case_sensitive else category.lower()
            if check_cat in entry_categories:
                logger.debug("Entry rejected: contains excluded category '%s'", category)
                return False

        # Check include categories
        if category_filter.include:
            for category in category_filter.include:
                check_cat = category if category_filter.case_sensitive else category.lower()
                if check_cat in entry_categories:
                    return True
            logger.debug("Entry rejected: no included categories found")
            return False

        return True

    def _check_authors(self, entry: RSSEntry) -> bool:
        """
        Check author filters.

        Parameters
        ----------
        entry : RSSEntry
            The entry to check.

        Returns
        -------
        bool
            True if the entry passes author filters.
        """
        author_filter = self.filters.authors

        # If no author filters configured, pass
        if not author_filter.include and not author_filter.exclude:
            return True

        author = entry.author
        if not author_filter.case_sensitive:
            author = author.lower()

        # Check exclude authors
        for excluded in author_filter.exclude:
            check_author = excluded if author_filter.case_sensitive else excluded.lower()
            if check_author in author:
                logger.debug("Entry rejected: excluded author '%s'", excluded)
                return False

        # Check include authors
        if author_filter.include:
            for included in author_filter.include:
                check_author = included if author_filter.case_sensitive else included.lower()
                if check_author in author:
                    return True
            logger.debug("Entry rejected: author not in include list")
            return False

        return True

    def _check_regex(self, entry: RSSEntry) -> bool:
        """
        Check regex filters.

        Parameters
        ----------
        entry : RSSEntry
            The entry to check.

        Returns
        -------
        bool
            True if the entry passes regex filters.
        """
        # Check title regex
        if "title" in self._compiled_regex:
            pattern = self._compiled_regex["title"]
            if pattern is not None and not pattern.search(entry.title):
                logger.debug("Entry rejected: title doesn't match regex")
                return False

        # Check content regex
        if "content" in self._compiled_regex:
            pattern = self._compiled_regex["content"]
            if pattern is not None and not pattern.search(entry.content):
                logger.debug("Entry rejected: content doesn't match regex")
                return False

        return True


def filter_entries(entries: list[RSSEntry], filters: FeedFilters) -> list[RSSEntry]:
    """
    Filter a list of entries using the given filters.

    Parameters
    ----------
    entries : list[RSSEntry]
        List of entries to filter.
    filters : FeedFilters
        Filter configuration to apply.

    Returns
    -------
    list[RSSEntry]
        Entries that pass all filters.
    """
    entry_filter = EntryFilter(filters)
    filtered = [entry for entry in entries if entry_filter.matches(entry)]

    logger.info(
        "Filtered %d entries down to %d",
        len(entries),
        len(filtered),
    )

    return filtered
