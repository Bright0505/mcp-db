"""Configuration management for MCP Multi-Database Connector."""

import os
from typing import Optional, Literal
from pathlib import Path
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# 載入 .env 檔案，支援多種路徑策略
_env_loaded = False

# 優先使用環境變數指定的路徑
env_file = os.getenv('ENV_FILE_PATH')
if env_file and Path(env_file).exists():
    load_dotenv(env_file, override=False)
    _env_loaded = True
else:
    # 嘗試多個可能的路徑
    possible_paths = [
        Path.cwd() / '.env',  # 當前工作目錄
        Path(__file__).parent.parent.parent / '.env',  # 專案根目錄
        Path('/app/.env')  # Docker 容器路徑（最後嘗試）
    ]
    for env_path in possible_paths:
        if env_path.exists():
            load_dotenv(str(env_path), override=False)
            _env_loaded = True
            break

if not _env_loaded:
    # Fallback 到預設行為
    load_dotenv()


# Database type enum
DatabaseType = Literal["mssql", "postgresql"]


def detect_mssql_driver() -> str:
    """檢測系統可用的 MSSQL ODBC 驅動程式

    Returns:
        str: 可用的驅動程式名稱，優先順序：Driver 18 > Driver 17 > Driver 13
    """
    try:
        import pyodbc
        available_drivers = pyodbc.drivers()

        # 優先順序：Driver 18 > Driver 17 > Driver 13
        preferred_drivers = [
            "ODBC Driver 18 for SQL Server",
            "ODBC Driver 17 for SQL Server",
            "ODBC Driver 13 for SQL Server",
        ]

        for driver in preferred_drivers:
            if driver in available_drivers:
                return driver

        # 如果都找不到，嘗試找任何 SQL Server 驅動程式
        for driver in available_drivers:
            if "SQL Server" in driver:
                return driver
    except (ImportError, Exception):
        # pyodbc 不可用或檢測失敗，使用預設值
        pass

    # 都找不到則使用預設值（會在連接時失敗並提示使用者）
    return "ODBC Driver 18 for SQL Server"


class DatabaseConfig(BaseModel):
    """Database connection configuration supporting multiple database types."""

    # Common fields
    db_type: DatabaseType = Field(default="mssql", description="Database type: mssql or postgresql")
    server: str = Field(description="Database server hostname or IP")
    database: str = Field(description="Database name")
    username: Optional[str] = Field(default=None, description="Database username")
    password: Optional[str] = Field(default=None, description="Database password")
    port: Optional[int] = Field(default=None, description="Database port (auto-detected if None)")
    timeout: int = Field(default=30, description="Connection timeout in seconds")
    command_timeout: int = Field(default=60, description="Async database command timeout in seconds")

    # SQL Server specific fields
    driver: str = Field(default="ODBC Driver 18 for SQL Server", description="ODBC driver for SQL Server")
    trusted_connection: bool = Field(default=False, description="Use Windows authentication for SQL Server")
    encrypt: bool = Field(default=True, description="Use encryption for SQL Server")
    trust_server_certificate: bool = Field(default=False, description="Trust self-signed certificates for SQL Server")

    # PostgreSQL specific fields
    sslmode: str = Field(default="prefer", description="SSL mode for PostgreSQL")
    schema: str = Field(default="public", description="Default schema for PostgreSQL")

    def __init__(self, **data):
        super().__init__(**data)
        # Auto-set default port based on database type if not specified
        if self.port is None:
            self.port = 1433 if self.db_type == "mssql" else 5432

    @classmethod
    def from_env(cls) -> "DatabaseConfig":
        """Create configuration from environment variables."""
        # Determine database type
        db_type = os.getenv("DB_TYPE", "mssql").lower()

        if db_type == "postgresql":
            # PostgreSQL configuration - only use universal DB_* variables
            return cls(
                db_type="postgresql",
                server=os.getenv("DB_HOST", "localhost"),
                database=os.getenv("DB_NAME", "postgres"),
                username=os.getenv("DB_USER"),
                password=os.getenv("DB_PASSWORD"),
                port=int(os.getenv("DB_PORT", "5432")),
                timeout=int(os.getenv("DB_TIMEOUT", "30")),
                command_timeout=int(os.getenv("DB_COMMAND_TIMEOUT", "60")),
                sslmode=os.getenv("DB_SSLMODE", "prefer"),
                schema=os.getenv("DB_SCHEMA", "public")
            )
        else:
            # SQL Server configuration (default) - only use universal DB_* variables
            # 優先使用環境變數，沒有則自動檢測驅動程式
            driver = os.getenv("MSSQL_DRIVER") or detect_mssql_driver()

            return cls(
                db_type="mssql",
                server=os.getenv("DB_HOST", "localhost"),
                database=os.getenv("DB_NAME", "master"),
                username=os.getenv("DB_USER"),
                password=os.getenv("DB_PASSWORD"),
                driver=driver,
                port=int(os.getenv("DB_PORT", "1433")),
                timeout=int(os.getenv("DB_TIMEOUT", "30")),
                command_timeout=int(os.getenv("DB_COMMAND_TIMEOUT", "60")),
                trusted_connection=os.getenv("MSSQL_TRUSTED_CONNECTION", "false").lower() == "true",
                encrypt=os.getenv("MSSQL_ENCRYPT", "true").lower() == "true",
                trust_server_certificate=os.getenv("MSSQL_TRUST_CERTIFICATE", "false").lower() == "true"
            )

    def get_connection_string(self) -> str:
        """Generate database connection string based on database type."""
        if self.db_type == "postgresql":
            return self._get_postgresql_connection_string()
        else:
            return self._get_mssql_connection_string()

    def _get_mssql_connection_string(self) -> str:
        """Generate ODBC connection string for SQL Server."""
        parts = [
            f"DRIVER={{{self.driver}}}",
            f"SERVER={self.server},{self.port}",
            f"DATABASE={self.database}",
            f"TIMEOUT={self.timeout}"
        ]

        if self.trusted_connection:
            parts.append("Trusted_Connection=yes")
        elif self.username and self.password:
            parts.extend([f"UID={self.username}", f"PWD={self.password}"])

        # For ODBC Driver 18, always specify encryption explicitly
        if self.encrypt:
            parts.append("Encrypt=yes")
            # Only add TrustServerCertificate if encryption is enabled
            if self.trust_server_certificate:
                parts.append("TrustServerCertificate=yes")
        else:
            parts.append("Encrypt=no")

        return ";".join(parts)

    def _get_postgresql_connection_string(self) -> str:
        """Generate connection string for PostgreSQL."""
        parts = [
            f"host={self.server}",
            f"port={self.port}",
            f"dbname={self.database}",
            f"connect_timeout={self.timeout}",
            f"sslmode={self.sslmode}"
        ]

        if self.username:
            parts.append(f"user={self.username}")
        if self.password:
            parts.append(f"password={self.password}")

        # Set search_path via options parameter (libpq format)
        # Format: options='-c search_path=schema1,schema2'
        if self.schema:
            parts.append(f"options='-c search_path={self.schema},public'")

        return " ".join(parts)


class SchemaConfig(BaseModel):
    """Schema caching and preload configuration."""

    enable_cache: bool = True
    cache_ttl_minutes: int = 60  # Default 1 hour, configurable via SCHEMA_CACHE_TTL_MINUTES
    preload_on_startup: bool = True
    schema_config_path: Optional[str] = None
    enable_parallel_preload: bool = True
    max_concurrent_queries: int = 5
    strict_mode: bool = False

    @classmethod
    def from_env(cls) -> "SchemaConfig":
        """Create schema configuration from environment variables."""
        return cls(
            enable_cache=os.getenv("SCHEMA_ENABLE_CACHE", "true").lower() == "true",
            cache_ttl_minutes=int(os.getenv("SCHEMA_CACHE_TTL_MINUTES", "60")),
            preload_on_startup=os.getenv("SCHEMA_PRELOAD_ON_STARTUP", "true").lower() == "true",
            schema_config_path=os.getenv("SCHEMA_CONFIG_PATH", "schemas_config/"),
            enable_parallel_preload=os.getenv("SCHEMA_PARALLEL_PRELOAD", "true").lower() == "true",
            max_concurrent_queries=int(os.getenv("SCHEMA_MAX_CONCURRENT_QUERIES", "5")),
            strict_mode=os.getenv("SCHEMA_STRICT_MODE", "false").lower() == "true"
        )

    def get_config_path(self) -> Optional[Path]:
        """Get path to schema configuration file."""
        if not self.schema_config_path:
            return None
        
        config_path = Path(self.schema_config_path)
        if not config_path.is_absolute():
            # Look in current directory first
            if config_path.exists():
                return config_path
            # Then look in project root
            project_root = Path(__file__).parent.parent.parent
            full_path = project_root / config_path
            if full_path.exists():
                return full_path
        else:
            if config_path.exists():
                return config_path
        
        return None


class QueryConfig(BaseModel):
    """Query validation and limit configuration."""

    max_query_length: int = 50000  # Maximum SQL query length in characters
    max_query_limit: int = 10000   # Maximum LIMIT value for query results

    @classmethod
    def from_env(cls) -> "QueryConfig":
        """Create query configuration from environment variables."""
        return cls(
            max_query_length=int(os.getenv("MAX_QUERY_LENGTH", "50000")),
            max_query_limit=int(os.getenv("MAX_QUERY_LIMIT", "10000"))
        )


class ClaudeConfig(BaseModel):
    """Claude API configuration for Streamlit AI features."""

    api_key: Optional[str] = None
    api_url: str = "https://api.anthropic.com/v1/messages"
    model: str = "claude-3-5-haiku-20241022"
    max_tokens: int = 4000
    temperature: float = 0.1
    timeout: int = 30
    enabled: bool = False
    
    @classmethod
    def from_env(cls) -> "ClaudeConfig":
        """Create Claude configuration from environment variables.

        Returns disabled config if CLAUDE_API_KEY is not set (for MCP/HTTP usage without AI).
        """
        import logging
        logger = logging.getLogger(__name__)

        api_key = os.getenv("CLAUDE_API_KEY")
        if not api_key:
            logger.info("CLAUDE_API_KEY not found - Claude AI features will be disabled")
            return cls(enabled=False)

        return cls(
            api_key=api_key,
            api_url=os.getenv("CLAUDE_API_URL", "https://api.anthropic.com/v1/messages"),
            model=os.getenv("CLAUDE_MODEL", "claude-3-5-haiku-20241022"),
            max_tokens=int(os.getenv("CLAUDE_MAX_TOKENS", "4000")),
            temperature=float(os.getenv("CLAUDE_TEMPERATURE", "0.1")),
            timeout=int(os.getenv("CLAUDE_TIMEOUT", "30")),
            enabled=True  # Always enabled when API key is present
        )
    
    @property
    def is_available(self) -> bool:
        """Check if Claude API is available and configured."""
        return self.enabled and bool(self.api_key)


class HTTPConfig(BaseModel):
    """HTTP server configuration including rate limiting and CORS."""

    rate_limit_default: str = Field(
        default="100/minute",
        description="Default rate limit for all endpoints"
    )
    rate_limit_query: str = Field(
        default="100/minute",
        description="Rate limit for query endpoints"
    )
    cors_preflight_max_age: int = Field(
        default=600,
        description="CORS preflight max age in seconds"
    )

    @classmethod
    def from_env(cls) -> "HTTPConfig":
        """Create HTTP configuration from environment variables."""
        return cls(
            rate_limit_default=os.getenv("RATE_LIMIT_DEFAULT", "100/minute"),
            rate_limit_query=os.getenv("RATE_LIMIT_QUERY", "30/minute"),
            cors_preflight_max_age=int(os.getenv("CORS_PREFLIGHT_MAX_AGE", "600"))
        )


def get_http_config() -> "HTTPConfig":
    """Get HTTPConfig singleton from environment variables."""
    return HTTPConfig.from_env()


class AppConfig(BaseModel):
    """Application configuration combining all configs."""

    database: DatabaseConfig
    schema_config: SchemaConfig
    query_config: QueryConfig
    claude_config: ClaudeConfig
    http_config: HTTPConfig
    expose_sensitive_info: bool = False  # Control whether to expose sensitive info in health checks
    tool_prefix: str = Field(default="db", description="Prefix for MCP tool names (e.g. db_query)")
    server_name: str = Field(default="mcp-db", description="MCP server name identifier")

    @classmethod
    def from_env(cls) -> "AppConfig":
        """Create full application configuration from environment variables."""
        return cls(
            database=DatabaseConfig.from_env(),
            schema_config=SchemaConfig.from_env(),
            query_config=QueryConfig.from_env(),
            claude_config=ClaudeConfig.from_env(),
            http_config=HTTPConfig.from_env(),
            expose_sensitive_info=os.getenv("EXPOSE_SENSITIVE_INFO", "false").lower() == "true",
            tool_prefix=os.getenv("TOOL_PREFIX", "db"),
            server_name=os.getenv("MCP_SERVER_NAME", "mcp-db")
        )