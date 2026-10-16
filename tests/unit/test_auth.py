"""共用 token 驗證測試（api/auth.py）

MCP_AUTH_TOKEN 是 opt-in：沒設＝不驗證（既有部署不受影響），有設＝除豁免路徑外
所有請求都要帶 Bearer token。token 由前面的閘道持有並在轉送時帶上，直連模組 port
沒有 token 就被拒絕。

本檔的值刻意使用抽象名稱（`token-*`、`/protected`），不寫任何特定部署的名字。
"""

import importlib
import json

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


# ── OAuth access tokens（MCP_OAUTH_*）────────────────────────────────────────
#
# 模組只做標準 resource server 的檢查（簽章／iss／aud／exp），不讀自訂 claim。
# 以下 issuer／audience 皆為抽象值。

import time as _time

import jwt
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from api.auth import JWKSCache, OAuthConfig, OAuthVerifier, load_oauth_config

ISSUER = "https://issuer.example"
AUDIENCE = "https://resource.example/mcp-example/mcp"
METADATA = "https://issuer.example/.well-known/oauth-protected-resource/mcp-example/mcp"


def _rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwk(private, kid):
    data = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private.public_key()))
    data.update(kid=kid, use="sig", alg="RS256")
    return data


class FakeJWKS:
    """取代 HTTP：回傳目前的 key set，可模擬故障並計算抓取次數。"""

    def __init__(self, *jwks):
        self.keys = list(jwks)
        self.calls = 0
        self.down = False

    def __call__(self):
        self.calls += 1
        if self.down:
            raise OSError("unreachable")
        return {"keys": self.keys}


def _token(private, kid="k1", alg="RS256", **overrides):
    now = int(_time.time())
    claims = {"iss": ISSUER, "aud": AUDIENCE, "sub": "user-1", "iat": now, "exp": now + 600}
    claims.update(overrides)
    claims = {k: v for k, v in claims.items() if v is not None}
    return jwt.encode(claims, private, algorithm=alg, headers={"kid": kid})


def _oauth_client(tokens=(), fetch=None, metadata=METADATA, algorithms=("RS256", "ES256")):
    config = OAuthConfig(ISSUER, AUDIENCE, "https://issuer.example/jwks", tuple(algorithms), metadata)
    verifier = OAuthVerifier(config, JWKSCache(config.jwks_url, fetch=fetch))
    app = Starlette(routes=[
        Route("/health", _ok),
        Route("/protected", _ok, methods=["GET", "POST"]),
        Mount("/mcp", app=_mounted),
    ])
    app.add_middleware(BearerTokenMiddleware, tokens=list(tokens), exempt_paths=("/health",), oauth=verifier)
    return TestClient(app)


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def key():
    return _rsa_key()


@pytest.fixture
def jwks(key):
    return FakeJWKS(_jwk(key, "k1"))


class TestOAuth:
    def test_valid_token_passes_on_mcp(self, key, jwks):
        assert _oauth_client(fetch=jwks).post("/mcp/", headers=_bearer(_token(key))).status_code == 200

    def test_oauth_alone_protects_mcp(self, jwks):
        """沒設共用 token、只開 OAuth 時，/mcp 一樣要驗"""
        assert _oauth_client(fetch=jwks).post("/mcp/").status_code == 401

    def test_rest_does_not_accept_oauth_tokens(self, key, jwks):
        """OAuth 只開 /mcp；REST 仍只認共用 token"""
        c = _oauth_client(tokens=["token-a"], fetch=jwks)
        assert c.get("/protected", headers=_bearer(_token(key))).status_code == 401
        assert c.get("/protected", headers=_bearer("token-a")).status_code == 200

    def test_shared_token_still_works_on_mcp(self, jwks):
        assert _oauth_client(tokens=["token-a"], fetch=jwks).post("/mcp/", headers=_bearer("token-a")).status_code == 200

    def test_wrong_audience_refused(self, key, jwks):
        """發給別的模組的 token 不能拿來用"""
        token = _token(key, aud="https://resource.example/mcp-other/mcp")
        assert _oauth_client(fetch=jwks).post("/mcp/", headers=_bearer(token)).status_code == 401

    def test_wrong_issuer_refused(self, key, jwks):
        token = _token(key, iss="https://someone-else.example")
        assert _oauth_client(fetch=jwks).post("/mcp/", headers=_bearer(token)).status_code == 401

    def test_expired_refused(self, key, jwks):
        token = _token(key, exp=int(_time.time()) - 3600)
        assert _oauth_client(fetch=jwks).post("/mcp/", headers=_bearer(token)).status_code == 401

    def test_missing_exp_refused(self, key, jwks):
        assert _oauth_client(fetch=jwks).post("/mcp/", headers=_bearer(_token(key, exp=None))).status_code == 401

    def test_signed_by_unknown_key_refused(self, jwks):
        token = _token(_rsa_key())  # 同 kid、不同私鑰
        assert _oauth_client(fetch=jwks).post("/mcp/", headers=_bearer(token)).status_code == 401

    def test_symmetric_token_using_public_jwk_refused(self, key, jwks):
        """經典攻擊：拿公開的金鑰當 HMAC secret 簽 HS256"""
        import base64
        import hashlib
        import hmac as _hmac

        def seg(obj):
            return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()

        # PyJWT 自己拒絕這樣簽，所以手工組
        signing_input = seg({"alg": "HS256", "kid": "k1", "typ": "JWT"}) + "." + seg(
            {"iss": ISSUER, "aud": AUDIENCE, "exp": int(_time.time()) + 600})
        mac = _hmac.new(json.dumps(jwks.keys[0]).encode(), signing_input.encode(), hashlib.sha256).digest()
        forged = signing_input + "." + base64.urlsafe_b64encode(mac).rstrip(b"=").decode()
        assert _oauth_client(fetch=jwks).post("/mcp/", headers=_bearer(forged)).status_code == 401

    def test_garbage_token_refused(self, jwks):
        assert _oauth_client(fetch=jwks).post("/mcp/", headers=_bearer("not-a-jwt")).status_code == 401

    def test_challenge_advertises_resource_metadata(self, key, jwks):
        c = _oauth_client(fetch=jwks)
        missing = c.post("/mcp/")
        assert missing.headers["www-authenticate"] == f'Bearer realm="mcp", resource_metadata="{METADATA}"'
        bad = c.post("/mcp/", headers=_bearer("x"))
        assert bad.headers["www-authenticate"].endswith(', error="invalid_token"')

    def test_challenge_unchanged_without_metadata_url(self, jwks):
        c = _oauth_client(fetch=jwks, metadata=None)
        assert c.post("/mcp/").headers["www-authenticate"] == 'Bearer realm="mcp"'

    def test_rest_challenge_has_no_oauth_hint(self, jwks):
        c = _oauth_client(tokens=["token-a"], fetch=jwks)
        assert c.get("/protected").headers["www-authenticate"] == 'Bearer realm="mcp"'

    def test_es256_key_accepted(self):
        private = ec.generate_private_key(ec.SECP256R1())
        data = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(private.public_key()))
        data.update(kid="ec1", use="sig", alg="ES256")
        c = _oauth_client(fetch=FakeJWKS(data))
        assert c.post("/mcp/", headers=_bearer(_token(private, kid="ec1", alg="ES256"))).status_code == 200


class TestJWKSCache:
    def test_keys_are_cached(self, key, jwks):
        c = _oauth_client(fetch=jwks)
        for _ in range(3):
            c.post("/mcp/", headers=_bearer(_token(key)))
        assert jwks.calls == 1

    def test_outage_keeps_known_keys(self, key, jwks, monkeypatch):
        import api.auth as auth
        c = _oauth_client(fetch=jwks)
        assert c.post("/mcp/", headers=_bearer(_token(key))).status_code == 200
        jwks.down = True
        monkeypatch.setattr(auth, "JWKS_TTL", -1)  # 強制每次都重抓
        assert c.post("/mcp/", headers=_bearer(_token(key))).status_code == 200

    def test_never_fetched_means_refused_but_shared_token_works(self, key, jwks):
        jwks.down = True
        c = _oauth_client(tokens=["token-a"], fetch=jwks)
        assert c.post("/mcp/", headers=_bearer(_token(key))).status_code == 401
        assert c.post("/mcp/", headers=_bearer("token-a")).status_code == 200

    def test_unknown_kid_refetch_is_rate_limited(self, key, jwks):
        c = _oauth_client(fetch=jwks)
        for _ in range(5):
            c.post("/mcp/", headers=_bearer(_token(key, kid="rotated")))
        assert jwks.calls == 1


class TestLoadOAuthConfig:
    @pytest.fixture
    def load(self, monkeypatch):
        import core.config as config
        import api.auth as auth
        importlib.reload(config)
        importlib.reload(auth)
        monkeypatch.delenv("ENV_PREFIX", raising=False)
        for name in ("ISSUER", "AUDIENCE", "JWKS_URL", "ALGORITHMS", "RESOURCE_METADATA_URL"):
            monkeypatch.delenv(f"MCP_OAUTH_{name}", raising=False)
        return auth.load_oauth_config

    def _set_required(self, monkeypatch):
        monkeypatch.setenv("MCP_OAUTH_ISSUER", ISSUER)
        monkeypatch.setenv("MCP_OAUTH_AUDIENCE", AUDIENCE)
        monkeypatch.setenv("MCP_OAUTH_JWKS_URL", "https://issuer.example/jwks")

    def test_unset_is_disabled(self, load):
        assert load() is None

    def test_shared_settings_without_audience_is_disabled(self, monkeypatch, load):
        """issuer／JWKS 是部署共用的；沒設 audience 的模組就是沒開 OAuth"""
        self._set_required(monkeypatch)
        monkeypatch.delenv("MCP_OAUTH_AUDIENCE")
        assert load() is None

    def test_audience_without_issuer_is_disabled(self, monkeypatch, load):
        monkeypatch.setenv("MCP_OAUTH_AUDIENCE", AUDIENCE)
        assert load() is None

    def test_complete(self, monkeypatch, load):
        self._set_required(monkeypatch)
        monkeypatch.setenv("MCP_OAUTH_RESOURCE_METADATA_URL", METADATA)
        cfg = load()
        assert (cfg.issuer, cfg.audience, cfg.algorithms, cfg.resource_metadata_url) == (
            ISSUER, AUDIENCE, ("RS256", "ES256"), METADATA)

    def test_audience_is_not_assumed_to_be_url(self, monkeypatch, load):
        self._set_required(monkeypatch)
        monkeypatch.setenv("MCP_OAUTH_AUDIENCE", "api://some-app-id")
        assert load().audience == "api://some-app-id"

    @pytest.mark.parametrize("algs", ["HS256", "RS256,none"])
    def test_symmetric_or_none_algorithms_disable(self, monkeypatch, load, algs):
        self._set_required(monkeypatch)
        monkeypatch.setenv("MCP_OAUTH_ALGORITHMS", algs)
        assert load() is None
