# Claude Code 開發環境與自動化設定

> 容器名以 `docker-compose.yml` 的 `container_name` 為準：樣板是 `mcp-db-dev`／`mcp-db-http-dev`，衍生模組是
> `mcp-{module}-dev`／`mcp-{module}-http-dev`（下文以 `{module}` 代稱）。本檔只談**本機開發**；正式機部署是推 `vX.Y.Z` tag。

## 🐳 **重要提醒：開發模式統一使用 Docker 容器**

**⚠️ 關鍵提醒：本專案在開發模式下統一使用 Docker 容器進行測試和開發**

### 開發環境設定原則

當進行任何測試、開發或功能驗證時，請務必記住：

1. **❌ 不要使用本地 Python 環境安裝依賴**
2. **✅ 總是使用 Docker 容器**  
3. **✅ 所有服務都通過 docker-compose 管理**

### 常用容器操作

### 常用容器操作

#### 檢查容器狀態
```bash
docker ps
# 應該看到運行中的容器：
# - mcp-{module}-dev (MCP 伺服器, stdio 模式)
# - mcp-{module}-http-dev (HTTP API, port 8000)
```

#### 重啟服務載入程式碼變更
```bash
# 重啟 HTTP API 服務
docker-compose restart mcp-{module}-http

# 重啟 MCP 伺服器
docker-compose restart mcp-{module}
```

#### 查看服務狀態與日誌
```bash
# 查看 HTTP API 日誌
docker logs mcp-{module}-http-dev --tail 10

# 查看 MCP 伺服器日誌
docker logs mcp-{module}-dev --tail 10
```

### 服務端點
- **MCP Server**: stdio 模式（用於 Claude Desktop）
- **HTTP API**: http://localhost:8000（用於 Open WebUI）
- **API 文檔**: http://localhost:8000/docs（OpenAPI/Swagger）

### 開發工作流程
1. 📝 修改 `src/` 目錄下的程式碼
2. 🔄 重啟相關容器: `docker-compose restart service-name`
3. 🧪 測試功能：
   - Claude Desktop: 重啟 Claude Desktop 測試 MCP 工具
   - HTTP API: 訪問 http://localhost:8000/docs 測試 API 端點
4. 📋 查看容器日誌確認狀態

---

## 🚀 自動化設定

本範本提供完整的 Claude Code hooks 實現以下自動化功能：

### SessionStart Hook
- **觸發時機**：每次開啟 Claude Code 會話時
- **功能**：自動讀取並載入 README.md 內容到對話上下文
- **好處**：Claude 會自動了解專案現狀，無需手動說明

### UserPromptSubmit Hook  
- **觸發時機**：當提示詞包含約定式提交關鍵詞或分支操作關鍵詞時
- **功能**：智能分支管理 + 約定式提交操作
- **好處**：自動化 Git 工作流程，提升開發效率

## 📝 提交約定

### Git 提交格式
- 使用 **約定式提交 (Conventional Commits)** 格式
- **不包含 Claude 署名**，保持提交記錄簡潔
- 格式：`<type>(<scope>): <description>`

### 提交類型 (Type)
- `feat`: 新功能
- `fix`: 修復 bug
- `docs`: 文檔更新
- `style`: 代碼格式調整（不影響功能）
- `refactor`: 代碼重構
- `perf`: 性能優化
- `test`: 測試相關
- `chore`: 其他雜項（構建、依賴等）
- `ci`: CI/CD 相關

### 範圍 (Scope) - 需自訂
請根據您的專案特性更新以下範圍定義：

```
範例範圍：
- api: API 相關
- ui: 使用者介面
- db: 資料庫相關
- auth: 認證授權
- config: 配置相關
- test: 測試相關
```

### 範例
```
feat(api): 添加用戶認證端點
fix(ui): 修正登入表單驗證問題
docs: 更新 API 使用說明
refactor(db): 重構資料庫連接層
chore(deps): 更新依賴套件版本
```

## 🌿 自動分支管理

### 分支創建觸發詞
當你說出以下關鍵詞時，Claude 會自動創建對應的分支：

| 觸發詞 | 分支格式 | 範例 |
|--------|----------|------|
| **新增功能** / **添加功能** / **實作功能** | `feature/功能描述` | `feature/user-authentication` |
| **修正** / **修復** / **fix** | `fix/問題描述` | `fix/login-validation` |
| **重構** / **refactor** | `refactor/重構內容` | `refactor/database-layer` |
| **優化** / **性能優化** / **perf** | `perf/優化內容` | `perf/api-response-time` |
| **文檔更新** / **docs** | `docs/文檔類型` | `docs/api-documentation` |
| **測試** / **test** | `test/測試內容` | `test/unit-tests` |
| **雜項** / **配置更新** / **chore** | `chore/更新內容` | `chore/dependency-update` |

### 自動分支命名規則
- 自動提取功能/問題描述作為分支名稱
- 轉換為 kebab-case 格式 (小寫，用破折號分隔)
- 移除特殊字符，保留英文、數字、破折號
- 限制分支名稱長度在 50 字符以內

### 分支操作流程
1. 檢測觸發詞和描述
2. 自動生成分支名稱
3. 從 main 分支創建新分支
4. 切換到新分支
5. 開始在新分支上開發

## ⚙️ 配置檔案說明

### `.claude/settings.json`
專案的 Claude Code 設定檔，包含所有 hooks 配置。

## 🎯 使用方式

### 1. 自動讀取專案資訊
- 開啟 Claude Code 時會自動載入 README.md

### 2. 智能分支管理
- 說「**新增功能：用戶認證系統**」→ 自動創建 `feature/user-authentication-system` 分支
- 說「**修正：登入驗證問題**」→ 自動創建 `fix/login-validation-issue` 分支
- 說「**重構：資料庫連接層**」→ 自動創建 `refactor/database-connection-layer` 分支

### 3. 約定式提交
- 明確說出「commit」或「提交」時，才會執行 git 提交操作
- **所有提交均採用約定式提交格式，不包含 Claude 署名**
- **不會自動執行 git push，需要手動推送到遠端**

### 4. 文檔更新
- 說出「更新 readme」時，會觸發 README.md 更新提示
- 自動更新 README 中的最後修改日期

### 5. 手動操作控制
- **不會因為一般修改而自動更新或提交**
- 只有明確使用觸發詞時才會執行對應自動化

## 🛠️ 自訂設置

### 修改觸發詞
在 `.claude/settings.json` 中的 `matcher` 欄位修改正規表達式來調整觸發條件。

### 新增分支類型
複製現有的 hook 模式並修改分支前綴和描述。

### 調整分支命名規則
修改命令中的 `sed` 和字符處理邏輯來改變分支命名方式。

### 專案特定範圍
更新本文檔中的「範圍 (Scope)」段落，定義適合您專案的提交範圍。

## 📋 檢查清單

設置完成後，請確認以下項目：

- [ ] `.claude/settings.json` 已放置在專案根目錄
- [ ] 修改 `docs/CLAUDE.md` 中的範圍定義適合您的專案
- [ ] README.md 包含「**最後更新**：YYYY-MM-DD」格式的日期
- [ ] Git 倉庫已初始化，且有 main 分支
- [ ] 測試觸發詞是否正確創建分支
- [ ] 測試提交自動化是否正常運作

## 💡 最佳實踐建議

1. **分支命名一致性**：使用統一的描述風格
2. **提交頻率**：小步提交，經常提交
3. **分支管理**：完成功能後及時合併並清理分支
4. **文檔同步**：定期更新 README 和相關文檔
5. **自動化測試**：配合 CI/CD 流程使用

---

## 🔧 故障排除

### 分支創建失敗
- 確認 Git 倉庫狀態和 main 分支存在
- 檢查是否有未提交的變更

### 提交自動化不工作
- 確認 README.md 包含正確的日期格式：`**最後更新**：YYYY-MM-DD`
- 檢查 Git 配置是否完整

### 觸發詞不生效
- 檢查 `.claude/settings.json` 語法正確性
- 重啟 Claude Code 重新載入設定

---

💡 **提醒**：此範本基於約定式提交和智能分支管理，可大幅提升開發效率！