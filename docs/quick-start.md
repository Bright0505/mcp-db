# 快速開始指南

歡迎使用 MCP Multi-Database Connector！這份 5 分鐘指南將幫助您快速上手 MCP + OpenAPI 雙模式架構。

## 選擇您的使用方式

MCP Multi-Database Connector 提供雙模式架構，請根據需求選擇：

| 使用方式 | 適合對象 | 時間需求 | 難度 |
|----------|----------|----------|------|
| 🖥️ **Claude Desktop (MCP)** | Claude Desktop 用戶 | 3 分鐘 | 🟡 中等 |
| 🌐 **HTTP API (OpenAPI)** | Open WebUI、開發者 | 5 分鐘 | 🟡 中等 |

---

## 方式 1: 🖥️ Claude Desktop (MCP 協議)

### 步驟 1: 安裝
```bash
# 克隆專案
git clone <此模組的 repo 網址>
cd mcp-{module}

# 安裝依賴
pip install -e .
```

### 步驟 2: 配置 Claude Desktop
編輯 Claude Desktop 配置檔案：

**macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
**Windows**: `%APPDATA%/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "mcp-db": {
      "command": "python",
      "args": ["-m", "server"],
      "env": {
        "DB_TYPE": "postgresql",
        "DB_HOST": "localhost",
        "DB_NAME": "your_database",
        "DB_USER": "your_username",
        "DB_PASSWORD": "your_password",
        "DB_PORT": "5432"
      }
    }
  }
}
```

### 步驟 3: 重啟 Claude Desktop
重啟 Claude Desktop 讓配置生效。

### 步驟 4: 開始使用
在 Claude Desktop 中輸入：
```
請幫我查詢資料庫中的所有表格
```

**🎉 完成！** Claude Desktop 現在可以透過 MCP 協議直接存取您的資料庫。

---

## 方式 2: 🌐 HTTP API (OpenAPI 文檔)

### 步驟 1: 安裝
```bash
# 克隆專案
git clone <此模組的 repo 網址>
cd mcp-{module}

# 安裝依賴
pip install -e .

# 配置環境變數
cp .env.example .env
# 編輯 .env 填入資料庫連線資訊
```

### 步驟 2: 啟動 HTTP API 服務
```bash
# 啟動 HTTP API 伺服器
python -m http_server

# 或使用命令腳本
mcp-{module}-http
```

### 步驟 3: 測試 API
```bash
# 測試連線
curl http://localhost:8000/api/v1/connection/test

# 查看所有可用工具
curl http://localhost:8000/api/v1/tools

# 查看 API 文檔
# 開啟瀏覽器到 http://localhost:8000/docs
```

### 步驟 4: 使用 OpenAPI 文檔
1. 開啟瀏覽器到 **http://localhost:8000/docs**
2. 查看完整的 API 端點和 Schema 文檔
3. 直接在 Swagger UI 中測試 API

**適用於 Open WebUI**: 將 API 端點 `http://localhost:8000` 配置到 Open WebUI 即可使用。

**🎉 完成！** HTTP API 現在提供完整的 OpenAPI/Swagger 文檔供整合使用。

---

## 🐳 使用 Docker (任何方式)

如果您偏好使用 Docker，可以一鍵啟動所有服務：

```bash
# 配置環境變數
cp .env.example .env
# 編輯 .env 設定資料庫連線

# 啟動所有服務
docker-compose up -d

# 檢查服務狀態
docker-compose ps
```

**服務地址**:
- MCP Server: stdio 模式（用於 Claude Desktop）
- HTTP API: http://localhost:8000（用於 Open WebUI）
- API 文檔: http://localhost:8000/docs

---

## 🎯 下一步該做什麼？

根據您選擇的使用方式，深入了解更多功能：

### 如果您使用 Claude Desktop (MCP)
- [MCP 快速入門](MCP_QUICK_START.md) — 完整 MCP 功能指南
- [schemas_config 業務客製化](../schemas_config/README.md) — 配置業務領域邏輯

### 如果您使用 HTTP API (OpenAPI)
- API 文件位於 http://localhost:8000/docs（啟動服務後存取）
- Open WebUI 整合 — 將 API 端點配置到 Open WebUI

### 通用進階主題
- [Schema 系統](schema-system.md) — 靜態 Schema 與 JSON 配置
- [效能優化](performance.md) — 快取系統與效能調校（60-80% Token 節省）
- [系統架構](architecture.md) — 分層架構設計與模組說明

---

## ❓ 遇到問題？

### 🔧 常見問題快速修復

**❌ 連線失敗**
```bash
# 檢查資料庫服務是否運行
# PostgreSQL
sudo systemctl status postgresql

# SQL Server (Linux)
sudo systemctl status mssql-server
```

**❌ 權限錯誤**
```sql
-- 授予基本權限 (PostgreSQL)
GRANT SELECT ON ALL TABLES IN SCHEMA public TO your_username;

-- 授予基本權限 (SQL Server)
GRANT SELECT ON SCHEMA::dbo TO your_username;
```

**❌ 埠號被佔用**
```bash
# 檢查埠號使用情況
netstat -tuln | grep 8000  # HTTP API
```

### 獲得更多幫助
- [GitHub Issues](https://github.com/Bright0505/MCP_DB/issues) — 問題回報

---

**版本**：v1.0.0
**最後更新**：2026-01-27