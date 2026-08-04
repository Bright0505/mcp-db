# 測試指南

## 📋 概述

MCP Multi-Database Connector 提供完整的測試套件，包括單元測試和整合測試，確保所有核心功能穩定可靠。

## 🧪 測試架構

### 測試類型

```
tests/
├── unit/                             # 單元測試
│   ├── test_validators.py            # SQL 驗證器（含安全攔截）
│   ├── test_schema_cache.py          # Schema 快取（LFU+LRU、TTL、預載）
│   ├── test_async_manager.py         # 異步資料庫管理
│   └── test_env_prefix.py            # TOOL_PREFIX 環境變數行為
└── integration/                      # 整合測試
    ├── test_api_endpoints.py         # REST API 端點
    └── test_mcp_protocol.py          # MCP 協議層（三層設計，見下）
```

## ✅ 測試統計

> **本檔不再內嵌測試數與覆蓋率數字。** 舊版寫死「101 個測試／27% 覆蓋率」，
> 在測試增加後就與現況不符，而文件本身無從察覺。請直接實測：

```bash
docker exec {module}-http python -m pytest /app/tests -q --cov=src --cov-report=term
```

（開發用容器名為 `{module}-http-dev`；正式 image 若未包含 `tests/` 與 pytest，
請改在開發 compose 下執行。）

### 覆蓋率的重點模組

覆蓋率不平均是刻意的 —— 安全與協議相關的模組維持高覆蓋，
純 I/O 包裝與格式化模組偏低：

| 模組 | 為什麼重要 |
|------|-----------|
| `tools/validators.py` | SQL 安全攔截的唯一入口（含門市／關鍵字管制），必須高覆蓋 |
| `tools/registry.py` | 工具路由，錯了會整批工具失效 |
| `database/async_manager.py` | 連線池與並發查詢 |
| `database/schema/cache.py` | 快取正確性直接影響回答是否用到舊 schema |
| `http_server.py` | REST 與 MCP 兩個對外面 |

### 測試模組說明

#### 1. test_validators.py

測試 SQL 安全驗證功能：
- SQL 注入防護
- 輸入驗證
- 安全邊緣案例

**關鍵測試**：
- 阻止危險 SQL 語句（DELETE, DROP, EXEC 等）
- SQL 注入攻擊防護（UNION, 註解等）
- 輸入長度和格式驗證

#### 2. test_schema_cache.py

測試 Schema 快取系統：
- 基本快取操作（設定、取得、失效）
- LFU+LRU 淘汰策略
- TTL 過期機制
- 並行預載
- 靜態 Schema 載入

**關鍵測試**：
- 快取命中/未命中
- 多層快取查詢（靜態→動態→資料庫）
- 線程安全性
- 性能測試

#### 3. test_async_manager.py

測試異步資料庫管理：
- 異步連接池
- 並發查詢執行
- 錯誤處理
- 敏感資訊保護

**關鍵測試**：
- 連接池重用
- 並發查詢執行
- 連接失敗處理
- 查詢錯誤處理

#### 4. test_env_prefix.py

測試 `TOOL_PREFIX` 環境變數如何影響工具名稱生成（`make_tool_name()`），
確保同一份程式碼在不同模組下產生正確的工具名。

## 🔌 MCP 協議層測試（test_mcp_protocol.py）

協議層在 2026-08-04 的遷移前**覆蓋率為 0** —— 沒有任何測試會在 transport
或 SDK 行為改變時失敗。這個檔案補上該守備，分三層：

| 層 | 驗證什麼 | 是否經過 HTTP |
|----|---------|--------------|
| 第 1 層 | 工具定義契約：名稱、`inputSchema` 形狀、JSON Schema 版本 | ❌ |
| 第 2 層 | handler 契約：`on_list_tools` / `on_call_tool` 的回傳型別、錯誤路徑 | ❌ |
| 第 3 層 | **兩個協議世代並存**：同一個 `/mcp` 端點分別以 `initialize` handshake 與無 handshake 的 2026-07-28 請求打進去 | ✅ |

第 3 層是不可省的：前兩層都在 handler 契約層驗證、不經過 HTTP，因此抓不到
「transport 換掉之後某個世代不通」這類問題 —— 而目前的部署正好依賴兩個世代並存
（MCPO 走 handshake 世代）。

第 3 層涵蓋的細節包含：

- 2026-07-28 請求缺少 `params._meta` 信封 → 必須回 **400 + `-32602`**
- `Mcp-Method` header 與 body 的 `method` 不一致 → 必須回 **400 + `-32020`**
- `cache_hints` 是否真的出現在線上回應（SDK 在 dispatch 時套用，不是在 handler 回傳值裡）
- 宣告的 `ttlMs` 必須 ≤ 1 小時（客戶端快取無法遠端失效，過長會讓白名單變更延遲生效）

> 負向測試刻意斷言**確切**狀態碼與 error code，而不是 `>= 400`：
> 用範圍斷言時，一個「端點根本不存在」的 404 也會讓測試通過。

## 🚀 執行測試

### 在 Docker 容器中執行

```bash
# 執行全部測試（單元 + 整合，含協議層）
docker exec mcp-db-http-dev pytest /app/tests -q

# 只跑單元測試
docker exec mcp-db-http-dev pytest /app/tests/unit/ -v

# 只跑協議層測試（改動 transport 或 SDK 版本後必跑）
docker exec mcp-db-http-dev pytest /app/tests/integration/test_mcp_protocol.py -v

# 執行特定測試文件
docker exec mcp-db-http-dev pytest /app/tests/unit/test_validators.py -v

# 執行帶覆蓋率報告的測試
docker exec mcp-db-http-dev pytest /app/tests \
  --cov=/app/src \
  --cov-report=term \
  --cov-report=html

# 查看 HTML 覆蓋率報告
# 報告位置：/app/htmlcov/index.html
```

> ⚠️ 正式（production target）image 不包含 `tests/` 與 pytest，
> 上述指令請對開發容器執行。

### 本地執行（需配置環境）

```bash
# 安裝測試依賴（含 constraints 以對齊 image 內版本）
pip install -c constraints.txt pytest pytest-asyncio pytest-cov

# 執行測試
pytest tests -q

# 執行帶覆蓋率報告
pytest tests --cov=src --cov-report=html
```

## 🔧 配置說明

### pytest 配置

測試配置位於 `pyproject.toml`：

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
```

這個配置確保異步測試正常運行。

### 必要依賴

```toml
[project.optional-dependencies]
dev = [
    "pytest>=7.0.0",
    "pytest-asyncio>=0.21.0",
    "pytest-cov>=4.0.0",
]
```

## 📊 測試覆蓋重點

### ✅ 完全覆蓋
- SQL 注入防護
- 輸入驗證
- 異步查詢執行
- 連接池管理
- 敏感資訊保護
- **MCP 協議層**（工具定義契約、handler 契約、兩世代 HTTP 相容性）
- **REST API 端點**（`test_api_endpoints.py`）

### ⚠️ 部分覆蓋
- Schema 快取系統
- LFU+LRU 淘汰策略
- 靜態 Schema 載入器
- 資料庫配置管理
- Tool Handlers（協議層測試會經過它們，但缺少各 handler 的專屬測試）

### ❌ 未覆蓋（未來改進）
- stdio 進入點（`server.py`）—— 只有 HTTP 進入點有協議層測試；
  兩者的 handler 邏輯是複製關係而非共用，因此 stdio 側改動不會被測試攔住
- Schema 格式化器（`database/schema/formatter.py`）
- 資料庫內省（`database/schema/introspector.py`）—— 需要真實資料庫
- **端到端**：Open WebUI → LiteLLM → MCPO → 模組的完整路徑無自動化測試

## 🎯 測試最佳實踐

### 1. 測試命名規範

```python
def test_valid_simple_select():          # ✅ 清晰的測試名稱
    """測試簡單的 SELECT 查詢驗證"""
    pass

def test_reject_delete_query():         # ✅ 清晰描述預期行為
    """測試拒絕 DELETE 語句"""
    pass
```

### 2. 使用 Fixtures

```python
@pytest.fixture
def mock_db_manager():
    """Mock 資料庫管理器"""
    manager = Mock()
    manager.test_connection.return_value = {"success": True}
    return manager
```

### 3. 異步測試

```python
@pytest.mark.asyncio
async def test_async_function():
    """測試異步函數"""
    result = await some_async_function()
    assert result is not None
```

## 📈 CI/CD 整合

### GitHub Actions 範例

```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: '3.11'
      - name: Install dependencies
        run: |
          pip install -c constraints.txt -e .
          pip install -c constraints.txt pytest pytest-asyncio pytest-cov
      - name: Run tests
        run: |
          pytest tests \
            --cov=src \
            --cov-report=xml \
            --cov-fail-under=40
      - name: Upload coverage
        uses: codecov/codecov-action@v2
```

## 🐛 故障排除

### 常見問題

#### 1. 異步測試失敗

**問題**: `SyntaxError: 'await' outside async function`

**解決方案**:
```bash
# 確保已安裝 pytest-asyncio
pip install pytest-asyncio

# 檢查 pyproject.toml 配置
[tool.pytest.ini_options]
asyncio_mode = "auto"
```

#### 2. 導入錯誤

**問題**: `ModuleNotFoundError: No module named 'src'`

**解決方案**:
```bash
# 在容器中執行測試
docker exec mcp-db-http-dev pytest /app/tests/unit/ -v

# 或設置 PYTHONPATH
export PYTHONPATH=/app/src
pytest tests/unit/ -v
```

#### 3. 資料庫連接失敗（整合測試）

**問題**: 整合測試需要真實資料庫連接

**解決方案**:
- 使用 Mock 物件進行單元測試
- 整合測試需要配置 .env 文件
- 或使用測試資料庫

## 📋 未來改進計劃

### 短期
- [ ] 提升 schema/cache.py 覆蓋率至 80%
- [ ] 修復整合測試（test_api_endpoints.py）
- [ ] 添加 Tool Handlers 單元測試

### 中期
- [ ] E2E 測試框架
- [ ] CI/CD 整合
- [ ] 性能基準測試

### 長期
- [ ] 負載測試
- [ ] 跨平台測試
- [ ] 覆蓋率監控儀表板

## 📚 參考資源

- [pytest 文檔](https://docs.pytest.org/)
- [pytest-asyncio 文檔](https://pytest-asyncio.readthedocs.io/)
- [pytest-cov 文檔](https://pytest-cov.readthedocs.io/)

---

**最後更新**：2026-08-04（新增 MCP 協議層測試；移除已過時的內嵌測試數與覆蓋率）
