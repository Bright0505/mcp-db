"""
HTTP API 端點整合測試

測試 FastAPI HTTP 伺服器的所有 API 端點功能。
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi.testclient import TestClient


class TestHealthEndpoint:
    """健康檢查端點測試"""

    @pytest.fixture
    def mock_db_manager(self):
        """Mock 資料庫管理器"""
        manager = Mock()
        manager.test_connection.return_value = {"success": True}
        return manager

    @pytest.fixture
    def test_client(self, mock_db_manager):
        """創建測試客戶端"""
        with patch("http_server.HybridDatabaseManager") as MockManager:
            MockManager.create_with_preload.return_value = mock_db_manager

            from http_server import MCPHTTPServer

            server = MCPHTTPServer()
            server.db_manager = mock_db_manager
            server._register_routes()

            return TestClient(server.app)

    def test_health_check_success(self, test_client):
        """✅ 健康檢查成功"""
        response = test_client.get("/api/v1/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ["healthy", "ok"]
        assert "version" in data
        assert "timestamp" in data

    def test_health_check_contains_db_status(self, test_client):
        """✅ 健康檢查包含資料庫狀態"""
        response = test_client.get("/api/v1/health")

        assert response.status_code == 200
        data = response.json()
        assert "database_connected" in data


class TestConnectionEndpoint:
    """連接測試端點測試"""

    @pytest.fixture
    def mock_db_manager(self):
        """Mock 資料庫管理器"""
        manager = AsyncMock()
        manager.test_connection_async = AsyncMock(return_value={
            "success": True,
            "message": "Connection successful",
            "server_info": {
                "database": "testdb",
                "connected": True
            }
        })
        return manager

    @pytest.fixture
    def test_client(self, mock_db_manager):
        """創建測試客戶端"""
        with patch("http_server.HybridDatabaseManager") as MockManager:
            MockManager.create_with_preload.return_value = mock_db_manager

            from http_server import MCPHTTPServer

            server = MCPHTTPServer()
            server.db_manager = mock_db_manager
            server._register_routes()

            return TestClient(server.app)

    def test_connection_test_success(self, test_client):
        """✅ 連接測試成功"""
        response = test_client.get("/api/v1/connection/test")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "data" in data or "message" in data

    def test_connection_test_includes_server_info(self, test_client, mock_db_manager):
        """✅ 連接測試包含伺服器資訊"""
        response = test_client.get("/api/v1/connection/test")

        assert response.status_code == 200
        # 驗證異步方法被調用
        mock_db_manager.test_connection_async.assert_called()


class TestQueryEndpoint:
    """查詢端點測試"""

    @pytest.fixture
    def mock_db_manager(self):
        """Mock 資料庫管理器"""
        manager = AsyncMock()
        manager.execute_query_async = AsyncMock(return_value={
            "success": True,
            "results": [
                {"id": 1, "name": "Alice"},
                {"id": 2, "name": "Bob"}
            ],
            "columns": ["id", "name"],
            "row_count": 2
        })
        return manager

    @pytest.fixture
    def test_client(self, mock_db_manager):
        """創建測試客戶端"""
        with patch("http_server.HybridDatabaseManager") as MockManager:
            with patch("http_server.SQLValidator") as MockValidator:
                MockValidator.validate_query.return_value = (True, "")
                MockManager.create_with_preload.return_value = mock_db_manager

                from http_server import MCPHTTPServer

                server = MCPHTTPServer()
                server.db_manager = mock_db_manager
                server._register_routes()

                return TestClient(server.app)

    def test_query_execution_success(self, test_client):
        """✅ 查詢執行成功"""
        response = test_client.post(
            "/api/v1/query",
            json={"query": "SELECT * FROM users"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "data" in data

    def test_query_with_results(self, test_client, mock_db_manager):
        """✅ 查詢返回結果"""
        response = test_client.post(
            "/api/v1/query",
            json={"query": "SELECT * FROM users"}
        )

        assert response.status_code == 200
        data = response.json()

        # 驗證異步查詢被調用
        mock_db_manager.execute_query_async.assert_called()

    def test_query_with_params(self, test_client, mock_db_manager):
        """✅ 帶參數的查詢"""
        response = test_client.post(
            "/api/v1/query",
            json={
                "query": "SELECT * FROM users WHERE id = ?",
                "params": [1]
            }
        )

        assert response.status_code == 200
        # 驗證參數被傳遞
        call_args = mock_db_manager.execute_query_async.call_args
        assert call_args is not None

    def test_query_validation_failure(self, test_client):
        """❌ 查詢驗證失敗 —— 錯誤走 response body，HTTP status 仍為 200

        這是刻意的設計（見 http_server.py 的 `_error_response`）：REST 層以
        `success: false` + `error` 表達失敗，不使用 4xx/5xx。理由是下游的
        Open WebUI Workspace Tools 都在檢查 body 的 `data.success`，
        改用 HTTP status 會破壞它們。

        因此本測試斷言的是 **body 語意**：失敗必須明確標示，且必須帶出可讀的原因
        （避免退回成「回 200 但看起來像空結果」的錯誤遮蔽問題）。
        """
        with patch("http_server.SQLValidator") as MockValidator:
            MockValidator.validate_query.return_value = (False, "Dangerous keyword 'DROP' not allowed")

            response = test_client.post(
                "/api/v1/query",
                json={"query": "DROP TABLE users"}
            )

            assert response.status_code == 200
            body = response.json()
            assert body["success"] is False
            assert body.get("error"), "驗證失敗必須帶出錯誤訊息，不可只有 success: false"
            assert "DROP" in body["error"], f"錯誤訊息應包含實際原因，實際為: {body['error']}"

    def test_query_missing_query_param(self, test_client):
        """❌ 缺少查詢參數"""
        response = test_client.post(
            "/api/v1/query",
            json={}
        )

        assert response.status_code == 422  # Validation error


class TestSchemaEndpoints:
    """Schema 端點測試"""

    @pytest.fixture
    def mock_db_manager(self):
        """Mock 資料庫管理器"""
        manager = Mock()
        manager.get_schema_info.return_value = {
            "success": True,
            "results": [
                {"TABLE_NAME": "users"},
                {"TABLE_NAME": "orders"}
            ]
        }
        manager.get_table_dependencies.return_value = {
            "success": True,
            "dependencies": []
        }
        manager.get_schema_summary.return_value = {
            "success": True,
            "summary": [
                {"OBJECT_TYPE": "Tables", "COUNT": 10}
            ]
        }
        return manager

    @pytest.fixture
    def test_client(self, mock_db_manager):
        """創建測試客戶端"""
        with patch("http_server.HybridDatabaseManager") as MockManager:
            MockManager.create_with_preload.return_value = mock_db_manager

            from http_server import MCPHTTPServer

            server = MCPHTTPServer()
            server.db_manager = mock_db_manager
            server._register_routes()

            return TestClient(server.app)

    def test_get_all_schemas(self, test_client):
        """✅ 獲取所有 schema"""
        response = test_client.get("/api/v1/schema")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_get_table_schema(self, test_client, mock_db_manager):
        """✅ 獲取特定表格 schema"""
        response = test_client.get("/api/v1/schema/users")

        assert response.status_code == 200
        # 驗證正確的表格名稱被傳遞
        mock_db_manager.get_schema_info.assert_called()

    def test_get_table_dependencies(self, test_client, mock_db_manager):
        """✅ 獲取表格依賴關係"""
        response = test_client.get("/api/v1/dependencies/orders")

        assert response.status_code == 200
        mock_db_manager.get_table_dependencies.assert_called_with("orders")

    def test_get_schema_summary(self, test_client):
        """✅ 獲取 schema 摘要"""
        response = test_client.get("/api/v1/summary")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True


class TestCacheEndpoints:
    """快取管理端點測試"""

    @pytest.fixture
    def mock_db_manager(self):
        """Mock 資料庫管理器"""
        manager = Mock()
        manager.get_cache_stats.return_value = {
            "success": True,
            "cache_size": 10,
            "hit_rate": 0.85
        }
        manager.get_cache_debug_info.return_value = {
            "success": True,
            "debug_info": {"total_keys": 10}
        }
        manager.invalidate_schema_cache.return_value = {
            "success": True,
            "message": "Cache invalidated"
        }
        manager.reload_schema_config.return_value = {
            "success": True,
            "message": "Schema config reloaded"
        }
        manager.get_static_schema_info.return_value = {
            "success": True,
            "static_tables": []
        }
        return manager

    @pytest.fixture
    def test_client(self, mock_db_manager):
        """創建測試客戶端"""
        with patch("http_server.HybridDatabaseManager") as MockManager:
            MockManager.create_with_preload.return_value = mock_db_manager

            from http_server import MCPHTTPServer

            server = MCPHTTPServer()
            server.db_manager = mock_db_manager
            server._register_routes()

            return TestClient(server.app)

    def test_get_cache_stats(self, test_client):
        """✅ 獲取快取統計"""
        response = test_client.get("/api/v1/cache/stats")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_get_cache_debug_info(self, test_client):
        """✅ 獲取快取調試資訊"""
        response = test_client.get("/api/v1/admin/cache-debug")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_invalidate_cache_all(self, test_client, mock_db_manager):
        """✅ 清除所有快取"""
        response = test_client.post("/api/v1/cache/invalidate", json={})

        assert response.status_code == 200
        mock_db_manager.invalidate_schema_cache.assert_called_with(None)

    def test_invalidate_cache_specific_table(self, test_client, mock_db_manager):
        """✅ 清除特定表格快取"""
        response = test_client.post(
            "/api/v1/cache/invalidate",
            json={"table_name": "users"}
        )

        assert response.status_code == 200
        mock_db_manager.invalidate_schema_cache.assert_called_with("users")

    def test_reload_schema_config(self, test_client):
        """✅ 重載 schema 配置"""
        response = test_client.post("/api/v1/schema/reload")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

    def test_get_static_schema_info(self, test_client):
        """✅ 獲取靜態 schema 資訊"""
        response = test_client.get("/api/v1/schema/static/info")

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True


class TestToolsEndpoint:
    """工具列表端點測試"""

    @pytest.fixture
    def test_client(self):
        """創建測試客戶端"""
        with patch("http_server.HybridDatabaseManager") as MockManager:
            mock_db_manager = Mock()
            MockManager.create_with_preload.return_value = mock_db_manager

            from http_server import MCPHTTPServer

            server = MCPHTTPServer()
            server.db_manager = mock_db_manager
            server._register_routes()

            return TestClient(server.app)

    def test_get_tools_list(self, test_client):
        """✅ 獲取工具列表"""
        response = test_client.get("/api/v1/tools")

        assert response.status_code == 200
        data = response.json()
        assert "tools" in data or "data" in data


class TestRateLimiting:
    """請求限流測試"""

    @pytest.fixture
    def test_client(self):
        """創建測試客戶端（啟用限流）"""
        with patch("http_server.HybridDatabaseManager") as MockManager:
            mock_db_manager = Mock()
            mock_db_manager.test_connection.return_value = {"success": True}
            MockManager.create_with_preload.return_value = mock_db_manager

            from http_server import MCPHTTPServer

            server = MCPHTTPServer()
            server.db_manager = mock_db_manager
            server._register_routes()

            return TestClient(server.app)

    def test_rate_limit_enforcement(self, test_client):
        """⚠️ 請求限流執行（概念測試）"""
        # 注意：這個測試可能需要實際配置 slowapi 限流器
        # 這裡只是驗證端點可以正常訪問

        # 快速發送多個請求
        responses = []
        for _ in range(5):
            response = test_client.get("/api/v1/health")
            responses.append(response)

        # 至少前幾個請求應該成功
        assert responses[0].status_code == 200
        assert responses[1].status_code == 200


class TestErrorHandling:
    """錯誤處理測試"""

    @pytest.fixture
    def test_client_with_failing_db(self):
        """創建帶失敗資料庫的測試客戶端"""
        with patch("http_server.HybridDatabaseManager") as MockManager:
            mock_db_manager = AsyncMock()
            mock_db_manager.execute_query_async = AsyncMock(
                side_effect=Exception("Database error")
            )
            MockManager.create_with_preload.return_value = mock_db_manager

            from http_server import MCPHTTPServer

            server = MCPHTTPServer()
            server.db_manager = mock_db_manager
            server._register_routes()

            return TestClient(server.app)

    def test_database_error_handling(self, test_client_with_failing_db):
        """❌ 資料庫錯誤處理 —— 錯誤走 response body，HTTP status 仍為 200

        同 `test_query_validation_failure`：REST 層刻意不使用 4xx/5xx。
        重點在於 DB 失敗**不可**被包成看起來成功的空結果 —— 這正是
        `_wrap_result` 要解決的問題（在它之前外層 `success` 恆為 true，
        錯誤只藏在 `data.success` 裡，呼叫端會把失敗當成查無資料）。
        """
        with patch("http_server.SQLValidator") as MockValidator:
            MockValidator.validate_query.return_value = (True, "")

            response = test_client_with_failing_db.post(
                "/api/v1/query",
                json={"query": "SELECT * FROM users"}
            )

            assert response.status_code == 200
            body = response.json()
            assert body["success"] is False, "DB 失敗不可回報為成功"
            assert body.get("error"), "DB 失敗必須帶出錯誤訊息"

    def test_invalid_json_payload(self):
        """❌ 無效的 JSON 載荷"""
        with patch("http_server.HybridDatabaseManager") as MockManager:
            mock_db_manager = Mock()
            MockManager.create_with_preload.return_value = mock_db_manager

            from http_server import MCPHTTPServer

            server = MCPHTTPServer()
            server.db_manager = mock_db_manager
            server._register_routes()

            client = TestClient(server.app)

            response = client.post(
                "/api/v1/query",
                data="invalid json",
                headers={"Content-Type": "application/json"}
            )

            assert response.status_code == 422  # Unprocessable Entity


class TestCORSHeaders:
    """CORS 標頭測試"""

    @pytest.fixture
    def test_client(self):
        """創建測試客戶端"""
        with patch("http_server.HybridDatabaseManager") as MockManager:
            mock_db_manager = Mock()
            mock_db_manager.test_connection.return_value = {"success": True}
            MockManager.create_with_preload.return_value = mock_db_manager

            from http_server import MCPHTTPServer

            server = MCPHTTPServer()
            server.db_manager = mock_db_manager
            server._register_routes()

            return TestClient(server.app)

    def test_cors_headers_present(self, test_client):
        """✅ CORS preflight 成功

        CORSMiddleware 只在請求帶 Origin + Access-Control-Request-Method 時才攔截 OPTIONS；
        裸 OPTIONS 沒有對應路由，回 405 是正確的 HTTP 行為，不是 CORS 壞掉。
        """
        response = test_client.options(
            "/api/v1/health",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )

        assert response.status_code in [200, 204]

    def test_cors_preflight_max_age_is_wired_to_config(self, test_client):
        """✅ `CORS_PREFLIGHT_MAX_AGE` 必須真的傳給 CORSMiddleware

        `CORS_PREFLIGHT_MAX_AGE` 曾被讀進 `HTTPConfig` 卻無任何使用點 ——
        唯一的消費者是已移除的 `sse_server.py`（本身是死碼），所以該設定在
        live 路徑上從未生效。

        **它沒被發現的原因是預設值 600 恰好等於 Starlette 的預設值**，
        因此不能只斷言回應 header 的值：沒接上時回應照樣是 600，測試會假通過
        （已實測會假通過）。而改用 monkeypatch 環境變數 + `importlib.reload`
        的做法會替換 `core.config` 的 class 物件，污染同一輪的其他測試
        （實測導致 `test_async_manager.py` 7 個轉紅）。

        所以改為直接檢查 middleware 堆疊裡 `CORSMiddleware` 的實際 kwargs ——
        沒傳 `max_age=` 時該 key 根本不存在，一定會被抓到，且無副作用。
        """
        from starlette.middleware.cors import CORSMiddleware
        from core.config import HTTPConfig

        app = test_client.app
        cors = [m for m in app.user_middleware if m.cls is CORSMiddleware]
        assert cors, "middleware 堆疊裡找不到 CORSMiddleware"

        kwargs = cors[0].kwargs
        assert "max_age" in kwargs, (
            "CORSMiddleware 未收到 max_age → CORS_PREFLIGHT_MAX_AGE 是死設定"
        )
        assert kwargs["max_age"] == HTTPConfig.from_env().cors_preflight_max_age, (
            f"max_age={kwargs['max_age']} 與 HTTPConfig 的 "
            f"{HTTPConfig.from_env().cors_preflight_max_age} 不一致"
        )

    def test_cors_allows_origin(self, test_client):
        """✅ CORS 允許來源"""
        response = test_client.get(
            "/api/v1/health",
            headers={"Origin": "http://localhost:3000"}
        )

        # 檢查 CORS 標頭（如果有配置）
        # 實際的 CORS 行為取決於 FastAPI 的 CORS 中間件配置
        assert response.status_code == 200


class TestResponseFormat:
    """回應格式測試"""

    @pytest.fixture
    def test_client(self):
        """創建測試客戶端"""
        with patch("http_server.HybridDatabaseManager") as MockManager:
            mock_db_manager = Mock()
            mock_db_manager.test_connection.return_value = {"success": True}
            mock_db_manager.get_schema_info.return_value = {
                "success": True,
                "results": []
            }
            MockManager.create_with_preload.return_value = mock_db_manager

            from http_server import MCPHTTPServer

            server = MCPHTTPServer()
            server.db_manager = mock_db_manager
            server._register_routes()

            return TestClient(server.app)

    def test_response_contains_timestamp(self, test_client):
        """✅ 回應包含時間戳"""
        response = test_client.get("/api/v1/health")

        assert response.status_code == 200
        data = response.json()
        assert "timestamp" in data

    def test_response_json_format(self, test_client):
        """✅ 回應為 JSON 格式"""
        response = test_client.get("/api/v1/schema")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")

    def test_error_response_format(self, test_client):
        """✅ 錯誤回應格式統一"""
        # 測試不存在的端點
        response = test_client.get("/api/v1/nonexistent")

        assert response.status_code == 404
