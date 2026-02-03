# 📡 RSS Watcher

> Monitor RSS/Atom feeds and receive Telegram notifications with advanced filtering

![Python 3.11+](https://img.shields.io/badge/python-3.11+-3776ab?style=flat-square&logo=python&logoColor=white)
![Docker Ready](https://img.shields.io/badge/docker-ready-2496ed?style=flat-square&logo=docker&logoColor=white)
![Telegram Bot](https://img.shields.io/badge/telegram-bot-26a5e4?style=flat-square&logo=telegram&logoColor=white)
![MIT License](https://img.shields.io/badge/license-MIT-green?style=flat-square)
![Async Powered](https://img.shields.io/badge/async-powered-ff6b6b?style=flat-square)

---

## ✨ Features

| Feature                | Description                                                          |
| ---------------------- | -------------------------------------------------------------------- |
| 📡 **Multiple Feeds**  | Monitor unlimited RSS/Atom feeds simultaneously                      |
| 🔍 **Smart Filtering** | Keywords, categories, authors, and regex patterns with AND/OR logic  |
| 📱 **Telegram Alerts** | Beautifully formatted notifications via Telegram bot                 |
| 💾 **Persistence**     | SQLite storage prevents duplicates across restarts                   |
| 🐳 **Docker Ready**    | One-command deployment with docker compose                           |
| 🎬 **Media Download**  | Automatically download videos from feed entries                      |
| 🌐 **Proxy Support**   | SOCKS4/5 and HTTP proxy for all requests                             |
| 🍪 **Auth Cookies**    | Per-feed cookie support for authenticated feeds                      |
| ⚙️ **Configurable**    | YAML config with environment variable substitution                   |

---

## 🚀 Quick Start

### Prerequisites

- **Python 3.11+** (local) or **Docker** (containerized)
- **Telegram Bot** token from [@BotFather](https://t.me/BotFather)
- **Chat ID** from [@userinfobot](https://t.me/userinfobot)

### 🐳 Docker (Recommended)

Pre-built images are available on [GitHub Container Registry](https://ghcr.io/obeone/rss-watcher) and [Docker Hub](https://hub.docker.com/r/obeoneorg/rss-watcher).

```bash
# Clone and configure
git clone https://github.com/obeone/rss-watcher.git
cd rss-watcher
cp config.example.yaml config.yaml
cp .env.example .env

# Edit .env with your Telegram credentials
# TELEGRAM_BOT_TOKEN=your_bot_token
# TELEGRAM_CHAT_ID=your_chat_id

# Launch (uses pre-built image)
docker compose up -d

# Or build locally
docker compose up -d --build
```

**Available images:**

- `ghcr.io/obeone/rss-watcher:latest` (recommended)
- `obeoneorg/rss-watcher:latest` (Docker Hub mirror)

### 🐍 Local Installation

```bash
# Clone and setup
git clone https://github.com/obeone/rss-watcher.git
cd rss-watcher

# Create environment with uv
uv venv && source .venv/bin/activate
uv pip install .

# Configure
cp config.example.yaml config.yaml
export TELEGRAM_BOT_TOKEN="your_bot_token"
export TELEGRAM_CHAT_ID="your_chat_id"

# Run
rss-watcher -c config.yaml
```

---

## ⚙️ Configuration

Configuration uses YAML with environment variable substitution (`${VAR}` or `${VAR:-default}`).

### 📋 Basic Structure

```yaml
telegram:
  bot_token: "${TELEGRAM_BOT_TOKEN}"
  chat_id: "${TELEGRAM_CHAT_ID}"
  parse_mode: "HTML"  # or "Markdown"

defaults:
  check_interval: 300  # seconds between checks
  request_timeout: 30
  max_retries: 3
  proxy: "socks5://user:pass@proxy:1080"  # optional
  media_dir: "media"  # optional, for video downloads

storage:
  database_path: "data/rss_watcher.db"

feeds:
  - name: "Tech News"
    url: "https://example.com/feed.xml"
    check_interval: 600  # override default
    filters:
      keywords:
        include: ["python", "rust"]
```

### 🔍 Filter Options

All filters combine with **AND** logic (all must pass). Within each filter, include rules use **OR** logic (any match passes).

#### 📝 Keywords Filter

Filter by words in title/content:

```yaml
filters:
  keywords:
    include: ["python", "rust"]  # Match if contains ANY
    exclude: ["spam", "ad"]      # Reject if contains ANY
    case_sensitive: false
```

#### 🏷️ Categories Filter

Filter by RSS categories/tags:

```yaml
filters:
  categories:
    include: ["tech", "programming"]
    exclude: ["offtopic"]
    case_sensitive: false
```

#### 👤 Authors Filter

Filter by author name:

```yaml
filters:
  authors:
    include: ["john", "jane"]
    exclude: ["bot"]
    case_sensitive: false
```

#### 🔤 Regex Filter

Filter using regular expressions:

```yaml
filters:
  regex:
    title: "^\\[IMPORTANT\\]"      # Match title pattern
    content: "release.*v[0-9]+"    # Match content pattern
```

### 🌐 Proxy Configuration

Route all requests through a proxy server:

```yaml
defaults:
  proxy: "socks5://user:pass@proxy.example.com:1080"
```

> **Supported protocols:** `socks4://`, `socks5://`, `http://`
>
> Applies to both RSS fetching and Telegram API requests.

### 🍪 Cookie Authentication

For feeds requiring authentication:

```yaml
feeds:
  - name: "Private Feed"
    url: "https://example.com/private-feed.xml"
    cookies:
      session_id: "${RSS_SESSION_ID}"
      auth_token: "your-auth-token"
```

### 🎬 Media Downloads

Automatically download videos from feed entries:

```yaml
defaults:
  media_dir: "media"  # Global default

feeds:
  - name: "Video Feed"
    url: "https://example.com/videos.xml"
    media_dir: "videos/special"  # Override per feed
    media_all_entries: true      # Download from all entries, not just filtered
```

> Videos are extracted from HTML `<video>` tags, RSS enclosures, and Media RSS extensions.

---

## 📖 Usage

### Command Line

```text
rss-watcher [-h] [-c CONFIG] [-v]

Options:
  -h, --help            Show help message
  -c, --config CONFIG   Config file path (default: config.yaml)
  -v, --verbose         Enable debug logging
```

### Docker Commands

| Command                        | Description         |
| ------------------------------ | ------------------- |
| `docker compose up -d`         | Start service       |
| `docker compose logs -f`       | View live logs      |
| `docker compose down`          | Stop service        |
| `docker compose up -d --build` | Rebuild and restart |

### 📬 Message Format

Notifications are sent in HTML format:

```text
[Feed Name]
📰 Entry Title (linked)
👤 by Author Name
🏷️ #tag1 #tag2

Entry summary/content...
```

---

## 🛠️ Development

### Setup

```bash
uv venv && source .venv/bin/activate
uv pip install -e ".[dev]"
```

### Commands

| Task             | Command                          |
| ---------------- | -------------------------------- |
| Run tests        | `pytest`                         |
| Single test file | `pytest tests/test_filters.py -v`|
| Lint code        | `ruff check .`                   |
| Format code      | `ruff format .`                  |

### Architecture

```mermaid
flowchart TB
    A[config.yaml] --> B[RSSWatcher.start]

    B --> F1[Feed 1]
    B --> F2[Feed 2]
    B --> FN[Feed N]

    F1 & F2 & FN --> P1[Fetch]
    P1 --> P2[Filter]
    P2 --> P3[Dedupe]
    P3 --> P4[Download Media]
    P4 --> P5[Telegram Notify]
```

---

## 📄 License

MIT License - see [LICENSE](LICENSE) for details.

---

Made with ❤️ by [Grégoire Compagnon](mailto:obeone@obeone.org)
