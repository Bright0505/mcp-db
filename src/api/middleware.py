"""API middleware for rate limiting and security."""

import os
import logging

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from core.config import HTTPConfig, AppConfig

logger = logging.getLogger(__name__)

# Create rate limiter instance with configurable default limit
_http_config = HTTPConfig.from_env()
limiter = Limiter(key_func=get_remote_address, default_limits=[_http_config.rate_limit_default])

GZIP_MIN_SIZE = 1000


def setup_rate_limiting(app: FastAPI):
    """Configure rate limiting for FastAPI application."""
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


def setup_middleware(app: FastAPI, app_config: AppConfig):
    """Configure all middleware for FastAPI application.

    Sets up CORS, GZip compression, and rate limiting.
    """
    # CORS
    cors_env = os.getenv("CORS_ALLOWED_ORIGINS", "")
    if cors_env:
        allowed_origins = [origin.strip() for origin in cors_env.split(",")]
    else:
        environment = os.getenv("ENVIRONMENT", "development")
        if environment == "development":
            allowed_origins = ["http://localhost:3000", "http://localhost:8000"]
        else:
            allowed_origins = []
            logger.warning("Production environment: CORS_ALLOWED_ORIGINS not set, CORS disabled")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        # MCP 2026-07-28 (SEP-2243) makes Mcp-Method / Mcp-Name required on requests,
        # and MCP-Protocol-Version carries the negotiated era. A browser-based MCP
        # client cannot send them unless the preflight allows them, so they are listed
        # here explicitly. Verified: without these, a preflight carrying
        # Access-Control-Request-Headers: Mcp-Method is rejected with 400.
        # Requests arriving via MCPO are server-to-server and unaffected either way.
        allow_headers=[
            "Content-Type",
            "Authorization",
            "Mcp-Method",
            "Mcp-Name",
            "MCP-Protocol-Version",
            "Mcp-Session-Id",
        ],
    )

    # GZip compression
    app.add_middleware(GZipMiddleware, minimum_size=GZIP_MIN_SIZE)

    # Rate limiting
    setup_rate_limiting(app)
