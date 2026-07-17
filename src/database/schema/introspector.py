"""Database schema inspectors for different database types."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Union
import logging

logger = logging.getLogger(__name__)


class BaseSchemaInspector(ABC):
    """Abstract base class for database schema inspectors."""

    def __init__(self, connection_context, config):
        """Initialize with database connection context manager and config."""
        self.get_connection = connection_context
        self.config = config

    @abstractmethod
    def get_schema_info(self, table_name: Optional[str] = None) -> Dict[str, Any]:
        """Get comprehensive database schema information."""
        pass

    @abstractmethod
    def get_table_dependencies(self, table_name: str) -> Dict[str, Any]:
        """Get table dependencies (foreign keys, referenced by)."""
        pass

    @abstractmethod
    def get_schema_summary(self) -> Dict[str, Any]:
        """Get a high-level summary of the database schema."""
        pass


class MSSQLSchemaInspector(BaseSchemaInspector):
    """SQL Server schema inspector implementation."""

    def get_schema_info(self, table_name: Optional[str] = None) -> Dict[str, Any]:
        """Get comprehensive SQL Server schema information."""
        if table_name:
            return self._get_table_schema(table_name)
        else:
            return self._get_database_schema()

    def _get_table_schema(self, table_name: str) -> Dict[str, Any]:
        """Get detailed schema information for a specific SQL Server table."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # SQL Server specific query for table columns with extended properties (comments)
                query = """
                SELECT
                    c.COLUMN_NAME,
                    c.DATA_TYPE,
                    c.IS_NULLABLE,
                    c.COLUMN_DEFAULT,
                    c.CHARACTER_MAXIMUM_LENGTH,
                    c.NUMERIC_PRECISION,
                    c.NUMERIC_SCALE,
                    pk.IS_PRIMARY_KEY,
                    fk.REFERENCED_TABLE_NAME,
                    fk.REFERENCED_COLUMN_NAME,
                    ep.value as COLUMN_COMMENT
                FROM INFORMATION_SCHEMA.COLUMNS c
                LEFT JOIN (
                    SELECT ku.COLUMN_NAME, 1 as IS_PRIMARY_KEY
                    FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS tc
                    JOIN INFORMATION_SCHEMA.KEY_COLUMN_USAGE ku
                        ON tc.CONSTRAINT_NAME = ku.CONSTRAINT_NAME
                    WHERE tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
                    AND tc.TABLE_NAME = ?
                ) pk ON c.COLUMN_NAME = pk.COLUMN_NAME
                LEFT JOIN (
                    SELECT
                        cp.name as COLUMN_NAME,
                        tr.name as REFERENCED_TABLE_NAME,
                        cr.name as REFERENCED_COLUMN_NAME
                    FROM sys.foreign_keys fk
                    JOIN sys.foreign_key_columns fkc ON fk.object_id = fkc.constraint_object_id
                    JOIN sys.tables tp ON fkc.parent_object_id = tp.object_id
                    JOIN sys.columns cp ON fkc.parent_object_id = cp.object_id AND fkc.parent_column_id = cp.column_id
                    JOIN sys.tables tr ON fkc.referenced_object_id = tr.object_id
                    JOIN sys.columns cr ON fkc.referenced_object_id = cr.object_id AND fkc.referenced_column_id = cr.column_id
                    WHERE tp.name = ?
                ) fk ON c.COLUMN_NAME = fk.COLUMN_NAME
                LEFT JOIN (
                    SELECT
                        t.name as TABLE_NAME,
                        col.name as COLUMN_NAME,
                        ep.value
                    FROM sys.tables t
                    JOIN sys.columns col ON t.object_id = col.object_id
                    JOIN sys.extended_properties ep ON ep.major_id = t.object_id AND ep.minor_id = col.column_id
                    WHERE ep.name = 'MS_Description' AND t.name = ?
                ) ep ON c.TABLE_NAME = ep.TABLE_NAME AND c.COLUMN_NAME = ep.COLUMN_NAME
                WHERE c.TABLE_NAME = ?
                ORDER BY c.ORDINAL_POSITION
                """

                cursor.execute(query, (table_name, table_name, table_name, table_name))
                rows = cursor.fetchall()

                columns = []
                for row in rows:
                    column = {
                        "COLUMN_NAME": row[0],
                        "DATA_TYPE": row[1],
                        "IS_NULLABLE": "YES" if row[2] == "YES" else "NO",
                        "COLUMN_DEFAULT": row[3],
                        "CHARACTER_MAXIMUM_LENGTH": row[4],
                        "NUMERIC_PRECISION": row[5],
                        "NUMERIC_SCALE": row[6],
                        "IS_PRIMARY_KEY": "YES" if bool(row[7]) else "NO",
                        "REFERENCED_TABLE_NAME": row[8],
                        "REFERENCED_COLUMN_NAME": row[9],
                        "COLUMN_COMMENT": row[10] if row[10] else None
                    }
                    columns.append(column)

                return {
                    "success": True,
                    "results": columns,
                    "table_name": table_name,
                    "total_count": len(columns)
                }

        except Exception as e:
            logger.error(f"SQL Server table schema query error: {e}")
            return {
                "success": False,
                "error": str(e),
                "table_name": table_name
            }

    def _get_database_schema(self) -> Dict[str, Any]:
        """Get overview of all SQL Server database objects."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # 診斷: 檢查當前資料庫和表格總數
                cursor.execute("""
                    SELECT
                        DB_NAME() as current_db,
                        COUNT(*) as total_tables
                    FROM INFORMATION_SCHEMA.TABLES
                    WHERE TABLE_TYPE='BASE TABLE'
                """)
                diag = cursor.fetchone()
                logger.info(f"[SQL-DEBUG] Current DB: {diag[0]}, Total BASE TABLES: {diag[1]}")

                # Get all tables and views with comments
                query = """
                SELECT
                    t.TABLE_SCHEMA,
                    t.TABLE_NAME,
                    t.TABLE_TYPE,
                    ep.value as TABLE_COMMENT
                FROM INFORMATION_SCHEMA.TABLES t
                LEFT JOIN (
                    SELECT
                        s.name as TABLE_SCHEMA,
                        tb.name as TABLE_NAME,
                        ep.value
                    FROM sys.tables tb
                    JOIN sys.schemas s ON tb.schema_id = s.schema_id
                    LEFT JOIN sys.extended_properties ep ON ep.major_id = tb.object_id AND ep.minor_id = 0
                    WHERE ep.name = 'MS_Description'
                ) ep ON t.TABLE_SCHEMA = ep.TABLE_SCHEMA AND t.TABLE_NAME = ep.TABLE_NAME
                WHERE t.TABLE_TYPE IN ('BASE TABLE', 'VIEW')
                ORDER BY t.TABLE_SCHEMA, t.TABLE_NAME
                """

                cursor.execute(query)
                rows = cursor.fetchall()
                logger.info(f"[SQL-DEBUG] Schema query returned {len(rows)} rows")

                tables = []
                for row in rows:
                    table = {
                        "TABLE_SCHEMA": row[0],
                        "TABLE_NAME": row[1],
                        "TABLE_TYPE": row[2],
                        "TABLE_COMMENT": row[3] if row[3] else None
                    }
                    tables.append(table)

                return {
                    "success": True,
                    "results": tables,
                    "total_count": len(tables),
                    "database_type": "mssql"
                }

        except Exception as e:
            logger.error(f"SQL Server database schema query error: {e}")
            return {
                "success": False,
                "error": str(e),
                "database_type": "mssql"
            }

    def get_table_dependencies(self, table_name: str) -> Dict[str, Any]:
        """Get SQL Server table dependencies."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # Foreign key dependencies
                query = """
                SELECT
                    fk.name as constraint_name,
                    tp.name as parent_table,
                    cp.name as parent_column,
                    tr.name as referenced_table,
                    cr.name as referenced_column
                FROM sys.foreign_keys fk
                JOIN sys.foreign_key_columns fkc ON fk.object_id = fkc.constraint_object_id
                JOIN sys.tables tp ON fkc.parent_object_id = tp.object_id
                JOIN sys.columns cp ON fkc.parent_object_id = cp.object_id AND fkc.parent_column_id = cp.column_id
                JOIN sys.tables tr ON fkc.referenced_object_id = tr.object_id
                JOIN sys.columns cr ON fkc.referenced_object_id = cr.object_id AND fkc.referenced_column_id = cr.column_id
                WHERE tp.name = ?
                """

                cursor.execute(query, (table_name,))
                dependencies = cursor.fetchall()

                return {
                    "success": True,
                    "table_name": table_name,
                    "dependencies": [
                        {
                            "constraint_name": dep[0],
                            "parent_table": dep[1],
                            "parent_column": dep[2],
                            "referenced_table": dep[3],
                            "referenced_column": dep[4]
                        } for dep in dependencies
                    ]
                }

        except Exception as e:
            logger.error(f"SQL Server dependencies query error: {e}")
            return {
                "success": False,
                "error": str(e),
                "table_name": table_name
            }

    def get_schema_summary(self) -> Dict[str, Any]:
        """Get SQL Server schema summary."""
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                # Count objects
                query = """
                SELECT
                    'Tables' as object_type,
                    COUNT(*) as count
                FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_TYPE = 'BASE TABLE'
                UNION ALL
                SELECT
                    'Views' as object_type,
                    COUNT(*) as count
                FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_TYPE = 'VIEW'
                """

                cursor.execute(query)
                results = cursor.fetchall()

                summary = {"success": True, "database_type": "mssql"}
                for row in results:
                    if row[0] == 'Tables':
                        summary["tables"] = row[1]
                    elif row[0] == 'Views':
                        summary["views"] = row[1]

                # Set defaults for missing values
                summary.setdefault("tables", 0)
                summary.setdefault("views", 0)
                summary.setdefault("procedures", 0)
                summary.setdefault("functions", 0)

                return summary

        except Exception as e:
            logger.error(f"SQL Server schema summary error: {e}")
            return {
                "success": False,
                "error": str(e),
                "database_type": "mssql"
            }


class PostgreSQLSchemaInspector(BaseSchemaInspector):
    """PostgreSQL schema inspector implementation."""

    def get_schema_info(self, table_name: Optional[str] = None) -> Dict[str, Any]:
        """Get comprehensive PostgreSQL schema information."""
        if table_name:
            return self._get_table_schema(table_name)
        else:
            return self._get_database_schema()

    def _get_table_schema(self, table_name: str) -> Dict[str, Any]:
        """Get detailed schema information for a specific PostgreSQL table."""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    # pg_catalog-based query so all queryable relation kinds are covered:
                    # ordinary/partitioned tables, views, materialized views, foreign tables.
                    # (information_schema.columns does not expose materialized views.)
                    query = """
                    SELECT
                        a.attname AS column_name,
                        pg_catalog.format_type(a.atttypid, NULL) AS data_type,
                        CASE WHEN a.attnotnull THEN 'NO' ELSE 'YES' END AS is_nullable,
                        pg_catalog.pg_get_expr(ad.adbin, ad.adrelid) AS column_default,
                        CASE WHEN a.atttypid IN (1042, 1043) AND a.atttypmod > 4
                             THEN a.atttypmod - 4 END AS character_maximum_length,
                        CASE WHEN a.atttypid = 1700 AND a.atttypmod > 4
                             THEN ((a.atttypmod - 4) >> 16) & 65535 END AS numeric_precision,
                        CASE WHEN a.atttypid = 1700 AND a.atttypmod > 4
                             THEN (a.atttypmod - 4) & 65535 END AS numeric_scale,
                        COALESCE(pk.is_pk, false) AS is_primary_key,
                        fk.foreign_table_name,
                        fk.foreign_column_name,
                        d.description AS column_comment
                    FROM pg_catalog.pg_class c
                    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                    JOIN pg_catalog.pg_attribute a
                        ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
                    LEFT JOIN pg_catalog.pg_attrdef ad
                        ON ad.adrelid = c.oid AND ad.adnum = a.attnum
                    LEFT JOIN (
                        SELECT x.indrelid, unnest(x.indkey) AS attnum, true AS is_pk
                        FROM pg_catalog.pg_index x
                        WHERE x.indisprimary
                    ) pk ON pk.indrelid = c.oid AND pk.attnum = a.attnum
                    LEFT JOIN (
                        SELECT
                            con.conrelid,
                            con.conkey[i] AS attnum,
                            fc.relname AS foreign_table_name,
                            fa.attname AS foreign_column_name
                        FROM pg_catalog.pg_constraint con
                        CROSS JOIN LATERAL generate_subscripts(con.conkey, 1) AS i
                        JOIN pg_catalog.pg_class fc ON fc.oid = con.confrelid
                        JOIN pg_catalog.pg_attribute fa
                            ON fa.attrelid = con.confrelid AND fa.attnum = con.confkey[i]
                        WHERE con.contype = 'f'
                    ) fk ON fk.conrelid = c.oid AND fk.attnum = a.attnum
                    LEFT JOIN pg_catalog.pg_description d
                        ON d.objoid = c.oid AND d.objsubid = a.attnum
                    WHERE c.relname = %s
                    AND n.nspname = %s
                    AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
                    ORDER BY a.attnum
                    """

                    schema = self.config.schema
                    cursor.execute(query, (table_name, schema))
                    rows = cursor.fetchall()

                    # PostgreSQL folds unquoted identifiers to lowercase; retry a
                    # cased lookup (e.g. "MY_TABLE" from a case-insensitive caller)
                    # against the folded name before reporting no columns.
                    if not rows and table_name != table_name.lower():
                        cursor.execute(query, (table_name.lower(), schema))
                        rows = cursor.fetchall()

                    columns = []
                    for row in rows:
                        column = {
                            "COLUMN_NAME": row[0],
                            "DATA_TYPE": row[1],
                            "IS_NULLABLE": "YES" if row[2] == "YES" else "NO",
                            "COLUMN_DEFAULT": row[3],
                            "CHARACTER_MAXIMUM_LENGTH": row[4],
                            "NUMERIC_PRECISION": row[5],
                            "NUMERIC_SCALE": row[6],
                            "IS_PRIMARY_KEY": "YES" if row[7] else "NO",
                            "REFERENCED_TABLE": row[8],
                            "REFERENCED_COLUMN": row[9],
                            "COLUMN_COMMENT": row[10] if row[10] else None
                        }
                        columns.append(column)

                    return {
                        "success": True,
                        "results": columns,
                        "table_name": table_name,
                        "total_count": len(columns)
                    }

        except Exception as e:
            logger.error(f"PostgreSQL table schema query error: {e}")
            return {
                "success": False,
                "error": str(e),
                "table_name": table_name
            }

    def _get_database_schema(self) -> Dict[str, Any]:
        """Get overview of all PostgreSQL database objects."""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    # pg_catalog-based listing so all queryable relation kinds are covered
                    # (information_schema.tables does not expose materialized views)
                    query = """
                    SELECT
                        n.nspname AS table_schema,
                        c.relname AS table_name,
                        CASE c.relkind
                            WHEN 'r' THEN 'BASE TABLE'
                            WHEN 'p' THEN 'BASE TABLE'
                            WHEN 'v' THEN 'VIEW'
                            WHEN 'm' THEN 'MATERIALIZED VIEW'
                            WHEN 'f' THEN 'FOREIGN TABLE'
                        END AS table_type,
                        d.description AS table_comment
                    FROM pg_catalog.pg_class c
                    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
                    LEFT JOIN pg_catalog.pg_description d
                        ON d.objoid = c.oid AND d.objsubid = 0
                    WHERE n.nspname = %s
                    AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
                    ORDER BY c.relname
                    """

                    cursor.execute(query, (self.config.schema,))
                    rows = cursor.fetchall()

                    tables = []
                    for row in rows:
                        table = {
                            "TABLE_SCHEMA": row[0],
                            "TABLE_NAME": row[1],
                            "TABLE_TYPE": row[2],
                            "TABLE_COMMENT": row[3] if row[3] else None
                        }
                        tables.append(table)

                    return {
                        "success": True,
                        "results": tables,
                        "total_count": len(tables),
                        "database_type": "postgresql"
                    }

        except Exception as e:
            logger.error(f"PostgreSQL database schema query error: {e}")
            return {
                "success": False,
                "error": str(e),
                "database_type": "postgresql"
            }

    def get_table_dependencies(self, table_name: str) -> Dict[str, Any]:
        """Get PostgreSQL table dependencies."""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    # Foreign key dependencies
                    query = """
                    SELECT
                        tc.constraint_name,
                        tc.table_name as parent_table,
                        kcu.column_name as parent_column,
                        ccu.table_name as referenced_table,
                        ccu.column_name as referenced_column
                    FROM information_schema.table_constraints tc
                    JOIN information_schema.key_column_usage kcu
                        ON tc.constraint_name = kcu.constraint_name
                    JOIN information_schema.constraint_column_usage ccu
                        ON tc.constraint_name = ccu.constraint_name
                    WHERE tc.constraint_type = 'FOREIGN KEY'
                    AND tc.table_name = %s
                    AND tc.table_schema = %s
                    """

                    cursor.execute(query, (table_name, self.config.schema))
                    dependencies = cursor.fetchall()

                    return {
                        "success": True,
                        "table_name": table_name,
                        "dependencies": [
                            {
                                "constraint_name": dep[0],
                                "parent_table": dep[1],
                                "parent_column": dep[2],
                                "referenced_table": dep[3],
                                "referenced_column": dep[4]
                            } for dep in dependencies
                        ]
                    }

        except Exception as e:
            logger.error(f"PostgreSQL dependencies query error: {e}")
            return {
                "success": False,
                "error": str(e),
                "table_name": table_name
            }

    def get_schema_summary(self) -> Dict[str, Any]:
        """Get PostgreSQL schema summary."""
        try:
            with self.get_connection() as conn:
                with conn.cursor() as cursor:
                    # Count objects
                    query = """
                    SELECT
                        'Tables' as object_type,
                        COUNT(*) as count
                    FROM information_schema.tables
                    WHERE table_schema = %s
                    AND table_type = 'BASE TABLE'
                    UNION ALL
                    SELECT
                        'Views' as object_type,
                        COUNT(*) as count
                    FROM information_schema.tables
                    WHERE table_schema = %s
                    AND table_type = 'VIEW'
                    """

                    cursor.execute(query, (self.config.schema, self.config.schema))
                    results = cursor.fetchall()

                    summary = {}
                    for row in results:
                        summary[row[0]] = row[1]

                    return {
                        "success": True,
                        "database_type": "postgresql",
                        "summary": summary
                    }

        except Exception as e:
            logger.error(f"PostgreSQL schema summary error: {e}")
            return {
                "success": False,
                "error": str(e),
                "database_type": "postgresql"
            }


def create_schema_inspector(connection_context, config) -> BaseSchemaInspector:
    """Factory function to create appropriate schema inspector."""
    if config.db_type == "postgresql":
        return PostgreSQLSchemaInspector(connection_context, config)
    elif config.db_type == "mssql":
        return MSSQLSchemaInspector(connection_context, config)
    else:
        raise ValueError(f"Unsupported database type: {config.db_type}")