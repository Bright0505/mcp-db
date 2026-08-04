"""MCP 協議層回歸測試。

存在理由
--------
Phase 1 之前，`tests/` 對協議層的覆蓋率是 **0** —— grep `list_tools` / `inputSchema` /
`ToolRegistry` / `SseServerTransport` 全部零命中。後果是任何協議層的破壞（工具消失、
schema 形狀改變、dispatch 斷掉）都不會被任何測試抓到，而 MCP 2026-07-28 遷移正要動這一層。

分層設計（重要）
----------------
本檔刻意分兩層，理由是遷移到 mcp SDK v2 時只有第 2 層需要改：

* **第 1 層 — SDK 無關（本檔絕大部分）**
  只依賴模組自己的 seam：`get_all_tools()`、`ToolRegistry.handle_tool()`。
  不 import 任何 SDK 的 server/transport 機制，因此 v1 → v2 不需要改動。
  這裡就能抓到絕大多數迴歸：工具數量、名稱、prefix 機制、schema 形狀、dispatch、錯誤路徑。

* **第 2 層 — SDK wiring（僅 `TestProtocolWiring`，已標記）**
  驗證 handler 真的被掛上 `mcp.server.Server` 並能完成一次真正的協議往返。
  ⚠️ v2 移除了 `create_connected_server_and_client_session`（只留下層的
  `create_client_server_memory_streams`），所以 Phase 3 必須改這個 class 的 fixture。
  刻意集中在一處，讓遷移只需動一個地方。
"""

import importlib
import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tools import get_all_tools
from tools.definitions import (
    TOOL_CACHE_STATS,
    TOOL_QUERY,
    TOOL_SCHEMA,
    get_tool_prefix,
    make_tool_name,
)
from tools.registry import ToolRegistry

EXPECTED_TOOL_SUFFIXES = {
    "query",
    "schema",
    "test_connection",
    "dependencies",
    "schema_summary",
    "cache_stats",
    "cache_invalidate",
    "schema_reload",
    "static_schema_info",
    "export_schema",
    "syntax_guide",
}


def _fake_request(name, arguments=None):
    """複製生產程式碼的鴨子型別 request。

    `http_server.py` 與 `server.py` 都用 `type('CallToolRequest', (), {...})()` 手捏 request，
    handler 只讀 `.name` / `.arguments`。測試沿用同一形狀，才不會綁上 SDK 型別
    —— 這也是為什麼 v2 的 camelCase → snake_case 不會滲進業務邏輯。
    """
    return type("CallToolRequest", (), {"name": name, "arguments": arguments or {}})()


# =============================================================================
# 第 1 層：SDK 無關
# =============================================================================


class TestToolInventory:
    """工具清單本身 —— 遷移最容易靜默弄壞的東西。"""

    def test_expected_tool_count(self):
        assert len(get_all_tools()) == len(EXPECTED_TOOL_SUFFIXES)

    def test_tool_suffixes_match_expected_set(self):
        prefix = get_tool_prefix()
        suffixes = {t.name[len(prefix) + 1 :] for t in get_all_tools()}
        assert suffixes == EXPECTED_TOOL_SUFFIXES

    def test_all_tool_names_carry_prefix(self):
        prefix = get_tool_prefix()
        for tool in get_all_tools():
            assert tool.name.startswith(f"{prefix}_"), tool.name

    def test_tool_names_are_unique(self):
        names = [t.name for t in get_all_tools()]
        assert len(names) == len(set(names))

    def test_every_tool_has_description(self):
        for tool in get_all_tools():
            assert tool.description and tool.description.strip(), tool.name

    def test_prefix_is_driven_by_env(self):
        """TOOL_PREFIX 機制若壞掉，8 個模組的工具名會同時失效。"""
        import tools.definitions as defs

        with patch.dict(os.environ, {"TOOL_PREFIX": "zzz"}):
            importlib.reload(defs)
            try:
                assert defs.get_tool_prefix() == "zzz"
                assert defs.make_tool_name("query") == "zzz_query"
                assert all(t.name.startswith("zzz_") for t in defs.get_all_tools())
            finally:
                importlib.reload(defs)


class TestInputSchema:
    """schema 形狀 —— v2 把 inputSchema 改名 input_schema，且 2020-12 更嚴格。"""

    def test_schema_is_object_with_properties(self):
        for tool in get_all_tools():
            schema = tool.inputSchema
            assert schema["type"] == "object", tool.name
            assert isinstance(schema.get("properties"), dict), tool.name

    def test_every_property_declares_a_type(self):
        for tool in get_all_tools():
            for prop_name, prop in tool.inputSchema["properties"].items():
                assert "type" in prop, f"{tool.name}.{prop_name}"

    def test_array_properties_declare_items(self):
        """JSON Schema 2020-12 就緒度：array 缺 items 會被降級成「任意型別的 list」。

        這正是 MCPO 手寫轉換器（mcpo/utils/main.py:215-218）出問題的形態。
        模組端目前是乾淨的，此測試防止它退化。
        """
        for tool in get_all_tools():
            for prop_name, prop in tool.inputSchema["properties"].items():
                if prop.get("type") == "array":
                    assert "items" in prop, f"{tool.name}.{prop_name} 缺 items"
                    assert "type" in prop["items"], f"{tool.name}.{prop_name}.items 缺 type"

    def test_object_properties_declare_their_shape(self):
        for tool in get_all_tools():
            for prop_name, prop in tool.inputSchema["properties"].items():
                if prop.get("type") == "object":
                    assert "properties" in prop or "additionalProperties" in prop, (
                        f"{tool.name}.{prop_name} 是 object 但未宣告形狀"
                    )

    def test_required_fields_exist_in_properties(self):
        for tool in get_all_tools():
            schema = tool.inputSchema
            for field in schema.get("required", []):
                assert field in schema["properties"], f"{tool.name}: required 的 {field} 不在 properties"

    def test_no_external_schema_refs(self):
        """SEP-2106 安全要求：不得自動解析外部 $ref URI。

        模組目前完全不用 $ref，此測試防止有人引入指向外部 URI 的 ref。
        """
        def walk(node, path):
            if isinstance(node, dict):
                ref = node.get("$ref")
                if isinstance(ref, str):
                    assert ref.startswith("#"), f"{path}: 外部 $ref «{ref}»"
                for k, v in node.items():
                    walk(v, f"{path}.{k}")
            elif isinstance(node, list):
                for i, v in enumerate(node):
                    walk(v, f"{path}[{i}]")

        for tool in get_all_tools():
            walk(tool.inputSchema, tool.name)

    def test_query_tool_accepts_query_and_params(self):
        """對最重要的工具做具體斷言，避免上面的通則測試被空 schema 蒙混過去。"""
        prefix = get_tool_prefix()
        tool = next(t for t in get_all_tools() if t.name == f"{prefix}_{TOOL_QUERY}")
        props = tool.inputSchema["properties"]
        assert props["query"]["type"] == "string"
        assert props["params"]["type"] == "array"
        assert props["params"]["items"]["type"] == "string"
        assert tool.inputSchema["required"] == ["query"]


class TestRegistryRouting:
    """dispatch —— 協議層與業務層的分界（registry.py:54 handle_tool）。"""

    def test_every_advertised_tool_has_a_handler(self):
        """工具清單與 handler 必須完全對齊。

        少了 handler，該工具會回 None（外部看起來是靜默無回應）；
        多了 handler 則是死碼。
        """
        registry = ToolRegistry()
        for tool in get_all_tools():
            assert registry.is_tool_registered(tool.name), f"{tool.name} 無對應 handler"

    def test_no_orphan_handlers(self):
        advertised = {t.name for t in get_all_tools()}
        orphans = set(ToolRegistry().handlers) - advertised
        assert not orphans, f"有 handler 但未公告的工具: {orphans}"

    async def test_unknown_tool_returns_none(self):
        result = await ToolRegistry().handle_tool(_fake_request("no_such_tool"), MagicMock())
        assert result is None

    async def test_routes_to_matching_handler(self):
        registry = ToolRegistry()
        name = make_tool_name(TOOL_CACHE_STATS)
        handler = registry.handlers[name]

        with patch.object(handler, "handle", new=AsyncMock(return_value={"content": []})) as mocked:
            await registry.handle_tool(_fake_request(name), MagicMock())

        mocked.assert_awaited_once()

    async def test_handler_result_carries_content_list(self):
        """所有 handler 的共同輸出契約（tools/base.py:40-47）。

        v2 移除了自動 return value wrapping，所以這個形狀在 Phase 3 必須維持。
        """
        registry = ToolRegistry()
        name = make_tool_name(TOOL_SCHEMA)
        db = MagicMock()
        db.get_schema_info = MagicMock(
            return_value={
                "success": True,
                "table_name": "t",
                "total_count": 1,
                "results": [{"column_name": "id", "data_type": "integer"}],
            }
        )

        result = await registry.handle_tool(_fake_request(name, {"table_name": "t"}), db)

        assert isinstance(result, dict)
        assert isinstance(result["content"], list)
        assert result["content"][0]["type"] == "text"

    async def test_handler_exception_propagates(self):
        """v2 起 handler 例外不再自動轉成 CallToolResult(is_error=True)。

        此測試釘住「例外會往外拋」這個事實，Phase 3 改寫時若行為改變會被抓到。
        """
        registry = ToolRegistry()
        name = make_tool_name(TOOL_CACHE_STATS)
        handler = registry.handlers[name]

        with patch.object(handler, "handle", new=AsyncMock(side_effect=RuntimeError("boom"))):
            with pytest.raises(RuntimeError, match="boom"):
                await registry.handle_tool(_fake_request(name), MagicMock())


# =============================================================================
# 第 2 層：SDK wiring —— ⚠️ Phase 3 需要改這個 class
# =============================================================================


class TestProtocolWiring:
    """驗證 handler 真的掛上 SDK 的 Server，並完成一次真正的協議往返。

    ⚠️ **Phase 3（mcp SDK v2）必須改這裡。** 原因：
      * v2 移除 `create_connected_server_and_client_session`
        （只保留 `create_client_server_memory_streams`）
      * v2 的 handler 註冊從 decorator 改為 `Server(on_list_tools=…, on_call_tool=…)`
      * v2 無 `initialize` handshake

    第 1 層的測試不受這些變更影響 —— 遷移時請只改本 class。
    """

    @pytest.fixture
    def mcp_server(self):
        """取出生產程式碼實際建構並註冊過 handler 的那個 Server。"""
        with patch("http_server.HybridDatabaseManager"):
            from http_server import MCPHTTPServer

            server = MCPHTTPServer()
            db = MagicMock()
            db.get_cache_stats = MagicMock(return_value={"success": True, "entries": 0})
            server.db_manager = db
            return server

    async def test_handlers_are_registered_on_server(self, mcp_server):
        """最低限度的 wiring 檢查：Server 上有 handler 被註冊。"""
        assert mcp_server.mcp_server.request_handlers, "Server 上沒有任何 request handler"

    async def test_protocol_round_trip_lists_and_calls_tools(self, mcp_server):
        from mcp.shared.memory import create_connected_server_and_client_session

        async with create_connected_server_and_client_session(mcp_server.mcp_server) as client:
            listed = await client.list_tools()
            assert {t.name for t in listed.tools} == {t.name for t in get_all_tools()}

            called = await client.call_tool(make_tool_name(TOOL_CACHE_STATS), {})
            assert called.content, "call_tool 沒有回傳任何 content"
