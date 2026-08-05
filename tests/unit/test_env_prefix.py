"""ENV_PREFIX 命名空間測試

讓多個模組共用同一份 env 檔而各自連不同資料庫。

本檔的變數值刻意使用抽象名稱（`MYMODULE_` / `shared-*`），不寫任何特定
部署或衍生模組的名字 —— 這是樣板，具體生態不應滲進來。
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
        monkeypatch.setenv("ENV_PREFIX", "MYMODULE_")
        monkeypatch.setenv("DB_HOST", "shared-host")
        monkeypatch.setenv("MYMODULE_DB_HOST", "module-host")
        assert env_helper("DB_HOST") == "module-host"

    def test_falls_back_to_shared_when_not_overridden(self, monkeypatch, env_helper):
        """命名空間沒設的變數，仍繼承共用值"""
        monkeypatch.setenv("ENV_PREFIX", "MYMODULE_")
        monkeypatch.delenv("MYMODULE_DB_TIMEOUT", raising=False)
        monkeypatch.setenv("DB_TIMEOUT", "30")
        assert env_helper("DB_TIMEOUT") == "30"

    def test_default_used_when_neither_set(self, monkeypatch, env_helper):
        monkeypatch.setenv("ENV_PREFIX", "MYMODULE_")
        monkeypatch.delenv("MYMODULE_DB_PORT", raising=False)
        monkeypatch.delenv("DB_PORT", raising=False)
        assert env_helper("DB_PORT", "1433") == "1433"

    def test_empty_prefixed_value_is_respected(self, monkeypatch, env_helper):
        """命名空間內顯式設為空字串，不應被共用值蓋掉"""
        monkeypatch.setenv("ENV_PREFIX", "MYMODULE_")
        monkeypatch.setenv("DB_USER", "shared-user")
        monkeypatch.setenv("MYMODULE_DB_USER", "")
        assert env_helper("DB_USER") == ""


class TestDatabaseConfigWithPrefix:
    def test_config_reads_namespaced_database(self, monkeypatch):
        """DatabaseConfig 應整組讀命名空間：共用是 PostgreSQL，模組是 SQL Server"""
        import core.config as config
        importlib.reload(config)

        # 共用 env：部署層共用的 PostgreSQL
        monkeypatch.setenv("DB_TYPE", "postgresql")
        monkeypatch.setenv("DB_HOST", "shared-pg-host")
        monkeypatch.setenv("DB_NAME", "shared-db")
        monkeypatch.setenv("DB_PORT", "5432")
        # 模組命名空間：另一台 SQL Server
        monkeypatch.setenv("ENV_PREFIX", "MYMODULE_")
        monkeypatch.setenv("MYMODULE_DB_TYPE", "mssql")
        monkeypatch.setenv("MYMODULE_DB_HOST", "mssql-host")
        monkeypatch.setenv("MYMODULE_DB_NAME", "master")
        monkeypatch.setenv("MYMODULE_DB_PORT", "1433")
        monkeypatch.setenv("MYMODULE_DB_USER", "sa")
        monkeypatch.setenv("MYMODULE_DB_PASSWORD", "pw")

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
        monkeypatch.setenv("DB_HOST", "shared-pg-host")
        monkeypatch.setenv("DB_NAME", "shared-db")

        cfg = config.DatabaseConfig.from_env()
        assert cfg.db_type == "postgresql"
        assert cfg.server == "shared-pg-host"


class TestNoBypassOfEnvPrefix:
    """DB_* 一律經 env()，不得直接 os.getenv。

    為什麼需要這一層
    ----------------
    `DatabaseConfig` 走 `env()` 是對的，但曾有 8 處程式碼直接
    `os.environ.get('DB_TYPE')`，繞過 ENV_PREFIX 讀到共用值。後果不是
    顯示瑕疵：`*_schema` 的輸出帶有 SQL 方言提示（PostgreSQL 的
    `LIMIT N` / `CURRENT_DATE` vs T-SQL 的 `TOP N` / `GETDATE()`），
    模型會照著寫查詢。設了 ENV_PREFIX 的模組因此被指示錯誤的方言。

    上面的測試都在 `core.config` 這一層，抓不到「別的檔案繞過它」，
    所以這裡改用靜態掃描守備。
    """

    def test_no_module_reads_db_vars_via_os_getenv(self):
        import re
        from pathlib import Path

        # 由已載入的 core.config 反推 src/，不用相對 __file__ 推算 ——
        # 容器內的 tests/ 比 repo 多一層嵌套（/app/tests/tests/...），
        # 相對路徑會指錯地方。
        import core.config as config
        src = Path(config.__file__).resolve().parents[1]
        assert (src / "core" / "config.py").is_file(), f"src 目錄推算錯誤：{src}"

        # core/config.py 是 env() 的定義處，本來就必須用 os.getenv
        pattern = re.compile(r"os\.(?:environ\.get|getenv)\(\s*['\"]DB_")
        offenders = []
        for path in sorted(src.rglob("*.py")):
            if path.relative_to(src).as_posix() == "core/config.py":
                continue
            for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if pattern.search(line):
                    offenders.append(f"{path.relative_to(src)}:{i}: {line.strip()}")

        assert not offenders, (
            "DB_* 必須經 core.config.env() 讀取，否則設了 ENV_PREFIX 的模組會拿到"
            "共用部署值（並對模型自報錯誤的 SQL 方言）。違規處：\n  "
            + "\n  ".join(offenders)
        )

    def test_schema_summary_reports_namespaced_db_type(self, monkeypatch):
        """快取層產生的 database_type 必須是命名空間的值，不是共用值。"""
        import importlib
        import core.config as config
        importlib.reload(config)

        monkeypatch.setenv("DB_TYPE", "postgresql")          # 共用
        monkeypatch.setenv("ENV_PREFIX", "MYMODULE_")
        monkeypatch.setenv("MYMODULE_DB_TYPE", "mssql")      # 本模組

        import database.schema.cache as cache_mod
        importlib.reload(cache_mod)
        assert cache_mod.env("DB_TYPE", "mssql").lower() == "mssql"
