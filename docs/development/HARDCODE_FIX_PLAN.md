# 硬編碼修復計劃

> **建立日期**：2025-12-30
> **專案**：MCP Database
> **目的**：系統性修復所有硬編碼問題，提升程式碼可維護性和可配置性
> **狀態**：15/15 項目已於 2025-12-31 全部完成

> ## ⚠️ 歷史文件（保留原文不改寫）
>
> 本文是已完成的修復計劃紀錄，**不是現況說明**。文中多處引用
> `src/protocol/sse_server.py` —— 該檔案已於 2026-08-04 的 MCP 2026-07-28
> 協議遷移中隨整個 `src/protocol/` 一併移除（死碼），SSE 傳輸也已改為
> **Streamable HTTP**（端點 `/mcp`）。
>
> 因此本文的「同步更新 SSE 伺服器」一類步驟已無對應檔案。
>
> ⚠️ **`CORS_PREFLIGHT_MAX_AGE` 目前是死設定**：它被 `core/config.py` 讀進
> `HTTPConfig.cors_preflight_max_age`，但**沒有任何地方使用它** ——
> 唯一的使用點在已移除的 `sse_server.py`。而 `sse_server.py` 本來就是死碼
> （兩個容器的 CMD 都不經過它），所以這個設定在 live 路徑上**從未生效過**，
> 並非 2026-08-04 遷移造成的退化。`src/api/middleware.py` 的
> `CORSMiddleware` 未傳 `max_age`，實際採用 Starlette 預設值 600 秒
> —— 恰好與本設定的預設值相同，這也是它一直沒被發現的原因。
>
> 現況請看 [`docs/architecture.md`](../architecture.md)；
> 遷移紀錄在主專案 `docs/mcp-2026-07-28-migration/`。

---

## 📋 修復計劃總覽

本計劃分為 **3 個階段**，共 **15 個修復項目**：

| 階段 | 優先級 | 項目數 | 狀態 | 進度 |
|------|--------|--------|------|------|
| 第一階段 | 高 | 5 項 | ✅ 已完成 | 5/5 (100%) |
| 第二階段 | 中 | 4 項 | ✅ 已完成 | 4/4 (100%) |
| 第三階段 | 低 | 6 項 | ✅ 已完成 | 6/6 (100%) |

**整體進度**：15/15 項目完成 (100%) 🎉

### 📅 最新更新

**2025-12-31 14:00** - ✅ 第三階段完成 🎉
- 完成所有 6 個低優先級優化項目
- 4 個檔案修改（config.py、server.py、http_server.py、sse_server.py）
- Claude 模型升級至 claude-3-5-haiku-20241022
- 新增 CORS_PREFLIGHT_MAX_AGE 環境變數
- 顯示限制常量文檔化（MAX_ROWS_FOR_LLM、MAX_TABLES_PREVIEW、GZIP_MIN_SIZE）
- 完成 .env.example 更新

**2025-12-31 06:50** - ✅ 第二階段完成
- 完成所有 4 個中優先級修復項目
- 6 個檔案修改（新增 HTTPConfig、動態表格描述生成等）
- 新增 3 個環境變數支援（DB_COMMAND_TIMEOUT、RATE_LIMIT_DEFAULT、RATE_LIMIT_QUERY）
- 實現 ODBC 驅動程式自動檢測功能

**2025-12-30 23:45** - ✅ 第一階段完成
- Commit: `fcc7303` - refactor(hardcode): 完成第一階段硬編碼修復（高優先級）
- 完成所有 5 個高優先級修復項目
- 7 個檔案修改（+107/-22 行）
- 新增 4 個環境變數支援

---

## 🚨 第一階段：高優先級修復（必須完成）

### 修復項目 1.1：表格計數 "319" 錯誤

**問題描述：**
- 工具描述中硬編碼 "319 available tables"
- 實際資料庫只有 22 個表格
- 誤導使用者

**受影響檔案：**
- `src/tools/definitions.py:46`
- `src/server.py:116`

**修復步驟：**

#### Step 1.1.1：修改 `src/tools/definitions.py`

```python
# 修改前（第 46 行）：
"Provide 'table_name' for specific table details, or omit it to list all 319 available tables. "

# 修改後：
"Provide 'table_name' for specific table details, or omit it to list all available tables. "
```

#### Step 1.1.2：修改 `src/server.py`

```python
# 修改前（第 116 行）：
"Provide 'table_name' for specific table details, or omit it to list all 319 available tables. "

# 修改後：
"Provide 'table_name' for specific table details, or omit it to list all available tables. "
```

**測試方法：**
```bash
# 1. 重啟 Docker 容器
docker-compose restart mcp-db mcp-db-http

# 2. 檢查工具描述
# 在 Claude Desktop 中呼叫 db_schema 工具，查看描述是否已更新
# 或訪問 http://localhost:8000/docs 查看 API 文檔
```

**檢查點：**
- [ ] `src/tools/definitions.py` 已修改
- [ ] `src/server.py` 已修改
- [ ] 工具描述不再顯示 "319"
- [ ] 功能正常運作

---

### 修復項目 1.2：Docker 容器絕對路徑

**問題描述：**
- 硬編碼 `/app/.env` 絕對路徑
- 本地開發環境無法正確載入
- 路徑耦合於 Docker 環境

**受影響檔案：**
- `src/core/config.py:11`

**修復步驟：**

#### Step 1.2.1：修改環境變數載入邏輯

```python
# 修改前（src/core/config.py 第 10-17 行）：
if not _env_loaded:
    for env_path in ['/app/.env', '.env']:
        if Path(env_path).exists():
            load_dotenv(env_path, override=False)
            _env_loaded = True
            break

# 修改後：
if not _env_loaded:
    # 優先使用環境變數指定的路徑
    env_file = os.getenv('ENV_FILE_PATH')
    if env_file and Path(env_file).exists():
        load_dotenv(env_file, override=False)
        _env_loaded = True
    else:
        # 嘗試多個可能的路徑
        possible_paths = [
            Path.cwd() / '.env',  # 當前工作目錄
            Path(__file__).parent.parent.parent / '.env',  # 專案根目錄
            Path('/app/.env')  # Docker 容器路徑（最後嘗試）
        ]
        for env_path in possible_paths:
            if env_path.exists():
                load_dotenv(str(env_path), override=False)
                _env_loaded = True
                break
```

#### Step 1.2.2：更新 `.env.example`

```bash
# 在 .env.example 中新增說明
# ENV_FILE_PATH=  # 可選：自定義 .env 檔案路徑（預設會自動搜尋）
```

**測試方法：**
```bash
# 1. 本地測試
python -m src.server
# 應該能正確載入 .env

# 2. Docker 測試
docker-compose up -d
docker logs mcp-db-dev --tail 20
# 應該沒有 .env 載入錯誤

# 3. 自定義路徑測試
export ENV_FILE_PATH=/custom/path/.env
python -m src.server
```

**檢查點：**
- [ ] 本地開發環境可載入 `.env`
- [ ] Docker 環境可載入 `/app/.env`
- [ ] 支援 `ENV_FILE_PATH` 環境變數
- [ ] 沒有路徑相關錯誤

---

### 修復項目 1.3：緩存 TTL 不一致

**問題描述：**
- `config.py:143` 硬編碼 1440 分鐘（24小時）
- 環境變數預設 60 分鐘
- 兩個不同的預設值造成混亂

**受影響檔案：**
- `src/core/config.py:143`
- `src/database/manager.py:18`
- `src/database/schema/cache.py:18`

**修復步驟：**

#### Step 1.3.1：統一 `config.py` 中的預設值

```python
# 修改前（src/core/config.py 第 143 行）：
cache_ttl_minutes: int = Field(
    default=1440,  # 增加到 24 小時防止緩存過期
    description="Schema cache TTL in minutes"
)

# 修改後：
cache_ttl_minutes: int = Field(
    default=60,  # 預設 1 小時，與環境變數一致
    description="Schema cache TTL in minutes (default: 60)"
)
```

#### Step 1.3.2：移除誤導性註解

```python
# 移除「增加到 24 小時防止緩存過期」註解
# 如果確實需要更長的 TTL，應該透過環境變數配置
```

#### Step 1.3.3：確認其他檔案的一致性

檢查以下檔案是否使用統一的預設值：
- `src/database/manager.py:18` → 確認為 60
- `src/database/schema/cache.py:18` → 確認為 60

**測試方法：**
```bash
# 1. 不設定環境變數，使用預設值
unset SCHEMA_CACHE_TTL_MINUTES
docker-compose restart mcp-db

# 2. 呼叫 db_cache_stats 查看 TTL
# 應該顯示 60 分鐘

# 3. 設定環境變數測試
export SCHEMA_CACHE_TTL_MINUTES=120
docker-compose restart mcp-db
# 應該顯示 120 分鐘
```

**檢查點：**
- [ ] 所有預設值統一為 60 分鐘
- [ ] 移除誤導性註解
- [ ] 環境變數可正確覆蓋預設值
- [ ] 文檔已更新說明

---

### 修復項目 1.4：查詢限制硬編碼

**問題描述：**
- SQL 查詢最大字元數：50000（硬編碼）
- 查詢結果最大行數：10000（硬編碼）
- 無法根據不同場景調整

**受影響檔案：**
- `src/tools/validators.py:74, 112`
- `tests/conftest.py:26`

**修復步驟：**

#### Step 1.4.1：在 `config.py` 新增配置

```python
# 在 src/core/config.py 的 SchemaConfig 類別中新增：
max_query_length: int = Field(
    default=50000,
    description="Maximum SQL query length in characters"
)

max_query_limit: int = Field(
    default=10000,
    description="Maximum LIMIT value for query results"
)
```

#### Step 1.4.2：新增環境變數載入

```python
# 在 from_env() 方法中新增：
max_query_length=int(os.getenv("MAX_QUERY_LENGTH", "50000")),
max_query_limit=int(os.getenv("MAX_QUERY_LIMIT", "10000")),
```

#### Step 1.4.3：修改 `validators.py` 使用配置

```python
# 修改前（src/tools/validators.py 第 74 行）：
if len(query) > 50000:
    raise ValueError("Query is too long (max 50KB)")

# 修改後：
from src.core.config import get_schema_config
config = get_schema_config()
if len(query) > config.max_query_length:
    raise ValueError(f"Query is too long (max {config.max_query_length} characters)")
```

```python
# 修改前（src/tools/validators.py 第 112 行）：
if limit > 10000:
    raise ValueError("LIMIT value is too large (max 10000)")

# 修改後：
if limit > config.max_query_limit:
    raise ValueError(f"LIMIT value is too large (max {config.max_query_limit})")
```

#### Step 1.4.4：更新 `.env.example`

```bash
# 新增到 .env.example：
# MAX_QUERY_LENGTH=50000  # 最大查詢字元數
# MAX_QUERY_LIMIT=10000   # 最大查詢結果行數
```

**測試方法：**
```bash
# 1. 測試預設限制
docker-compose restart mcp-db-http
# 發送超過 50000 字元的查詢，應該被拒絕

# 2. 測試環境變數覆蓋
export MAX_QUERY_LENGTH=100000
export MAX_QUERY_LIMIT=20000
docker-compose restart mcp-db-http
# 發送 60000 字元的查詢，應該成功
```

**檢查點：**
- [ ] `config.py` 新增配置欄位
- [ ] `validators.py` 使用配置而非硬編碼
- [ ] 環境變數可正確覆蓋
- [ ] 錯誤訊息包含實際限制值
- [ ] 測試通過

---

### 修復項目 1.5：CORS 允許源檢查

**問題描述：**
- 硬編碼 `localhost:3000, localhost:8000`
- 生產環境可能不安全
- 需要確認環境變數配置

**受影響檔案：**
- `src/http_server.py:141`
- `src/protocol/sse_server.py:71`

**修復步驟：**

#### Step 1.5.1：檢查現有程式碼

```python
# 查看 src/http_server.py:141 附近
# 確認是否已支援 CORS_ALLOWED_ORIGINS 環境變數
```

#### Step 1.5.2：改善預設值安全性

```python
# 修改前：
allowed_origins = os.getenv(
    "CORS_ALLOWED_ORIGINS",
    "http://localhost:3000,http://localhost:8000"
).split(",")

# 修改後（更安全的預設）：
# 在生產環境應該明確設定，不提供不安全的預設值
cors_env = os.getenv("CORS_ALLOWED_ORIGINS", "")
if cors_env:
    allowed_origins = [origin.strip() for origin in cors_env.split(",")]
else:
    # 只在明確的開發環境才允許 localhost
    if os.getenv("ENVIRONMENT") == "development":
        allowed_origins = ["http://localhost:3000", "http://localhost:8000"]
    else:
        allowed_origins = []  # 生產環境必須明確設定
        logger.warning("CORS_ALLOWED_ORIGINS not set, CORS disabled")
```

#### Step 1.5.3：更新環境變數文檔

```bash
# 更新 .env.example：
# CORS 設定（生產環境必須設定）
CORS_ALLOWED_ORIGINS=http://localhost:3000,http://localhost:8000

# 環境標識
# ENVIRONMENT=development  # development 或 production
```

#### Step 1.5.4：同步更新 SSE 伺服器

在 `src/protocol/sse_server.py` 套用相同的修改。

**測試方法：**
```bash
# 1. 開發環境測試
export ENVIRONMENT=development
docker-compose restart mcp-db-http
curl -H "Origin: http://localhost:3000" http://localhost:8000/api/v1/health
# 應該包含 CORS 標頭

# 2. 生產環境測試（未設定 CORS）
export ENVIRONMENT=production
unset CORS_ALLOWED_ORIGINS
docker-compose restart mcp-db-http
curl -H "Origin: http://evil.com" http://localhost:8000/api/v1/health
# 不應該包含 CORS 標頭

# 3. 生產環境測試（已設定 CORS）
export CORS_ALLOWED_ORIGINS=https://your-domain.com
docker-compose restart mcp-db-http
curl -H "Origin: https://your-domain.com" http://localhost:8000/api/v1/health
# 應該包含 CORS 標頭
```

**檢查點：**
- [ ] 支援 `ENVIRONMENT` 環境變數
- [ ] 開發環境有預設 CORS 設定
- [ ] 生產環境需明確設定 CORS
- [ ] SSE 伺服器同步更新
- [ ] 文檔已更新

---

## ⚡ 第二階段：中優先級修復（建議完成）

### 修復項目 2.1：ODBC 驅動程式版本配置

**問題描述：**
- 硬編碼 "ODBC Driver 18 for SQL Server"
- 不同系統可能安裝不同版本
- 應該支援驅動程式檢測或配置

**受影響檔案：**
- `src/core/config.py:39, 81`

**修復步驟：**

#### Step 2.1.1：新增驅動程式檢測功能

```python
# 在 src/core/config.py 新增驅動程式檢測函數
import pyodbc

def detect_mssql_driver() -> str:
    """檢測系統可用的 MSSQL ODBC 驅動程式"""
    available_drivers = pyodbc.drivers()

    # 優先順序：Driver 18 > Driver 17 > Driver 13
    preferred_drivers = [
        "ODBC Driver 18 for SQL Server",
        "ODBC Driver 17 for SQL Server",
        "ODBC Driver 13 for SQL Server",
    ]

    for driver in preferred_drivers:
        if driver in available_drivers:
            return driver

    # 如果都找不到，嘗試找任何 SQL Server 驅動程式
    for driver in available_drivers:
        if "SQL Server" in driver:
            return driver

    # 都找不到則使用預設值（會在連接時失敗）
    return "ODBC Driver 18 for SQL Server"
```

#### Step 2.1.2：在配置初始化時使用檢測

```python
# 修改 Field default
driver: str = Field(
    default_factory=detect_mssql_driver,  # 使用檢測結果
    description="MSSQL ODBC driver name"
)
```

#### Step 2.1.3：環境變數仍可覆蓋

```python
# 在 from_env() 中保持環境變數優先
driver=os.getenv("MSSQL_DRIVER") or detect_mssql_driver()
```

**測試方法：**
```bash
# 1. 列出系統可用驅動程式
python -c "import pyodbc; print(pyodbc.drivers())"

# 2. 測試自動檢測
unset MSSQL_DRIVER
python -m src.server
# 查看日誌，應該使用檢測到的驅動程式

# 3. 測試環境變數覆蓋
export MSSQL_DRIVER="ODBC Driver 17 for SQL Server"
python -m src.server
# 應該使用 Driver 17
```

**檢查點：**
- [ ] 新增驅動程式檢測函數
- [ ] 自動檢測可用驅動程式
- [ ] 環境變數仍可覆蓋
- [ ] 記錄使用的驅動程式版本
- [ ] 多種驅動程式版本測試通過

---

### 修復項目 2.2：異步連接器超時統一

**問題描述：**
- `aioodbc` 超時：30 秒（硬編碼）
- `asyncpg` 超時：60 秒（硬編碼）
- 不一致且無法配置

**受影響檔案：**
- `src/database/async_connectors.py:75, 188`

**修復步驟：**

#### Step 2.2.1：在 `config.py` 新增異步超時配置

```python
# 在 DatabaseConfig 類別中新增
command_timeout: int = Field(
    default=60,
    description="Async database command timeout in seconds"
)
```

#### Step 2.2.2：環境變數載入

```python
# 在 from_env() 中新增
command_timeout=int(os.getenv("DB_COMMAND_TIMEOUT", "60"))
```

#### Step 2.2.3：修改 `async_connectors.py`

```python
# 修改前（第 75 行附近）：
timeout=30

# 修改後：
timeout=self.config.command_timeout

# 修改前（第 188 行附近）：
command_timeout=60

# 修改後：
command_timeout=self.config.command_timeout
```

#### Step 2.2.4：更新 `.env.example`

```bash
# DB_COMMAND_TIMEOUT=60  # 異步資料庫命令超時（秒）
```

**測試方法：**
```bash
# 1. 測試預設超時
docker-compose restart mcp-db
# 執行慢查詢，應該在 60 秒後超時

# 2. 測試自定義超時
export DB_COMMAND_TIMEOUT=120
docker-compose restart mcp-db
# 慢查詢應該在 120 秒後超時
```

**檢查點：**
- [ ] 新增 `command_timeout` 配置
- [ ] MSSQL 和 PostgreSQL 使用相同超時
- [ ] 環境變數可覆蓋
- [ ] 超時功能正常運作

---

### 修復項目 2.3：速率限制配置化

**問題描述：**
- 全局限制：`100/minute`（硬編碼）
- 查詢限制：`30/minute`（硬編碼）
- 無法根據環境調整

**受影響檔案：**
- `src/api/middleware.py:10`
- `src/http_server.py:344`

**修復步驟：**

#### Step 2.3.1：在 `config.py` 新增速率限制配置

```python
# 新增一個 HTTPConfig 類別或在現有類別中新增
rate_limit_default: str = Field(
    default="100/minute",
    description="Default rate limit"
)

rate_limit_query: str = Field(
    default="30/minute",
    description="Rate limit for query endpoints"
)
```

#### Step 2.3.2：環境變數載入

```python
rate_limit_default=os.getenv("RATE_LIMIT_DEFAULT", "100/minute")
rate_limit_query=os.getenv("RATE_LIMIT_QUERY", "30/minute")
```

#### Step 2.3.3：修改 middleware 和 server

```python
# src/api/middleware.py
from src.core.config import get_http_config
config = get_http_config()

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[config.rate_limit_default]
)
```

```python
# src/http_server.py
@limiter.limit(config.rate_limit_query)
async def query_endpoint():
    ...
```

#### Step 2.3.4：更新 `.env.example`

```bash
# 速率限制設定
# RATE_LIMIT_DEFAULT=100/minute  # 全局速率限制
# RATE_LIMIT_QUERY=30/minute     # 查詢端點速率限制
```

**測試方法：**
```bash
# 1. 測試預設限制
for i in {1..101}; do curl http://localhost:8000/api/v1/health; done
# 第 101 次應該被限制

# 2. 測試自定義限制
export RATE_LIMIT_DEFAULT=10/minute
docker-compose restart mcp-db-http
for i in {1..11}; do curl http://localhost:8000/api/v1/health; done
# 第 11 次應該被限制
```

**檢查點：**
- [ ] 新增速率限制配置
- [ ] 環境變數可覆蓋
- [ ] 不同端點可設定不同限制
- [ ] 限制功能正常運作

---

### 修復項目 2.4：工具描述中的表格名稱動態化

**問題描述：**
- 硬編碼表格名稱範例（SALE00, SALE01 等）
- 不同資料庫有不同的主要表格
- 應該從配置或資料庫動態生成

**受影響檔案：**
- `src/tools/definitions.py:20, 47`
- `src/server.py:90, 117`

**修復步驟：**

#### Step 2.4.1：從 schema config 讀取主要表格

```python
# 在初始化時讀取 schemas_config/tables_list.json
def get_key_tables_description() -> str:
    """從配置或資料庫取得主要表格說明"""
    try:
        # 嘗試從 schemas_config 讀取
        tables_list_path = Path("schemas_config/tables_list.json")
        if tables_list_path.exists():
            with open(tables_list_path) as f:
                tables_data = json.load(f)
                # 取前 3-5 個主要表格
                key_tables = tables_data.get("key_tables", [])[:5]
                if key_tables:
                    examples = ", ".join([
                        f"{t['name']} ({t.get('description', '')})"
                        for t in key_tables
                    ])
                    return f"Key tables: {examples}, etc."
    except Exception:
        pass

    # Fallback 到通用說明
    return "Use db_schema_summary to discover available tables."
```

#### Step 2.4.2：在工具定義中使用動態描述

```python
# 修改前：
"Common tables: SALE00 (sales master), SALE01 (sales detail), PRODUCT00, etc."

# 修改後：
key_tables_desc = get_key_tables_description()
description = (
    "Execute a SELECT query on SQL Server (MSSQL) database and return results. "
    "READ-ONLY: Only SELECT queries are supported. "
    "\n\n"
    "DATABASE TYPE: Microsoft SQL Server (T-SQL syntax)\n"
    "...\n"
    f"{key_tables_desc}"
)
```

**測試方法：**
```bash
# 1. 有 tables_list.json 的情況
# 確認 schemas_config/tables_list.json 存在且包含 key_tables
docker-compose restart mcp-db
# 查看工具描述應該包含實際的主要表格

# 2. 沒有 tables_list.json 的情況
mv schemas_config/tables_list.json schemas_config/tables_list.json.bak
docker-compose restart mcp-db
# 應該顯示 fallback 訊息
mv schemas_config/tables_list.json.bak schemas_config/tables_list.json
```

**檢查點：**
- [ ] 新增動態描述生成函數
- [ ] 從 tables_list.json 讀取主要表格
- [ ] Fallback 機制正常運作
- [ ] 工具描述準確反映實際表格

---

## 📋 第三階段：低優先級優化（可選）

### 修復項目 3.1：Claude 模型版本更新

**問題描述：**
- 使用 `claude-3-haiku-20240307`（較舊）
- 建議更新到更新的模型

**受影響檔案：**
- `src/core/config.py:190, 213`

**修復步驟：**

檢查最新可用的 Claude 模型版本並更新：

```python
# 修改前：
model: str = Field(default="claude-3-haiku-20240307", ...)

# 修改後（檢查最新版本）：
model: str = Field(default="claude-3-5-haiku-20241022", ...)
```

**檢查點：**
- [ ] 確認最新模型版本
- [ ] 更新預設模型
- [ ] 測試 AI 功能正常運作
- [ ] 更新文檔

---

### 修復項目 3.2：CORS Preflight Max-Age 配置化

**受影響檔案：**
- `src/protocol/sse_server.py:142`

**修復步驟：**

```python
# 新增環境變數
cors_preflight_max_age = int(os.getenv("CORS_PREFLIGHT_MAX_AGE", "600"))

# 使用配置
headers["Access-Control-Max-Age"] = str(cors_preflight_max_age)
```

---

### 修復項目 3.3：顯示限制常量文檔化

**受影響檔案：**
- `src/server.py:328` (200 行顯示限制)
- `src/server.py:664` (前 10 個表格)
- `src/http_server.py:157` (GZip 1000 字節)

**修復步驟：**

新增常數定義並加上文檔註解：

```python
# Display limits for LLM context optimization
MAX_ROWS_FOR_LLM = 200  # Maximum rows to display in LLM context
MAX_TABLES_PREVIEW = 10  # Number of tables to show in preview
GZIP_MIN_SIZE = 1000    # Minimum response size for GZip compression (bytes)
```

---

### 修復項目 3.4 - 3.6：其他小型優化

這些項目包括：
- 3.4：統一日誌格式
- 3.5：錯誤訊息改善
- 3.6：配置驗證增強

詳細步驟可在實施時補充。

---

## 📊 執行追蹤表

### ✅ 第一階段（高優先級）- 已完成 🎉

**完成日期**：2025-12-30
**Commit**：fcc7303 - refactor(hardcode): 完成第一階段硬編碼修復（高優先級）

- [x] 1.1：表格計數 "319" 錯誤 ✅
- [x] 1.2：Docker 容器絕對路徑 ✅
- [x] 1.3：緩存 TTL 不一致 ✅
- [x] 1.4：查詢限制硬編碼 ✅
- [x] 1.5：CORS 允許源檢查 ✅

**成果**：
- 7 個檔案修改（+107/-22 行）
- 新增 4 個環境變數支援
- 提升安全性、可配置性和環境可移植性

### ✅ 第二階段（中優先級）- 已完成 🎉

**完成日期**：2025-12-31
**修改檔案**：
- src/core/config.py - 新增 HTTPConfig、ODBC 驅動檢測、command_timeout
- src/database/async_connectors.py - 統一超時配置
- src/api/middleware.py - 使用配置的速率限制
- src/http_server.py - 導入 HTTPConfig，使用配置的速率限制
- src/tools/definitions.py - 新增動態表格描述生成函數
- src/server.py - 使用動態表格描述
- .env.example - 新增環境變數說明

- [x] 2.1：ODBC 驅動程式版本配置 ✅
- [x] 2.2：異步連接器超時統一 ✅
- [x] 2.3：速率限制配置化 ✅
- [x] 2.4：工具描述表格名稱動態化 ✅

**成果**：
- 6 個檔案修改
- 新增 3 個環境變數支援
- ODBC 驅動程式自動檢測（Driver 18 > 17 > 13）
- 統一異步超時為 60 秒（可配置）
- 速率限制完全可配置
- 工具描述從 schemas_config 動態讀取表格資訊

### ✅ 第三階段（低優先級）- 已完成 🎉

**完成日期**：2025-12-31
**修改檔案**：
- src/core/config.py - Claude 模型升級、CORS preflight 配置
- src/protocol/sse_server.py - 使用配置的 CORS max-age
- src/server.py - 新增顯示限制常量
- src/http_server.py - 新增 GZip 常量
- .env.example - 新增環境變數說明

- [x] 3.1：Claude 模型版本更新 ✅
- [x] 3.2：CORS Preflight Max-Age 配置化 ✅
- [x] 3.3：顯示限制常量文檔化 ✅
- [x] 3.4：統一日誌格式 ✅ (現有實現已使用 logger)
- [x] 3.5：錯誤訊息改善 ✅ (現有實現已清晰)
- [x] 3.6：配置驗證增強 ✅ (使用 Pydantic 自動驗證)

**成果**：
- Claude 模型從 claude-3-haiku-20240307 升級至 claude-3-5-haiku-20241022
- CORS preflight max-age 可配置（預設 600 秒）
- 新增 3 個常量：MAX_ROWS_FOR_LLM (200)、MAX_TABLES_PREVIEW (10)、GZIP_MIN_SIZE (1000)
- 程式碼可讀性和可維護性提升

---

## 🧪 整體測試計劃

完成所有修復後，執行以下整體測試：

### 1. 功能測試
```bash
# 啟動所有服務
docker-compose up -d

# 測試 MCP 工具
python test_mcp_tools.py

# 測試 HTTP API
curl http://localhost:8000/docs
```

### 2. 環境變數測試
```bash
# 建立測試環境變數檔案
cp .env.example .env.test

# 修改各種配置值
# 重啟服務並驗證配置生效
```

### 3. 回歸測試
```bash
# 執行所有單元測試
pytest tests/ -v

# 檢查測試覆蓋率
pytest --cov=src tests/
```

---

## 📚 相關文檔更新

完成修復後，需要更新以下文檔：

1. **README.md**
   - 更新環境變數列表
   - 新增配置說明

2. **.env.example**
   - 新增所有新的環境變數
   - 加上詳細註解

3. **docs/configuration.md**
   - 完整的配置選項說明
   - 各選項的預設值和影響

4. **CHANGELOG.md**
   - 記錄所有修復項目
   - 標註 Breaking Changes（如有）

---

## 🎯 預期成果

完成所有修復後，專案將達到：

✅ **無硬編碼業務數據**：所有數字和名稱都動態獲取或可配置
✅ **環境可移植性**：本地、Docker、生產環境都可正常運作
✅ **高度可配置性**：透過環境變數控制所有關鍵參數
✅ **一致性**：預設值、超時、限制等都統一且有文檔
✅ **安全性**：CORS、速率限制等有合理的預設和警告
✅ **可維護性**：程式碼清晰，配置集中，易於理解和修改

---

## 💡 注意事項

1. **向後兼容性**：修改環境變數名稱時要考慮舊配置的兼容
2. **測試覆蓋**：每個修復都應該有對應的測試
3. **文檔同步**：程式碼修改要同步更新文檔
4. **版本控制**：建議每完成一個階段就建立一個 commit
5. **生產部署**：完成後在測試環境充分驗證再部署到生產

---

**最後更新**：2025-12-31
**狀態**：✅ 已完成所有三個階段
**實際時間**：第一階段 2 小時，第二階段 3 小時，第三階段 1.5 小時
