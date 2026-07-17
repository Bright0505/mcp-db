"""ENV_PREFIX 命名空間測試

讓多個模組共用同一份 env 檔而各自連不同資料庫。
"""

import importlib
import pytest


@pytest.fixture
def env_helper(monkeypatch):
    """取得 env() helper（每次重新載入以避免模組載入期的 dotenv 汙染）。"""
    import core.config as config
    importlib.reload(config)
    return config.env


class TestEnvPrefix:
    def test_no_prefix_reads_plain_name(self, monkeypatch, env_helper):
        """未設 ENV_PREFIX 時等同 os.getenv（既有部署不受影響）"""
        monkeypatch.delenv("ENV_PREFIX", raising=False)
        monkeypatch.setenv("DB_HOST", "shared-host")
        assert env_helper("DB_HOST") == "shared-host"

    def test_prefixed_value_wins(self, monkeypatch, env_helper):
        """設了 ENV_PREFIX 時，命名空間變數優先於共用變數"""
        monkeypatch.setenv("ENV_PREFIX", "FENGTIEN_")
        monkeypatch.setenv("DB_HOST", "shared-host")
        monkeypatch.setenv("FENGTIEN_DB_HOST", "module-host")
        assert env_helper("DB_HOST") == "module-host"

    def test_falls_back_to_shared_when_not_overridden(self, monkeypatch, env_helper):
        """命名空間沒設的變數，仍繼承共用值"""
        monkeypatch.setenv("ENV_PREFIX", "FENGTIEN_")
        monkeypatch.delenv("FENGTIEN_DB_TIMEOUT", raising=False)
        monkeypatch.setenv("DB_TIMEOUT", "30")
        assert env_helper("DB_TIMEOUT") == "30"

    def test_default_used_when_neither_set(self, monkeypatch, env_helper):
        monkeypatch.setenv("ENV_PREFIX", "FENGTIEN_")
        monkeypatch.delenv("FENGTIEN_DB_PORT", raising=False)
        monkeypatch.delenv("DB_PORT", raising=False)
        assert env_helper("DB_PORT", "1433") == "1433"

    def test_empty_prefixed_value_is_respected(self, monkeypatch, env_helper):
        """命名空間內顯式設為空字串，不應被共用值蓋掉"""
        monkeypatch.setenv("ENV_PREFIX", "FENGTIEN_")
        monkeypatch.setenv("DB_USER", "shared-user")
        monkeypatch.setenv("FENGTIEN_DB_USER", "")
        assert env_helper("DB_USER") == ""


class TestDatabaseConfigWithPrefix:
    def test_config_reads_namespaced_database(self, monkeypatch):
        """DatabaseConfig 應整組讀命名空間：共用是 PostgreSQL，模組是 SQL Server"""
        import core.config as config
        importlib.reload(config)

        # 共用 env：data-lake PostgreSQL
        monkeypatch.setenv("DB_TYPE", "postgresql")
        monkeypatch.setenv("DB_HOST", "data-lake-host")
        monkeypatch.setenv("DB_NAME", "data-lake")
        monkeypatch.setenv("DB_PORT", "5432")
        # 模組命名空間：另一台 SQL Server
        monkeypatch.setenv("ENV_PREFIX", "FENGTIEN_")
        monkeypatch.setenv("FENGTIEN_DB_TYPE", "mssql")
        monkeypatch.setenv("FENGTIEN_DB_HOST", "mssql-host")
        monkeypatch.setenv("FENGTIEN_DB_NAME", "master")
        monkeypatch.setenv("FENGTIEN_DB_PORT", "1433")
        monkeypatch.setenv("FENGTIEN_DB_USER", "sa")
        monkeypatch.setenv("FENGTIEN_DB_PASSWORD", "pw")

        cfg = config.DatabaseConfig.from_env()
        assert cfg.db_type == "mssql"
        assert cfg.server == "mssql-host"
        assert cfg.database == "master"
        assert cfg.port == 1433
        assert cfg.username == "sa"

    def test_config_without_prefix_unchanged(self, monkeypatch):
        """未設 ENV_PREFIX 的模組維持原行為（共用 env）"""
        import core.config as config
        importlib.reload(config)

        monkeypatch.delenv("ENV_PREFIX", raising=False)
        monkeypatch.setenv("DB_TYPE", "postgresql")
        monkeypatch.setenv("DB_HOST", "data-lake-host")
        monkeypatch.setenv("DB_NAME", "data-lake")

        cfg = config.DatabaseConfig.from_env()
        assert cfg.db_type == "postgresql"
        assert cfg.server == "data-lake-host"
