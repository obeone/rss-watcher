# RSS Watcher

Monitor RSS/Atom feeds and receive Telegram notifications for new entries with advanced filtering.

## Features

- **Multiple feeds**: Monitor multiple RSS/Atom feeds simultaneously
- **Advanced filtering**: Filter entries by keywords, categories, authors, and regex patterns
- **Telegram notifications**: Receive formatted notifications via Telegram bot
- **Persistence**: SQLite storage prevents duplicate notifications after restarts
- **Docker support**: Easy deployment with Docker and docker compose
- **Configurable**: YAML configuration with environment variable support
- **Proxy support**: Optional SOCKS/HTTP proxy for all network requests
- **Cookie authentication**: Per-feed cookies for authenticated RSS feeds

## Quick Start

### Prerequisites

- Python 3.11+ (for local installation)
- Docker and docker compose (for containerized deployment)
- Telegram Bot token (get from [@BotFather](https://t.me/BotFather))
- Telegram Chat ID (get from [@userinfobot](https://t.me/userinfobot))

### Installation

#### Using Docker (Recommended)

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/rss-watcher.git
   cd rss-watcher
   ```

2. Create configuration:
   ```bash
   cp config.example.yaml config.yaml
   cp .env.example .env
   ```

3. Edit `.env` with your Telegram credentials:
   ```bash
   TELEGRAM_BOT_TOKEN=your_bot_token_here
   TELEGRAM_CHAT_ID=your_chat_id_here
   ```

4. Edit `config.yaml` with your feeds (see [Configuration](#configuration))

5. Start the service:
   ```bash
   docker compose up -d
   ```

#### Local Installation

1. Clone and setup:
   ```bash
   git clone https://github.com/yourusername/rss-watcher.git
   cd rss-watcher
   ```

2. Create virtual environment with uv:
   ```bash
   uv venv
   source .venv/bin/activate
   uv pip install .
   ```

3. Create and edit configuration:
   ```bash
   cp config.example.yaml config.yaml
   # Edit config.yaml with your settings
   ```

4. Set environment variables:
   ```bash
   export TELEGRAM_BOT_TOKEN="your_bot_token"
   export TELEGRAM_CHAT_ID="your_chat_id"
   ```

5. Run:
   ```bash
   rss-watcher -c config.yaml
   ```

## Configuration

Configuration is done via YAML file with environment variable substitution.

### Basic Structure

```yaml
telegram:
  bot_token: "${TELEGRAM_BOT_TOKEN}"
  chat_id: "${TELEGRAM_CHAT_ID}"
  parse_mode: "HTML"  # or "Markdown"
  disable_web_page_preview: false

defaults:
  check_interval: 300  # seconds
  request_timeout: 30
  max_retries: 3
  proxy: "socks5://user:pass@proxy:1080"  # optional

storage:
  database_path: "data/rss_watcher.db"

feeds:
  - name: "Feed Name"
    url: "https://example.com/feed.xml"
    check_interval: 600  # optional override
    enabled: true
    cookies:  # optional, for authenticated feeds
      session_id: "${SESSION_ID}"
    filters:
      # ... see below
```

### Filter Options

All filters are optional and combinable. All filter types must pass for an entry to be accepted (AND logic). Within each filter type, include rules use OR logic.

#### Keywords Filter

Filter by words in title and content:

```yaml
filters:
  keywords:
    include: ["python", "rust"]  # Include if contains any of these
    exclude: ["spam", "ad"]      # Exclude if contains any of these
    case_sensitive: false        # Default: false
```

#### Categories Filter

Filter by RSS categories/tags:

```yaml
filters:
  categories:
    include: ["tech", "programming"]
    exclude: ["offtopic"]
    case_sensitive: false
```

#### Authors Filter

Filter by author name:

```yaml
filters:
  authors:
    include: ["john", "jane"]
    exclude: ["bot"]
    case_sensitive: false
```

#### Regex Filter

Filter using regular expressions:

```yaml
filters:
  regex:
    title: "^\\[IMPORTANT\\]"      # Match title pattern
    content: "release.*v[0-9]+"    # Match content pattern
```

### Proxy Configuration

Route all HTTP requests through a SOCKS or HTTP proxy:

```yaml
defaults:
  proxy: "socks5://user:pass@proxy.example.com:1080"
```

Supported protocols: `socks4://`, `socks5://`, `http://`

The proxy applies to both RSS feed fetching and Telegram API requests.

### Cookie Authentication

For RSS feeds requiring authentication, configure per-feed cookies:

```yaml
feeds:
  - name: "Private Feed"
    url: "https://example.com/private-feed.xml"
    cookies:
      session_id: "${RSS_SESSION_ID}"
      auth_token: "your-auth-token"
```

Cookies support environment variable substitution for secure credential management.

### Environment Variables

Variables in the format `${VAR_NAME}` or `${VAR_NAME:-default}` are substituted from environment:

```yaml
telegram:
  bot_token: "${TELEGRAM_BOT_TOKEN}"
  chat_id: "${TELEGRAM_CHAT_ID:-12345}"  # With default value
```

## Usage

### Command Line Options

```
rss-watcher [-h] [-c CONFIG] [-v]

Options:
  -h, --help            Show help message
  -c, --config CONFIG   Path to configuration file (default: config.yaml)
  -v, --verbose         Enable verbose (debug) logging
```

### Docker Commands

```bash
# Start service
docker compose up -d

# View logs
docker compose logs -f

# Stop service
docker compose down

# Rebuild after changes
docker compose up -d --build
```

## Message Format

Notifications are sent in HTML format by default:

```
[Feed Name]
Entry Title (linked)
by Author Name
#tag1 #tag2

Entry summary/content...
```

## Development

### Setup

```bash
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"
```

### Running Tests

```bash
pytest
```

### Code Quality

```bash
ruff check .
ruff format .
```

## License

MIT License - see [LICENSE](LICENSE) for details.

## Author

Grégoire Compagnon <obeone@obeone.org>
