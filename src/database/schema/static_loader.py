"""
靜態 Schema 定義檔案 v3.0 - 純淨重構版本
基於 JSON 配置系統的高效能 Schema 管理器
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Any
import logging

# DB_* must be read through env(), not os.getenv: a module with ENV_PREFIX set
# has its own namespace and would otherwise pick up the shared deployment value.
from core.config import env

logger = logging.getLogger(__name__)


class SchemaConfigManager:
    """
    高效能 Schema 配置管理器
    特點：快取、延遲載入、智能錯誤處理
    """

    def __init__(self, base_path: Optional[str] = None):
        if base_path is None:
            current_file = Path(__file__)
            # Go up 4 levels: static_loader.py -> schema -> database -> src -> app (project root)
            self.base_path = current_file.parent.parent.parent.parent
        else:
            self.base_path = Path(base_path)

        self.config_path = self.base_path / "schemas_config"

        # 內部快取
        self._configs_cache = {}
        self._table_schemas_cache = {}
        self._loaded = False

    def _ensure_loaded(self) -> bool:
        """確保配置已載入（延遲載入）"""
        if self._loaded:
            return True

        try:
            self._load_all_configs()
            self._loaded = True
            return True
        except Exception as e:
            logger.error(f"載入配置失敗: {e}")
            return False

    def _load_all_configs(self) -> None:
        """載入所有配置檔案"""
        config_files = {
            'tables_list': 'tables_list.json',
            'global_patterns': 'global_patterns.json',
            'ai_enhancement': 'ai_enhancement.json'
        }

        for config_name, filename in config_files.items():
            file_path = self.config_path / filename
            if file_path.exists():
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        self._configs_cache[config_name] = json.load(f)
                    logger.debug(f"✓ 載入 {filename}")
                except Exception as e:
                    logger.warning(f"載入 {filename} 失敗: {e}")
                    self._configs_cache[config_name] = {}
            else:
                self._configs_cache[config_name] = {}

        # 載入個別表格配置
        self._load_table_configs()

    def _load_table_configs(self) -> None:
        """載入個別表格配置檔案"""
        tables_dir = self.config_path / "tables"
        table_configs = {}

        if tables_dir.exists():
            for json_file in tables_dir.glob("*.json"):
                try:
                    with open(json_file, 'r', encoding='utf-8') as f:
                        config = json.load(f)
                        table_name = config.get('table_name', json_file.stem).upper()
                        table_configs[table_name] = config
                except Exception as e:
                    logger.warning(f"載入表格配置 {json_file} 失敗: {e}")

        self._configs_cache['table_configs'] = table_configs
        logger.info(f"✓ 載入 {len(table_configs)} 個表格配置")

    def get_table_schema(self, table_name: str) -> Optional[Dict[str, Any]]:
        """取得表格 Schema（使用實例快取，無需 @lru_cache）"""
        if not self._ensure_loaded():
            return None

        table_name_upper = table_name.upper()

        # 檢查快取
        if table_name_upper in self._table_schemas_cache:
            return self._table_schemas_cache[table_name_upper]

        # 生成增強 Schema
        schema = self._build_enhanced_schema(table_name_upper)
        if schema:
            self._table_schemas_cache[table_name_upper] = schema

        return schema

    def _build_enhanced_schema(self, table_name: str) -> Optional[Dict[str, Any]]:
        """建構增強版 Schema"""
        # 1. 從 JSON 配置取得
        table_config = self._configs_cache.get('table_configs', {}).get(table_name, {})

        # 2. 從 JSON 表格清單取得基本資訊
        basic_info = self._get_table_from_json_list(table_name)

        if not any([table_config, basic_info]):
            return None

        # 建構完整 Schema
        enhanced_schema = {
            'table_name': table_name,
            'display_name': (
                table_config.get('display_name') or
                basic_info.get('DISPLAY_NAME') or
                table_name
            ),
            'type': table_config.get('type', 'TABLE'),
            'category': table_config.get('category', 'unknown'),
            'business_importance': table_config.get('business_importance', 'medium'),
            'columns': [],
            'relationships': table_config.get('relationships', {}),
            'business_logic': table_config.get('business_logic', {}),
            'ai_context': table_config.get('ai_context', {})
        }

        # 整合欄位資訊（僅使用 JSON 配置）
        if table_config.get('columns'):
            # 如果有完整欄位列表，使用 _enhance_columns 增強
            enhanced_schema['columns'] = self._enhance_columns(
                table_config['columns'],
                table_config
            )
            enhanced_schema['total_count'] = len(enhanced_schema['columns'])
        elif table_config.get('key_columns'):
            # 如果有 key_columns 配置，轉換為標準格式
            columns = []
            for col_name, col_config in table_config.get('key_columns', {}).items():
                column = {
                    'COLUMN_NAME': col_name,
                    'display_name': col_config.get('display_name', col_name),
                    'description': col_config.get('description', f'欄位: {col_name}'),
                    'semantic_type': col_config.get('semantic_type'),
                    'business_importance': col_config.get('business_importance'),
                    'usage_notes': col_config.get('usage_notes'),
                    'ai_hints': col_config.get('ai_hints')
                }
                columns.append(column)
            enhanced_schema['columns'] = columns
            enhanced_schema['total_count'] = len(columns)
        else:
            enhanced_schema['columns'] = []
            enhanced_schema['total_count'] = 0

        return enhanced_schema

    def _enhance_columns(self, columns: List[Dict], table_config: Dict) -> List[Dict]:
        """增強欄位資訊"""
        enhanced_columns = []
        key_columns = table_config.get('key_columns', {})
        global_patterns = self._configs_cache.get('global_patterns', {}).get('column_patterns', {})

        for column in columns:
            col_name = column['COLUMN_NAME']
            enhanced_col = column.copy()

            # 從 JSON 配置增強
            if col_name in key_columns:
                col_config = key_columns[col_name]
                enhanced_col.update({
                    'semantic_type': col_config.get('semantic_type'),
                    'business_importance': col_config.get('business_importance'),
                    'enhanced_description': col_config.get('description'),
                    'usage_notes': col_config.get('usage_notes'),
                    'ai_hints': col_config.get('ai_hints')
                })
            else:
                # 應用全域模式匹配
                for pattern, config in global_patterns.items():
                    if re.search(pattern, col_name, re.IGNORECASE):
                        enhanced_col.update({
                            'semantic_type': config.get('semantic_type'),
                            'pattern_description': config.get('default_description'),
                            'business_hints': config.get('business_hints')
                        })
                        break

            enhanced_columns.append(enhanced_col)

        return enhanced_columns


    def _get_table_from_json_list(self, table_name: str) -> Optional[Dict[str, Any]]:
        """從 JSON 表格清單取得表格資訊（使用 _configs_cache，無需額外快取）"""
        tables_list_config = self._configs_cache.get('tables_list', {})
        tables = tables_list_config.get('tables', {})

        # 嘗試用大寫和小寫兩種方式查詢（相容性處理）
        table_name_upper = table_name.upper()
        table_name_lower = table_name.lower()
        table_info = tables.get(table_name_upper) or tables.get(table_name_lower) or tables.get(table_name)
        if table_info:
            return {
                'TABLE_TYPE': table_info.get('table_type', 'TABLE'),
                'TABLE_NAME': table_name.upper(),
                'DISPLAY_NAME': table_info.get('display_name', table_name)
            }

        return None

    def get_all_tables(self) -> List[Dict[str, Any]]:
        """取得所有表格清單"""
        if not self._ensure_loaded():
            return []

        tables = []
        processed_tables = set()

        # 從 JSON 配置載入
        tables_list_config = self._configs_cache.get('tables_list', {})
        json_tables = tables_list_config.get('tables', {})

        for table_name, table_config in json_tables.items():
            # 統一使用小寫作為表格名稱（PostgreSQL 慣例）
            table_name_lower = table_name.lower()
            table_name_upper = table_name.upper()

            if table_name_lower not in processed_tables:
                # Determine default schema based on database type
                db_type = env('DB_TYPE', 'mssql').lower()
                default_schema = 'public' if db_type == 'postgresql' else 'dbo'
                db_schema = env('DB_SCHEMA', default_schema) or default_schema

                table_info = {
                    'TABLE_NAME': table_name_lower,  # 使用小寫（PostgreSQL 慣例）
                    'TABLE_TYPE': table_config.get('table_type', 'TABLE'),
                    'DISPLAY_NAME': table_config.get('display_name', table_name),
                    'TABLE_SCHEMA': db_schema,
                    'ROW_COUNT': 0,
                    'SIZE_MB': 0.0
                }

                # 從詳細的 JSON 配置增強（嘗試大寫和小寫）
                detailed_config = (
                    self._configs_cache.get('table_configs', {}).get(table_name_upper, {}) or
                    self._configs_cache.get('table_configs', {}).get(table_name_lower, {}) or
                    self._configs_cache.get('table_configs', {}).get(table_name, {})
                )
                if detailed_config:
                    table_info.update({
                        'ENHANCED_DISPLAY_NAME': detailed_config.get('display_name'),
                        'CATEGORY': detailed_config.get('category'),
                        'BUSINESS_IMPORTANCE': detailed_config.get('business_importance')
                    })

                tables.append(table_info)
                processed_tables.add(table_name_lower)

        return tables

    def get_summary(self) -> Dict[str, Any]:
        """取得系統摘要"""
        if not self._ensure_loaded():
            return {'error': 'Configuration not loaded'}

        tables = self.get_all_tables()
        total_columns = 0

        # 計算總欄位數
        for table in tables:
            schema = self.get_table_schema(table['TABLE_NAME'])
            if schema:
                total_columns += len(schema.get('columns', []))

        return {
            'total_tables': len(tables),
            'total_columns': total_columns,
            'table_names': [t['TABLE_NAME'] for t in tables],
            'source': 'json_config_system_v3',
            'config_status': {
                'json_configs_loaded': len(self._configs_cache.get('table_configs', {})),
                'has_global_patterns': bool(self._configs_cache.get('global_patterns')),
                'has_ai_enhancement': bool(self._configs_cache.get('ai_enhancement')),
                'cache_size': len(self._table_schemas_cache)
            },
            'performance': {
                'loaded': self._loaded,
                'cached_schemas': len(self._table_schemas_cache)
            }
        }

    def get_ai_enhancement_config(self) -> Dict[str, Any]:
        """取得 AI 增強配置"""
        if not self._ensure_loaded():
            return {}
        return self._configs_cache.get('ai_enhancement', {})

    def get_global_patterns(self) -> Dict[str, Any]:
        """取得全域模式配置"""
        if not self._ensure_loaded():
            return {}
        return self._configs_cache.get('global_patterns', {})

    def clear_cache(self) -> None:
        """清除快取"""
        self._table_schemas_cache.clear()
        logger.info("✓ 快取已清除")

    def reload_configs(self) -> bool:
        """重新載入配置"""
        self.clear_cache()
        self._configs_cache.clear()
        self._loaded = False
        return self._ensure_loaded()


# 全域管理器實例
_schema_manager = None

def get_schema_manager() -> SchemaConfigManager:
    """取得全域 Schema 管理器實例"""
    global _schema_manager
    if _schema_manager is None:
        _schema_manager = SchemaConfigManager()
    return _schema_manager

# 公開 API - 簡化版本
def get_table_schema(table_name: str) -> Optional[Dict[str, Any]]:
    """取得表格 Schema"""
    return get_schema_manager().get_table_schema(table_name)

def get_all_tables() -> List[Dict[str, Any]]:
    """取得所有表格清單"""
    return get_schema_manager().get_all_tables()

def get_summary() -> Dict[str, Any]:
    """取得系統摘要"""
    return get_schema_manager().get_summary()

def get_ai_enhancement_config() -> Dict[str, Any]:
    """取得 AI 增強配置"""
    return get_schema_manager().get_ai_enhancement_config()

def get_global_patterns() -> Dict[str, Any]:
    """取得全域模式配置"""
    return get_schema_manager().get_global_patterns()

def reload_configs() -> bool:
    """重新載入配置"""
    return get_schema_manager().reload_configs()

def clear_cache() -> None:
    """清除快取"""
    get_schema_manager().clear_cache()