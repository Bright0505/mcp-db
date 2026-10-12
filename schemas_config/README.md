# Schema 配置系統 - 使用手冊

## 概述

本系統採用純 JSON 配置，搭配三層知識注入架構來管理資料庫表格與欄位的語義定義，幫助 AI 精準理解您的業務邏輯。

## 快速開始

### 步驟一：了解檔案結構
```
schemas_config/
├── tables_list.json          # [必要] 表格白名單與全域設定
├── global_patterns.json      # [必要] 全域欄位命名模式與可重用邏輯
├── ai_enhancement.json       # [必要] AI 查詢增強設定
├── examples/                 # 參考範例
│   └── sample_table.json     # 完整表格配置範例
└── tables/                   # [選用] 個別表格詳細配置（樣板為空；衍生模組以實際檔案為準）
    └── .gitkeep
```

### 步驟二：最小化配置（快速上手）
1. **確保必要檔案存在**：`tables_list.json`、`global_patterns.json`、`ai_enhancement.json`
2. **在 `tables_list.json` 中註冊您的表格**：
   ```json
   {
     "tables": {
       "YOUR_TABLE": {"table_type": "TABLE", "display_name": "您的表格名稱"}
     }
   }
   ```
3. **系統將自動套用 `global_patterns.json` 的命名規則**

### 步驟三：為重要表格新增詳細配置（選用）
針對重要性為 Critical/High 的表格，建立 `tables/YOUR_TABLE.json`：
```json
{
  "table_name": "YOUR_TABLE",
  "display_name": "您的表格名稱",
  "business_logic": {
    "primary_date_field": "DATE_COLUMN",
    "primary_amount_field": "AMOUNT_COLUMN"
  },
  "key_columns": {
    "ID": {"semantic_type": "primary_identifier", "description": "主鍵"}
  }
}
```

參考 `examples/sample_table.json` 取得完整範例。

### 步驟四：測試您的配置
1. 重新啟動 MCP 伺服器或 HTTP API
2. 使用 `get_cached_schema` 工具驗證 Schema 是否正確載入
3. 測試 AI 查詢以確認配置已被正確理解

## 系統架構

### 三層 Schema 架構

本系統採用 **白名單 + 增強配置** 的分層設計：

#### 第一層：白名單層 (tables_list.json)
- **用途**：定義所有可存取的表格
- **必要性**：是 — 所有可存取的表格都必須在此註冊
- **內容**：基本資訊（table_type、display_name）
- **存取控制**：`SCHEMA_STRICT_MODE=true` 時，schema 探索（`{prefix}_schema` 等）只認此處註冊的表格；
  ⚠️ 白名單**不會**擋 `{prefix}_query` 的實際執行（驗證層只檢查唯讀，不比對 `tables_list.json`），
  資料庫帳號可讀的表格仍可被 SQL 直接查到，敏感表格請在資料庫帳號權限層處理

#### 第二層：詳細配置層 (tables/*.json)
- **用途**：為重要表格提供詳細的中繼資料
- **必要性**：選用 — 僅建議用於 Critical/High 重要性的表格
- **內容**：columns、relationships、business_logic、ai_context

#### 第三層：全域模式層 (global_patterns.json + ai_enhancement.json)
- **global_patterns.json**：通用欄位命名模式（如 `_ID$`、`_DATE$`）
- **ai_enhancement.json**：自然語言查詢對應與模式

### 載入邏輯與嚴格模式

**載入順序**（優先權由高到低）：
1. `tables/*.json`（詳細配置層）
2. `tables_list.json`（白名單層）
3. `global_patterns.json`（全域模式）

**嚴格模式行為**：
- `SCHEMA_STRICT_MODE=false`（**預設**，`src/core/config.py`）：快取未命中時允許動態資料庫 Schema 查詢
- `SCHEMA_STRICT_MODE=true`：schema 探索僅允許 `tables_list.json` 中的表格（只影響探索，不影響 query 執行）

## 配置檔案參考

### 1. tables_list.json
定義所有表格的基本資訊、分類與重要性等級。

### 2. global_patterns.json
定義可重用的欄位命名規則與計算公式。時間模式同時包含 SQL Server 與 PostgreSQL 語法，使用 `{date_column}` 佔位符。

### 3. ai_enhancement.json
定義自然語言到 SQL 的對應，用於 AI 查詢優化。

### 4. tables/*.json
個別表格的詳細配置。參考 `examples/sample_table.json` 取得完整範例。

## 語義類型 (semantic_type) 參考

| 類型 | 說明 | 範例 | 用途 |
|------|------|------|------|
| `primary_identifier` | 主鍵 | ORDER_ID | 表格的唯一識別碼 |
| `foreign_key` | 外鍵 | CUSTOMER_ID | 參照其他表格 |
| `primary_date` | 主要日期 | ORDER_DATE | 最重要的時間欄位 |
| `primary_amount` | 主要金額 | TOTAL_AMOUNT | 最重要的金額欄位 |
| `status` | 狀態 | STATUS | 記錄狀態（啟用/取消等） |
| `money` | 金額 | PRICE | 一般金額欄位 |
| `quantity` | 數量 | QTY | 數量相關欄位 |
| `datetime` | 日期/時間 | CREATE_DATE | 一般日期時間欄位 |
| `code` | 代碼 | DEPT_CODE | 代碼分類欄位 |
| `identifier` | 識別碼 | PROD_ID | 一般識別碼（非主鍵） |
| `name` | 名稱 | PROD_NAME | 顯示名稱欄位 |
| `category` | 分類 | TYPE, KIND | 分類欄位 |

## 維護指南

- **新增表格**：更新 `tables_list.json`。若為重要表格，另建立 `tables/<TABLE>.json`。
- **新增命名模式**：若多個表格共用欄位命名慣例，更新 `global_patterns.json`。
- **新增查詢情境**：更新 `ai_enhancement.json` 以支援新的自然語言關鍵字。
- **驗證配置**：變更後請驗證 JSON 語法並測試 AI 查詢理解。

## 驗證與測試

### JSON 語法驗證
```bash
for file in schemas_config/*.json schemas_config/tables/*.json; do
  python -m json.tool "$file" > /dev/null && echo "OK: $file"
done
```

### Schema 載入測試
```python
from src.database.schema.static_loader import get_cached_schema
schema = get_cached_schema("YOUR_TABLE")
print(schema)
```

## 常見問題

- **Q：配置未生效？** 請檢查 JSON 語法、檔案路徑，並重新啟動服務。
- **Q：每個表格都需要 tables/*.json 嗎？** 不需要，僅 Critical/High 重要性的表格需要。其他表格使用 global_patterns 即可。
- **Q：如何新增表格？** 在 `tables_list.json` 的 `tables` 中新增。可選擇性建立 `tables/{TABLE}.json`。
