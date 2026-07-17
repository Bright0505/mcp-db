"""HTTP server wrapper for MCP Multi-Database Connector.

Provides REST API access and MCP SSE (Server-Sent Events) support for external integrations.
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

from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import Tool, Prompt, Resource

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
        self.mcp_server = Server(self.server_name)
        self.sse_transport = SseServerTransport("/messages")

        self._setup_mcp_handlers()

        @asynccontextmanager
        async def lifespan(app: FastAPI):
            await self.initialize()
            logger.info("Service started, schema preloaded")
            yield
            logger.info("Service shutting down")

        self.app = FastAPI(
            title="MCP Database API",
            description="REST API & SSE for Multi-Database Connector via MCP",
            version="1.2.0",
            docs_url="/docs",
            redoc_url="/redoc",
            lifespan=lifespan
        )

        # Mount MCP SSE ASGI sub-app
        async def mcp_sse_asgi_app(scope, receive, send):
            path = scope.get("path", "/")
            method = scope.get("method", "GET")

            if path == "/sse/" and method == "GET":
                async with self.sse_transport.connect_sse(scope, receive, send) as streams:
                    await self.mcp_server.run(
                        streams[0],
                        streams[1],
                        self.mcp_server.create_initialization_options()
                    )
            elif path.startswith("/sse/messages") and method == "POST":
                await self.sse_transport.handle_post_message(scope, receive, send)
            else:
                await send({
                    'type': 'http.response.start',
                    'status': 404,
                    'headers': [[b'content-type', b'text/plain']],
                })
                await send({
                    'type': 'http.response.body',
                    'body': b'Not Found',
                })

        self.app.mount("/sse", mcp_sse_asgi_app)

        # Apply all middleware (CORS, GZip, rate limiting)
        from core.config import AppConfig
        app_config = AppConfig.from_env()
        setup_middleware(self.app, app_config)

        # Rate limiter reference for route-specific limits
        self.limiter = Limiter(key_func=get_remote_address)

        self._register_routes()

    def _setup_mcp_handlers(self):
        """Setup MCP protocol handlers."""

        @self.mcp_server.list_tools()
        async def list_tools() -> List[Tool]:
            return get_all_tools()

        @self.mcp_server.call_tool()
        async def handle_tool_call(name: str, arguments: dict) -> list:
            if not self.db_manager:
                return [{"type": "text", "text": "Error: Database not initialized"}]

            try:
                request = type('CallToolRequest', (), {
                    'name': name,
                    'arguments': arguments or {}
                })()
                result = await self.tool_registry.handle_tool(request, self.db_manager)
                if isinstance(result, dict) and "content" in result:
                    return result["content"]
                return result if isinstance(result, list) else [result]
            except Exception as e:
                logger.error(f"Tool execution error: {e}")
                return [{"type": "text", "text": f"Error: {str(e)}"}]

        @self.mcp_server.list_prompts()
        async def list_prompts() -> List[Prompt]:
            return []

        @self.mcp_server.list_resources()
        async def list_resources() -> List[Resource]:
            return []

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
