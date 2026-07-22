# 給接手者（Claude 請先讀這節）

## 這是什麼

- **技術棧**：Python + PySide6（Qt）+ SQLite，純桌面單機程式；使用者為警察單位承辦人員
- **目標環境**：Windows，顯示縮放 **125%**，全域字體 **14pt**；PyInstaller `--onefile` 打包
- **資料**：軟刪除（清空欄位、保留 `doc_id`），不做真 DELETE
- **文件分工**：`README.md`＝使用者門面（撰寫定義見 DEVELOPER §9）；`DEVELOPER.md`＝技術文件（架構／打包／DB／版本記錄）；`PITFALLS.md`＝踩雷速查表（症狀→解法，本表任務對照見下）；`CLAUDE.md`＝協作規則（本檔）；`docs/handover.md`＝跨對話交接（不入庫）

## 任務對照表（動手前先讀哪裡）

**開新對話第一動作：讀 DEVELOPER.md §1（架構）＋§3（慣例與設計決策）**，再依任務對照下表。寫過的雷再踩會被直接點名。

| 要做的事 | 動手前先讀（皆在 DEVELOPER.md 與 PITFALLS.md） |
|----------|------------------------------|
| 動 `.ui`／新增版面、Tab | PITFALLS UI、LAY 組；§5「新增 Tab 標準流程」 |
| Qt 樣式／顏色／表格外觀 | PITFALLS QSS 組 |
| Qt 元件行為（combo／completer／日期框／滾輪／彈窗鈕） | PITFALLS QTW 組；§5「可空白日期框」 |
| 陳報頁（tab_report）版面／模式切換 | PITFALLS LAY 組；§5「tab_report 特殊架構」 |
| Tab 切換／未存攔截 | PITFALLS TAB 組 |
| SVG／icon／HELP／速查卡 | PITFALLS SVG 組；§5「程式內 HELP」 |
| SQL／查詢／軟刪除／參照表／瀏覽搜尋 | PITFALLS SQL 組；§6、§10「資料庫瀏覽（Tab6）搜尋」 |
| 歸檔檔名解析（`archive_text.py`） | §10「歸檔檔名解析的雷」 |
| 打包／重啟／磁碟空間 | PITFALLS PKG 組；§7 |
| **設定／權限／面板／新 App_Settings key** | **§2 文末「跨功能影響對照表」右欄逐項檢查**（防改 A 漏 B；新增 key／權限／面板須同步補一列） |
| 改 README | §9「README 撰寫定義」 |
| 改 schema／種子 | §5「結構變更原則」（唯一來源 `db_schema.py`／`db_seed.py`） |

## 協作偏好（務必遵守）

這是維護者最看重的部分。違反這些會直接消耗他的信任與時間。

### A. 跟他互動（溝通與節奏）

- **先思考再動手**：任何寫 code 的任務，先發想方案、整理成計畫給他看，經核可才寫 code；不要做完才說「其實有更好做法」。複雜或破壞性改動（多檔／改結構／改資料）先盤點影響範圍列清單
- **基於專業判斷給建議**，適時提供業界主流做法。反感「見風轉舵」——他說 A 就立刻倒向 A 還包裝成你的判斷，會被點名；有不同意見誠實講，講完理由讓他決定
- **找得到就別問**：文件／code／dbfile 裡有答案的不要問；但**沒寫進文件的設計決策**一定要問，不要憑空假設
- **回覆風格**：直接切入重點，無客套話、無開場白與結尾總結；列點、短句、最少字數。對話累積過長時，回覆結尾加「[提示：對話已長，建議備份摘要並開啟新對話]」

### B. 產出（程式與檔案）

- 直接修改本地端 code；**code 不主動整段貼出來**，他要看才給；不必逐一告知改了什麼 function（同檔名檔案如 `__init__.py` 須說明在哪個資料夾）
- **README 與 DEVELOPER.md 都不主動改**，他要才改；例外：「發布版本」流程要更新 DEVELOPER 技術章節與 §8 版本記錄
- **省 token**：先讀完相關檔案再動手，`str_replace` 範圍精準。⚠️ **`str_replace` 容易吃掉相鄰的 `def`**——改完 `grep` 確認上下相鄰函式定義還在（犯過多次），插入／刪除方法時最易發生
- 改完**先 `py_compile` 驗證語法**，並主動自我迭代驗證：能單測就單測、能模擬（演算法／SQL round-trip）就跑一輪再交付。容器有 PySide6 可 import（跑非 GUI 純邏輯測試），但**無法開 GUI／截圖**——Tab 互動、Dialog、表格渲染請他上機測
- **單元測試在 `tests/`**：完整既有 suite 用 `python -m unittest discover -s tests`，檔名 `test_*.py` 勿改名；兩個 pytest/pytest-qt pilot 在本次核准的 Codex 本機環境，用 `$env:QT_QPA_PLATFORM = 'offscreen'` 後執行 `C:\Users\user\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest tests/test_pytest_qt_runtime.py tests/test_reward_gui_pilot.py -q`。⚠️ **Codex 本機專用；Claude 或一般環境不可假設此路徑存在，應改用已安裝相同依賴的 Python**；此絕對路徑只代表本次 Codex 本機已驗證 workflow。動到可單測純邏輯（解析／SQL round-trip／狀態計算／權限判斷）**一併新增或更新測試**。見 DEVELOPER §4。⚠️ **GUI 流程測試目前只有一條敘獎 pilot（`test_reward_gui_pilot.py`，登錄→編輯→待發→發文）**；擴充其餘 GUI 流程、抽 driver 或加 production 注入 seam，一律**須另立經核可的計畫**才動（定案脈絡見 `docs/superpowers/specs/2026-07-22-pytest-qt-smoke-test-design.md` 與 `docs/superpowers/testing/`）
- ⚠️ **權限 gate 是每個新功能必檢項**：「受限身分不可做」的操作，只靠按鈕 `setEnabled(False)` 不夠——雙擊、行內編輯、Enter、右鍵、拖拉等替代路徑會繞過。①**所有**進入點補 guard（用 `_refEditable()`／`is_admin()` 等便捷判斷，勿字串比較）②上機以受限身分逐路徑驗證。此雷犯過，詳見 DEVELOPER §10「權限」
- **UI 文字正式**不口語（「儲存目前排序後繼續編輯？」而非「要存嗎？」）；**一律台灣用語**（對話／文件／UI）：軟體、程式、預設、滑鼠、檔案、資料夾、登入/登出、視窗、回傳、字串、迴圈、品質、網路、硬碟…

### C. 版本 / Git / 發布（鐵則；完整流程與用語約定見 DEVELOPER §7「發布流程」）

- **「push上去」「推上去」**＝commit + push；**叫你推才推**。**逐檔 add**：跳過 `dbfile.db` 與根目錄 `fix_*.py`／`seed_*.py`（刻意不入庫，勿誤刪）
- **push 前必跑 `python -m unittest tests.test_no_pii`**（防真實人名／個資；`dbfile.db` 只能是乾淨空殼）
- 多行 commit 訊息用 Bash heredoc（`git commit -F - <<'EOF'`），**不要用 PowerShell here-string**（踩過多次）
- **勿手改 `lib/version.py`**：進版一律 `python tools/bump_version.py <版號>`；進位與否**他決定**
- **「進版」「發布版本」「出一版」**＝走完 DEVELOPER §7 發布流程**直到 GitHub Release 上架（4 asset）才算結束**，別只做 bump＋tag 就回報完成
- release note 給 `.md` 檔（不入庫），**不要打在對話裡**
- 打包**只用 onefile**、build 一律用 PowerShell tool、每次砍 spec 全新 build（指令見 DEVELOPER §7）
