# Schema 配置系統 - 完整指南

> 本指南提供深入的逐步說明，幫助您掌握 Schema 配置系統。

## 目錄

1. [核心概念](#核心概念)
2. [三層架構](#三層架構)
3. [完整配置流程](#完整配置流程)
4. [進階技巧](#進階技巧)
5. [效能優化](#效能優化)
6. [疑難排解](#疑難排解)

---

## 核心概念

### 為什麼需要 Schema 配置？

資料庫 Schema 僅包含技術資訊（表格名稱、欄位名稱、資料型別），缺乏業務語義：

```sql
-- AI 無法從技術 Schema 理解業務含義
CREATE TABLE orders (
  order_id int,
  order_date timestamp,
  total_amount decimal(10,2),
  status varchar(20)
);
```

問題：
- `order_id` 是什麼？只知道是整數，格式與用途不明
- `status` 的值代表什麼意思？
- 哪些欄位最重要？時間查詢該用哪個日期欄位？

**Schema 配置解決了這些問題**：

```json
{
  "key_columns": {
    "ORDER_ID": {
      "semantic_type": "primary_identifier",
      "description": "訂單編號",
      "usage_notes": "格式：YYYYMMDD-NNNNNN"
    },
    "STATUS": {
      "semantic_type": "status",
      "enum_values": {"pending": "待處理", "confirmed": "已確認", "cancelled": "已取消"},
      "ai_hints": "查詢有效訂單時使用 STATUS != 'cancelled' 過濾"
    }
  }
}
```

現在 AI 可以：
- 理解 ORDER_ID 是用於 JOIN 的主鍵
- 知道 STATUS='cancelled' 的記錄應被排除
- 自動使用正確的欄位進行查詢

---

## 三層架構

### 架構概覽

本系統採用 **白名單 + 增強配置** 的三層架構：

1. **白名單層 (tables_list.json)**：定義所有可存取的表格
2. **詳細配置層 (tables/*.json)**：為重要表格提供詳細的中繼資料
3. **全域模式層 (global_patterns.json)**：定義可重用的欄位規則

**關鍵設計原則**：
- 所有表格必須在 `tables_list.json` 中註冊才能被存取
- 沒有詳細配置（columns 為空）的表格仍可存取基本資訊
- 嚴格模式會阻止存取未註冊的表格

### 第一層：白名單層 (tables_list.json)

**用途**：存取控制與基本資訊。

**必要性**：所有可存取的表格都必須在此註冊。

```json
{
  "tables": {
    "ORDERS": {"table_type": "TABLE", "display_name": "訂單"},
    "CUSTOMERS": {"table_type": "TABLE", "display_name": "客戶"}
  }
}
```

**嚴格模式行為**：
- 在白名單中 -> 允許存取
- 不在白名單中 -> 拒絕存取
- 在白名單中但無詳細配置 -> 可存取基本資訊

### 第二層：詳細配置層 (tables/*.json)

**用途**：為重要表格提供詳細的業務邏輯與中繼資料。

**必要性**：選用 — 僅建議用於 Critical/High 重要性的表格。

```json
{
  "table_name": "ORDERS",
  "columns": [{"COLUMN_NAME": "ORDER_ID", "description": "訂單編號"}],
  "relationships": {"foreign_keys": [...]},
  "business_logic": {"primary_key": "ORDER_ID"}
}
```

### 第三層：全域模式層

**用途**：定義可重用的命名規則，減少重複配置。

#### 運作方式

系統使用正規表達式模式匹配欄位名稱：

```json
{
  "column_patterns": {
    "_ID$": {
      "semantic_type": "identifier",
      "default_description": "識別碼"
    }
  }
}
```

匹配範例：
- `ORDER_ID` -> 匹配
- `CUSTOMER_ID` -> 匹配
- `ID_NUMBER` -> 不匹配（不在結尾）

#### 何時使用全域模式

**適用情境**：
- 多個表格共用相同的欄位命名慣例
- 標準化術語（例如所有 `_ID` 欄位都是識別碼）
- 減少重複配置的維護成本

**不適用情境**：
- 表格特有的業務邏輯（使用 tables/*.json）
- 相同欄位名稱在不同表格中含義不同（在 tables/*.json 中覆寫）

### 欄位優先順序

當同一欄位在多處定義時：

```
tables/*.json > global_patterns.json > 資料庫 Schema
```

---

## 完整配置流程

### 範例：建立電子商務訂單系統

#### 步驟一：評估需求

**系統描述**：
- 3 個表格：ORDERS（訂單表頭）、ORDER_ITEMS（訂單明細）、CUSTOMERS（客戶）
- 重要性：ORDERS 與 ORDER_ITEMS 為 Critical，CUSTOMERS 為 High

#### 步驟二：建立目錄結構

```bash
mkdir -p schemas_config/tables
```

#### 步驟三：配置 tables_list.json

```json
{
  "schema_version": "2.1",
  "loading_strategy": {
    "priority_order": ["table_json_config", "global_patterns"]
  },
  "table_categories": {
    "order_data": {
      "display_name": "訂單資料",
      "description": "訂單交易資料",
      "tables": ["ORDERS", "ORDER_ITEMS"]
    },
    "master_data": {
      "display_name": "主檔資料",
      "description": "核心參考資料",
      "tables": ["CUSTOMERS"]
    }
  },
  "importance_levels": {
    "critical": {"tables": ["ORDERS", "ORDER_ITEMS"]},
    "high": {"tables": ["CUSTOMERS"]}
  },
  "tables": {
    "ORDERS": {"table_type": "TABLE", "display_name": "訂單"},
    "ORDER_ITEMS": {"table_type": "TABLE", "display_name": "訂單明細"},
    "CUSTOMERS": {"table_type": "TABLE", "display_name": "客戶"}
  }
}
```

#### 步驟四：建立詳細表格配置

建立 `schemas_config/tables/ORDERS.json`（參考 `examples/sample_table.json` 取得完整範例）：

```json
{
  "table_name": "ORDERS",
  "display_name": "訂單",
  "business_importance": "critical",
  "business_logic": {
    "primary_date_field": "ORDER_DATE",
    "primary_amount_field": "TOTAL_AMOUNT",
    "status_field": "STATUS",
    "status_values": {
      "pending": "待處理",
      "confirmed": "已確認",
      "shipped": "已出貨",
      "cancelled": "已取消"
    },
    "active_records_filter": "STATUS NOT IN ('cancelled')"
  },
  "relationships": {
    "primary_key": ["ORDER_ID"],
    "foreign_keys": [
      {"column": "CUSTOMER_ID", "references": "CUSTOMERS.CUSTOMER_ID"}
    ]
  },
  "key_columns": {
    "ORDER_ID": {"semantic_type": "primary_identifier", "description": "訂單編號"},
    "ORDER_DATE": {"semantic_type": "primary_date", "description": "訂單日期"},
    "TOTAL_AMOUNT": {"semantic_type": "primary_amount", "description": "總金額"}
  }
}
```

#### 步驟五：配置 AI 增強

```json
{
  "query_patterns": {
    "order_analysis": {
      "keywords": ["訂單", "購買", "營收"],
      "primary_tables": ["ORDERS", "ORDER_ITEMS"],
      "sample_queries": ["今日訂單摘要", "熱銷商品排行"]
    }
  },
  "natural_language_mappings": {
    "chinese_keywords": {
      "今天": "DATE(ORDER_DATE) = CURRENT_DATE",
      "本月": "DATE_TRUNC('month', ORDER_DATE) = DATE_TRUNC('month', CURRENT_DATE)"
    }
  }
}
```

#### 步驟六：測試配置

```bash
# 1. 驗證 JSON 語法
for f in schemas_config/*.json schemas_config/tables/*.json; do
  python -m json.tool "$f" > /dev/null && echo "OK: $f"
done

# 2. 重新載入設定（本機開發：重啟容器；正式機的 schemas_config 已打包進 image，要打新 tag）
docker-compose restart mcp-{module}-http

# 3. 測試 Schema 載入
curl http://localhost:8000/api/v1/schema/ORDERS
```

---

## 進階技巧

### 1. 計算欄位

```json
{
  "calculated_fields": {
    "net_revenue": {
      "formula": "TOTAL_AMOUNT - DISCOUNT",
      "description": "淨營收",
      "sql_template": "(COALESCE(TOTAL_AMOUNT, 0) - COALESCE(DISCOUNT, 0))"
    }
  }
}
```

### 2. 時區處理

```json
{
  "metadata": {
    "timezone": "UTC",
    "utc_offset": "+00:00"
  },
  "key_columns": {
    "ORDER_DATE": {
      "semantic_type": "primary_date",
      "timezone_aware": true,
      "ai_hints": "以 UTC 儲存，顯示時需轉換為當地時間"
    }
  }
}
```

### 3. SQL Server / PostgreSQL 雙語法

在 `global_patterns.json` 的時間模式中使用 `{date_column}` 佔位符。系統同時提供 SQL Server 與 PostgreSQL 範本：

```json
{
  "time_patterns": {
    "current_month": {
      "sql_server": "MONTH({date_column}) = MONTH(GETDATE())",
      "postgresql": "DATE_TRUNC('month', {date_column}) = DATE_TRUNC('month', CURRENT_DATE)"
    }
  }
}
```

---

## 效能優化

### 快取策略

```env
SCHEMA_ENABLE_CACHE=true
SCHEMA_CACHE_TTL_MINUTES=60
```

**快取層級**：
1. **靜態 JSON 預載**（啟動時）：毫秒級回應
2. **動態 TTL 快取**（執行時）：自動重新整理
3. **資料庫 Schema**（後備）：即時但較慢

### 配置檔案大小

- 僅配置必要欄位 — 優先處理主鍵、外鍵、日期、金額
- 使用 `global_patterns` 避免重複的逐表格定義
- 保持描述簡潔

---

## 疑難排解

### 問題一：配置未生效

```bash
# 1. 驗證 JSON 語法
python -m json.tool schemas_config/tables/YOUR_TABLE.json

# 2. 重新啟動服務
docker-compose restart mcp-{module}-http

# 3. 清除快取
curl -X POST http://localhost:8000/api/v1/cache/invalidate
```

### 問題二：AI 產生不正確的 SQL

1. **檢查 semantic_type** — 確認 `primary_date` 與 `datetime` 是否正確
2. **檢查 ai_hints** — 提供清楚的過濾指示
3. **新增自然語言對應** 至 `ai_enhancement.json`

### 問題三：JSON 語法錯誤

常見錯誤：
- 屬性之間缺少逗號
- 最後一個屬性後多了逗號
- 使用單引號（JSON 要求雙引號）
- 使用註解（JSON 不支援註解）

驗證工具：
```bash
python -m json.tool file.json
jq . file.json
```

---

## 總結

### 最佳實踐檢查清單

- [ ] 所有 JSON 檔案語法正確
- [ ] Critical/High 表格已建立 `tables/*.json` 配置
- [ ] 關鍵欄位已定義 `semantic_type`
- [ ] 業務規則記錄於 `business_logic` 中
- [ ] 表格關聯定義於 `relationships` 中
- [ ] 自然語言關鍵字已對應至 `ai_enhancement.json`
- [ ] 已啟用快取（`SCHEMA_ENABLE_CACHE=true`）
- [ ] 已透過 AI 查詢測試配置
