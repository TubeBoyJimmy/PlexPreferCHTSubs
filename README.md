# PlexPreferCHTSubs

**Automatically set Traditional Chinese (繁體中文) as the preferred subtitle in Plex.**

自動掃描 Plex 媒體庫，將所有影片和劇集的預設字幕設為繁體中文。

---

## Why? / 為什麼需要這個工具？

Plex treats Chinese subtitles as a single language and often defaults to Simplified Chinese (簡體中文) when multiple Chinese subtitle tracks are available. There is no built-in way to prefer Traditional Chinese.

Plex 將中文字幕視為單一語言，當媒體檔案同時包含繁體和簡體字幕時，往往預設選擇簡體中文。Plex 沒有內建的方式讓使用者偏好繁體中文字幕。

This tool scans your Plex library, identifies Traditional Chinese subtitle tracks using a smart scoring system, and sets them as the default.

此工具掃描你的 Plex 媒體庫，透過智慧評分系統辨識繁體中文字幕軌，並將其設為預設。

## Features / 功能

- **Smart CHT/CHS detection** — Regex + language metadata scoring to distinguish 繁體 from 簡體
- **Configurable fallback** — When no CHT subtitle is found: skip, use English, accept CHS, or disable subtitles
- **Multi-threaded scanning** — Process large libraries quickly with parallel workers
- **Scan range** — Only process recently updated items, or do a full library scan
- **Dry-run mode** — Preview all changes before applying
- **Flexible config** — CLI arguments, environment variables, or YAML config file
- **Docker-ready** — Run as a one-shot container or schedule periodic scans

## Quick Start / 快速開始

### Quick Run / 直接執行（不需安裝）

```bash
git clone https://github.com/TubeBoyJimmy/PlexPreferCHTSubs.git
cd PlexPreferCHTSubs
pip install -r requirements.txt
python run.py --help
```

### Install / 安裝（進階，可選）

```bash
pip install -e .
# 安裝後可直接使用：
plexchtsubs --help
python -m plexchtsubs --help
```

### Usage / 使用方式

```bash
# Basic — scan recent 30 days
python run.py --plex-url http://localhost:32400 --plex-token YOUR_TOKEN

# Dry run — preview only, don't change anything
python run.py --dry-run --scan-range 30

# Full scan, force overwrite, fall back to English if no CHT found
python run.py --scan-range 0 --force --fallback english

# Using environment variables (Docker-friendly)
export PLEX_URL=http://192.168.1.100:32400
export PLEX_TOKEN=your-token
plexchtsubs
```

Or run as a Python module:

```bash
python -m plexchtsubs --help
```

### Config File / 設定檔

Copy `config.example.yaml` to `config.yaml` and edit:

```yaml
plex:
  url: "http://localhost:32400"
  token: "your-token-here"

scan:
  range_days: 30
  fallback: skip       # skip | english | chs | none
  force_overwrite: false

workers: 8
```

Config priority: **CLI args > Environment variables > config.yaml > defaults**

## CLI Options / 命令列參數

```
Connection:
  --plex-url URL          Plex server URL (default: http://localhost:32400)
  --plex-token TOKEN      Plex authentication token
  --config FILE           Path to config.yaml

Scan:
  --scan-range DAYS       Scan items updated within N days (0 = full scan)
  --fallback STRATEGY     When no CHT found: skip | english | chs | none
  --force                 Force overwrite existing subtitle selections
  --workers N             Parallel threads (default: 8)

Schedule:
  --schedule              Run as a persistent service with cron scheduling
  --cron EXPR             Cron expression (default: "0 3 * * *")

Output:
  --dry-run               Preview changes without applying
  --log-file PATH         Write logs to file
  -v, --verbose           Verbose output
```

## Fallback Strategies / 找不到繁中時的策略

| `--fallback` | Behavior | 行為 |
|---|---|---|
| `skip` (default) | Don't change — keep Plex's current setting | 不動，保留原設定 |
| `english` | Fall back to English subtitles | 退而求其次用英文字幕 |
| `chs` | Accept Simplified Chinese | 接受簡體中文 |
| `none` | Disable subtitles | 關閉字幕 |

## How Detection Works / 偵測原理

Each subtitle track receives a confidence score:

| Score | Meaning |
|---|---|
| +100 | Definite CHT (title contains: 繁體, CHT, Traditional, BIG5, zh-TW...) |
| +95 | CHT by language code (zh-tw, zh-hant) |
| +90 | CHT by language description ("Traditional", "Taiwan", "Hong Kong") |
| +10 | Unknown Chinese variant — triggers fallback |
| 0 | Not Chinese |
| -100 | Definite CHS (title contains: 简体, CHS, Simplified, zh-CN...) |

Forced subtitles receive an additional -50 penalty.

## Docker / Docker 使用

### Build / 建置

```bash
docker build -t plexchtsubs .
```

### One-shot scan / 單次掃描

```bash
docker run --rm \
  -e PLEX_URL=http://plex:32400 \
  -e PLEX_TOKEN=your-token \
  plexchtsubs --dry-run --scan-range 30
```

### Service mode / 常駐排程

```bash
# Using docker-compose (recommended)
# Edit docker-compose.yml with your PLEX_TOKEN, then:
docker compose up -d

# Or run directly:
docker run -d --restart unless-stopped \
  -e PLEX_URL=http://plex:32400 \
  -e PLEX_TOKEN=your-token \
  --name plexchtsubs \
  plexchtsubs --schedule --cron "0 3 * * *"
```

Service mode runs the scan immediately on startup, then repeats on the cron schedule.
常駐模式會在啟動時立刻執行一次掃描，之後按照 cron 排程定期執行。

## Attribution / 致謝

Inspired by [PlexPreferNonForcedSubs](https://github.com/RileyXX/PlexPreferNonForcedSubs) by RileyXX (MIT License).

## License

[MIT](LICENSE)
