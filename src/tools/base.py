"""Base classes for MCP tool handlers."""

from abc import ABC, abstractmethod
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import UUID

from mcp.types import CallToolRequest


def to_json_safe(value: Any) -> Any:
    """Coerce a database value into something JSON can carry.

    Needed only for `structuredContent`: the text branch renders values with `str()`,
    which never fails, whereas structured content is serialised as JSON.

    Type choices, and why:
      * `Decimal` -> `float`. Money in these databases stays far below float64's
        ~15 significant digits (the largest figure encountered is ~4e8 with two
        decimals), so no precision is lost, and a number is directly usable by a
        caller doing arithmetic. A non-finite Decimal cannot be represented in JSON
        and falls through to `str()`.
      * `datetime` / `date` / `time` -> ISO 8601 string. Unambiguous and sortable.
      * `bytes` -> `repr()`, not a decode attempt: binary columns are not text, and a
        lossy decode would silently corrupt them.
      * anything else unknown -> `str()`, matching the text branch.
    """
    if value is None or isinstance(value, (bool, int, float, str)):
        # bool before int is not needed here (both pass through), but note that
        # isinstance(True, int) is True -- listing bool explicitly documents intent.
        if isinstance(value, float) and value != value:  # NaN
            return str(value)
        return value
    if isinstance(value, Decimal):
        if value.is_finite():
            return float(value)
        return str(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (list, tuple, set)):
        return [to_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {str(k): to_json_safe(v) for k, v in value.items()}
    if isinstance(value, bytes):
        return repr(value)
    return str(value)


class ToolHandler(ABC):
    """Abstract base class for MCP tool handlers.

    Structured output (SEP-2106)
    ----------------------------
    A handler may return a `structuredContent` key alongside `content`; the protocol
    layer forwards it to `CallToolResult.structured_content`.

    Declaring `outputSchema` on a tool is a **binding contract**, not a hint. The SDK
    client validates it automatically inside `ClientSession.call_tool`
    (`mcp/client/session.py`): for any result where `is_error` is false, a missing or
    non-conforming `structuredContent` raises `RuntimeError` on the client side. Since
    the tool layer's `isError` flag is deliberately not propagated to
    `CallToolResult.is_error` (see `_error_response`), *every* return path of such a
    handler -- including the ones that report failure -- has to carry conforming
    structured content.

    That is why a handler that declares `outputSchema` should build its structured
    payload through one helper it controls, so no branch can forget it. See
    `QueryHandler._structured` and the protocol tests that exercise every branch of it.
    """

    @property
    @abstractmethod
    def tool_names(self) -> List[str]:
        """Return list of tool names this handler supports."""
        pass

    @abstractmethod
    async def handle(self, request: CallToolRequest, db_manager: Any) -> Dict[str, Any]:
        """
        Handle tool invocation.

        Args:
            request: MCP tool call request
            db_manager: Database manager instance

        Returns:
            MCP response dictionary with 'content' key, optionally 'structuredContent'
        """
        pass

    def _error_response(
        self, error_message: str, structured: Optional[Any] = None
    ) -> Dict[str, Any]:
        """Create standardized error response.

        The `isError` flag is machine-readable and sits alongside `content`, not inside
        it, so it never reaches the model as text.

        Not yet consumed by the protocol layer: propagating it to
        `CallToolResult.is_error` made failures inconsistent, because not every handler
        routes failure through this method (some format their own error text and return
        it as a success). Making failure reporting uniform across handlers is a
        prerequisite -- see the migration ISSUES log.

        Why it matters: without the flag a failed tool call is indistinguishable from a
        successful one carrying error text, and a model that cannot tell the difference
        may present the failure as if it were data.

        `structured` is mandatory for tools that declare `outputSchema`: because
        `isError` is not propagated, the client still validates this result.
        """
        response: Dict[str, Any] = {
            "isError": True,
            "content": [{
                "type": "text",
                "text": f"❌ Error: {error_message}"
            }]
        }
        if structured is not None:
            response["structuredContent"] = structured
        return response

    def _success_response(
        self, text: str, structured: Optional[Any] = None
    ) -> Dict[str, Any]:
        """Create standardized success response."""
        response: Dict[str, Any] = {
            "content": [{
                "type": "text",
                "text": text
            }]
        }
        if structured is not None:
            response["structuredContent"] = structured
        return response
