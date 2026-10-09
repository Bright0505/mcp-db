"""共用 token 驗證測試（api/auth.py）

MCP_AUTH_TOKEN 是 opt-in：沒設＝不驗證（既有部署不受影響），有設＝除豁免路徑外
所有請求都要帶 Bearer token。token 由前面的閘道持有並在轉送時帶上，直連模組 port
沒有 token 就被拒絕。

本檔的值刻意使用抽象名稱（`token-*`、`/protected`），不寫任何特定部署的名字。
"""

import importlib

import pytest
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Mount, Route
from starlette.testclient import TestClient

from api.auth import BearerTokenMiddleware


async def _ok(request):
    return PlainTextResponse("ok")


async def _mounted(scope, receive, send):
    await PlainTextResponse("mounted")(scope, receive, send)


def _client(tokens, exempt=("/health",)):
    app = Starlette(routes=[
        Route("/health", _ok),
        Route("/protected", _ok, methods=["GET", "POST", "OPTIONS"]),
        Mount("/mcp", app=_mounted),
    ])
    app.add_middleware(BearerTokenMiddleware, tokens=tokens, exempt_paths=exempt)
    return TestClient(app)


class TestDisabled:
    def test_no_tokens_lets_everything_through(self):
        """沒設 token 時行為與未掛 middleware 相同"""
        c = _client([])
        assert c.get("/protected").status_code == 200
        assert c.post("/mcp/").status_code == 200


class TestEnabled:
    def test_missing_header_is_refused(self):
        r = _client(["token-a"]).get("/protected")
        assert r.status_code == 401
        assert r.headers["www-authenticate"] == 'Bearer realm="mcp"'
        assert r.json() == {"success": False, "error": "Unauthorized"}

    def test_wrong_token_is_refused(self):
        r = _client(["token-a"]).get("/protected", headers={"Authorization": "Bearer token-x"})
        assert r.status_code == 401

    def test_non_bearer_scheme_is_refused(self):
        r = _client(["token-a"]).get("/protected", headers={"Authorization": "Basic token-a"})
        assert r.status_code == 401

    def test_correct_token_passes(self):
        r = _client(["token-a"]).get("/protected", headers={"Authorization": "Bearer token-a"})
        assert r.status_code == 200

    def test_scheme_is_case_insensitive(self):
        r = _client(["token-a"]).get("/protected", headers={"Authorization": "bearer token-a"})
        assert r.status_code == 200

    def test_mounted_mcp_app_is_protected(self):
        """/mcp 是 mount 的 ASGI app，也要受保護"""
        c = _client(["token-a"])
        assert c.post("/mcp/").status_code == 401
        assert c.post("/mcp/", headers={"Authorization": "Bearer token-a"}).status_code == 200

    def test_exempt_path_needs_no_token(self):
        """健康檢查（CI wait_for_health 不帶憑證）"""
        assert _client(["token-a"]).get("/health").status_code == 200

    def test_options_preflight_needs_no_token(self):
        assert _client(["token-a"]).options("/protected").status_code == 200

    def test_any_of_several_tokens_passes(self):
        """換 token 期間新舊兩把同時有效"""
        c = _client(["token-old", "token-new"])
        for t in ("token-old", "token-new"):
            assert c.get("/protected", headers={"Authorization": f"Bearer {t}"}).status_code == 200


class TestLoadTokens:
    @pytest.fixture
    def load(self, monkeypatch):
        import core.config as config
        import api.auth as auth
        importlib.reload(config)
        importlib.reload(auth)
        monkeypatch.delenv("ENV_PREFIX", raising=False)
        return auth.load_auth_tokens

    def test_unset_is_empty(self, monkeypatch, load):
        monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)
        assert load() == []

    def test_empty_string_is_empty(self, monkeypatch, load):
        """空字串＝不驗證，與沒設相同"""
        monkeypatch.setenv("MCP_AUTH_TOKEN", "")
        assert load() == []

    def test_comma_separated_and_trimmed(self, monkeypatch, load):
        monkeypatch.setenv("MCP_AUTH_TOKEN", " token-a , token-b ,")
        assert load() == ["token-a", "token-b"]

    def test_unprefixed_value_shared_by_prefixed_module(self, monkeypatch, load):
        """有 ENV_PREFIX 的模組也讀得到共用（無前綴）的 MCP_AUTH_TOKEN"""
        monkeypatch.setenv("ENV_PREFIX", "MYMODULE_")
        monkeypatch.delenv("MYMODULE_MCP_AUTH_TOKEN", raising=False)
        monkeypatch.setenv("MCP_AUTH_TOKEN", "token-shared")
        assert load() == ["token-shared"]
