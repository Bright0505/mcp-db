# MCP Multi-Database Connector

[![Python](https://img.shields.io/badge/python-3.11+-green.svg)](https://python.org)
[![Database](https://img.shields.io/badge/database-SQL%20Server%20%7C%20PostgreSQL-orange.svg)](https://github.com/)
[![License](https://img.shields.io/badge/license-MIT-lightgrey.svg)](LICENSE)

MCP (Model Context Protocol) 多資料庫連接器範本，支援 Microsoft SQL Server 與 PostgreSQL。透過靜態 Schema 預載與智慧分析，讓 AI 精準理解您的資料庫結構與業務邏輯。

使用 `schemas_config/` 目錄自訂您的業務領域配置。

> **本 repo 是樣板，不單獨部署。** 各業務模組（member、hr-db、promotion-analysis、fengtien…）複製自本樣板，
> 各自有 repo 與 `.gitlab-ci.yml`，由模組 repo 推 `vX.Y.Z` tag 才會 build＋部署（見下方〈部署〉）。
> 文中 `{prefix}` 代表工具前綴（環境變數 `TOOL_PREFIX`，樣板預設 `db`），`{module}` 代表模組名。

---
```text
┌─────────────────────────────────────────────────────┐
│                    用戶端層                           │
│  ┌──────────────┐  ┌──────────┐  ┌───────────────┐   │
│  │Claude Desktop│  │ Web 瀏覽器│  │ 第三方應用程式  │   │
│  └──────┬───────┘  └────┬─────┘  └───────┬───────┘   │
└─────────┼───────────────┼────────────────┼──────────┘
          │               │                │
┌─────────┼───────────────┼────────────────┼──────────┐
│         ▼               ▼                ▼          │
│  ┌──────────────┐  ┌─────────────────────────┐      │
│  │  MCP Server  │  │     HTTP API Server     │      │
│  │  (stdio)     │  │ (REST /api/v1 + /mcp/)  │      │
│  └──────┬───────┘  └───────────┬─────────────┘      │
│         │       服務層          │                    │
└─────────┼──────────────────────┼────────────────────┘
          │                      │
┌─────────┼──────────────────────┼────────────────────┐
│         ▼                      ▼                    │
│  ┌────────────────────────────────────────────┐     │
│  │            統一工具處理層 (Tools)             │    │
│  │  {prefix}_query / {prefix}_schema ...       │    │
│  └──────────────────────┬──────────────────────┘    │
│                         │  核心層                    │
│  ┌──────────┐  ┌────────┴────────┐  ┌────────────┐  │
│  │ 配置管理  │  │  資料庫管理器     │  │ 錯誤處理     │  │
│  │ (Config) │  │(DatabaseManager)│  │(Exceptions)│  │
│  └──────────┘  └────────┬────────┘  └────────────┘  │
└─────────────────────────┼───────────────────────────┘
                          │
┌─────────────────────────┼────────────────────────────┐
│                         ▼                            │
│  ┌──────────────┐  ┌──────────┐  ┌───────────────┐   │
│  │ Schema 快取   │  │Schema    │  │ 靜態 Schema   │   │
│  │(LFU+LRU+TTL) │  │ 內省器    │  │  載入器(JSON)  │   │
│  └──────────────┘  └────┬─────┘  └───────┬───────┘   │
│                   資料層 │                │           │
│           ┌─────────────┼────────────────┤           │
│           ▼             ▼                ▼           │
│    ┌────────────┐ ┌────────────┐ ┌───────────────┐   │
│    │ SQL Server │ │ PostgreSQL │ │schemas_config/│   │
│    │  (MSSQL)   │ │            │ │  JSON 配置檔   │   │
│    └────────────┘ └────────────┘ └───────────────┘   │
└──────────────────────────────────────────────────────┘
```

---

## 核心功能

### 基礎能力
- **多資料庫支援**：原生 SQL Server 與 PostgreSQL 連接器
- **10+ 資料庫工具**：查詢、Schema 分析、依賴關係分析、匯出等
- **靜態 Schema 預載**：透過 JSON 配置注入業務語義
- **智慧快取**：LFU+LRU+TTL 多層快取，毫秒級回應
- **關聯分析**：表格依賴與外鍵關係分析

### AI 增強
- **Schema 感知 AI**：根據實際資料庫結構與業務語義產生精確 SQL
- **Token 優化**：Schema 壓縮節省 60-80% Token 用量
- **SQL 語法導引**：自動偵測資料庫類型，提供對應語法提示

### 三種入口
- **Claude Desktop（MCP stdio）**：`python -m server`，提供完整 MCP 工具
- **Streamable HTTP（`/mcp/`）**：Open WebUI 的原生 MCP 連線（`tool_server.connections`，`type: "mcp"`）直接打這個端點。
  MCP SDK 版本以 `constraints.txt` 為準（目前 `mcp==2.0.0`）；同一端點同時服務 `initialize` handshake 與無狀態的 2026-07-28 兩個協議世代，由 SDK 判別。
  舊的 SSE（`/sse/`）已移除；MCPO 已於 2026-08-11 除役，不再需要
- **REST（`/api/v1/*`）**：FastAPI + OpenAPI/Swagger（`/docs`），供除錯與腳本使用

---

## 快速開始

### 方式一：Claude Desktop (MCP 協議)

**1. 準備環境**
```bash
git clone https://github.com/Bright0505/mcp-db.git   # 衍生模組請改用各自的 repo 網址
cd mcp-db
cp .env.example .env
# 編輯 .env 填入資料庫連線資訊
```

**2. 配置 Claude Desktop**

找到配置檔案：
- macOS：`~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows：`%APPDATA%\Claude\claude_desktop_config.json`
- Linux：`~/.config/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "mcp-db": {
      "command": "python",
      "args": ["-m", "server"],
      "cwd": "/path/to/mcp-db/src",
      "env": {
        "DB_TYPE": "postgresql",
        "DB_HOST": "localhost",
        "DB_NAME": "your_database",
        "DB_USER": "your_username",
        "DB_PASSWORD": "your_password",
        "DB_PORT": "5432",
        "SCHEMA_ENABLE_CACHE": "true"
      }
    }
  }
}
```

**3. 重啟 Claude Desktop 並測試**
```
請測試資料庫連線狀態
```

### 方式二：HTTP（REST ＋ `/mcp/`，Open WebUI）

```bash
# 本機開發（docker-compose.yml 是 development target，掛載 src/）
cp .env.example .env
# 編輯 .env
docker-compose up -d

# 或本地執行（需 Python >= 3.11）
pip install -e .
python -m http_server
```

- API 文件：http://localhost:8000/docs
- MCP 端點：http://localhost:8000/mcp/（Open WebUI 原生 MCP 連線指向這裡）
- 容器內 `HTTP_PORT` 預設 8000；正式機的 port 與容器名由各模組 `.gitlab-ci.yml` 決定

### 使用範例

```bash
# 健康檢查（不需 token）
curl http://localhost:8000/api/v1/health

# 測試資料庫連線（GET）
curl http://localhost:8000/api/v1/connection/test

# 執行查詢（POST；body 為 query ＋ 選填 params）
curl -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"query": "SELECT COUNT(*) AS n FROM ORDERS"}'

# 資料庫 Schema 總覽／單一表格 Schema（GET）
curl http://localhost:8000/api/v1/schema
curl http://localhost:8000/api/v1/schema/ORDERS

# 所有 REST 端點清單
curl http://localhost:8000/api/v1/tools
```

若設定了 `MCP_AUTH_TOKEN`，除 `/api/v1/health` 外每個請求（REST 與 `/mcp/`）都要帶 `Authorization: Bearer <token>`。
另可選用 OAuth（`MCP_OAUTH_ISSUER`／`MCP_OAUTH_AUDIENCE`／`MCP_OAUTH_JWKS_URL` 三者都設才啟用）：`/mcp/` 另接受外部授權伺服器簽發的 JWT，只驗簽章、`iss`、`aud`、`exp`，REST 仍只認共用 token；`/api/v1/health` 的 `oauth_enabled` 顯示是否啟用。說明見 `.env.example`。
SQL 語法依資料庫而異（例如 SQL Server 用 `TOP`、PostgreSQL 用 `LIMIT`），可呼叫 `{prefix}_syntax_guide` 取得對應提示。

---

## 環境配置

```bash
# 資料庫類型
DB_TYPE=postgresql        # 或 mssql

# 資料庫連線
DB_HOST=localhost
DB_NAME=your_database
DB_USER=your_username
DB_PASSWORD=your_password
DB_PORT=5432              # PostgreSQL: 5432, SQL Server: 1433

# Schema 快取（建議啟用）
SCHEMA_ENABLE_CACHE=true
SCHEMA_CACHE_TTL_MINUTES=60

# HTTP API
HTTP_HOST=0.0.0.0
HTTP_PORT=8000

# 工具前綴（工具名＝{prefix}_query 等；未設為 db）
TOOL_PREFIX=db

# 環境變數命名空間（選用）：設 ENV_PREFIX=FOO_ 後，FOO_DB_HOST 優先於 DB_HOST，
# 供同一份 .env 服務多個模組時各自隔離
# ENV_PREFIX=

# Schema 白名單嚴格模式（預設 false；true 時 schema 探索只認 tables_list.json 的表格，
# 不影響 {prefix}_query 的實際執行，見 schemas_config/README.md）
SCHEMA_STRICT_MODE=false

# 共用 Bearer token（選用、opt-in）：未設或留空＝不驗證；設了之後除 /api/v1/health 外
# 的 REST 與 /mcp/ 都要帶 Authorization: Bearer <token>。可用逗號列多把 token 以便輪替。
# token 預期由前面的閘道（nginx）持有並轉發，不是每個 client 各持一把
MCP_AUTH_TOKEN=

# 速率限制
RATE_LIMIT_DEFAULT=100/minute
RATE_LIMIT_QUERY=30/minute
```

完整變數清單見 `.env.example`；預設值以 `src/core/config.py` 為準。

---

## 部署

- **樣板本身不部署**，沒有 `.gitlab-ci.yml`；`docker-compose.yml` 只是本機開發用（development target、掛載 `src/`）
- **衍生模組**（各自一個 GitLab `mcp` group 的 repo）的 `.gitlab-ci.yml` `include` 共用範本 `mcp/ci-templates`，
  **推 `vX.Y.Z` tag** 才會 build＋deploy 到正式機（runner 標籤 `mcp-prod`）；推分支、MR 不會部署
- 每個模組的 `.gitlab-ci.yml` 只放自己獨有的設定：`MCP_NAME`、`HOST_PORT`／`APP_PORT`、`MCP_RUN_ARGS`（含 `-e TOOL_PREFIX=...`）
- 連線資訊與 secret 放在 mcp group 的 File 變數 `MCP_PROD`，不進 repo
- `schemas_config/` 在衍生模組的 Dockerfile production stage 已打包進 image：改白名單／表格設定＝打新 tag，不是改掛載目錄後重啟
- 部署後驗證看 `/api/v1/health` 的 `database_connected`（`degraded`＝連不上資料庫）與 MCP `tools/list` 的工具數，容器在跑不代表設定正確
- 部署後，Open WebUI 的 MCP 連線若有函式名白名單（`function_name_filter_list`），新增工具要一併加入，否則會被靜默濾掉


---

## MCP 工具一覽

共 11 支。工具名 ＝ `{prefix}_` ＋ 下表名稱，前綴由 `TOOL_PREFIX` 決定（樣板預設 `db`）。
⚠️ 在 Open WebUI 裡最終函式名會再接上「連線識別碼」，變成 `{連線識別碼}_{prefix}_query` 這種形式。

| 工具名稱 | 說明 |
|----------|------|
| `{prefix}_query` | 執行 SELECT 查詢（唯讀模式） |
| `{prefix}_schema` | 查看表格結構與欄位資訊 |
| `{prefix}_schema_summary` | 資料庫物件摘要統計 |
| `{prefix}_dependencies` | 分析表格依賴關係 |
| `{prefix}_test_connection` | 測試資料庫連線 |
| `{prefix}_cache_stats` | 查看快取統計 |
| `{prefix}_cache_invalidate` | 清除快取 |
| `{prefix}_schema_reload` | 重新載入 Schema 配置 |
| `{prefix}_static_schema_info` | 查看靜態 Schema 資訊 |
| `{prefix}_export_schema` | 匯出表格 Schema |
| `{prefix}_syntax_guide` | SQL 語法參考指南 |

---

## 業務客製化

本專案是一個**範本**，透過 `schemas_config/` 目錄進行客製化：

### 三層知識注入架構

```
schemas_config/
├── tables_list.json         # 表格白名單與全域設定
├── global_patterns.json     # 全域欄位命名模式（如 _ID$、_DATE$、_AMT$）
├── ai_enhancement.json      # AI 查詢增強（關鍵字對應、查詢模板）
├── tables/                  # 個別表格詳細配置
│   └── ORDERS.json          # 欄位說明、狀態值定義、JOIN 建議
└── examples/
    └── sample_table.json    # 完整範例參考
```

### 客製化步驟

1. 在 `schemas_config/tables_list.json` 註冊您的表格
2. 為重要表格建立 `schemas_config/tables/<TABLE>.json` 詳細配置
3. 在 `schemas_config/ai_enhancement.json` 配置 AI 查詢模式
4. 參考 `schemas_config/examples/sample_table.json` 取得完整範例

詳細指南：[schemas_config/README.md](schemas_config/README.md) | [完整配置手冊](schemas_config/SCHEMA_CONFIG_GUIDE.md)

---

## 文件導覽

### 入門
- [MCP 快速入門](docs/MCP_QUICK_START.md) — MCP 功能完整指南（推薦）
- [快速開始](docs/quick-start.md) — 5 分鐘上手指南
- [安裝指南](docs/installation.md) — 環境設定與安裝步驟

### 技術
- [系統架構](docs/architecture.md) — 分層架構設計與模組說明
- [Schema 系統](docs/schema-system.md) — 靜態 Schema 與 JSON 配置
- [效能優化](docs/performance.md) — 快取系統與 Token 優化

### 開發
- [測試指南](docs/testing.md) — 單元測試與覆蓋率
- [Claude Code 設定](docs/CLAUDE.md) — Claude Code hooks 與自動化

---

## 授權

MIT License — 詳見 [LICENSE](LICENSE)

---

**版本**：以 git tag 為準（樣板本身不打 tag；`pyproject.toml` 的 version 不代表部署版本）
**最後更新**：2026-10-12（文件更新）
