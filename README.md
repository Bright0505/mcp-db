# MCP Multi-Database Connector

[![Python](https://img.shields.io/badge/python-3.8+-green.svg)](https://python.org)
[![Database](https://img.shields.io/badge/database-SQL%20Server%20%7C%20PostgreSQL-orange.svg)](https://github.com/)
[![License](https://img.shields.io/badge/license-MIT-lightgrey.svg)](LICENSE)

MCP (Model Context Protocol) 多資料庫連接器範本，支援 Microsoft SQL Server 與 PostgreSQL。透過靜態 Schema 預載與智慧分析，讓 AI 精準理解您的資料庫結構與業務邏輯。

使用 `schemas_config/` 目錄自訂您的業務領域配置。

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
│  │  (stdio)     │  │  (FastAPI + OpenAPI)    │      │
│  └──────┬───────┘  └───────────┬─────────────┘      │
│         │       服務層          │                    │
└─────────┼──────────────────────┼────────────────────┘
          │                      │
┌─────────┼──────────────────────┼────────────────────┐
│         ▼                      ▼                    │
│  ┌────────────────────────────────────────────┐     │
│  │            統一工具處理層 (Tools)             │    │
│  │  db_query / db_schema / db_dependencies ... │    │
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

### 雙模式架構
- **Claude Desktop (MCP 協議)**：透過 stdio 提供完整 MCP 工具支援
- **Open WebUI (HTTP API)**：RESTful API + OpenAPI/Swagger 文件

---

## 快速開始

### 方式一：Claude Desktop (MCP 協議)

**1. 準備環境**
```bash
git clone https://github.com/Bright0505/mcp-db.git
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

### 方式二：HTTP API (Open WebUI)

```bash
# Docker 部署（推薦）
cp .env.example .env
# 編輯 .env
docker-compose up -d

# 或本地執行
pip install -e .
python -m http_server
```

存取 API 文件：http://localhost:8000/docs

### 使用範例

```bash
# 測試連線
curl -X POST http://localhost:8000/api/test-connection

# 執行查詢
curl -X POST http://localhost:8000/api/query \
  -H "Content-Type: application/json" \
  -d '{"query": "SELECT TOP 10 * FROM ORDERS"}'

# 查看表格 Schema
curl -X POST http://localhost:8000/api/schema \
  -H "Content-Type: application/json" \
  -d '{"table_name": "ORDERS"}'
```

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
```

---

## MCP 工具一覽

| 工具名稱 | 說明 |
|----------|------|
| `db_query` | 執行 SELECT 查詢（唯讀模式） |
| `db_schema` | 查看表格結構與欄位資訊 |
| `db_schema_summary` | 資料庫物件摘要統計 |
| `db_dependencies` | 分析表格依賴關係 |
| `db_test_connection` | 測試資料庫連線 |
| `db_cache_stats` | 查看快取統計 |
| `db_cache_invalidate` | 清除快取 |
| `db_schema_reload` | 重新載入 Schema 配置 |
| `db_static_schema_info` | 查看靜態 Schema 資訊 |
| `db_export_schema` | 匯出表格 Schema |
| `db_syntax_guide` | SQL 語法參考指南 |

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
- [開發環境](docs/development/README.md) — 開發歷史與貢獻指南
- [測試指南](docs/testing.md) — 單元測試與覆蓋率
- [Claude Code 設定](docs/CLAUDE.md) — Claude Code hooks 與自動化

---

## 授權

MIT License — 詳見 [LICENSE](LICENSE)

---

**版本**：v1.0.0
**最後更新**：2026-01-27
