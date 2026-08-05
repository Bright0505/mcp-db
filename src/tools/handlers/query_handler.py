"""Query execution handler with security validation."""

import logging
from typing import Any, Dict, List, Optional
from mcp.types import CallToolRequest

from tools.base import ToolHandler, to_json_safe
from tools.definitions import make_tool_name, TOOL_QUERY
from tools.validators import SQLValidator

logger = logging.getLogger(__name__)

# How many rows leave this handler, in both the text and the structured branch. The cap
# exists because a result set has no upper bound while a tool response does. What stops
# the cap from being silent is `truncated` in the structured payload and the
# "... and N more rows" line in the text branch.
DISPLAY_LIMIT = 200


class QueryHandler(ToolHandler):
    """Handler for database query execution.

    This tool declares `outputSchema` (`QUERY_OUTPUT_SCHEMA`), which makes structured
    content mandatory on *every* return path -- including failures, because the tool
    layer's `isError` flag is not propagated to `CallToolResult.is_error`, so the client
    validates failures too. All paths therefore build their payload through
    `_structured()`; nothing here assembles one by hand.
    """

    @property
    def tool_names(self) -> List[str]:
        return [make_tool_name(TOOL_QUERY)]

    @staticmethod
    def _structured(
        *,
        success: bool,
        row_count: int = 0,
        returned_row_count: int = 0,
        columns: Optional[List[str]] = None,
        rows: Optional[List[Dict[str, Any]]] = None,
        error: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build a payload conforming to QUERY_OUTPUT_SCHEMA.

        `truncated` is derived, not passed in, so it can never disagree with the counts.
        """
        return {
            "success": success,
            "row_count": row_count,
            "returned_row_count": returned_row_count,
            "truncated": returned_row_count < row_count,
            "columns": list(columns or []),
            "rows": list(rows or []),
            "error": error,
        }

    async def handle(self, request: CallToolRequest, db_manager: Any) -> Dict[str, Any]:
        """
        Execute SQL SELECT query with security validation.

        Args:
            request: MCP tool call request
            db_manager: Database manager instance

        Returns:
            Formatted query results or error message
        """
        query = request.arguments.get("query")
        params = request.arguments.get("params")

        # Validate query parameter
        if not query:
            message = "Query parameter is required"
            return self._error_response(
                message, structured=self._structured(success=False, error=message)
            )

        # Security validation (NEW - prevents SQL injection and dangerous operations)
        is_valid, error_msg = SQLValidator.validate_query(query)
        if not is_valid:
            logger.warning(f"Query blocked by security validation: {error_msg}")
            message = f"Security validation failed: {error_msg}"
            return self._error_response(
                message, structured=self._structured(success=False, error=message)
            )

        # Execute query asynchronously (uses connection pool for performance)
        result = await db_manager.execute_query_async(query, params)

        # Format response
        return self._format_query_result(result, query)

    def _format_query_result(self, result: Dict[str, Any], query: str) -> Dict[str, Any]:
        """Format query execution result for MCP response."""
        if result["success"]:
            columns = list(result["columns"])
            all_rows = result["results"] or []
            row_count = result["row_count"]
            shown = all_rows[:DISPLAY_LIMIT]

            output = "✅ Query executed successfully\n"
            output += f"📊 Rows returned: {row_count}\n"
            output += f"📋 Columns: {', '.join(columns)}\n\n"

            if all_rows:
                output += "📋 Results:\n"
                for i, row in enumerate(shown):
                    output += f"Row {i+1}: {row}\n"

                if len(all_rows) > DISPLAY_LIMIT:
                    output += f"... and {len(all_rows) - DISPLAY_LIMIT} more rows\n"
            else:
                output += "📋 No results returned\n"

            return self._success_response(
                output,
                structured=self._structured(
                    success=True,
                    row_count=row_count,
                    returned_row_count=len(shown),
                    columns=columns,
                    rows=[
                        {str(k): to_json_safe(v) for k, v in row.items()}
                        for row in shown
                    ],
                ),
            )
        else:
            # Error case
            error_msg = (result.get('message') or '').strip()
            # 防禦：若 message 為空、或為「Query execution failed:」尾端冒號（代表 str(e) 為空）
            if not error_msg or error_msg.rstrip(':').strip() in ('', 'Query execution failed'):
                error_msg = result.get('error') or 'Unknown error (empty exception, possible timeout or connection drop)'
            output = f"❌ Query failed: {error_msg}\n\n"

            # Include query for debugging
            output += "📝 Query:\n"
            output += f"```sql\n{query}\n```\n"

            # Deliberately not routed through _error_response: this branch has always
            # reported failure as a readable result rather than a protocol error, because
            # MCPO turns is_error into an HTTP 500 and the message is lost. Only the
            # structured payload is new, and it is what makes this failure
            # machine-distinguishable from a query that matched zero rows.
            return {
                "content": [{
                    "type": "text",
                    "text": output
                }],
                "structuredContent": self._structured(success=False, error=error_msg),
            }
