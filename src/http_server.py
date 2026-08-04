"""HTTP server wrapper for MCP Multi-Database Connector.

Provides REST API access and MCP over Streamable HTTP for external integrations.

Transport note: Streamable HTTP replaces the previous SSE transport. One endpoint
serves both protocol eras -- the `initialize` handshake era (up to 2025-11-25) and
the stateless 2026-07-28 era -- so existing clients keep working unchanged while
2026-07-28 clients are also accepted. Era selection is handled by the SDK's
StreamableHTTPSessionManager; the module does not negotiate versions itself.
"""

import asyncio
from contextlib import asynccontextmanager
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request
import uvicorn
from slowapi import Limiter
from slowapi.util import get_remote_address

import mcp_types as types
from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

from core.config import DatabaseConfig, HTTPConfig
from database.async_manager import HybridDatabaseManager
from tools import ToolRegistry, get_all_tools
from tools.validators import SQLValidator
from api.middleware import setup_middleware
from api.models import QueryRequest, CacheInvalidateRequest, HealthResponse

logger = logging.getLogger(__name__)


class MCPHTTPServer:
    """HTTP server wrapper for MCP database tools with SSE support."""

    def __init__(self, config: Optional[DatabaseConfig] = None):
        self.config = config or DatabaseConfig.from_env()
        self.http_config = HTTPConfig.from_env()
        self.db_manager = None

        self.tool_registry = ToolRegistry()

        self.server_name = os.getenv("MCP_SERVER_NAME", "mcp-db")

        # Handlers are passed as constructor arguments: the decorator API
        # (@server.list_tools() etc.) was removed in mcp SDK v2.
        self.mcp_server = Server(
            self.server_name,
            on_list_tools=self._on_list_tools,
            on_call_tool=self._on_call_tool,
            on_list_prompts=self._on_list_prompts,
            on_list_resources=self._on_list_resources,
        )

        # stateless=True matches the 2026-07-28 stateless model and keeps the
        # handshake era working; there is no server-side session to pin a client to,
        # so no sticky routing is required in front of this service.
        self.session_manager = StreamableHTTPSessionManager(
            app=self.mcp_server,
            stateless=True,
            json_response=True,
        )

        @asynccontextmanager
        async def lifespan(app: FastAPI):
            async with self.session_manager.run():
                await self.initialize()
                logger.info("Service started, schema preloaded")
                yield
                logger.info("Service shutting down")

        self.app = FastAPI(
            title="MCP Database API",
            description="REST API & MCP over Streamable HTTP for Multi-Database Connector",
            version="1.2.0",
            docs_url="/docs",
            redoc_url="/redoc",
            lifespan=lifespan
        )

        # Mount the MCP endpoint. The SDK handles method routing, protocol-era
        # detection and the Mcp-Method / Mcp-Name / MCP-Protocol-Version header
        # requirements, so no hand-written ASGI dispatch is needed here.
        async def mcp_asgi_app(scope, receive, send):
            await self.session_manager.handle_request(scope, receive, send)

        self.app.mount("/mcp", mcp_asgi_app)

        # Apply all middleware (CORS, GZip, rate limiting)
        from core.config import AppConfig
        app_config = AppConfig.from_env()
        setup_middleware(self.app, app_config)

        # Rate limiter reference for route-specific limits
        self.limiter = Limiter(key_func=get_remote_address)

        self._register_routes()

    @staticmethod
    def _to_content_blocks(content: Any) -> List[types.ContentBlock]:
        """Convert the handlers' {"type": "text", "text": ...} dicts into typed blocks.

        SDK v2 no longer wraps handler return values automatically, so the tool layer's
        plain-dict output has to be converted here. Keeping the conversion at this
        boundary is deliberate: the handlers under ToolRegistry stay free of SDK types.
        """
        blocks: List[types.ContentBlock] = []
        for item in content if isinstance(content, list) else [content]:
            if isinstance(item, dict) and item.get("type") == "text":
                blocks.append(types.TextContent(type="text", text=str(item.get("text", ""))))
            elif isinstance(item, str):
                blocks.append(types.TextContent(type="text", text=item))
            else:
                blocks.append(types.TextContent(type="text", text=str(item)))
        return blocks

    async def _on_list_tools(self, ctx, params) -> types.ListToolsResult:
        return types.ListToolsResult(tools=get_all_tools())

    async def _on_call_tool(
        self, ctx, params: types.CallToolRequestParams
    ) -> types.CallToolResult:
        if not self.db_manager:
            return types.CallToolResult(
                content=[types.TextContent(type="text", text="Error: Database not initialized")],
                is_error=True,
            )

        # Same duck-typed request the tool layer has always received: handlers only read
        # .name / .arguments, which is why they need no changes for the SDK upgrade.
        request = type('CallToolRequest', (), {
            'name': params.name,
            'arguments': params.arguments or {}
        })()

        try:
            result = await self.tool_registry.handle_tool(request, self.db_manager)
        except Exception as e:
            # v2 turns an uncaught exception into a JSON-RPC error instead of a
            # CallToolResult(is_error=True). Catching it here preserves the previous
            # behaviour, where a failing tool still returns a readable result.
            logger.error(f"Tool execution error: {e}", exc_info=True)
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=f"Error: {str(e)}")],
                is_error=True,
            )

        if result is None:
            return types.CallToolResult(
                content=[types.TextContent(type="text", text=f"Unknown tool: {params.name}")],
                is_error=True,
            )

        if isinstance(result, dict) and "content" in result:
            return types.CallToolResult(content=self._to_content_blocks(result["content"]))
        return types.CallToolResult(content=self._to_content_blocks(result))

    async def _on_list_prompts(self, ctx, params) -> types.ListPromptsResult:
        return types.ListPromptsResult(prompts=[])

    async def _on_list_resources(self, ctx, params) -> types.ListResourcesResult:
        return types.ListResourcesResult(resources=[])

    async def initialize(self):
        """Initialize database manager asynchronously."""
        self.db_manager = HybridDatabaseManager.create_with_preload()

        preload_result = self.db_manager.reload_schema_config()
        if preload_result.get("success"):
            logger.info("Schema config preloaded successfully")
        else:
            logger.warning(f"Schema config preload failed: {preload_result.get('message')}")

        result = await self.db_manager.test_connection_async()
        if result.get("success"):
            logger.info("Database connection test passed (async pool)")
        else:
            logger.warning(f"Database connection test failed: {result.get('error')}")

    def _register_routes(self):
        """Register all API routes."""

        @self.app.get("/api/v1/health", response_model=HealthResponse)
        async def health_check():
            db_connected = False
            if self.db_manager:
                try:
                    result = self.db_manager.test_connection()
                    db_connected = result.get("success", False)
                except Exception:
                    pass

            return HealthResponse(
                status="healthy" if db_connected else "degraded",
                timestamp=datetime.now().isoformat(),
                version="1.2.0",
                database_connected=db_connected
            )

        @self.app.get("/api/v1/tools")
        async def list_api_tools():
            tools = [
                {"name": "connection_test", "endpoint": "/api/v1/connection/test", "method": "GET", "description": "Test database connection"},
                {"name": "query", "endpoint": "/api/v1/query", "method": "POST", "description": "Execute SELECT query"},
                {"name": "schema", "endpoint": "/api/v1/schema", "method": "GET", "description": "Get database schema"},
                {"name": "table_schema", "endpoint": "/api/v1/schema/{table_name}", "method": "GET", "description": "Get table schema"},
                {"name": "dependencies", "endpoint": "/api/v1/dependencies/{table_name}", "method": "GET", "description": "Analyze table dependencies"},
                {"name": "summary", "endpoint": "/api/v1/summary", "method": "GET", "description": "Get database summary"},
                {"name": "database_info", "endpoint": "/api/v1/database/info", "method": "GET", "description": "Get database info"},
                {"name": "cache_stats", "endpoint": "/api/v1/cache/stats", "method": "GET", "description": "Get cache statistics"},
                {"name": "cache_invalidate", "endpoint": "/api/v1/cache/invalidate", "method": "POST", "description": "Invalidate cache"},
                {"name": "schema_reload", "endpoint": "/api/v1/schema/reload", "method": "POST", "description": "Reload schema config"},
                {"name": "static_schema_info", "endpoint": "/api/v1/schema/static/info", "method": "GET", "description": "Get static schema info"},
            ]
            return self._success_response(tools)

        @self.app.get("/api/v1/connection/test")
        async def test_connection():
            if not self.db_manager:
                raise HTTPException(status_code=503, detail="Database manager not initialized")
            try:
                result = await self.db_manager.test_connection_async()
                return self._wrap_result(result)
            except Exception as e:
                logger.error(f"Connection test failed: {e}")
                return self._error_response(f"Connection test failed: {str(e)}")

        @self.app.post("/api/v1/query")
        @self.limiter.limit(self.http_config.rate_limit_query)
        async def execute_query(request: Request, query_request: QueryRequest):
            if not self.db_manager:
                raise HTTPException(status_code=503, detail="Database manager not initialized")

            is_valid, error_msg = SQLValidator.validate_query(query_request.query)
            if not is_valid:
                logger.warning(f"Query blocked by security validation: {error_msg}")
                return self._error_response(f"Security validation failed: {error_msg}")

            try:
                result = await self.db_manager.execute_query_async(query_request.query, query_request.params or [])
                return self._wrap_result(result)
            except Exception as e:
                logger.error(f"Query execution failed: {e}")
                return self._error_response(f"Query execution failed: {str(e)}")

        @self.app.get("/api/v1/schema")
        async def get_schema():
            if not self.db_manager:
                raise HTTPException(status_code=503, detail="Database manager not initialized")
            try:
                result = self.db_manager.get_schema_info()
                return self._wrap_result(result)
            except Exception as e:
                logger.error(f"Schema query failed: {e}")
                return self._error_response(f"Schema query failed: {str(e)}")

        @self.app.get("/api/v1/schema/{table_name}")
        async def get_table_schema(table_name: str):
            if not self.db_manager:
                raise HTTPException(status_code=503, detail="Database manager not initialized")
            try:
                result = self.db_manager.get_schema_info(table_name)
                return self._wrap_result(result)
            except Exception as e:
                logger.error(f"Table schema query failed: {e}")
                return self._error_response(f"Table schema query failed: {str(e)}")

        @self.app.get("/api/v1/dependencies/{table_name}")
        async def get_table_dependencies(table_name: str):
            if not self.db_manager:
                raise HTTPException(status_code=503, detail="Database manager not initialized")
            try:
                result = self.db_manager.get_table_dependencies(table_name)
                return self._wrap_result(result)
            except Exception as e:
                logger.error(f"Dependency analysis failed: {e}")
                return self._error_response(f"Dependency analysis failed: {str(e)}")

        @self.app.get("/api/v1/summary")
        async def get_database_summary():
            if not self.db_manager:
                raise HTTPException(status_code=503, detail="Database manager not initialized")
            try:
                result = self.db_manager.get_schema_summary()
                return self._wrap_result(result)
            except Exception as e:
                logger.error(f"Database summary query failed: {e}")
                return self._error_response(f"Database summary query failed: {str(e)}")

        @self.app.get("/api/v1/database/info")
        async def get_database_info():
            if not self.db_manager:
                raise HTTPException(status_code=503, detail="Database manager not initialized")
            try:
                result = self.db_manager.get_database_info()
                return self._wrap_result(result)
            except Exception as e:
                logger.error(f"Database info query failed: {e}")
                return self._error_response(f"Database info query failed: {str(e)}")

        @self.app.get("/api/v1/cache/stats")
        async def get_cache_stats():
            if not self.db_manager:
                raise HTTPException(status_code=503, detail="Database manager not initialized")
            try:
                result = self.db_manager.get_cache_stats()
                return self._wrap_result(result)
            except Exception as e:
                logger.error(f"Cache stats query failed: {e}")
                return self._error_response(f"Cache stats query failed: {str(e)}")

        @self.app.get("/api/v1/admin/cache-debug", tags=["Cache Management"])
        async def get_cache_debug():
            if not self.db_manager:
                raise HTTPException(status_code=503, detail="Database manager not initialized")
            try:
                result = self.db_manager.get_cache_debug_info()
                return self._wrap_result(result)
            except Exception as e:
                logger.error(f"Cache debug query failed: {e}")
                return self._error_response(f"Cache debug query failed: {str(e)}")

        @self.app.post("/api/v1/cache/invalidate")
        async def invalidate_cache(request: CacheInvalidateRequest):
            if not self.db_manager:
                raise HTTPException(status_code=503, detail="Database manager not initialized")
            try:
                result = self.db_manager.invalidate_schema_cache(request.table_name)
                return self._wrap_result(result)
            except Exception as e:
                logger.error(f"Cache invalidation failed: {e}")
                return self._error_response(f"Cache invalidation failed: {str(e)}")

        @self.app.post("/api/v1/schema/reload")
        async def reload_schema_config():
            if not self.db_manager:
                raise HTTPException(status_code=503, detail="Database manager not initialized")
            try:
                result = self.db_manager.reload_schema_config()
                return self._wrap_result(result)
            except Exception as e:
                logger.error(f"Schema reload failed: {e}")
                return self._error_response(f"Schema reload failed: {str(e)}")

        @self.app.get("/api/v1/schema/static/info")
        async def get_static_schema_info():
            if not self.db_manager:
                raise HTTPException(status_code=503, detail="Database manager not initialized")
            try:
                result = self.db_manager.get_static_schema_info()
                return self._wrap_result(result)
            except Exception as e:
                logger.error(f"Static schema info query failed: {e}")
                return self._error_response(f"Static schema info query failed: {str(e)}")

    def _success_response(self, data: Any) -> Dict[str, Any]:
        return {
            "success": True,
            "data": data,
            "timestamp": datetime.now().isoformat()
        }

    def _wrap_result(self, result: Any) -> Dict[str, Any]:
        """Wrap a manager result dict, propagating inner failure to the outer envelope.

        Manager methods report handled failures as {"success": False, ...} instead of
        raising; without this check the envelope would always say success=True and
        clients that only look at the outer flag would treat failures as empty results.
        """
        if isinstance(result, dict) and result.get("success") is False:
            error_message = result.get("error") or result.get("message") or "Operation failed"
            response = self._error_response(str(error_message))
            response["data"] = result
            return response
        return self._success_response(result)

    def _error_response(self, error_message: str) -> Dict[str, Any]:
        return {
            "success": False,
            "error": error_message,
            "timestamp": datetime.now().isoformat()
        }


async def create_server(config: Optional[DatabaseConfig] = None) -> MCPHTTPServer:
    """Create and initialize HTTP server."""
    server = MCPHTTPServer(config)
    await server.initialize()
    return server


def run_http_server(
    host: str = "0.0.0.0",
    port: int = 8000,
    config: Optional[DatabaseConfig] = None
):
    """Run HTTP server."""
    async def start_server():
        server = MCPHTTPServer(config)

        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )

        logger.info(f"Starting MCP Database HTTP API + SSE server at http://{host}:{port}")
        logger.info(f"API docs: http://{host}:{port}/docs")
        logger.info(f"MCP SSE endpoint: http://{host}:{port}/sse")

        config_uvicorn = uvicorn.Config(
            server.app,
            host=host,
            port=port,
            log_level="info",
            workers=int(os.environ.get("MCP_WORKERS", "1")),
        )
        server_uvicorn = uvicorn.Server(config_uvicorn)
        await server_uvicorn.serve()

    asyncio.run(start_server())


if __name__ == "__main__":
    host = os.getenv("HTTP_HOST", "0.0.0.0")
    port = int(os.getenv("HTTP_PORT", "8000"))
    run_http_server(host, port)
