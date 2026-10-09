"""Shared-token authentication for every HTTP entry point (MCP and REST).

Opt-in: with MCP_AUTH_TOKEN unset or empty, requests pass through unchanged, so an
existing deployment keeps working until the token is configured. When set, every
request except the exempt paths must carry ``Authorization: Bearer <token>``.

The token is meant to be held by the gateway in front of the modules (nginx), not by
each client: the gateway authenticates its own callers and attaches this token when it
forwards. Calling a module port directly without the token is then refused.

MCP_AUTH_TOKEN may list several comma-separated tokens so that a rotation never has a
gap: accept old and new, switch the gateway to the new one, then drop the old one.
"""

import hmac
import json
import logging
from typing import Iterable, List

from core.config import env

logger = logging.getLogger(__name__)


def load_auth_tokens() -> List[str]:
    """Return the configured tokens; an empty list means authentication is disabled."""
    raw = env("MCP_AUTH_TOKEN", "") or ""
    return [t.strip() for t in raw.split(",") if t.strip()]


class BearerTokenMiddleware:
    """Pure ASGI middleware, so streamed MCP responses are never buffered or wrapped."""

    def __init__(self, app, tokens: Iterable[str], exempt_paths: Iterable[str] = ()):
        self.app = app
        self.tokens = [t.encode() for t in tokens]
        self.exempt_paths = frozenset(exempt_paths)

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] != "http"
            or not self.tokens
            or scope.get("method") == "OPTIONS"  # CORS preflight carries no Authorization
            or scope.get("path") in self.exempt_paths
        ):
            await self.app(scope, receive, send)
            return

        if self._authorized(scope):
            await self.app(scope, receive, send)
            return

        body = json.dumps({"success": False, "error": "Unauthorized"}).encode()
        await send({
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"www-authenticate", b'Bearer realm="mcp"'),
            ],
        })
        await send({"type": "http.response.body", "body": body})

    def _authorized(self, scope) -> bool:
        for name, value in scope.get("headers", []):
            if name == b"authorization":
                scheme, _, presented = value.partition(b" ")
                if scheme.lower() != b"bearer":
                    return False
                presented = presented.strip()
                # compare_digest against every token so the check time does not
                # reveal which one, if any, came close
                return any([hmac.compare_digest(presented, t) for t in self.tokens])
        return False
