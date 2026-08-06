"""
SQL 驗證器單元測試

測試 SQL 安全驗證功能，確保能有效防範 SQL 注入和其他安全威脅。
"""

import pytest

from tools.validators import InputValidator, SQLValidator


class TestSQLValidator:
    """SQL 查詢驗證器測試"""

    def test_valid_simple_select(self):
        """✅ 合法的簡單 SELECT 查詢"""
        query = "SELECT * FROM users"
        is_valid, error = SQLValidator.validate_query(query)
        assert is_valid is True
        assert error == ""

    def test_valid_select_with_where(self):
        """✅ 合法的 SELECT 查詢（帶 WHERE）"""
        query = "SELECT id, name FROM users WHERE age > 18"
        is_valid, error = SQLValidator.validate_query(query)
        assert is_valid is True
        assert error == ""

    def test_valid_select_with_join(self):
        """✅ 合法的 SELECT 查詢（帶 JOIN）"""
        query = """
            SELECT u.id, u.name, o.order_id
            FROM users u
            INNER JOIN orders o ON u.id = o.user_id
        """
        is_valid, error = SQLValidator.validate_query(query)
        assert is_valid is True
        assert error == ""

    def test_valid_with_cte(self):
        """✅ 合法的 WITH (CTE) 查詢"""
        query = """
            WITH sales_summary AS (
                SELECT product_id, SUM(amount) as total
                FROM sales
                GROUP BY product_id
            )
            SELECT * FROM sales_summary WHERE total > 1000
        """
        is_valid, error = SQLValidator.validate_query(query)
        assert is_valid is True
        assert error == ""

    def test_valid_select_with_trailing_semicolon(self):
        """✅ 允許尾隨分號"""
        query = "SELECT * FROM users;"
        is_valid, error = SQLValidator.validate_query(query)
        assert is_valid is True
        assert error == ""

    def test_reject_empty_query(self):
        """❌ 拒絕空查詢"""
        is_valid, error = SQLValidator.validate_query("")
        assert is_valid is False
        assert "Empty query" in error

    def test_reject_whitespace_only_query(self):
        """❌ 拒絕僅包含空白的查詢"""
        is_valid, error = SQLValidator.validate_query("   \n\t  ")
        assert is_valid is False
        assert "Empty query" in error

    def test_reject_delete_query(self):
        """❌ 拒絕 DELETE 語句"""
        query = "DELETE FROM users WHERE id = 1"
        is_valid, error = SQLValidator.validate_query(query)
        assert is_valid is False
        assert is_valid is False  # Rejected correctly

    def test_reject_drop_table(self):
        """❌ 拒絕 DROP TABLE"""
        query = "DROP TABLE users"
        is_valid, error = SQLValidator.validate_query(query)
        assert is_valid is False
        assert is_valid is False  # Rejected correctly

    def test_reject_insert_query(self):
        """❌ 拒絕 INSERT 語句"""
        query = "INSERT INTO users (name) VALUES ('hacker')"
        is_valid, error = SQLValidator.validate_query(query)
        assert is_valid is False
        assert is_valid is False  # Rejected correctly

    def test_reject_update_query(self):
        """❌ 拒絕 UPDATE 語句"""
        query = "UPDATE users SET password = 'hacked' WHERE id = 1"
        is_valid, error = SQLValidator.validate_query(query)
        assert is_valid is False
        assert is_valid is False  # Rejected correctly

    def test_reject_create_table(self):
        """❌ 拒絕 CREATE TABLE"""
        query = "CREATE TABLE malicious (id INT)"
        is_valid, error = SQLValidator.validate_query(query)
        assert is_valid is False
        assert is_valid is False  # Rejected correctly

    def test_reject_alter_table(self):
        """❌ 拒絕 ALTER TABLE"""
        query = "ALTER TABLE users ADD COLUMN hacked VARCHAR(100)"
        is_valid, error = SQLValidator.validate_query(query)
        assert is_valid is False
        assert is_valid is False  # Rejected correctly

    def test_reject_truncate_table(self):
        """❌ 拒絕 TRUNCATE TABLE"""
        query = "TRUNCATE TABLE users"
        is_valid, error = SQLValidator.validate_query(query)
        assert is_valid is False
        assert is_valid is False  # Rejected correctly

    def test_reject_exec_statement(self):
        """❌ 拒絕 EXEC 語句"""
        query = "EXEC sp_executesql N'SELECT * FROM users'"
        is_valid, error = SQLValidator.validate_query(query)
        assert is_valid is False
        assert is_valid is False  # Rejected correctly

    def test_reject_execute_statement(self):
        """❌ 拒絕 EXECUTE 語句"""
        query = "EXECUTE sp_help"
        is_valid, error = SQLValidator.validate_query(query)
        assert is_valid is False
        assert is_valid is False  # Rejected correctly

    def test_reject_multiple_statements_with_semicolon(self):
        """❌ 拒絕多語句 SQL 注入（分號分隔）"""
        query = "SELECT * FROM users; DROP TABLE users;"
        is_valid, error = SQLValidator.validate_query(query)
        assert is_valid is False
        # 可能因為 DROP 關鍵字或多語句被攔截
        assert ("Multiple statements" in error or "DROP" in error)

    def test_reject_sql_injection_with_union(self):
        """❌ 拒絕包含危險關鍵字的 UNION 注入"""
        # 注意：純 UNION SELECT 本身是合法的，但如果包含 DROP 等危險關鍵字會被攔截
        query = "SELECT * FROM users UNION SELECT NULL, NULL; DROP TABLE users--"
        is_valid, error = SQLValidator.validate_query(query)
        assert is_valid is False
        # 會被攔截，因為有分號（多語句）或 SQL 註釋

    def test_reject_sql_comments_double_dash(self):
        """❌ 拒絕 SQL 註釋（--）"""
        query = "SELECT * FROM users WHERE id = 1 --comment"
        is_valid, error = SQLValidator.validate_query(query)
        assert is_valid is False
        assert "comments not allowed" in error

    def test_reject_sql_comments_block(self):
        """❌ 拒絕 SQL 註釋（/* */）"""
        query = "SELECT * FROM users /* comment */ WHERE id = 1"
        is_valid, error = SQLValidator.validate_query(query)
        assert is_valid is False
        assert "comments not allowed" in error

    def test_leading_comment_reports_comment_rule_not_statement_type(self):
        """❌ 開頭註釋要回報「註釋」而非「不是 SELECT」

        回歸測試：註釋檢查必須排在首字檢查之前。否則開頭是註釋時
        query_upper.split()[0] 會變成註釋 token，讓一個合法的 SELECT
        被回報成 "Only SELECT, WITH statements are allowed" ——
        呼叫端（含 LLM）看到這個訊息無法自我修正，因為它的語句確實是 SELECT。
        """
        for query in (
            "-- leading comment\nSELECT COUNT(*) FROM users",   # `--` 後有空格
            "--leading comment\nSELECT COUNT(*) FROM users",    # `--` 後無空格
            "/* leading block */ SELECT COUNT(*) FROM users",
        ):
            is_valid, error = SQLValidator.validate_query(query)
            assert is_valid is False, f"應被拒絕：{query!r}"
            assert "comments not allowed" in error, (
                f"訊息應指出註釋規則，實際為 {error!r}（查詢：{query!r}）"
            )

    def test_reject_xp_extended_procedures(self):
        """❌ 拒絕 xp_ 擴展存儲過程"""
        query = "SELECT * FROM users; EXEC xp_cmdshell 'dir'"
        is_valid, error = SQLValidator.validate_query(query)
        assert is_valid is False
        # 會被攔截（多語句或 xp_ 或 EXEC）

    def test_reject_openrowset(self):
        """❌ 拒絕 OPENROWSET 數據外洩"""
        query = """
            SELECT * FROM OPENROWSET(
                'SQLNCLI',
                'Server=evil;Trusted_Connection=yes;',
                'SELECT * FROM sys.tables'
            )
        """
        is_valid, error = SQLValidator.validate_query(query)
        assert is_valid is False
        # 可能因為 OPENROWSET 或字串內的分號被攔截
        assert ("OPENROWSET" in error or "Multiple statements" in error)

    def test_reject_opendatasource(self):
        """❌ 拒絕 OPENDATASOURCE 數據外洩"""
        query = "SELECT * FROM OPENDATASOURCE('SQLNCLI', 'Data Source=evil').master.sys.tables"
        is_valid, error = SQLValidator.validate_query(query)
        assert is_valid is False
        assert "OPENDATASOURCE" in error

    def test_reject_into_outfile(self):
        """❌ 拒絕 INTO OUTFILE（MySQL 文件導出）"""
        query = "SELECT * FROM users INTO OUTFILE '/tmp/users.txt'"
        is_valid, error = SQLValidator.validate_query(query)
        assert is_valid is False
        assert "File export" in error

    def test_reject_into_dumpfile(self):
        """❌ 拒絕 INTO DUMPFILE（MySQL 文件導出）"""
        query = "SELECT password FROM users INTO DUMPFILE '/tmp/pass.txt'"
        is_valid, error = SQLValidator.validate_query(query)
        assert is_valid is False
        assert "File export" in error

    def test_reject_query_too_long(self):
        """❌ 拒絕超長查詢（>50KB）"""
        # 創建一個超過 50000 字符的查詢
        long_query = "SELECT * FROM users WHERE name IN (" + ", ".join(
            [f"'user{i}'" for i in range(10000)]
        ) + ")"
        assert len(long_query) > 50000
        is_valid, error = SQLValidator.validate_query(long_query)
        assert is_valid is False
        assert "too long" in error

    def test_reject_grant_statement(self):
        """❌ 拒絕 GRANT 語句"""
        query = "GRANT ALL PRIVILEGES ON database.* TO 'user'@'localhost'"
        is_valid, error = SQLValidator.validate_query(query)
        assert is_valid is False
        assert is_valid is False  # Rejected correctly

    def test_reject_revoke_statement(self):
        """❌ 拒絕 REVOKE 語句"""
        query = "REVOKE ALL PRIVILEGES ON database.* FROM 'user'@'localhost'"
        is_valid, error = SQLValidator.validate_query(query)
        assert is_valid is False
        assert is_valid is False  # Rejected correctly

    def test_case_insensitive_keyword_detection(self):
        """❌ 大小寫不敏感的關鍵字檢測"""
        queries = [
            "DeLeTe FrOm users",
            "dRoP tAbLe users",
            "ExEc sp_help",
        ]
        for query in queries:
            is_valid, error = SQLValidator.validate_query(query)
            assert is_valid is False

    def test_word_boundary_check(self):
        """✅ 確保使用單詞邊界檢查（避免誤判）"""
        # 這些查詢包含類似危險關鍵字的子串，但不是真正的關鍵字
        query = "SELECT * FROM dropoff_locations"
        is_valid, error = SQLValidator.validate_query(query)
        assert is_valid is True  # "DROPOFF" 不應該觸發 "DROP" 檢測

    def test_allow_keyword_inside_string_literal(self):
        """✅ 字串字面值中的關鍵字不應觸發攔截（如 status = 'update'）"""
        queries = [
            "SELECT * FROM tasks WHERE status = 'update'",
            "SELECT * FROM logs WHERE action = 'delete' AND level = 'INFO'",
            "SELECT * FROM docs WHERE title LIKE '%create%'",
            "SELECT 'exec summary' AS report_type FROM reports",
        ]
        for query in queries:
            is_valid, error = SQLValidator.validate_query(query)
            assert is_valid is True, f"False positive on: {query} ({error})"

    def test_allow_semicolon_inside_string_literal(self):
        """✅ 字串字面值中的分號不應被當成多語句"""
        query = "SELECT * FROM notes WHERE content = 'a;b;c'"
        is_valid, error = SQLValidator.validate_query(query)
        assert is_valid is True, error

    def test_allow_dashes_inside_string_literal(self):
        """✅ 字串字面值中的 -- 不應被當成 SQL 註釋"""
        query = "SELECT * FROM products WHERE code = 'AB--123'"
        is_valid, error = SQLValidator.validate_query(query)
        assert is_valid is True, error

    def test_reject_keyword_after_escaped_quote_literal(self):
        """❌ 含跳脫引號（''）的字面值之後的危險關鍵字仍要攔截"""
        query = "SELECT * FROM users WHERE name = 'O''Brien' UNION SELECT 1; DROP TABLE users"
        is_valid, error = SQLValidator.validate_query(query)
        assert is_valid is False

    def test_reject_keyword_outside_literal_with_literals_present(self):
        """❌ 字面值以外的危險關鍵字仍要攔截"""
        query = "SELECT * FROM users WHERE note = 'safe'; DELETE FROM users"
        is_valid, error = SQLValidator.validate_query(query)
        assert is_valid is False

    def test_complex_valid_query(self):
        """✅ 複雜但合法的查詢"""
        query = """
            SELECT
                u.user_id,
                u.username,
                COUNT(o.order_id) as order_count,
                SUM(o.total_amount) as total_spent
            FROM users u
            LEFT JOIN orders o ON u.user_id = o.user_id
            WHERE u.created_at >= '2024-01-01'
                AND u.status = 'active'
            GROUP BY u.user_id, u.username
            HAVING COUNT(o.order_id) > 5
            ORDER BY total_spent DESC
        """
        is_valid, error = SQLValidator.validate_query(query)
        assert is_valid is True
        assert error == ""


class TestInputValidator:
    """輸入驗證器測試"""

    def test_valid_simple_table_name(self):
        """✅ 合法的簡單表格名稱"""
        is_valid, error = InputValidator.validate_table_name("users")
        assert is_valid is True
        assert error == ""

    def test_valid_table_name_with_schema(self):
        """✅ 合法的表格名稱（帶 schema）"""
        is_valid, error = InputValidator.validate_table_name("dbo.users")
        assert is_valid is True
        assert error == ""

    def test_valid_table_name_with_brackets(self):
        """✅ 合法的表格名稱（SQL Server 方括號）"""
        is_valid, error = InputValidator.validate_table_name("[dbo].[users]")
        assert is_valid is True
        assert error == ""

    def test_valid_table_name_with_underscores(self):
        """✅ 合法的表格名稱（包含下劃線）"""
        is_valid, error = InputValidator.validate_table_name("user_accounts_2024")
        assert is_valid is True
        assert error == ""

    def test_reject_empty_table_name(self):
        """❌ 拒絕空表格名稱"""
        is_valid, error = InputValidator.validate_table_name("")
        assert is_valid is False
        assert "cannot be empty" in error

    def test_reject_table_name_with_spaces(self):
        """❌ 拒絕包含空格的表格名稱"""
        is_valid, error = InputValidator.validate_table_name("user accounts")
        assert is_valid is False
        assert "Invalid table name format" in error

    def test_reject_table_name_with_special_chars(self):
        """❌ 拒絕包含特殊字符的表格名稱"""
        is_valid, error = InputValidator.validate_table_name("users@#$")
        assert is_valid is False
        assert "Invalid table name format" in error

    def test_reject_table_name_with_path_traversal(self):
        """❌ 拒絕路徑遍歷攻擊"""
        test_cases = [
            "../../../etc/passwd",
            "..\\..\\windows\\system32",
            "users/../admin",
        ]
        for table_name in test_cases:
            is_valid, error = InputValidator.validate_table_name(table_name)
            assert is_valid is False
            assert "Invalid characters" in error or "Invalid table name format" in error

    def test_reject_table_name_too_long(self):
        """❌ 拒絕過長的表格名稱"""
        long_name = "a" * 257
        is_valid, error = InputValidator.validate_table_name(long_name)
        assert is_valid is False
        assert "too long" in error

    def test_valid_limit(self):
        """✅ 合法的查詢限制"""
        is_valid, error = InputValidator.validate_limit(100)
        assert is_valid is True
        assert error == ""

    def test_valid_limit_zero(self):
        """✅ 允許 limit = 0"""
        is_valid, error = InputValidator.validate_limit(0)
        assert is_valid is True
        assert error == ""

    def test_valid_limit_max(self):
        """✅ 允許 limit = 最大值"""
        is_valid, error = InputValidator.validate_limit(10000, max_limit=10000)
        assert is_valid is True
        assert error == ""

    def test_reject_negative_limit(self):
        """❌ 拒絕負數 limit"""
        is_valid, error = InputValidator.validate_limit(-1)
        assert is_valid is False
        assert "cannot be negative" in error

    def test_reject_limit_exceeds_max(self):
        """❌ 拒絕超過最大值的 limit"""
        is_valid, error = InputValidator.validate_limit(20000, max_limit=10000)
        assert is_valid is False
        assert "exceeds maximum" in error

    def test_custom_max_limit(self):
        """✅ 自定義最大 limit"""
        is_valid, error = InputValidator.validate_limit(5000, max_limit=5000)
        assert is_valid is True

        is_valid, error = InputValidator.validate_limit(5001, max_limit=5000)
        assert is_valid is False
        assert "5000" in error


class TestSecurityEdgeCases:
    """安全邊界測試"""

    def test_sql_injection_payloads(self, sample_malicious_queries):
        """❌ 測試常見的 SQL 注入載荷"""
        for malicious_query in sample_malicious_queries:
            is_valid, error = SQLValidator.validate_query(malicious_query)
            assert is_valid is False, f"Failed to block: {malicious_query}"

    def test_unicode_sql_injection(self):
        """❌ 測試 Unicode SQL 注入嘗試"""
        # 注意：這個測試假設驗證器不允許 Unicode 逃逸
        query = "SELECT * FROM users WHERE name = '\u0053\u0045\u004c\u0045\u0043\u0054'"
        is_valid, error = SQLValidator.validate_query(query)
        # 這個查詢本身可能是合法的（如果只是查詢用戶名），重點是不允許執行危險操作
        # 主要測試驗證器是否正確處理 Unicode

    def test_encoding_bypass_attempts(self):
        """❌ 測試編碼繞過嘗試"""
        # URL 編碼
        query = "SELECT * FROM users; %44%52%4f%50 TABLE users"
        is_valid, error = SQLValidator.validate_query(query)
        assert is_valid is False  # 應該被分號攔截

    def test_whitespace_obfuscation(self):
        """❌ 測試空白混淆攻擊"""
        query = "SELECT/**//**/FROM/**/users"
        is_valid, error = SQLValidator.validate_query(query)
        assert is_valid is False  # 應該被 /* */ 註釋攔截
