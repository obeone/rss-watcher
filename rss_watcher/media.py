"""
Media download module for RSS Watcher.

Handles extraction and downloading of video files from RSS entry content.
"""

import logging
import re
import ssl
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse

import aiohttp
from aiohttp_socks import ProxyConnector

from rss_watcher.filters import RSSEntry

logger = logging.getLogger(__name__)

# Allowed URL schemes for media downloads (SSRF protection)
ALLOWED_URL_SCHEMES = frozenset({"http", "https"})

# Video MIME types to match in enclosures
VIDEO_MIME_TYPES = frozenset(
    {
        "video/mp4",
        "video/webm",
        "video/ogg",
        "video/quicktime",
        "video/x-msvideo",
        "video/x-matroska",
        "video/mpeg",
        "video/3gpp",
        "video/x-flv",
    }
)

# Regex patterns for extracting video URLs from HTML content
VIDEO_SRC_PATTERN = re.compile(
    r'<video[^>]*\ssrc=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
SOURCE_SRC_PATTERN = re.compile(
    r'<source[^>]*\ssrc=["\']([^"\']+)["\']',
    re.IGNORECASE,
)


def redact_proxy_url(proxy_url: str) -> str:
    """
    Redact credentials from a proxy URL for safe logging.

    Parameters
    ----------
    proxy_url : str
        The proxy URL potentially containing credentials.

    Returns
    -------
    str
        The proxy URL with password redacted.
    """
    try:
        parsed = urlparse(proxy_url)
        if parsed.password:
            # Reconstruct URL with redacted password
            netloc = parsed.hostname or ""
            if parsed.port:
                netloc = f"{netloc}:{parsed.port}"
            if parsed.username:
                netloc = f"{parsed.username}:****@{netloc}"
            return f"{parsed.scheme}://{netloc}{parsed.path}"
        return proxy_url
    except Exception:
        # Fallback: return a generic message if parsing fails
        return "<proxy url>"


class MediaDownloader:
    """
    Downloads media files (videos) from RSS entries.

    Extracts video URLs from HTML content, RSS enclosures, and Media RSS
    extensions, then downloads them to a local directory.
    """

    def __init__(
        self,
        proxy_url: str | None = None,
        timeout: int = 300,
        user_agent: str = "RSS-Watcher/1.0",
        max_download_size: int | None = None,
    ):
        """
        Initialize the media downloader.

        Parameters
        ----------
        proxy_url : str | None
            Optional SOCKS proxy URL (e.g., socks5://user:pass@host:port).
        timeout : int
            HTTP request timeout in seconds for downloads.
        user_agent : str
            User-Agent header for HTTP requests.
        max_download_size : int | None
            Maximum file size in bytes to download. None means no limit.
        """
        self.proxy_url = proxy_url
        self.timeout = timeout
        self.user_agent = user_agent
        self.max_download_size = max_download_size
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create the HTTP session."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.timeout)
            headers = {"User-Agent": self.user_agent}

            # Create explicit SSL context for secure connections
            ssl_context = ssl.create_default_context()

            connector = None
            if self.proxy_url:
                connector = ProxyConnector.from_url(self.proxy_url, ssl=ssl_context)
                logger.debug(
                    "Media downloader using proxy: %s", redact_proxy_url(self.proxy_url)
                )
            else:
                connector = aiohttp.TCPConnector(ssl=ssl_context)

            self._session = aiohttp.ClientSession(
                timeout=timeout, headers=headers, connector=connector
            )
        return self._session

    def _validate_url(self, url: str) -> bool:
        """
        Validate that a URL is safe to fetch (SSRF protection).

        Parameters
        ----------
        url : str
            The URL to validate.

        Returns
        -------
        bool
            True if the URL is safe to fetch, False otherwise.
        """
        try:
            parsed = urlparse(url)
            if parsed.scheme.lower() not in ALLOWED_URL_SCHEMES:
                logger.warning(
                    "Blocked URL with disallowed scheme '%s': %s",
                    parsed.scheme,
                    url[:100],
                )
                return False
            if not parsed.netloc:
                logger.warning("Blocked URL without host: %s", url[:100])
                return False
            return True
        except Exception as e:
            logger.warning("Failed to parse URL '%s': %s", url[:100], e)
            return False

    def _validate_path_within_base(self, base_dir: Path, target_path: Path) -> bool:
        """
        Validate that target_path stays within base_dir (path traversal protection).

        Parameters
        ----------
        base_dir : Path
            The base directory that should contain the target.
        target_path : Path
            The path to validate.

        Returns
        -------
        bool
            True if target_path is within base_dir, False otherwise.
        """
        try:
            resolved_base = base_dir.resolve()
            resolved_target = target_path.resolve()
            # Check if target is relative to base (i.e., contained within it)
            resolved_target.relative_to(resolved_base)
            return True
        except ValueError:
            return False

    def extract_video_urls_from_html(self, html_content: str) -> list[str]:
        """
        Extract video URLs from HTML content.

        Parses HTML to find <video src="..."> and <source src="..."> tags.

        Parameters
        ----------
        html_content : str
            HTML content to parse.

        Returns
        -------
        list[str]
            List of extracted video URLs.
        """
        urls: list[str] = []

        # Find <video src="..."> tags
        for match in VIDEO_SRC_PATTERN.finditer(html_content):
            url = match.group(1)
            if url and url not in urls:
                urls.append(url)

        # Find <source src="..."> tags (inside video elements)
        for match in SOURCE_SRC_PATTERN.finditer(html_content):
            url = match.group(1)
            if url and url not in urls:
                urls.append(url)

        return urls

    def extract_video_urls_from_enclosures(self, raw_entry: dict) -> list[str]:
        """
        Extract video URLs from RSS enclosures and Media RSS extensions.

        Parameters
        ----------
        raw_entry : dict
            Raw feedparser entry dictionary.

        Returns
        -------
        list[str]
            List of extracted video URLs.
        """
        urls: list[str] = []

        # Check enclosures (standard RSS)
        enclosures = raw_entry.get("enclosures", [])
        for enclosure in enclosures:
            mime_type = enclosure.get("type", "").lower()
            href = enclosure.get("href") or enclosure.get("url")
            if (
                href
                and (mime_type.startswith("video/") or mime_type in VIDEO_MIME_TYPES)
                and href not in urls
            ):
                urls.append(href)

        # Check media_content (Media RSS extension)
        media_content = raw_entry.get("media_content", [])
        for media in media_content:
            mime_type = media.get("type", "").lower()
            medium = media.get("medium", "").lower()
            url = media.get("url")
            if (
                url
                and (
                    mime_type.startswith("video/")
                    or mime_type in VIDEO_MIME_TYPES
                    or medium == "video"
                )
                and url not in urls
            ):
                urls.append(url)

        return urls

    def _extract_filename_from_url(self, url: str) -> str:
        """
        Extract a filename from a URL.

        Parameters
        ----------
        url : str
            URL to extract filename from.

        Returns
        -------
        str
            Extracted filename or a generated one.
        """
        parsed = urlparse(url)
        path = unquote(parsed.path)
        filename = Path(path).name

        if not filename or filename == "/":
            # Generate a filename based on URL hash
            filename = f"video_{hash(url) & 0xFFFFFFFF:08x}"

        return filename

    def _sanitize_filename(self, filename: str) -> str:
        """
        Sanitize a filename for safe filesystem use.

        Parameters
        ----------
        filename : str
            Original filename.

        Returns
        -------
        str
            Sanitized filename.
        """
        # Replace problematic characters
        sanitized = re.sub(r'[<>:"/\\|?*]', "_", filename)
        # Remove leading/trailing spaces and dots
        sanitized = sanitized.strip(" .")
        # Limit length
        if len(sanitized) > 200:
            name, ext = Path(sanitized).stem, Path(sanitized).suffix
            sanitized = name[: 200 - len(ext)] + ext
        return sanitized or "video"

    def _sanitize_feed_name(self, feed_name: str) -> str:
        """
        Sanitize a feed name for use as a directory name.

        Parameters
        ----------
        feed_name : str
            Original feed name.

        Returns
        -------
        str
            Sanitized directory name.
        """
        sanitized = re.sub(r'[<>:"/\\|?*]', "_", feed_name)
        sanitized = sanitized.strip(" .")
        return sanitized or "unknown_feed"

    async def download_video(self, url: str, feed_name: str, media_dir: str) -> Path | None:
        """
        Download a video from a URL.

        Parameters
        ----------
        url : str
            URL of the video to download.
        feed_name : str
            Name of the source feed (used for directory organization).
        media_dir : str
            Base directory for saving the downloaded file.

        Returns
        -------
        Path | None
            Path to the downloaded file, or None if download failed.
        """
        # SSRF protection: validate URL scheme
        if not self._validate_url(url):
            return None

        session = await self._get_session()

        # Create feed-specific directory
        base_media_dir = Path(media_dir).resolve()
        safe_feed_name = self._sanitize_feed_name(feed_name)
        feed_dir = base_media_dir / safe_feed_name

        # Path traversal protection: validate feed_dir stays within media_dir
        if not self._validate_path_within_base(base_media_dir, feed_dir):
            logger.error(
                "Path traversal attempt detected: feed_dir '%s' escapes media_dir '%s'",
                feed_dir,
                base_media_dir,
            )
            return None

        feed_dir.mkdir(parents=True, exist_ok=True)

        # Generate timestamped filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        original_filename = self._extract_filename_from_url(url)
        safe_filename = self._sanitize_filename(original_filename)
        final_filename = f"{timestamp}_{safe_filename}"
        file_path = feed_dir / final_filename

        # Path traversal protection: validate file_path stays within feed_dir
        if not self._validate_path_within_base(feed_dir, file_path):
            logger.error(
                "Path traversal attempt detected: file '%s' escapes feed_dir '%s'",
                file_path,
                feed_dir,
            )
            return None

        try:
            logger.debug("Downloading video from %s", url)

            async with session.get(url) as response:
                response.raise_for_status()

                # Check Content-Length for size limit enforcement
                content_length = response.headers.get("Content-Length")
                if content_length and self.max_download_size:
                    try:
                        size = int(content_length)
                        if size > self.max_download_size:
                            logger.warning(
                                "File too large (%d bytes > %d max): %s",
                                size,
                                self.max_download_size,
                                url,
                            )
                            return None
                    except ValueError:
                        pass  # Invalid Content-Length, proceed with streaming check

                # Check if response is actually a video (optional content-type check)
                content_type = response.headers.get("Content-Type", "").lower()
                if content_type and not (
                    content_type.startswith("video/")
                    or content_type.startswith("application/octet-stream")
                    or content_type in VIDEO_MIME_TYPES
                ):
                    logger.warning(
                        "Unexpected content type '%s' for URL %s, downloading anyway",
                        content_type,
                        url,
                    )

                # Stream download to file with size limit check
                downloaded_bytes = 0
                with open(file_path, "wb") as f:
                    async for chunk in response.content.iter_chunked(8192):
                        downloaded_bytes += len(chunk)
                        if (
                            self.max_download_size
                            and downloaded_bytes > self.max_download_size
                        ):
                            logger.warning(
                                "Download exceeded size limit (%d > %d bytes): %s",
                                downloaded_bytes,
                                self.max_download_size,
                                url,
                            )
                            f.close()
                            if file_path.exists():
                                file_path.unlink()
                            return None
                        f.write(chunk)

            file_size = file_path.stat().st_size
            logger.info(
                "Downloaded video: %s (%.2f MB)",
                file_path.name,
                file_size / (1024 * 1024),
            )
            return file_path

        except aiohttp.ClientError as e:
            logger.warning("Failed to download video from %s: %s", url, e)
            # Clean up partial file if it exists
            if file_path.exists():
                file_path.unlink()
            return None
        except OSError as e:
            logger.warning("Failed to save video to %s: %s", file_path, e)
            return None

    async def process_entry(self, entry: RSSEntry, media_dir: str) -> list[Path]:
        """
        Extract and download all videos from an RSS entry.

        Parameters
        ----------
        entry : RSSEntry
            RSS entry to process.
        media_dir : str
            Base directory for saving downloaded files.

        Returns
        -------
        list[Path]
            List of paths to downloaded video files.
        """
        video_urls: list[str] = []

        # Extract from HTML content
        if entry.content:
            html_urls = self.extract_video_urls_from_html(entry.content)
            video_urls.extend(html_urls)
            if html_urls:
                logger.debug(
                    "Found %d video URL(s) in HTML content for '%s'",
                    len(html_urls),
                    entry.title[:50] if entry.title else "untitled",
                )

        # Extract from enclosures and media_content
        if entry.raw:
            enclosure_urls = self.extract_video_urls_from_enclosures(entry.raw)
            for url in enclosure_urls:
                if url not in video_urls:
                    video_urls.append(url)
            if enclosure_urls:
                logger.debug(
                    "Found %d video URL(s) in enclosures for '%s'",
                    len(enclosure_urls),
                    entry.title[:50] if entry.title else "untitled",
                )

        if not video_urls:
            return []

        logger.info(
            "Processing %d video(s) for entry '%s'",
            len(video_urls),
            entry.title[:50] if entry.title else "untitled",
        )

        # Download all videos
        downloaded: list[Path] = []
        for url in video_urls:
            result = await self.download_video(url, entry.feed_name, media_dir)
            if result:
                downloaded.append(result)

        return downloaded

    async def close(self) -> None:
        """Close the HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
            logger.debug("Media downloader session closed")

    async def __aenter__(self) -> "MediaDownloader":
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.close()
