"""Schema caching and preload functionality."""

import json
import logging
from typing import Any, Dict, List, Optional
from pathlib import Path
from datetime import datetime, timedelta
from threading import RLock
from concurrent.futures import ThreadPoolExecutor, as_completed

# DB_* must be read through env(), not os.getenv: a module with ENV_PREFIX set
# has its own namespace and would otherwise pick up the shared deployment value.
from core.config import env

logger = logging.getLogger(__name__)


class SchemaCache:
    """Thread-safe high-performance schema caching system with preload tracking."""

    def __init__(self, cache_ttl_minutes: int = 60, max_size: int = 1000):
        """Initialize schema cache with configurable TTL and size limit."""
        self.cache: Dict[str, Any] = {}
        self.cache_ttl = timedelta(minutes=cache_ttl_minutes)
        self.last_updated: Dict[str, datetime] = {}
        self.max_size = max_size
        self._lock = RLock()

        # LFU+LRU tracking (for intelligent cache eviction)
        self.access_count: Dict[str, int] = {}  # Access frequency
        self.last_access: Dict[str, datetime] = {}  # Last access time

        # Preload tracking
        self.preload_status: Dict[str, Dict[str, Any]] = {
            "static_preload_completed": False,
            "dynamic_preload_completed": False,
            "static_tables": set(),
            "dynamic_tables": set(),
            "preload_timestamp": None
        }
        
    def get(self, key: str) -> Optional[Any]:
        """Get cached value if not expired (thread-safe), with access tracking."""
        with self._lock:
            hit = key in self.cache
            valid = self._is_valid(key) if hit else False
            logger.info(f"[CACHE-GET] key='{key}', cache_id={id(self)}, hit={hit}, valid={valid}, total_keys={len(self.cache)}")

            if key in self.cache:
                if self._is_valid(key):
                    # Record access for LFU+LRU eviction strategy
                    self.access_count[key] = self.access_count.get(key, 0) + 1
                    self.last_access[key] = datetime.now()
                    return self.cache[key]
                else:
                    self._invalidate(key)
            return None
    
    def set(self, key: str, value: Any) -> None:
        """Cache value with timestamp (thread-safe)."""
        with self._lock:
            # LFU+LRU hybrid eviction strategy
            if len(self.cache) >= self.max_size:
                self._evict_lfu_lru(int(self.max_size * 0.1))
            self.cache[key] = value
            self.last_updated[key] = datetime.now()
            # Initialize access tracking for new entries
            self.access_count[key] = self.access_count.get(key, 0)
            self.last_access[key] = datetime.now()
            logger.info(f"[CACHE-SET] key='{key}', cache_id={id(self)}, total_keys={len(self.cache)}")
    
    def invalidate(self, key: str) -> None:
        """Manually invalidate cache entry (thread-safe)."""
        with self._lock:
            self._invalidate(key)

    def clear(self) -> None:
        """Clear all cache entries (thread-safe)."""
        with self._lock:
            self.cache.clear()
            self.last_updated.clear()
            self.access_count.clear()
            self.last_access.clear()
    
    def _is_valid(self, key: str) -> bool:
        """Check if cache entry is still valid."""
        if key not in self.last_updated:
            return False
        return datetime.now() - self.last_updated[key] < self.cache_ttl
    
    def _invalidate(self, key: str) -> None:
        """Remove expired cache entry and its access tracking."""
        self.cache.pop(key, None)
        self.last_updated.pop(key, None)
        self.access_count.pop(key, None)
        self.last_access.pop(key, None)

    def _evict_lfu_lru(self, count: int) -> None:
        """
        Evict cache entries using LFU+LRU hybrid strategy.

        Score = frequency / (1 + hours_since_access)
        - High frequency + recent access = high score (keep)
        - Low frequency or old access = low score (evict)

        This ensures hot (frequently accessed) entries are never evicted,
        while cold entries are removed even if recently added.
        """
        if not self.cache:
            return

        now = datetime.now()
        scores = {}

        for key in self.cache:
            # Get access frequency (default 0 for entries without access tracking)
            frequency = self.access_count.get(key, 0)

            # Get last access time (default to creation time if never accessed)
            last_access_time = self.last_access.get(key, self.last_updated.get(key, now - timedelta(days=365)))

            # Calculate hours since last access
            hours_since_access = (now - last_access_time).total_seconds() / 3600

            # Calculate score: frequency / (1 + hours)
            # Higher frequency and recent access = higher score
            scores[key] = frequency / (1 + hours_since_access)

        # Sort by score (ascending) and evict lowest-scoring entries
        evict_keys = sorted(scores.items(), key=lambda x: x[1])[:count]

        for key, score in evict_keys:
            logger.debug(f"[CACHE-EVICT] key='{key}', score={score:.4f}, freq={self.access_count.get(key, 0)}, hours={hours_since_access:.2f}")
            self.cache.pop(key, None)
            self.last_updated.pop(key, None)
            self.access_count.pop(key, None)
            self.last_access.pop(key, None)

        logger.info(f"[CACHE-EVICT] Evicted {len(evict_keys)} entries using LFU+LRU strategy")

    def mark_static_preload_complete(self, table_names: List[str]) -> None:
        """Mark static preload as completed (thread-safe)."""
        with self._lock:
            self.preload_status["static_preload_completed"] = True
            self.preload_status["static_tables"] = set(table_names)
            self.preload_status["preload_timestamp"] = datetime.now()
            logger.info(f"Static preload completed: {len(table_names)} tables")

    def mark_dynamic_preload_complete(self, table_names: List[str]) -> None:
        """Mark dynamic preload as completed (thread-safe)."""
        with self._lock:
            self.preload_status["dynamic_preload_completed"] = True
            self.preload_status["dynamic_tables"] = set(table_names)
            self.preload_status["preload_timestamp"] = datetime.now()
            logger.info(f"Dynamic preload completed: {len(table_names)} tables")

    def get_preload_status(self) -> Dict[str, Any]:
        """Get current preload status (thread-safe)."""
        with self._lock:
            return {
                "static_preload_completed": self.preload_status["static_preload_completed"],
                "dynamic_preload_completed": self.preload_status["dynamic_preload_completed"],
                "static_tables_count": len(self.preload_status["static_tables"]),
                "dynamic_tables_count": len(self.preload_status["dynamic_tables"]),
                "total_tables": len(self.preload_status["static_tables"] | self.preload_status["dynamic_tables"]),
                "preload_timestamp": self.preload_status["preload_timestamp"].isoformat() if self.preload_status["preload_timestamp"] else None,
                "cache_size": len(self.cache)
            }

    def is_table_preloaded(self, table_name: str) -> Dict[str, bool]:
        """Check if a table is preloaded and from which source (thread-safe)."""
        with self._lock:
            return {
                "in_static": table_name.upper() in self.preload_status["static_tables"],
                "in_dynamic": table_name.upper() in self.preload_status["dynamic_tables"],
                "preloaded": (table_name.upper() in self.preload_status["static_tables"]) or
                            (table_name.upper() in self.preload_status["dynamic_tables"])
            }


class SchemaPreloader:
    """Schema preloading from configuration files."""
    
    def __init__(self, schema_introspector, cache: SchemaCache):
        """Initialize with schema introspector and cache."""
        self.introspector = schema_introspector
        self.cache = cache
        self.preload_config: Dict[str, Any] = {}
        self.static_loader = None  # Will be initialized if static files are available
    
    def load_schema_config(self, config_path: str) -> bool:
        """Load schema configuration from JSON file."""
        try:
            config_file = Path(config_path)
            if not config_file.exists():
                logger.warning(f"Schema config file not found: {config_path}")
                return False
            
            # 如果是目錄，可能不需要載入特定的預載配置，而是依賴靜態掃描
            if config_file.is_dir():
                logger.debug(f"Config path is a directory: {config_path}, skipping specific preload config load")
                return True

            with open(config_file, 'r', encoding='utf-8') as f:
                self.preload_config = json.load(f)
            
            logger.info(f"Loaded schema configuration from {config_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to load schema config: {e}")
            return False

    def load_config_and_preload(self, config_path: str, max_concurrent: int = 5) -> bool:
        """Load configuration and execute parallel preload."""
        try:
            # 嘗試載入配置
            if config_path:
                self.load_schema_config(config_path)

            # 執行並行預載（使用線程池）
            return self.preload_schemas_concurrent(max_concurrent)
        except Exception as e:
            logger.error(f"Load config and preload failed: {e}")
            return False
    
    def preload_schemas(self) -> bool:
        """Preload schemas based on configuration with status tracking."""
        success = True

        # First, try to preload static schemas if available
        if self._try_preload_static_schemas():
            logger.info("✅ Static schema files preloaded successfully")

        # Then preload from database if configuration exists
        if not self.preload_config:
            logger.info("No dynamic schema preload configuration found")
            return success

        try:
            # Preload database overview
            if self.preload_config.get("preload_overview", True):
                self._preload_database_overview()

            # Preload specific tables
            tables_to_preload = self.preload_config.get("preload_tables", [])
            successfully_loaded = []
            for table_name in tables_to_preload:
                if self._preload_table_schema(table_name):
                    successfully_loaded.append(table_name)

            # Preload dependencies for critical tables
            critical_tables = self.preload_config.get("critical_tables", [])
            for table_name in critical_tables:
                self._preload_table_dependencies(table_name)
                if table_name not in successfully_loaded:
                    successfully_loaded.append(table_name)

            # Mark dynamic preload as completed
            self.cache.mark_dynamic_preload_complete(successfully_loaded)

            logger.info(f"Preloaded dynamic schemas for {len(successfully_loaded)} tables")
            return True

        except Exception as e:
            logger.error(f"Schema preload failed: {e}")
            return False

    def preload_schemas_concurrent(self, max_concurrent: int = 5) -> bool:
        """
        Preload schemas using parallel execution with ThreadPoolExecutor.

        This provides significant performance improvement (3-10x faster) compared
        to sequential preloading, especially with many tables.

        Args:
            max_concurrent: Maximum number of concurrent preload operations

        Returns:
            True if preload succeeded, False otherwise
        """
        import time
        start_time = time.time()

        # First, try to preload static schemas (sequential, fast)
        if self._try_preload_static_schemas():
            logger.info("✅ Static schema files preloaded successfully")

        # Then preload from database if configuration exists
        if not self.preload_config:
            logger.info("No dynamic schema preload configuration found")
            return True

        try:
            # Preload database overview (single operation, keep sequential)
            if self.preload_config.get("preload_overview", True):
                self._preload_database_overview()

            # Collect all tables to preload
            tables_to_preload = self.preload_config.get("preload_tables", [])
            critical_tables = self.preload_config.get("critical_tables", [])
            all_tables = list(set(tables_to_preload + critical_tables))

            if not all_tables:
                logger.info("No tables configured for preload")
                return True

            logger.info(f"Starting parallel preload for {len(all_tables)} tables (max_concurrent={max_concurrent})")

            # Parallel preload using ThreadPoolExecutor
            successfully_loaded = []
            failed_tables = []

            with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
                # Submit all tasks
                future_to_table = {
                    executor.submit(self._preload_table_schema, table): table
                    for table in all_tables
                }

                # Collect results as they complete
                for future in as_completed(future_to_table):
                    table_name = future_to_table[future]
                    try:
                        if future.result():
                            successfully_loaded.append(table_name)
                        else:
                            failed_tables.append(table_name)
                    except Exception as e:
                        logger.error(f"Error preloading table {table_name}: {e}")
                        failed_tables.append(table_name)

            # Preload dependencies for critical tables (parallel)
            if critical_tables:
                with ThreadPoolExecutor(max_workers=max_concurrent) as executor:
                    futures = [
                        executor.submit(self._preload_table_dependencies, table)
                        for table in critical_tables
                    ]
                    for future in as_completed(futures):
                        try:
                            future.result()
                        except Exception as e:
                            logger.error(f"Error preloading dependencies: {e}")

            # Mark dynamic preload as completed
            self.cache.mark_dynamic_preload_complete(successfully_loaded)

            elapsed_time = time.time() - start_time
            logger.info(
                f"✅ Parallel preload completed in {elapsed_time:.2f}s: "
                f"{len(successfully_loaded)} succeeded, {len(failed_tables)} failed"
            )

            if failed_tables:
                logger.warning(f"Failed to preload tables: {', '.join(failed_tables[:10])}")

            return True

        except Exception as e:
            logger.error(f"Parallel schema preload failed: {e}")
            return False

    def _try_preload_static_schemas(self) -> bool:
        """Try to preload static schema definitions with database validation."""
        try:
            from database.schema.static_loader import get_schema_manager

            manager = get_schema_manager()

            # Load database overview
            tables = manager.get_all_tables()
            overview_result = {
                'success': True,
                'results': tables,
                'table_name': None,
                'total_count': len(tables),
                'source': 'json_config_system'
            }
            self.cache.set("database_overview_static", overview_result)
            logger.info(f"[PRELOAD] Set database_overview_static, cache_id={id(self.cache)}, tables={len(tables)}")

            # Verify the cache was set correctly
            verify_result = self.cache.get("database_overview_static")
            if verify_result is None:
                logger.error("[PRELOAD-ERROR] Failed to verify database_overview_static in cache!")
                return False
            else:
                logger.info(f"[PRELOAD-VERIFY] Successfully verified database_overview_static, tables={len(verify_result.get('results', []))}")

            # Validate whitelist against actual database
            validated_tables = []
            missing_tables = []
            loaded_count = 0
            loaded_table_names = []

            for table in tables:
                table_name = table['TABLE_NAME']
                schema = manager.get_table_schema(table_name)

                # Validate table exists in database if introspector is available
                table_exists = True
                if self.introspector:
                    try:
                        db_schema = self.introspector.get_schema_info(table_name)
                        table_exists = db_schema.get("success", False)
                        if table_exists:
                            validated_tables.append(table_name)
                        else:
                            missing_tables.append(table_name)
                            logger.warning(f"⚠️  Whitelist table '{table_name}' not found in database")
                    except Exception as e:
                        logger.debug(f"Could not validate table '{table_name}': {e}")
                        # Assume table exists if validation fails
                        validated_tables.append(table_name)

                # Load all tables in whitelist, regardless of validation result
                # This allows access to static config even if table doesn't exist yet
                if schema:
                    result = {
                        'success': True,
                        'results': schema.get('columns', []),
                        'table_name': table_name,
                        'total_count': len(schema.get('columns', [])),
                        'source': 'json_config_system',
                        'relationships': schema.get('relationships', {}),
                        'business_logic': schema.get('business_logic', {}),
                        'ai_context': schema.get('ai_context', {}),
                        'display_name': schema.get('display_name', table_name),
                        'category': schema.get('category', 'unknown'),
                        'business_importance': schema.get('business_importance', 'medium'),
                        'database_validated': table_exists  # Mark validation status
                    }
                    cache_key = f"table_schema_{table_name.upper()}_static"
                    self.cache.set(cache_key, result)
                    loaded_count += 1
                    loaded_table_names.append(table_name.upper())

            # Cache summary with validation info
            summary = manager.get_summary()
            # Use flat structure to match database query format (introspector.py:263-276)
            summary_result = {
                'success': True,
                'database_type': env('DB_TYPE', 'mssql').lower(),
                'tables': summary['total_tables'],
                'views': 0,  # JSON config doesn't track views
                'procedures': 0,  # JSON config doesn't track procedures
                'functions': 0,  # JSON config doesn't track functions
                'source': 'json_config_system',
                'validated_tables': validated_tables,
                'missing_tables': missing_tables,
                'total_columns': summary['total_columns'],
                'json_configs_loaded': summary.get('config_status', {}).get('json_configs_loaded', 0)
            }
            self.cache.set("schema_summary_static", summary_result)

            # Mark static preload as completed
            self.cache.mark_static_preload_complete(loaded_table_names)

            # Log validation results
            if missing_tables:
                logger.warning(f"⚠️  {len(missing_tables)} whitelist tables not found in database: {', '.join(missing_tables)}")
            logger.info(f"✅ Preloaded {loaded_count} table schemas via JSON system ({len(validated_tables)} validated)")
            return True

        except Exception as e:
            logger.error(f"Failed to preload static schemas: {e}")
            return False
    
    def _preload_database_overview(self) -> None:
        """Preload database overview information."""
        try:
            # Cache database schema overview
            overview = self.introspector.get_schema_info()
            if overview.get("success"):
                self.cache.set("database_overview", overview)
                logger.debug("Preloaded database overview")
            
            # Cache schema summary
            summary = self.introspector.get_schema_summary()
            if summary.get("success"):
                self.cache.set("schema_summary", summary)
                logger.debug("Preloaded schema summary")
                
        except Exception as e:
            logger.error(f"Failed to preload database overview: {e}")
    
    def _preload_table_schema(self, table_name: str) -> bool:
        """Preload specific table schema.

        Returns:
            True if schema was successfully preloaded, False otherwise
        """
        try:
            schema = self.introspector.get_schema_info(table_name)
            if schema.get("success"):
                cache_key = f"table_schema_{table_name}"
                self.cache.set(cache_key, schema)
                logger.debug(f"Preloaded schema for table: {table_name}")
                return True
            else:
                logger.warning(f"Failed to preload schema for table: {table_name}")
                return False

        except Exception as e:
            logger.error(f"Failed to preload table schema for {table_name}: {e}")
            return False
    
    def _preload_table_dependencies(self, table_name: str) -> None:
        """Preload table dependency information."""
        try:
            dependencies = self.introspector.get_table_dependencies(table_name)
            if dependencies.get("success"):
                cache_key = f"table_dependencies_{table_name}"
                self.cache.set(cache_key, dependencies)
                logger.debug(f"Preloaded dependencies for table: {table_name}")
            else:
                logger.warning(f"Failed to preload dependencies for table: {table_name}")
                
        except Exception as e:
            logger.error(f"Failed to preload dependencies for {table_name}: {e}")
    
    def create_sample_config(self, output_path: str) -> bool:
        """Create a sample schema configuration file."""
        sample_config = {
            "preload_overview": True,
            "preload_tables": [
                # 請根據您的實際表格名稱修改這些示例
                # "table1",
                # "table2",
                # "table3"
            ],
            "critical_tables": [
                # 請根據您的關鍵業務表格修改這些示例
                # "important_table1",
                # "important_table2"
            ],
            "cache_ttl_minutes": 60,
            "description": "Schema preload configuration - 請根據實際需求自訂表格清單",
            "usage_note": "請將上方註解中的示例表格名稱替換為您資料庫中的實際表格名稱",
            "created": datetime.now().isoformat()
        }
        
        try:
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(sample_config, f, indent=2, ensure_ascii=False)
            logger.info(f"Created sample schema config at {output_path}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create sample config: {e}")
            return False


class CachedSchemaIntrospector:
    """Schema introspector with caching capabilities."""
    
    def __init__(self, original_introspector, cache: SchemaCache, strict_mode: bool = False):
        """Initialize with original introspector and cache."""
        self.introspector = original_introspector
        self.cache = cache
        self.strict_mode = strict_mode
        logger.info(f"[INTROSPECTOR] cache_id={id(cache)}, strict_mode={strict_mode}")
    
    def get_schema_info(self, table_name: Optional[str] = None) -> Dict[str, Any]:
        """Get schema info with caching and static fallback.

        Returns schema with source tracking to distinguish:
        - dynamic_cache: From database query cache
        - static_cache: From JSON configuration preload
        - database_query: Fresh database query
        """
        if table_name:
            # Normalize table name to uppercase for consistent cache keys
            table_name_upper = table_name.upper()
            cache_key = f"table_schema_{table_name_upper}"
            static_cache_key = f"table_schema_{table_name_upper}_static"
        else:
            cache_key = "database_overview"
            static_cache_key = "database_overview_static"

        # Try dynamic cache first
        cached_result = self.cache.get(cache_key)
        if cached_result:
            logger.debug(f"Dynamic cache hit for {cache_key}")
            # Mark source if not already marked
            if isinstance(cached_result, dict) and "cache_source" not in cached_result:
                cached_result["cache_source"] = "dynamic_cache"
            return cached_result

        # Try static cache as fallback
        static_result = self.cache.get(static_cache_key)
        if static_result:
            logger.debug(f"Static cache hit for {static_cache_key}")
            # Mark source to distinguish from dynamic cache
            if isinstance(static_result, dict):
                static_result["cache_source"] = "static_cache"
            return static_result

        # Strict mode check: if not in either cache, deny access
        if self.strict_mode:
            logger.warning(f"Strict mode enabled: Schema lookup blocked for {table_name_upper if table_name else 'overview'}")
            return {
                "success": False,
                "error": f"Schema access denied (Strict Mode): Table '{table_name_upper if table_name else 'database overview'}' not found in preloaded configuration",
                "strict_mode": True,
                "cache_source": "denied",
                "hint": "Only pre-configured tables in schemas_config/ are accessible in strict mode"
            }

        # Cache miss - query database.
        # Pass the original table name: uppercasing is only for cache keys.
        # PostgreSQL identifiers are case-sensitive (folded to lowercase), so an
        # uppercased name would never match and the lookup would return empty.
        result = self.introspector.get_schema_info(table_name if table_name else None)

        # Mark as fresh database query and cache successful results
        if result.get("success"):
            if isinstance(result, dict):
                result["cache_source"] = "database_query"
            self.cache.set(cache_key, result)

        return result
    
    def get_table_dependencies(self, table_name: str) -> Dict[str, Any]:
        """Get table dependencies with caching and source tracking."""
        # Normalize table name to uppercase for consistent cache keys
        table_name_upper = table_name.upper()
        cache_key = f"table_dependencies_{table_name_upper}"

        # Try cache first
        cached_result = self.cache.get(cache_key)
        if cached_result:
            logger.debug(f"Cache hit for dependencies: {table_name}")
            if isinstance(cached_result, dict) and "cache_source" not in cached_result:
                cached_result["cache_source"] = "dynamic_cache"
            return cached_result

        # Attempt to get dependencies from static schema configuration first
        # This bridges the gap between schemas_config (which has relationships) and the dependencies endpoint
        schema_info = self.get_schema_info(table_name_upper)
        if schema_info and schema_info.get("success") and schema_info.get("source") == "json_config_system":
            relationships = schema_info.get("relationships", {})
            if relationships:
                # Transform JSON relationships to API dependency format
                # JSON: { "foreign_keys": [{"column": "...", "references": "TABLE.COL", ...}] }
                # API: { "dependencies": [{"constraint_name": "FK_...", "parent_table": "...", "parent_column": "...", "referenced_table": "...", "referenced_column": "..."}] }

                dependencies_list = []

                # Process outgoing foreign keys (parent -> referenced)
                for fk in relationships.get("foreign_keys", []):
                    ref_parts = fk.get("references", "").split(".")
                    ref_table = ref_parts[0] if len(ref_parts) > 0 else ""
                    ref_col = ref_parts[1] if len(ref_parts) > 1 else ""

                    dependencies_list.append({
                        "constraint_name": f"FK_{table_name_upper}_{fk.get('column')}", # Synthetic name
                        "parent_table": table_name_upper,
                        "parent_column": fk.get("column"),
                        "referenced_table": ref_table,
                        "referenced_column": ref_col
                    })

                # Note: 'referenced_by' (incoming) are not standard dependencies in this API format usually,
                # but we could add them if needed. For now, we stick to outgoing FKs to match DB inspector behavior.

                result = {
                    "success": True,
                    "table_name": table_name_upper,
                    "dependencies": dependencies_list,
                    "source": "json_config_system",
                    "cache_source": "static_cache"
                }

                # Cache this result
                self.cache.set(cache_key, result)
                return result

        # Strict mode check
        if self.strict_mode:
             logger.warning(f"Strict mode enabled: Dependency lookup blocked for {table_name_upper}")
             return {
                 "success": False,
                 "error": f"Dependency access denied (Strict Mode): Table '{table_name_upper}' not found in preloaded configuration",
                 "strict_mode": True,
                 "cache_source": "denied",
                 "hint": "Only pre-configured tables in schemas_config/ are accessible in strict mode"
             }

        # Cache miss - query database (original name: uppercasing is only for cache keys)
        logger.debug(f"Cache miss for dependencies: {table_name_upper}, querying database")
        result = self.introspector.get_table_dependencies(table_name)

        # Mark as fresh database query and cache successful results
        if result.get("success"):
            if isinstance(result, dict):
                result["cache_source"] = "database_query"
            self.cache.set(cache_key, result)

        return result
    
    def get_schema_summary(self) -> Dict[str, Any]:
        """Get schema summary with caching and static fallback.

        Returns summary with source tracking to distinguish cache origins.
        """
        cache_key = "schema_summary"
        static_cache_key = "schema_summary_static"

        # Try dynamic cache first
        cached_result = self.cache.get(cache_key)
        if cached_result:
            logger.debug("Dynamic cache hit for schema summary")
            if isinstance(cached_result, dict) and "cache_source" not in cached_result:
                cached_result["cache_source"] = "dynamic_cache"
            return cached_result

        # Try static cache as fallback
        static_result = self.cache.get(static_cache_key)
        if static_result:
            logger.debug("Static cache hit for schema summary")
            if isinstance(static_result, dict):
                static_result["cache_source"] = "static_cache"
            return static_result

        # Strict mode check
        if self.strict_mode:
            return {
                "success": False,
                "error": "Schema summary denied (Strict Mode): No static configuration loaded",
                "strict_mode": True,
                "cache_source": "denied",
                "hint": "Load schema configuration in schemas_config/ to enable strict mode access"
            }

        # Cache miss - query database
        logger.debug("Cache miss for schema summary, querying database")
        result = self.introspector.get_schema_summary()

        # Mark as fresh database query and cache successful results
        if result.get("success"):
            if isinstance(result, dict):
                result["cache_source"] = "database_query"
            self.cache.set(cache_key, result)

        return result
    
    def invalidate_cache(self, table_name: Optional[str] = None) -> None:
        """Invalidate specific cache entries."""
        if table_name:
            # Normalize table name to uppercase for consistent cache keys
            table_name_upper = table_name.upper()
            self.cache.invalidate(f"table_schema_{table_name_upper}")
            self.cache.invalidate(f"table_dependencies_{table_name_upper}")
            # Also invalidate static cache keys
            self.cache.invalidate(f"table_schema_{table_name_upper}_static")
        else:
            self.cache.clear()
        logger.info(f"Invalidated cache for: {table_name or 'all entries'}")