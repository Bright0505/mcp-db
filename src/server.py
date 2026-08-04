"""MCP server implementation for Multi-Database Connector."""

import asyncio
import logging
import os
from typing import Any, List, Optional

import mcp_types as types
from mcp.server import Server
from mcp.server.runner import serve_dual_era_loop
from mcp.server.stdio import stdio_server

from database.async_manager import HybridDatabaseManager
from tools.registry import ToolRegistry
from tools.definitions import DB_TOOLS as TOOLS_DEFINITIONS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global database manager (Hybrid: supports both sync and async)
db_manager: Optional[HybridDatabaseManager] = None

# Global tool registry for modular tool handlers
_tool_registry: Optional[ToolRegistry] = None


def get_tool_registry() -> ToolRegistry:
    """Get or create tool registry instance."""
    global _tool_registry
    if _tool_registry is None:
        _tool_registry = ToolRegistry()
    return _tool_registry


def get_db_manager() -> HybridDatabaseManager:
    """Get or create hybrid database manager instance with preload support."""
    global db_manager
    if db_manager is None:
        db_manager = HybridDatabaseManager.create_with_preload()
        logger.info("Hybrid database manager initialized (sync + async support)")
    return db_manager


async def handle_call_tool(
    request: Any,
    db_manager: Optional[HybridDatabaseManager] = None
) -> dict:
    """Handle MCP tool calls via the tool registry."""
    try:
        db = db_manager if db_manager is not None else get_db_manager()
        registry = get_tool_registry()

        result = await registry.handle_tool(request, db)
        if result is not None:
            return result

        return {
            "content": [{"type": "text", "text": f"Unknown tool: {request.name}"}]
        }

    except Exception as e:
        logger.error(f"Tool call error in {request.name}: {e}", exc_info=True)
        return {
            "content": [{"type": "text", "text": f"Internal server error in tool '{request.name}': {e}"}]
        }


def _to_content_blocks(content: Any) -> List[types.ContentBlock]:
    """Convert the tool layer's plain dicts into typed content blocks.

    SDK v2 no longer wraps handler return values automatically.
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


async def main():
    """Main server entry point."""
    server_name = os.getenv("MCP_SERVER_NAME", "mcp-db")

    async def on_list_tools(ctx, params) -> types.ListToolsResult:
        return types.ListToolsResult(tools=TOOLS_DEFINITIONS)

    async def on_call_tool(ctx, params: types.CallToolRequestParams) -> types.CallToolResult:
        # Duck-typed request, unchanged: the tool layer only reads .name / .arguments.
        request = type('CallToolRequest', (), {
            'name': params.name,
            'arguments': params.arguments or {}
        })()
        result = await handle_call_tool(request)
        content = result.get("content", []) if isinstance(result, dict) else result
        # See http_server.py _on_call_tool: the tool layer's `isError` flag is not
        # propagated yet because handlers report failure inconsistently.
        return types.CallToolResult(content=_to_content_blocks(content))

    async def on_list_prompts(ctx, params) -> types.ListPromptsResult:
        return types.ListPromptsResult(prompts=[])

    async def on_list_resources(ctx, params) -> types.ListResourcesResult:
        return types.ListResourcesResult(resources=[])

    # Handlers are constructor arguments: the decorator API was removed in SDK v2.
    server = Server(
        server_name,
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
        on_list_prompts=on_list_prompts,
        on_list_resources=on_list_resources,
    )

    logger.info(f"Starting MCP Database Server ({server_name})...")
    # serve_dual_era_loop serves both the initialize-handshake era and the stateless
    # 2026-07-28 era. lifespan_state is required, so enter the server lifespan first.
    async with server.lifespan(server) as lifespan_state:
        async with stdio_server() as (read_stream, write_stream):
            await serve_dual_era_loop(
                server, read_stream, write_stream, lifespan_state=lifespan_state
            )


if __name__ == "__main__":
    asyncio.run(main())
