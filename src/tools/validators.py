"""Input validators for security and data integrity."""

import re
from typing import Tuple


class SQLValidator:
    """SQL query security validator."""

    # Allowed SQL statement types
    ALLOWED_STATEMENTS = {'SELECT', 'WITH'}  # WITH for CTEs

    # Dangerous SQL keywords that should be blocked
    DANGEROUS_KEYWORDS = {
        'DROP', 'DELETE', 'TRUNCATE', 'ALTER', 'CREATE',
        'INSERT', 'UPDATE', 'EXEC', 'EXECUTE', 'GRANT',
        'REVOKE', 'SHUTDOWN', 'KILL', 'MERGE'
    }

    @classmethod
    def validate_query(cls, query: str) -> Tuple[bool, str]:
        """
        Validate that a SQL query is safe to execute.

        Args:
            query: SQL query string to validate

        Returns:
            Tuple of (is_valid, error_message)
            - is_valid: True if query passes all security checks
            - error_message: Empty string if valid, error description if invalid
        """
        if not query or not query.strip():
            return False, "Empty query"

        query_stripped = query.strip()
        query_upper = query_stripped.upper()

        # Check if statement type is allowed
        first_keyword = query_upper.split()[0] if query_upper.split() else ""
        if first_keyword not in cls.ALLOWED_STATEMENTS:
            allowed = ', '.join(cls.ALLOWED_STATEMENTS)
            return False, f"Only {allowed} statements are allowed"

        # Remove string literal contents before scanning for dangerous constructs,
        # so values like WHERE status = 'update' or names containing ';' / '--'
        # do not trigger false positives. Doubled quotes ('') inside a literal
        # are part of the same literal per the SQL standard.
        scannable = re.sub(r"'(?:[^']|'')*'", "''", query_upper)

        # Check for dangerous keywords using word boundaries
        for keyword in cls.DANGEROUS_KEYWORDS:
            # Use regex to match whole words only (avoid false positives like "DROPOFF")
            pattern = rf'\b{keyword}\b'
            if re.search(pattern, scannable):
                return False, f"Dangerous keyword '{keyword}' not allowed"

        # Prevent SQL injection via multiple statements
        # Allow trailing semicolon but not in the middle
        if ';' in scannable[:-1]:
            return False, "Multiple statements not allowed"

        # Block SQL comments that could be used to bypass validation
        if '--' in scannable or '/*' in scannable:
            return False, "SQL comments not allowed"

        # Block xp_ extended stored procedures (SQL Server specific attack vector)
        # Use word boundary to avoid false positives with REGEXP_MATCH, REGEXP_REPLACE etc.
        if re.search(r'\bXP_', scannable):
            return False, "Extended stored procedures not allowed"

        # Block OPENROWSET and OPENDATASOURCE (data exfiltration vectors)
        if 'OPENROWSET' in scannable or 'OPENDATASOURCE' in scannable:
            return False, "OPENROWSET/OPENDATASOURCE not allowed"

        # Block INTO OUTFILE (MySQL) and similar export commands
        if 'INTO OUTFILE' in scannable or 'INTO DUMPFILE' in scannable:
            return False, "File export commands not allowed"

        # Limit query length to prevent DOS attacks
        from core.config import QueryConfig
        config = QueryConfig.from_env()
        if len(query) > config.max_query_length:
            return False, f"Query too long (max {config.max_query_length} characters)"

        return True, ""


class InputValidator:
    """General input validation utilities."""

    @staticmethod
    def validate_table_name(table_name: str) -> Tuple[bool, str]:
        """
        Validate table name format.

        Args:
            table_name: Table name to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        if not table_name:
            return False, "Table name cannot be empty"

        # Allow alphanumeric, underscores, dots (for schema.table), and brackets (for SQL Server)
        if not re.match(r'^[\w\.\[\]]+$', table_name):
            return False, "Invalid table name format (only alphanumeric, _, ., [ ] allowed)"

        # Prevent excessively long names
        if len(table_name) > 256:
            return False, "Table name too long (max 256 characters)"

        # Prevent path traversal attempts
        if '..' in table_name or '/' in table_name or '\\' in table_name:
            return False, "Invalid characters in table name"

        return True, ""

    @staticmethod
    def validate_limit(limit: int, max_limit: int = None) -> Tuple[bool, str]:
        """
        Validate query result limit.

        Args:
            limit: Requested limit value
            max_limit: Maximum allowed limit

        Returns:
            Tuple of (is_valid, error_message)
        """
        from core.config import QueryConfig

        if limit < 0:
            return False, "Limit cannot be negative"

        # Use config default if max_limit not provided
        if max_limit is None:
            config = QueryConfig.from_env()
            max_limit = config.max_query_limit

        if limit > max_limit:
            return False, f"Limit exceeds maximum allowed ({max_limit})"

        return True, ""
