# PlexPreferCHTSubs

> **[中文版 README](README.zh-TW.md)**

**Automatically set Traditional Chinese (繁體中文) as the preferred subtitle in Plex.**

---

## Why?

Plex treats Chinese subtitles as a single language and often defaults to Simplified Chinese when multiple Chinese subtitle tracks are available. There is no built-in way to prefer Traditional Chinese.

This tool scans your Plex library, identifies Traditional Chinese subtitle tracks using a multi-layered scoring system, and sets them as the default.

## Features

- **Smart CHT/CHS detection** — Multi-layered scoring: title regex, language metadata, and character frequency analysis
- **Content analysis** — For unlabeled Chinese subtitles (just "中文"), downloads and analyzes subtitle text to distinguish Traditional from Simplified using 90 character pairs
- **External subtitle preference** — Prioritizes external subtitle files (.srt/.ass) over embedded MKV tracks
- **Real-time watcher** — WebSocket listener detects new/updated media instantly (no Plex Pass required)
- **Configurable fallback** — When no CHT subtitle is found: accept CHS, use English, skip, or disable
- **Multi-threaded scanning** — Process large libraries quickly with parallel workers
- **Dry-run mode** — Preview all changes before applying
- **Flexible config** — CLI arguments, environment variables, or YAML config file
- **Web UI dashboard** — Browser-based status monitoring and manual scan trigger
- **Docker-ready** — One-shot container or persistent service with cron + watcher + web UI

## Quick Start

### Option A: Standalone exe (Windows)

Download `plexchtsubs.exe` from [Releases](https://github.com/TubeBoyJimmy/PlexPreferCHTSubs/releases). No Python installation required.

```bash
# Place config.yaml in the same directory as the exe, then:
plexchtsubs.exe --dry-run
plexchtsubs.exe --help
```

### Option B: Python

```bash
git clone https://github.com/TubeBoyJimmy/PlexPreferCHTSubs.git
cd PlexPreferCHTSubs
pip install -r requirements.txt
python run.py --help
```

### Configure

Copy `config.example.yaml` to `config.yaml` and fill in your Plex URL and token:

```yaml
plex:
  url: "http://localhost:32400"
  token: "your-token-here"       # https://www.plexopedia.com/plex-media-server/general/plex-token/

scan:
  range_days: 30                 # Scan items updated within N days (null = full scan)
  fallback: chs                  # chs | english | skip | none
  force_overwrite: false

workers: 8

schedule:
  enabled: false
  cron: "0 3 * * 0"             # Weekly Sunday 03:00

watch:
  enabled: false
  debounce: 5.0                  # Seconds to batch events before processing

web:
  enabled: false
  port: 9527
  # username: "admin"            # Uncomment to enable Basic Auth
  # password: "changeme"
```

Config priority: **CLI args > Environment variables > config.yaml > defaults**

### Run

```bash
# Dry run — preview changes without applying
python run.py --dry-run

# Apply changes (scan recent 30 days, per config default)
python run.py

# Full scan with fallback to English
python run.py --scan-range 0 --fallback english

# Force re-evaluate all items (even already-set ones)
python run.py --force
```

## How Detection Works

Each subtitle track receives a confidence score. The highest-scoring CHT track is selected.

### Scoring Table

| Score | Source | Meaning |
|------:|--------|---------|
| +100 | Title regex | Definite CHT — title contains keywords (see below) |
| +95 | Language code | CHT by code: `zh-tw`, `zh-hant` |
| +90 | Language description | CHT by description: "Traditional", "Taiwan", "Hong Kong" |
| +85 | Content analysis | CHT detected by character frequency (>=70% Traditional characters) |
| +10 | Generic Chinese | Unknown variant (code is `chi`/`zho` with no variant info) — triggers fallback |
| 0 | Non-Chinese | Not Chinese at all |
| -100 | CHS detected | Definite Simplified Chinese (by title, code, description, or content) |

### Title Keywords

| Category | Keywords |
|----------|----------|
| CHT | `CHT`, `TC`, `JPTC`, `繁體`, `繁体`, `繁中`, `繁日`, `繁英`, `正體`, `正体`, `Traditional`, `BIG5`, `fanti`, `zh-Hant`, `zh-TW`, `Taiwan`, `台灣`, `台湾`, `Hong Kong`, `香港`, `HK` |
| CHS | `CHS`, `SC`, `JPSC`, `简体`, `简中`, `簡體`, `简日`, `简英`, `Simplified`, `jianti`, `zh-Hans`, `zh-CN`, `GB2312`, `GBK` |

### Modifiers

| Modifier | Effect | Reason |
|----------|--------|--------|
| Forced subtitle | -50 penalty | Avoid forced/SDH tracks with only essential dialogue |
| External subtitle file | +2 bonus | Prefer external .srt/.ass over embedded MKV tracks |

### Selection Logic

1. **CHT by category** — any track classified as CHT is selected (highest score wins among multiple CHT)
2. **"Second Generic" heuristic** — when 2+ unknown Chinese tracks exist with no metadata, pick the second by stream order (common MKV convention: CHS first, CHT second). External subtitles with higher scores take priority.
3. **Fallback** — if no CHT found, apply the configured fallback strategy

### Content Analysis

When a Chinese subtitle has no clear CHT/CHS indicator in its metadata, the tool downloads a sample of the subtitle text and counts Traditional vs Simplified character usage using 90 high-frequency character pairs (e.g., 們/们, 這/这, 會/会).

- **>=70% Traditional** → CHT (score 85)
- **<=30% Traditional** → CHS (score -100)
- **30-70%** → ambiguous, triggers fallback
- Skips image-based subtitles (PGS, VobSub)
- Supports UTF-8, UTF-16, Big5, GB18030 encoding
- Downloads at most 50KB per subtitle — fast and lightweight

## Fallback Strategies

| `--fallback` | Behavior |
|---|---|
| `chs` (default) | Accept Simplified Chinese — at least it's Chinese |
| `english` | Fall back to English subtitles |
| `skip` | Don't change — keep Plex's current setting |
| `none` | Disable subtitles |

## CLI Options

```
Connection:
  --plex-url URL          Plex server URL (default: http://localhost:32400)
  --plex-token TOKEN      Plex authentication token
  --config FILE           Path to config.yaml

Scan:
  --scan-range DAYS       Scan items updated within N days (0 = full scan)
  --fallback STRATEGY     When no CHT found: chs | english | skip | none (default: chs)
  --force                 Force overwrite existing subtitle selections
  --workers N             Parallel threads (default: 8)

Schedule:
  --schedule              Run as a persistent service with cron scheduling
  --cron EXPR             Cron expression (default: "0 3 * * 0", weekly Sun 3AM)

Watch:
  --watch                 Enable real-time watcher via WebSocket
  --no-watch              Disable watcher (even if --schedule is used)
  --watch-debounce SECS   Batch delay before processing (default: 5.0)

Web UI:
  --web                   Enable web UI dashboard (default port: 9527)
  --web-port PORT         Web UI port (default: 9527)

Output:
  --dry-run               Preview changes without applying
  --log-file PATH         Write logs to file
  -v, --verbose           Verbose output
```

## Watch Mode

Watch mode uses Plex's WebSocket Alert Listener to detect media changes in real-time. When new media is added or updated, the watcher processes only the affected items — no full scan needed. **Does not require Plex Pass.**

Events are debounced (default 5 seconds) to batch rapid changes — e.g., importing a full season triggers a single batch instead of per-episode processing.

```bash
# Watch only (no cron)
python run.py --watch --dry-run

# Schedule + watch (recommended for persistent service)
# --schedule automatically enables --watch unless --no-watch is specified
python run.py --schedule

# Schedule only, disable watcher
python run.py --schedule --no-watch
```

Auto-reconnect: if the WebSocket connection drops, the watcher reconnects with exponential backoff (2s → 4s → 8s → ... up to 5 minutes).

## Web UI

A browser-based dashboard for remote monitoring and manual scan triggering. Useful when running as a Docker service on a NAS.

```bash
# Web UI only
python run.py --web

# Web UI + schedule + watcher (full service mode)
python run.py --schedule --web

# Custom port
python run.py --web --web-port 3000
```

Open `http://your-server:9527` in a browser to access the dashboard.

Features:
- Real-time status display (Plex connection, watcher, scan progress)
- One-click manual scan with dry-run option
- Scan history with statistics
- Current configuration overview
- Optional Basic Auth (set `web.username` and `web.password` in config)

## Docker

### One-shot scan

```bash
docker compose run --rm plexchtsubs --dry-run
```

### Service mode

```bash
# Start service (real-time watcher + web UI dashboard)
docker compose up -d

# View logs
docker compose logs -f

# Stop
docker compose down
```

The default Docker Compose command runs `--watch --web`: real-time watcher for instant subtitle processing on new media, plus a web dashboard at port 9527 for monitoring and manual scans. Add `--schedule` to also enable periodic cron scans.

### Build from source

```bash
docker build -t plexchtsubs .
```

### Remote deployment (NAS, etc.)

```bash
# On build machine
docker build -t plexchtsubs .
docker save plexchtsubs -o plexchtsubs.tar

# Copy plexchtsubs.tar, docker-compose.yml, config.yaml to target machine

# On target machine
sudo docker load < plexchtsubs.tar
sudo docker compose up -d
sudo docker compose logs -f
```

## Environment Variables

All config options can be set via environment variables (useful for Docker):

| Variable | Description |
|----------|-------------|
| `PLEX_URL` | Plex server URL |
| `PLEX_TOKEN` | Plex authentication token |
| `SCAN_RANGE` | Days to scan (0 = full) |
| `FALLBACK` | Fallback strategy |
| `WORKERS` | Parallel threads |
| `DRY_RUN` | `true` for preview mode |
| `SCHEDULE_ENABLED` | `true` for service mode |
| `SCHEDULE_CRON` | Cron expression |
| `WATCH_ENABLED` | `true` for real-time watcher |
| `WATCH_DEBOUNCE` | Debounce seconds |
| `WEB_ENABLED` | `true` for web UI dashboard |
| `WEB_HOST` | Web UI bind address (default: `0.0.0.0`) |
| `WEB_PORT` | Web UI port (default: `9527`) |
| `WEB_USERNAME` | Basic Auth username (empty = no auth) |
| `WEB_PASSWORD` | Basic Auth password |

## Attribution

Inspired by [PlexPreferNonForcedSubs](https://github.com/RileyXX/PlexPreferNonForcedSubs) by RileyXX (MIT License).

## License

[MIT](LICENSE)
