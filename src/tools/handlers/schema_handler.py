"""Schema information handlers."""

import logging
from typing import Any, Dict, List
from mcp.types import CallToolRequest

# DB_* must be read through env(), not os.getenv: a module with ENV_PREFIX set
# has its own namespace and would otherwise pick up the shared deployment value.
# Reporting the wrong DB_TYPE here is not cosmetic -- the schema output carries a
# SQL dialect hint that the model follows when writing queries.
from core.config import env
from tools.base import ToolHandler
from tools.definitions import make_tool_name, TOOL_SCHEMA, TOOL_SCHEMA_SUMMARY
from tools.validators import InputValidator

logger = logging.getLogger(__name__)


class SchemaHandler(ToolHandler):
    """Handler for schema information queries."""

    @property
    def tool_names(self) -> List[str]:
        return [
            make_tool_name(TOOL_SCHEMA),
            make_tool_name(TOOL_SCHEMA_SUMMARY)
        ]

    async def handle(self, request: CallToolRequest, db_manager: Any) -> Dict[str, Any]:
        """
        Handle schema information requests.

        Args:
            request: MCP tool call request
            db_manager: Database manager instance

        Returns:
            Schema information
        """
        if request.name == make_tool_name(TOOL_SCHEMA):
            table_name = request.arguments.get("table_name")
            return self._handle_schema(db_manager, table_name)
        elif request.name == make_tool_name(TOOL_SCHEMA_SUMMARY):
            return self._handle_schema_summary(db_manager)
        else:
            return self._error_response(f"Unknown schema operation: {request.name}")

    def _handle_schema(self, db_manager: Any, table_name: str = None) -> Dict[str, Any]:
        """Get detailed schema information for a table or list all tables."""
        # Validate table name if provided
        if table_name:
            is_valid, error_msg = InputValidator.validate_table_name(table_name)
            if not is_valid:
                return self._error_response(error_msg)
        
        result = db_manager.get_schema_info(table_name)

        # 添加診斷日誌
        logger.info(f"[SCHEMA-DEBUG] get_schema_info({table_name or 'ALL'}) - "
                   f"success={result.get('success')}, "
                   f"total_count={result.get('total_count')}, "
                   f"cache_source={result.get('cache_source')}, "
                   f"source={result.get('source')}")

        if not result["success"]:
            error_msg = result.get('message') or result.get('error', 'Unknown error')
            return self._error_response(f"Schema query failed: {error_msg}")
        
        if table_name:
            return self._format_table_schema(result, table_name)
        else:
            return self._format_all_tables(result, db_manager)

    def _format_table_schema(self, result: Dict[str, Any], table_name: str) -> Dict[str, Any]:
        """Format detailed table schema."""
        db_type = result.get('database_type') or env('DB_TYPE', 'mssql').lower()
        db_type_display = 'SQL Server (T-SQL)' if db_type == 'mssql' else 'PostgreSQL'

        output = f"✅ Schema for table '{table_name}':\n"
        output += f"🗄️  Database: {db_type_display}\n\n"

        # Table statistics
        if result.get("table_stats"):
            stats = result["table_stats"]
            output += "📊 Table Statistics:\n"
            output += f"   • Rows: {stats['row_count']:,}\n"
            output += f"   • Size: {stats['size_mb']:.2f} MB\n\n"
        
        # Business Logic
        if result.get("business_logic"):
            logic = result["business_logic"]
            output += "💼 Business Logic:\n"
            if logic.get("primary_date_field"):
                output += f"   • Primary Date: {logic['primary_date_field']}\n"
            if logic.get("active_records_filter"):
                output += f"   • Active Filter: {logic['active_records_filter']}\n"
            if logic.get("status_values"):
                status_str = ", ".join([f"{k}={v}" for k, v in logic["status_values"].items()])
                output += f"   • Status Values: {status_str}\n"
            if logic.get("main_business_rules"):
                output += "   • Rules:\n"
                for rule in logic["main_business_rules"]:
                    output += f"     - {rule}\n"
            output += "\n"

        # AI Context
        if result.get("ai_context"):
            ctx = result["ai_context"]
            output += "🤖 AI Context (Prompt Injection):\n"
            if ctx.get("query_keywords"):
                output += f"   • Keywords: {', '.join(ctx['query_keywords'])}\n"
            if ctx.get("common_filters"):
                output += "   • Common Filters:\n"
                for filter_txt in ctx["common_filters"]:
                    output += f"     - {filter_txt}\n"
            if ctx.get("suggested_joins"):
                output += "   • Suggested Joins:\n"
                for join in ctx["suggested_joins"]:
                    output += f"     - {join}\n"
            output += "\n"
        
        # Columns
        output += f"📋 Columns ({result['total_count']}):\n"
        for column in result["results"]:
            output += self._format_column(column) + "\n"
        
        return self._success_response(output)

    def _format_column(self, column: Dict[str, Any]) -> str:
        """Format a single column's information with semantic type labels."""
        col_name = column.get('COLUMN_NAME', 'unknown')
        col_type = column.get('DATA_TYPE') or column.get('data_type', 'unknown')
        col_info = f"   • {col_name}: {col_type}"

        # Add length/precision
        if column.get('CHARACTER_MAXIMUM_LENGTH'):
            col_info += f"({column['CHARACTER_MAXIMUM_LENGTH']})"
        elif column.get('NUMERIC_PRECISION'):
            precision = column['NUMERIC_PRECISION']
            scale = column.get('NUMERIC_SCALE', 0)
            col_info += f"({precision},{scale})"

        # Nullable
        is_nullable = column.get('IS_NULLABLE', column.get('is_nullable', 'YES'))
        col_info += f" {'NULL' if is_nullable == 'YES' else 'NOT NULL'}"

        # Semantic type label (AI-friendly hints)
        semantic_label = self._get_semantic_label(column)
        if semantic_label:
            col_info += f" {semantic_label}"

        # Keys (only if no semantic label already shows this)
        if column.get('IS_PRIMARY_KEY') == 'YES' and 'primary' not in semantic_label.lower():
            col_info += " 🔑PK"
        if column.get('IS_FOREIGN_KEY') == 'YES':
            ref_table = column.get('REFERENCED_TABLE_NAME')
            ref_column = column.get('REFERENCED_COLUMN_NAME')
            if ref_table and '→' not in col_info:
                col_info += f" →{ref_table}.{ref_column}"

        # Default
        if column.get('COLUMN_DEFAULT'):
            col_info += f" DEFAULT {column['COLUMN_DEFAULT']}"

        # Description (prioritize DESCRIPTION, then ai_hints)
        description = self._get_column_description(column)
        if description:
            col_info += f" - {description}"

        return col_info

    def _get_semantic_label(self, column: Dict[str, Any]) -> str:
        """Get semantic type label with emoji for AI readability."""
        semantic_type = column.get('semantic_type', '').lower()

        # Semantic type to emoji/label mapping
        semantic_labels = {
            'primary_identifier': '[🔑主鍵]',
            'primary_date': '[📅日期]',
            'primary_amount': '[💰金額]',
            'total_amount': '[💰總額]',
            'money': '[💰金額]',
            'foreign_key': '[🔗外鍵]',
            'quantity': '[📊數量]',
            'status': '[⚙️狀態]',
            'identifier': '[🆔識別碼]',
            'datetime': '[📅時間]',
            'name': '[📛名稱]',
            'category': '[📁分類]',
            'number': '[🔢序號]',
        }

        return semantic_labels.get(semantic_type, '')

    def _get_column_description(self, column: Dict[str, Any]) -> str:
        """Get the best description for a column."""
        # Priority: description/DESCRIPTION > ai_hints > usage_notes > REMARKS
        desc = column.get('description') or column.get('DESCRIPTION')
        if desc and str(desc).strip():
            return str(desc).strip()
        if column.get('ai_hints') and str(column['ai_hints']).strip():
            return str(column['ai_hints']).strip()
        if column.get('usage_notes') and str(column['usage_notes']).strip():
            return str(column['usage_notes']).strip()
        if column.get('REMARKS') and str(column['REMARKS']).strip():
            return str(column['REMARKS']).strip()
        return ''

    def _format_all_tables(self, result: Dict[str, Any], db_manager: Any) -> Dict[str, Any]:
        """Format list of all database tables."""

        # 檢查空結果
        if result.get('total_count', 0) == 0:
            output = "⚠️  No database objects found\n\n"
            output += "📋 Troubleshooting:\n"
            output += "   1. Database may have no tables/views\n"
            output += "   2. Insufficient permissions to query INFORMATION_SCHEMA\n"
            output += "   3. Cache not properly initialized\n"
            output += "   4. Connected to wrong database/schema\n\n"
            db_type_env = env('DB_TYPE', 'unknown').lower()
            output += f"🗄️  Database Type: {result.get('database_type') or db_type_env}\n"
            output += f"💾 Cache Source: {result.get('cache_source', 'unknown')}\n"
            output += f"📡 Source: {result.get('source', 'unknown')}\n"
            return self._success_response(output)

        db_type = result.get('database_type') or env('DB_TYPE', 'mssql').lower()
        db_type_display = {
            'mssql': 'SQL Server (T-SQL)',
            'postgresql': 'PostgreSQL'
        }.get(db_type, db_type)

        output = f"✅ Database schema (showing {result['total_count']} objects):\n\n"
        output += f"🗄️  Database Type: {db_type_display}\n"
        # 根據資料庫類型顯示對應的語法提示
        if db_type == 'postgresql':
            output += f"📝 Syntax Guide: Use CURRENT_DATE for current date, LIMIT N for limits, PostgreSQL functions\n\n"
        else:
            output += f"📝 Syntax Guide: Use GETDATE() for current date, TOP N for limits, T-SQL functions\n\n"

        # Group by schema and type
        tables = {}
        total_rows = 0
        total_size = 0.0

        for obj in result["results"]:
            schema = obj['TABLE_SCHEMA']
            obj_type = obj['TABLE_TYPE']

            # Normalize table type: 'TABLE' -> 'BASE TABLE'
            if obj_type == 'TABLE':
                obj_type = 'BASE TABLE'

            if schema not in tables:
                tables[schema] = {'BASE TABLE': [], 'VIEW': []}

            size_mb_raw = obj.get('SIZE_MB', 0.0)
            rows_raw = obj.get('ROW_COUNT', 0)
            # 優先使用 DISPLAY_NAME，其次 ENHANCED_DISPLAY_NAME
            display_name = obj.get('DISPLAY_NAME') or obj.get('ENHANCED_DISPLAY_NAME') or ''
            obj_info = {
                'name': obj['TABLE_NAME'],
                'display_name': display_name,
                'rows': int(rows_raw) if rows_raw is not None else 0,
                'size_mb': float(size_mb_raw) if size_mb_raw is not None else 0.0
            }

            if obj_type in tables[schema]:
                tables[schema][obj_type].append(obj_info)

            if obj_type == 'BASE TABLE':
                total_rows += obj_info['rows'] or 0
                total_size += obj_info['size_mb'] or 0.0
        
        # Summary
        if total_rows > 0 or total_size > 0:
            output += f"📊 Summary: {total_rows:,} total rows, {total_size:.2f} MB total size\n\n"
        
        # Show objects by schema
        for schema, types in tables.items():
            output += f"📂 Schema: {schema}\n"
            
            if types['BASE TABLE']:
                output += f"   📋 Tables ({len(types['BASE TABLE'])}):\n"
                for table in types['BASE TABLE']:
                    # 顯示表格註解
                    display_info = f" - {table['display_name']}" if table.get('display_name') else ""
                    size_info = f" ({table['rows']:,} rows, {table['size_mb']:.1f} MB)" if table['rows'] or table['size_mb'] else ""
                    output += f"      • {table['name']}{display_info}{size_info}\n"
            
            if types['VIEW']:
                output += f"   👁️ Views ({len(types['VIEW'])}):\n"
                for view in types['VIEW']:
                    output += f"      • {view['name']}\n"
            
            output += "\n"
        
        return self._success_response(output)

    def _handle_schema_summary(self, db_manager: Any) -> Dict[str, Any]:
        """Get high-level database summary."""
        result = db_manager.get_database_info()
        
        if not result["success"]:
            error_msg = result.get('message') or result.get('error', 'Unknown error')
            return self._error_response(f"Database info query failed: {error_msg}")

        db_type = result.get('database_type') or env('DB_TYPE', 'mssql').lower()
        db_type_display = {
            'mssql': 'SQL Server (T-SQL)',
            'postgresql': 'PostgreSQL'
        }.get(db_type, db_type)
        
        output = "📊 Database Overview\n\n"
        output += f"🗄️  Type: {db_type_display}\n"
        output += f"💾 Database: {result.get('database_name', 'N/A')}\n"
        output += f"📡 Server: {result.get('server_name', 'N/A')}\n\n"
        
        summary = result.get('summary', {})
        output += "📋 Object Counts:\n"
        output += f"   • Tables: {summary.get('total_tables', 0)}\n"
        output += f"   • Views: {summary.get('total_views', 0)}\n"
        output += f"   • Stored Procedures: {summary.get('total_procedures', 0)}\n"
        output += f"   • Functions: {summary.get('total_functions', 0)}\n"
        
        if summary.get('total_size_mb'):
            output += f"\n📊 Total Size: {summary['total_size_mb']:.2f} MB\n"
        
        return self._success_response(output)
