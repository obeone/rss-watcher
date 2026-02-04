"""
Unit tests for the filtering module.

Tests cover RSSEntry dataclass creation, EntryFilter logic,
and the filter_entries function.
"""

from typing import Any

import pytest

from rss_watcher.config import FeedFilters, KeywordFilter, RegexFilter
from rss_watcher.filters import (
    EntryFilter,
    RSSEntry,
    filter_entries,
    MAX_REGEX_PATTERN_LENGTH,
)


class TestRSSEntry:
    """Tests for RSSEntry dataclass."""

    def test_default_values(self) -> None:
        """Test RSSEntry default values."""
        entry = RSSEntry()

        assert entry.title == ""
        assert entry.content == ""
        assert entry.link == ""
        assert entry.guid == ""
        assert entry.categories == []
        assert entry.author == ""
        assert entry.published == ""
        assert entry.feed_name == ""
        assert entry.raw == {}

    def test_custom_values(self, sample_rss_entry: RSSEntry) -> None:
        """Test RSSEntry with custom values."""
        assert sample_rss_entry.title == "Test Entry Title"
        assert "Python" in sample_rss_entry.content
        assert sample_rss_entry.link == "https://example.com/test-entry"
        assert sample_rss_entry.guid == "https://example.com/test-entry"
        assert "Technology" in sample_rss_entry.categories
        assert sample_rss_entry.author == "Test Author"
        assert sample_rss_entry.feed_name == "Test Feed"

    def test_from_feedparser_basic(self, feedparser_entry: dict[str, Any]) -> None:
        """Test RSSEntry.from_feedparser with basic entry."""

        class MockEntry(dict):
            """Mock feedparser entry that supports dict() conversion."""

            def __init__(self, data: dict[str, Any]) -> None:
                super().__init__(data)
                self._data = data

            def __getattr__(self, name: str) -> Any:
                if name.startswith("_"):
                    raise AttributeError(name)
                if name in self._data:
                    return self._data[name]
                raise AttributeError(name)

        mock_entry = MockEntry(feedparser_entry)
        entry = RSSEntry.from_feedparser(mock_entry, "Test Feed")

        assert entry.title == "Test Entry"
        assert entry.link == "https://example.com/entry"
        assert entry.guid == "https://example.com/entry"
        assert entry.feed_name == "Test Feed"

    def test_from_feedparser_with_content(self) -> None:
        """Test RSSEntry.from_feedparser extracts content over summary."""

        class MockEntry(dict):
            def __init__(self) -> None:
                data = {"content": [{"value": "Full content here"}], "summary": "Just a summary"}
                super().__init__(data)
                self.content = data["content"]
                self.summary = data["summary"]

        entry = RSSEntry.from_feedparser(MockEntry(), "Feed")
        assert entry.content == "Full content here"

    def test_from_feedparser_summary_fallback(self) -> None:
        """Test RSSEntry.from_feedparser falls back to summary."""

        class MockEntry(dict):
            def __init__(self) -> None:
                data = {"summary": "Summary text"}
                super().__init__(data)
                self.summary = data["summary"]

        entry = RSSEntry.from_feedparser(MockEntry(), "Feed")
        assert entry.content == "Summary text"

    def test_from_feedparser_with_categories(self) -> None:
        """Test RSSEntry.from_feedparser extracts categories from tags."""

        class MockEntry(dict):
            def __init__(self) -> None:
                data = {"tags": [{"term": "Tech"}, {"term": "News"}, {"term": ""}]}
                super().__init__(data)
                self.tags = data["tags"]

        entry = RSSEntry.from_feedparser(MockEntry(), "Feed")
        assert entry.categories == ["Tech", "News"]

    def test_from_feedparser_author_detail(self) -> None:
        """Test RSSEntry.from_feedparser extracts author from author_detail."""

        class MockEntry(dict):
            def __init__(self) -> None:
                data = {"author_detail": {"name": "Detailed Author"}}
                super().__init__(data)
                self.author_detail = data["author_detail"]

        entry = RSSEntry.from_feedparser(MockEntry(), "Feed")
        assert entry.author == "Detailed Author"

    def test_guid_fallback_to_link(self) -> None:
        """Test that guid falls back to link when id is missing."""

        class MockEntry(dict):
            def __init__(self) -> None:
                data = {"id": "", "link": "https://example.com/link"}
                super().__init__(data)

        entry = RSSEntry.from_feedparser(MockEntry(), "Feed")
        assert entry.guid == "https://example.com/link"


class TestEntryFilterKeywords:
    """Tests for EntryFilter keyword filtering."""

    def test_no_keywords_passes(self, sample_rss_entry: RSSEntry) -> None:
        """Test that entry passes with no keyword filters."""
        filters = FeedFilters()
        entry_filter = EntryFilter(filters)

        assert entry_filter.matches(sample_rss_entry) is True

    def test_include_keyword_match(self, sample_rss_entry: RSSEntry) -> None:
        """Test entry passes when include keyword matches."""
        filters = FeedFilters(
            keywords=KeywordFilter(include=["Python"])
        )
        entry_filter = EntryFilter(filters)

        assert entry_filter.matches(sample_rss_entry) is True

    def test_include_keyword_no_match(self, sample_rss_entry: RSSEntry) -> None:
        """Test entry fails when no include keyword matches."""
        filters = FeedFilters(
            keywords=KeywordFilter(include=["JavaScript", "Ruby"])
        )
        entry_filter = EntryFilter(filters)

        assert entry_filter.matches(sample_rss_entry) is False

    def test_exclude_keyword_rejects(self, sample_rss_entry: RSSEntry) -> None:
        """Test entry is rejected when exclude keyword matches."""
        filters = FeedFilters(
            keywords=KeywordFilter(exclude=["Python"])
        )
        entry_filter = EntryFilter(filters)

        assert entry_filter.matches(sample_rss_entry) is False

    def test_case_sensitive_match(self) -> None:
        """Test case-sensitive keyword matching."""
        entry = RSSEntry(title="Python Tutorial", content="")
        filters = FeedFilters(
            keywords=KeywordFilter(include=["python"], case_sensitive=True)
        )
        entry_filter = EntryFilter(filters)

        assert entry_filter.matches(entry) is False

    def test_case_insensitive_match(self) -> None:
        """Test case-insensitive keyword matching."""
        entry = RSSEntry(title="PYTHON Tutorial", content="")
        filters = FeedFilters(
            keywords=KeywordFilter(include=["python"], case_sensitive=False)
        )
        entry_filter = EntryFilter(filters)

        assert entry_filter.matches(entry) is True

    def test_keyword_in_title_and_content(self) -> None:
        """Test keyword matching searches both title and content."""
        entry = RSSEntry(title="Generic Title", content="Talks about Python")
        filters = FeedFilters(
            keywords=KeywordFilter(include=["Python"])
        )
        entry_filter = EntryFilter(filters)

        assert entry_filter.matches(entry) is True

    def test_exclude_takes_precedence(self) -> None:
        """Test that exclude keyword rejects even with matching include."""
        entry = RSSEntry(title="Python spam tutorial", content="")
        filters = FeedFilters(
            keywords=KeywordFilter(include=["Python"], exclude=["spam"])
        )
        entry_filter = EntryFilter(filters)

        assert entry_filter.matches(entry) is False


class TestEntryFilterCategories:
    """Tests for EntryFilter category filtering."""

    def test_no_categories_passes(self, sample_rss_entry: RSSEntry) -> None:
        """Test that entry passes with no category filters."""
        filters = FeedFilters()
        entry_filter = EntryFilter(filters)

        assert entry_filter.matches(sample_rss_entry) is True

    def test_include_category_match(self, sample_rss_entry: RSSEntry) -> None:
        """Test entry passes when include category matches."""
        filters = FeedFilters(
            categories=KeywordFilter(include=["Technology"])
        )
        entry_filter = EntryFilter(filters)

        assert entry_filter.matches(sample_rss_entry) is True

    def test_include_category_no_match(self, sample_rss_entry: RSSEntry) -> None:
        """Test entry fails when no include category matches."""
        filters = FeedFilters(
            categories=KeywordFilter(include=["Sports"])
        )
        entry_filter = EntryFilter(filters)

        assert entry_filter.matches(sample_rss_entry) is False

    def test_exclude_category_rejects(self, sample_rss_entry: RSSEntry) -> None:
        """Test entry is rejected when exclude category matches."""
        filters = FeedFilters(
            categories=KeywordFilter(exclude=["Programming"])
        )
        entry_filter = EntryFilter(filters)

        assert entry_filter.matches(sample_rss_entry) is False

    def test_category_case_insensitive(self) -> None:
        """Test category matching is case-insensitive by default."""
        entry = RSSEntry(categories=["TECHNOLOGY", "NEWS"])
        filters = FeedFilters(
            categories=KeywordFilter(include=["technology"])
        )
        entry_filter = EntryFilter(filters)

        assert entry_filter.matches(entry) is True

    def test_category_case_sensitive(self) -> None:
        """Test category matching with case sensitivity."""
        entry = RSSEntry(categories=["TECHNOLOGY"])
        filters = FeedFilters(
            categories=KeywordFilter(include=["technology"], case_sensitive=True)
        )
        entry_filter = EntryFilter(filters)

        assert entry_filter.matches(entry) is False


class TestEntryFilterAuthors:
    """Tests for EntryFilter author filtering."""

    def test_no_author_filter_passes(self, sample_rss_entry: RSSEntry) -> None:
        """Test that entry passes with no author filters."""
        filters = FeedFilters()
        entry_filter = EntryFilter(filters)

        assert entry_filter.matches(sample_rss_entry) is True

    def test_include_author_partial_match(self) -> None:
        """Test author matching uses partial/contains match."""
        entry = RSSEntry(author="John Doe Smith")
        filters = FeedFilters(
            authors=KeywordFilter(include=["Doe"])
        )
        entry_filter = EntryFilter(filters)

        assert entry_filter.matches(entry) is True

    def test_include_author_no_match(self) -> None:
        """Test entry fails when author not in include list."""
        entry = RSSEntry(author="John Doe")
        filters = FeedFilters(
            authors=KeywordFilter(include=["Jane"])
        )
        entry_filter = EntryFilter(filters)

        assert entry_filter.matches(entry) is False

    def test_exclude_author(self) -> None:
        """Test entry is rejected when author matches exclude."""
        entry = RSSEntry(author="Spammer Bot")
        filters = FeedFilters(
            authors=KeywordFilter(exclude=["spammer"])
        )
        entry_filter = EntryFilter(filters)

        assert entry_filter.matches(entry) is False


class TestEntryFilterRegex:
    """Tests for EntryFilter regex filtering."""

    def test_no_regex_passes(self, sample_rss_entry: RSSEntry) -> None:
        """Test that entry passes with no regex filters."""
        filters = FeedFilters()
        entry_filter = EntryFilter(filters)

        assert entry_filter.matches(sample_rss_entry) is True

    def test_title_regex_match(self) -> None:
        """Test entry passes when title matches regex."""
        entry = RSSEntry(title="[BREAKING] News Alert!")
        filters = FeedFilters(
            regex=RegexFilter(title=r"^\[BREAKING\]")
        )
        entry_filter = EntryFilter(filters)

        assert entry_filter.matches(entry) is True

    def test_title_regex_no_match(self) -> None:
        """Test entry fails when title doesn't match regex."""
        entry = RSSEntry(title="Regular News")
        filters = FeedFilters(
            regex=RegexFilter(title=r"^\[BREAKING\]")
        )
        entry_filter = EntryFilter(filters)

        assert entry_filter.matches(entry) is False

    def test_content_regex_match(self) -> None:
        """Test entry passes when content matches regex."""
        entry = RSSEntry(content="The version is v2.3.1 and stable")
        filters = FeedFilters(
            regex=RegexFilter(content=r"v\d+\.\d+\.\d+")
        )
        entry_filter = EntryFilter(filters)

        assert entry_filter.matches(entry) is True

    def test_content_regex_no_match(self) -> None:
        """Test entry fails when content doesn't match regex."""
        entry = RSSEntry(content="No version number here")
        filters = FeedFilters(
            regex=RegexFilter(content=r"v\d+\.\d+\.\d+")
        )
        entry_filter = EntryFilter(filters)

        assert entry_filter.matches(entry) is False

    def test_invalid_regex_logged_and_skipped(self, caplog: pytest.LogCaptureFixture) -> None:
        """Test that invalid regex is logged but doesn't crash."""
        filters = FeedFilters(
            regex=RegexFilter(title=r"[invalid")  # Missing closing bracket
        )
        entry_filter = EntryFilter(filters)
        entry = RSSEntry(title="Test")

        # Should not crash and entry should pass (invalid regex is skipped)
        result = entry_filter.matches(entry)

        assert "Invalid title regex pattern" in caplog.text
        # When regex is invalid, it's set to None and the check passes
        assert result is True

    def test_regex_case_insensitive(self) -> None:
        """Test regex matching is case-insensitive."""
        entry = RSSEntry(title="PYTHON Tutorial")
        filters = FeedFilters(
            regex=RegexFilter(title=r"python")
        )
        entry_filter = EntryFilter(filters)

        assert entry_filter.matches(entry) is True


class TestEntryFilterCombined:
    """Tests for EntryFilter combined AND logic."""

    def test_all_filters_must_pass_and_logic(self) -> None:
        """Test that all filter types must pass (AND logic)."""
        entry = RSSEntry(
            title="Python Tutorial",
            content="Learn Python programming",
            categories=["Technology"],
            author="Good Author",
        )
        filters = FeedFilters(
            keywords=KeywordFilter(include=["Python"]),
            categories=KeywordFilter(include=["Technology"]),
            authors=KeywordFilter(include=["Good"]),
        )
        entry_filter = EntryFilter(filters)

        assert entry_filter.matches(entry) is True

    def test_one_filter_fails_rejects(self) -> None:
        """Test that failing one filter type rejects entry."""
        entry = RSSEntry(
            title="Python Tutorial",
            content="Learn Python programming",
            categories=["Sports"],  # Wrong category
            author="Good Author",
        )
        filters = FeedFilters(
            keywords=KeywordFilter(include=["Python"]),
            categories=KeywordFilter(include=["Technology"]),  # Won't match
            authors=KeywordFilter(include=["Good"]),
        )
        entry_filter = EntryFilter(filters)

        assert entry_filter.matches(entry) is False

    def test_include_or_logic_within_type(self) -> None:
        """Test that includes within a type use OR logic."""
        entry = RSSEntry(title="Rust Tutorial", content="")
        filters = FeedFilters(
            keywords=KeywordFilter(include=["Python", "Rust", "Go"])
        )
        entry_filter = EntryFilter(filters)

        # Entry contains "Rust", one of the includes, so it passes
        assert entry_filter.matches(entry) is True


class TestFilterEntries:
    """Tests for filter_entries function."""

    def test_empty_list(self) -> None:
        """Test filtering empty list returns empty list."""
        filters = FeedFilters()

        result = filter_entries([], filters)

        assert result == []

    def test_all_entries_pass(self) -> None:
        """Test filtering when all entries pass."""
        entries = [
            RSSEntry(title="Python 1", content=""),
            RSSEntry(title="Python 2", content=""),
        ]
        filters = FeedFilters(keywords=KeywordFilter(include=["Python"]))

        result = filter_entries(entries, filters)

        assert len(result) == 2

    def test_some_entries_pass(self) -> None:
        """Test filtering when some entries pass."""
        entries = [
            RSSEntry(title="Python Tutorial", content=""),
            RSSEntry(title="JavaScript Guide", content=""),
            RSSEntry(title="More Python", content=""),
        ]
        filters = FeedFilters(keywords=KeywordFilter(include=["Python"]))

        result = filter_entries(entries, filters)

        assert len(result) == 2
        assert all("Python" in e.title for e in result)

    def test_no_entries_pass(self) -> None:
        """Test filtering when no entries pass."""
        entries = [
            RSSEntry(title="JavaScript Guide", content=""),
            RSSEntry(title="Ruby Tutorial", content=""),
        ]
        filters = FeedFilters(keywords=KeywordFilter(include=["Python"]))

        result = filter_entries(entries, filters)

        assert result == []

    def test_filter_preserves_order(self) -> None:
        """Test that filtering preserves original entry order."""
        entries = [
            RSSEntry(title="First Python", content="", guid="1"),
            RSSEntry(title="Skip This", content="", guid="2"),
            RSSEntry(title="Second Python", content="", guid="3"),
            RSSEntry(title="Third Python", content="", guid="4"),
        ]
        filters = FeedFilters(keywords=KeywordFilter(include=["Python"]))

        result = filter_entries(entries, filters)

        assert [e.guid for e in result] == ["1", "3", "4"]


class TestReDoSProtection:
    """Tests for ReDoS (regex denial of service) protection."""

    def test_max_pattern_length_enforced(self, caplog: pytest.LogCaptureFixture) -> None:
        """Test that regex patterns exceeding max length are rejected."""
        long_pattern = "a" * (MAX_REGEX_PATTERN_LENGTH + 100)
        filters = FeedFilters(regex=RegexFilter(title=long_pattern))
        entry_filter = EntryFilter(filters)
        entry = RSSEntry(title="test")

        # Pattern should be rejected during compilation
        assert "exceeds max length" in caplog.text
        # Entry should pass since invalid regex is skipped
        assert entry_filter.matches(entry) is True

    def test_valid_length_pattern_accepted(self) -> None:
        """Test that regex patterns within length limit work."""
        valid_pattern = r"test.*pattern"
        filters = FeedFilters(regex=RegexFilter(title=valid_pattern))
        entry_filter = EntryFilter(filters)

        assert entry_filter.matches(RSSEntry(title="test some pattern")) is True
        assert entry_filter.matches(RSSEntry(title="no match here")) is False

    def test_catastrophic_backtracking_pattern(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Test that potentially dangerous regex patterns are handled.

        Note: This test may behave differently on Windows (no SIGALRM).
        The pattern is designed to cause catastrophic backtracking on certain inputs.
        """
        # A pattern known to cause catastrophic backtracking
        # This should either timeout or work but not hang indefinitely
        filters = FeedFilters(regex=RegexFilter(title=r"(a+)+$"))
        entry_filter = EntryFilter(filters)

        # Short input should work fine
        assert entry_filter.matches(RSSEntry(title="aaa")) is True

        # Longer input with non-matching ending might cause issues
        # but should be protected by timeout
        entry = RSSEntry(title="a" * 20 + "!")
        # Should not hang - either matches, doesn't match, or times out
        result = entry_filter.matches(entry)
        # Result doesn't matter, just verify it completes
        assert isinstance(result, bool)

    def test_content_regex_length_enforced(self, caplog: pytest.LogCaptureFixture) -> None:
        """Test that content regex patterns also have length limit."""
        long_pattern = "b" * (MAX_REGEX_PATTERN_LENGTH + 50)
        filters = FeedFilters(regex=RegexFilter(content=long_pattern))
        entry_filter = EntryFilter(filters)

        assert "exceeds max length" in caplog.text
        # Entry passes since regex was rejected
        assert entry_filter.matches(RSSEntry(content="test")) is True
