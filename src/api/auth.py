"""Authentication for every HTTP entry point (MCP and REST).

Two independent, opt-in mechanisms:

Shared token (MCP_AUTH_TOKEN)
    With MCP_AUTH_TOKEN unset or empty, requests pass through unchanged, so an
    existing deployment keeps working until the token is configured. When set, every
    request except the exempt paths must carry ``Authorization: Bearer <token>``.
    MCP_AUTH_TOKEN may list several comma-separated tokens so that a rotation never has
    a gap: accept old and new, switch the callers to the new one, then drop the old one.

OAuth access tokens (MCP_OAUTH_*)
    The module acts as a standard OAuth resource server: it accepts JWT access tokens
    issued by an external authorization server, on the MCP endpoint only. It checks
    the signature (JWKS), ``iss``, ``aud``, ``exp`` and ``nbf`` and nothing else -- it
    reads no custom claims, so which users may reach which module is decided entirely
    by the authorization server before it issues the token. Swapping the identity
    provider therefore needs no change here; pointing at a different authorization
    server that issues JWTs is a configuration change.

    Enabled only when MCP_OAUTH_ISSUER, MCP_OAUTH_AUDIENCE and MCP_OAUTH_JWKS_URL are
    all set. Issuer and JWKS URL can be shared by every module of a deployment; the
    audience identifies this module, so setting it is what turns OAuth on here.
    MCP_OAUTH_AUDIENCE is compared as a plain string (no URL assumptions).
    MCP_OAUTH_RESOURCE_METADATA_URL, when set, is advertised in the 401 challenge so
    clients can discover the authorization server (RFC 9728).

A shared token is checked first; a JWT is only tried when that does not match.
"""

import hmac
import json
import logging
import threading
import time
import urllib.request
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple

import anyio
import jwt

from core.config import env

logger = logging.getLogger(__name__)

DEFAULT_OAUTH_ALGORITHMS = ("RS256", "ES256")
# Symmetric algorithms would let anyone holding the (public) JWKS forge tokens
FORBIDDEN_ALGORITHMS = {"none", "HS256", "HS384", "HS512"}
JWKS_TTL = 300  # seconds before the key set is refetched
JWKS_RETRY_AFTER = 30  # minimum gap between refetches triggered by an unknown kid
JWKS_TIMEOUT = 5


def load_auth_tokens() -> List[str]:
    """Return the configured tokens; an empty list means authentication is disabled."""
    raw = env("MCP_AUTH_TOKEN", "") or ""
    return [t.strip() for t in raw.split(",") if t.strip()]


@dataclass(frozen=True)
class OAuthConfig:
    issuer: str
    audience: str
    jwks_url: str
    algorithms: Tuple[str, ...] = DEFAULT_OAUTH_ALGORITHMS
    resource_metadata_url: Optional[str] = None
    # Only the MCP endpoint accepts OAuth tokens; REST stays shared-token only
    path_prefixes: Tuple[str, ...] = ("/mcp",)


def load_oauth_config() -> Optional[OAuthConfig]:
    """Return the OAuth settings, or None when OAuth is not (fully) configured."""
    issuer = (env("MCP_OAUTH_ISSUER", "") or "").strip()
    audience = (env("MCP_OAUTH_AUDIENCE", "") or "").strip()
    jwks_url = (env("MCP_OAUTH_JWKS_URL", "") or "").strip()
    if not audience:
        # Issuer and JWKS may be shared by every module of a deployment while the audience
        # is set per module, so a missing audience simply means OAuth is off here.
        if issuer or jwks_url:
            logger.info("OAuth not enabled for this module: MCP_OAUTH_AUDIENCE is not set")
        return None
    if not (issuer and jwks_url):
        logger.error("OAuth disabled: MCP_OAUTH_AUDIENCE is set but MCP_OAUTH_ISSUER or MCP_OAUTH_JWKS_URL is missing")
        return None
    raw_algs = env("MCP_OAUTH_ALGORITHMS", "") or ""
    algorithms = tuple(a.strip() for a in raw_algs.split(",") if a.strip()) or DEFAULT_OAUTH_ALGORITHMS
    bad = [a for a in algorithms if a in FORBIDDEN_ALGORITHMS]
    if bad:
        logger.error(f"OAuth disabled: MCP_OAUTH_ALGORITHMS must not include {bad}")
        return None
    metadata_url = (env("MCP_OAUTH_RESOURCE_METADATA_URL", "") or "").strip() or None
    return OAuthConfig(issuer, audience, jwks_url, algorithms, metadata_url)


class JWKSCache:
    """Keeps the last good key set: a failed refetch never drops keys already known."""

    def __init__(self, url: str, fetch=None):
        self.url = url
        self._fetch = fetch or self._http_fetch
        self._keys = {}
        self._fetched_at = 0.0
        self._lock = threading.Lock()

    def _http_fetch(self) -> dict:
        with urllib.request.urlopen(self.url, timeout=JWKS_TIMEOUT) as resp:
            return json.loads(resp.read())

    def _refresh(self) -> None:
        with self._lock:
            try:
                key_set = jwt.PyJWKSet.from_dict(self._fetch())
            except Exception as e:  # network, JSON or key-format errors alike
                logger.warning(f"JWKS fetch failed ({type(e).__name__}); keeping {len(self._keys)} cached key(s)")
                self._fetched_at = time.monotonic() - JWKS_TTL + JWKS_RETRY_AFTER
                return
            self._keys = {k.key_id: k for k in key_set.keys if k.key_id}
            self._fetched_at = time.monotonic()

    async def get(self, kid: Optional[str]):
        age = time.monotonic() - self._fetched_at
        stale = age > JWKS_TTL
        unknown = kid not in self._keys and age > JWKS_RETRY_AFTER
        if stale or unknown:
            await anyio.to_thread.run_sync(self._refresh)
        return self._keys.get(kid)


class OAuthVerifier:
    def __init__(self, config: OAuthConfig, jwks: Optional[JWKSCache] = None):
        self.config = config
        self.jwks = jwks or JWKSCache(config.jwks_url)

    def applies_to(self, path: str) -> bool:
        return any(path == p or path.startswith(p + "/") for p in self.config.path_prefixes)

    async def verify(self, token: str) -> bool:
        try:
            header = jwt.get_unverified_header(token)
        except jwt.PyJWTError:
            return False
        if header.get("alg") not in self.config.algorithms:
            return False
        key = await self.jwks.get(header.get("kid"))
        if key is None:
            return False
        try:
            jwt.decode(
                token,
                key.key,
                algorithms=list(self.config.algorithms),
                audience=self.config.audience,
                issuer=self.config.issuer,
                options={"require": ["exp", "iss", "aud"]},
                leeway=30,
            )
        except jwt.PyJWTError:
            return False
        return True


class BearerTokenMiddleware:
    """Pure ASGI middleware, so streamed MCP responses are never buffered or wrapped."""

    def __init__(
        self,
        app,
        tokens: Iterable[str],
        exempt_paths: Iterable[str] = (),
        oauth: Optional[OAuthVerifier] = None,
    ):
        self.app = app
        self.tokens = [t.encode() for t in tokens]
        self.exempt_paths = frozenset(exempt_paths)
        self.oauth = oauth

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] != "http"
            or not (self.tokens or self.oauth)
            or scope.get("method") == "OPTIONS"  # CORS preflight carries no Authorization
            or scope.get("path") in self.exempt_paths
        ):
            await self.app(scope, receive, send)
            return

        presented = self._bearer(scope)
        if presented is not None and await self._authorized(scope, presented):
            await self.app(scope, receive, send)
            return

        challenge = 'Bearer realm="mcp"'
        if self.oauth and self.oauth.applies_to(scope.get("path", "")):
            if self.oauth.config.resource_metadata_url:
                challenge += f', resource_metadata="{self.oauth.config.resource_metadata_url}"'
            if presented is not None:
                challenge += ', error="invalid_token"'
        body = json.dumps({"success": False, "error": "Unauthorized"}).encode()
        await send({
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"www-authenticate", challenge.encode()),
            ],
        })
        await send({"type": "http.response.body", "body": body})

    @staticmethod
    def _bearer(scope) -> Optional[bytes]:
        for name, value in scope.get("headers", []):
            if name == b"authorization":
                scheme, _, presented = value.partition(b" ")
                if scheme.lower() != b"bearer":
                    return None
                return presented.strip()
        return None

    async def _authorized(self, scope, presented: bytes) -> bool:
        # compare_digest against every token so the check time does not
        # reveal which one, if any, came close
        if any([hmac.compare_digest(presented, t) for t in self.tokens]):
            return True
        if self.oauth and self.oauth.applies_to(scope.get("path", "")):
            try:
                return await self.oauth.verify(presented.decode("ascii"))
            except UnicodeDecodeError:
                return False
        return False
