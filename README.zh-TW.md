# PlexPreferCHTSubs

> **[English README](README.md)**

**自動將 Plex 媒體庫的預設字幕設為繁體中文（Traditional Chinese）。**

---

## 為什麼需要這個工具？

Plex 將中文字幕視為單一語言，當媒體檔案同時包含繁體和簡體字幕時，往往預設選擇簡體中文。Plex 沒有內建的方式讓使用者偏好繁體中文字幕。

此工具掃描你的 Plex 媒體庫，透過多層評分系統辨識繁體中文字幕軌，並將其設為預設。

## 功能

- **智慧繁簡辨識** — 多層評分：標題正規表達式、語言 metadata、字元頻率分析
- **內容分析** — 針對未標示繁簡的中文字幕（僅標記「中文」），下載字幕文本，以 90 組繁簡對照字元自動判斷
- **外掛字幕優先** — 同時有內嵌 MKV 字幕和外掛 .srt/.ass 時，優先選擇外掛字幕
- **即時監控** — WebSocket 監聽 Plex 媒體變更，即時處理新增/更新的項目，不需要 Plex Pass
- **備援策略** — 找不到繁中時可選擇：接受簡中、切換英文、不動、或關閉字幕
- **多執行緒掃描** — 平行處理大型媒體庫
- **預覽模式** — 套用前先預覽所有變更
- **彈性設定** — 支援 CLI 參數、環境變數、YAML 設定檔
- **Web UI 儀表板** — 瀏覽器介面，遠端監控狀態及手動觸發掃描
- **Docker 支援** — 單次執行或常駐服務（cron + watcher + Web UI）

## 快速開始

### 方式 A：直接下載 exe（Windows）

從 [Releases](https://github.com/TubeBoyJimmy/PlexPreferCHTSubs/releases) 下載 `plexchtsubs.exe`，不需要安裝 Python。

```bash
# 將 config.yaml 放在 exe 同目錄下，然後：
plexchtsubs.exe --dry-run
plexchtsubs.exe --help
```

### 方式 B：Python 執行

```bash
git clone https://github.com/TubeBoyJimmy/PlexPreferCHTSubs.git
cd PlexPreferCHTSubs
pip install -r requirements.txt
python run.py --help
```

### 設定

將 `config.example.yaml` 複製為 `config.yaml`，填入你的 Plex URL 和 token：

```yaml
plex:
  url: "http://localhost:32400"
  token: "your-token-here"       # https://www.plexopedia.com/plex-media-server/general/plex-token/

scan:
  range_days: 30                 # 掃描最近 N 天內更新的項目（null = 全部掃描）
  fallback: chs                  # chs | english | skip | none
  force_overwrite: false

workers: 8

schedule:
  enabled: false
  cron: "0 3 * * 0"             # 每週日凌晨 03:00

watch:
  enabled: false
  debounce: 5.0                  # 批次處理前等待秒數

web:
  enabled: false
  port: 9527
  # username: "admin"            # 取消註解以啟用 Basic Auth
  # password: "changeme"
```

設定優先順序：**CLI 參數 > 環境變數 > config.yaml > 預設值**

### 執行

```bash
# 預覽模式 — 只看不改
python run.py --dry-run

# 套用變更（預設掃描近 30 天）
python run.py

# 全掃描，找不到繁中時退而用英文
python run.py --scan-range 0 --fallback english

# 強制重新評估所有項目（含已設定的）
python run.py --force
```

## 偵測原理

每條字幕軌會得到一個信心分數，分數最高的繁體中文字幕會被選為預設。

### 評分表

| 分數 | 來源 | 說明 |
|-----:|------|------|
| +100 | 標題正規匹配 | 確定繁中 — 標題含有關鍵字（見下表） |
| +95 | 語言代碼 | 繁中代碼：`zh-tw`、`zh-hant` |
| +90 | 語言描述 | 繁中描述：「Traditional」、「Taiwan」、「Hong Kong」 |
| +85 | 內容分析 | 字元頻率分析判定為繁中（繁體字元 ≥70%） |
| +10 | 泛中文 | 無法判斷繁簡（代碼為 `chi`/`zho` 且無變體資訊）— 觸發備援策略 |
| 0 | 非中文 | 不是中文字幕 |
| -100 | 確定簡中 | 確定簡體中文（標題、代碼、描述或內容分析判定） |

### 標題關鍵字

| 分類 | 關鍵字 |
|------|--------|
| 繁中 | `CHT`、`TC`、`JPTC`、`繁體`、`繁体`、`繁中`、`繁日`、`繁英`、`正體`、`正体`、`Traditional`、`BIG5`、`fanti`、`zh-Hant`、`zh-TW`、`Taiwan`、`台灣`、`台湾`、`Hong Kong`、`香港`、`HK` |
| 簡中 | `CHS`、`SC`、`JPSC`、`简体`、`简中`、`簡體`、`简日`、`简英`、`Simplified`、`jianti`、`zh-Hans`、`zh-CN`、`GB2312`、`GBK` |

### 修正項

| 修正項 | 效果 | 原因 |
|--------|------|------|
| Forced 字幕 | -50 扣分 | 避免選到只含關鍵對白的強制字幕 |
| 外掛字幕檔 | +2 加分 | 外掛 .srt/.ass 通常是刻意添加的，品質較佳 |

### 選取邏輯

1. **繁中分類優先** — 任何被分類為 CHT 的字幕軌都會被選取（多條 CHT 時選分數最高的）
2. **「第二軌」啟發式** — 當有 2 條以上的泛中文字幕且無 metadata 可判斷時，選取第二軌（常見 MKV 慣例：第一軌簡中、第二軌繁中）。外掛字幕因加分較高會優先被選取。
3. **備援策略** — 找不到繁中時，套用設定的備援策略

### 內容分析

當中文字幕的 metadata 沒有明確的繁簡標示時（僅標記為「中文」或「Chinese」），工具會下載字幕文本樣本，使用 90 組高頻繁簡對照字元（如 們/们、這/这、會/会）統計繁體與簡體字元的使用比例。

- **≥70% 繁體字元** → 繁中（85 分）
- **≤30% 繁體字元** → 簡中（-100 分）
- **30-70%** → 無法判斷，觸發備援策略
- 跳過圖片式字幕（PGS、VobSub）
- 支援 UTF-8、UTF-16、Big5、GB18030 編碼
- 每條字幕最多下載 50KB — 快速且輕量

## 備援策略

找不到繁體中文字幕時的處理方式：

| `--fallback` | 行為 |
|---|---|
| `chs`（預設） | 接受簡體中文，至少還是中文 |
| `english` | 退而求其次用英文字幕 |
| `skip` | 不動，保留 Plex 原本設定 |
| `none` | 關閉字幕 |

## 命令列參數

```
連線:
  --plex-url URL          Plex 伺服器網址（預設: http://localhost:32400）
  --plex-token TOKEN      Plex 認證 token
  --config FILE           設定檔路徑

掃描:
  --scan-range DAYS       掃描最近 N 天內更新的項目（0 = 全掃描）
  --fallback STRATEGY     找不到繁中時: chs | english | skip | none（預設: chs）
  --force                 強制重新評估已選定的字幕
  --workers N             平行執行緒數（預設: 8）

排程:
  --schedule              以常駐服務模式運行（含 cron 排程）
  --cron EXPR             Cron 表達式（預設: "0 3 * * 0"，每週日凌晨 3 點）

即時監控:
  --watch                 啟用 WebSocket 即時監控
  --no-watch              停用監控（即使使用 --schedule）
  --watch-debounce SECS   批次處理前的等待秒數（預設: 5.0）

Web UI:
  --web                   啟用 Web UI 儀表板（預設 port: 9527）
  --web-port PORT         Web UI 埠號（預設: 9527）

輸出:
  --dry-run               預覽模式，不實際變更
  --log-file PATH         日誌輸出到檔案
  -v, --verbose           詳細輸出
```

## 即時監控模式

透過 Plex 的 WebSocket Alert Listener 即時偵測媒體變更。當新增或更新媒體時（如替換檔案、新增字幕），監控器只處理受影響的項目，不需要全面掃描。**不需要 Plex Pass。**

事件會進行防抖處理（預設 5 秒），批次處理快速連續的變更 — 例如一次匯入整季會合併為一次批次處理，而非逐集觸發。

```bash
# 僅監控（無 cron 排程）
python run.py --watch --dry-run

# 排程 + 監控（建議的常駐模式）
# --schedule 自動啟用 --watch，除非指定 --no-watch
python run.py --schedule

# 僅排程，不啟用監控
python run.py --schedule --no-watch
```

自動重連：若 WebSocket 斷線，監控器會以指數退避方式自動重連（2 秒 → 4 秒 → 8 秒 → 最長 5 分鐘）。

## Web UI

瀏覽器介面的儀表板，適合 Docker / NAS 環境下遠端監控和手動操作。

```bash
# 僅 Web UI
python run.py --web

# Web UI + 排程 + 監控（完整服務模式）
python run.py --schedule --web

# 自訂 port
python run.py --web --web-port 3000
```

開啟瀏覽器前往 `http://你的伺服器:9527` 即可存取。

功能：
- 即時顯示 Plex 連線狀態、Watcher 狀態、掃描進度
- 一鍵觸發手動掃描（可選 dry-run）
- 掃描歷史紀錄及統計
- 目前設定總覽
- 可選 Basic Auth 認證（在 config 中設定 `web.username` 和 `web.password`）

## Docker

### 單次掃描

```bash
docker compose run --rm plexchtsubs --dry-run
```

### 常駐模式

```bash
# 啟動服務（即時監控 + Web UI 儀表板）
docker compose up -d

# 查看日誌
docker compose logs -f

# 停止
docker compose down
```

Docker Compose 預設指令為 `--watch --web`：即時監控新增媒體並自動處理字幕，同時在 port 9527 提供 Web 儀表板供遠端監控和手動掃描。如需定時 cron 排程，可加入 `--schedule`。

### 從原始碼建置

```bash
docker build -t plexchtsubs .
```

### 遠端部署（NAS 等）

```bash
# 在建置機器上
docker build -t plexchtsubs .
docker save plexchtsubs -o plexchtsubs.tar

# 將 plexchtsubs.tar、docker-compose.yml、config.yaml 複製到目標機器

# 在目標機器上
sudo docker load < plexchtsubs.tar
sudo docker compose up -d
sudo docker compose logs -f
```

## 環境變數

所有設定都可透過環境變數設定（適合 Docker 使用）：

| 變數 | 說明 |
|------|------|
| `PLEX_URL` | Plex 伺服器網址 |
| `PLEX_TOKEN` | Plex 認證 token |
| `SCAN_RANGE` | 掃描天數（0 = 全掃描） |
| `FALLBACK` | 備援策略 |
| `WORKERS` | 平行執行緒數 |
| `DRY_RUN` | 設為 `true` 啟用預覽模式 |
| `SCHEDULE_ENABLED` | 設為 `true` 啟用常駐模式 |
| `SCHEDULE_CRON` | Cron 排程表達式 |
| `WATCH_ENABLED` | 設為 `true` 啟用即時監控 |
| `WATCH_DEBOUNCE` | 防抖秒數 |
| `WEB_ENABLED` | 設為 `true` 啟用 Web UI 儀表板 |
| `WEB_HOST` | Web UI 綁定位址（預設: `0.0.0.0`） |
| `WEB_PORT` | Web UI 埠號（預設: `9527`） |
| `WEB_USERNAME` | Basic Auth 帳號（空白 = 不啟用認證） |
| `WEB_PASSWORD` | Basic Auth 密碼 |

## 致謝

靈感來自 [PlexPreferNonForcedSubs](https://github.com/RileyXX/PlexPreferNonForcedSubs)，由 RileyXX 開發（MIT License）。

## 授權

[MIT](LICENSE)
