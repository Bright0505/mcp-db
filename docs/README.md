# MCP Multi-Database Connector 技術文件

歡迎使用 MCP Multi-Database Connector 技術文件。

> 本目錄文件由樣板（`mcp-db`）維護，各衍生模組沿用同一份。文中 `{module}`、`{prefix}` 為佔位符：
> `{module}` ＝ 模組名（容器名 `mcp-{module}-dev`、`mcp-{module}-http-dev`），`{prefix}` ＝ 工具前綴（`TOOL_PREFIX`）。
> 範例中的 `mcp-db` 若出現在 Claude Desktop 設定的 key／路徑，請換成你的模組名。
> 現況（REST 在 `/api/v1/`、MCP 在 Streamable HTTP `/mcp/`、
> 部署＝模組 repo 推 `vX.Y.Z` tag）以各模組 README 為準。

## 文件導覽

### 入門指南

| 文件 | 說明 | 適合對象 |
|------|------|----------|
| [快速開始](quick-start.md) | 5 分鐘快速上手（雙模式） | 新手用戶 |
| [安裝指南](installation.md) | 詳細安裝步驟與環境需求 | 所有用戶 |
| [MCP 快速入門](MCP_QUICK_START.md) | Claude Desktop MCP 功能完整指南 | Claude Desktop 用戶 |

### 技術指南

| 文件 | 說明 | 適合對象 |
|------|------|----------|
| [系統架構](architecture.md) | 分層架構設計與模組說明 | 開發者、架構師 |
| [Schema 系統](schema-system.md) | 靜態 Schema 與 JSON 配置 | 系統管理員、開發者 |
| [效能優化](performance.md) | 快取系統與 Token 優化 | 進階用戶 |

### 開發環境

| 文件 | 說明 | 適合對象 |
|------|------|----------|
| [Claude Code 開發環境](CLAUDE.md) | Claude Code hooks 與自動化設定 | 專案貢獻者 |
| [測試指南](testing.md) | 單元測試與覆蓋率 | 開發者 |

## 按使用場景查找

- **第一次使用**：[快速開始](quick-start.md) → [安裝指南](installation.md)
- **Claude Desktop 用戶**：[MCP 快速入門](MCP_QUICK_START.md)
- **Open WebUI 用戶**：[快速開始](quick-start.md)（方式二：HTTP API）
- **業務客製化**：[Schema 系統](schema-system.md) → [schemas_config](../schemas_config/README.md)
- **效能調校**：[效能優化](performance.md)

## 按角色查找

- **開發者**：安裝指南 → 系統架構 → Schema 系統 → 測試指南
- **系統管理員**：MCP 快速入門 → Schema 系統 → 效能優化
- **架構師**：系統架構 → Schema 系統 → 效能優化 → 開發歷史文件
