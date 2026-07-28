# 給接手者（Claude 請先讀這節）

## 通用工作習慣在維護者的全域設定

跨專案共通的規則（回覆風格、台灣用語、先計畫再寫 code、公版樣板、commit／push 鐵則等）
放在維護者的 Claude 全域設定 **`C:\Users\user\.claude\CLAUDE.md`**，本檔不重複。

- **Claude**：該檔每次對話自動載入，不必另外開檔。
- **Codex／其他工具**：開始工作前**自行讀取該檔**（讀不到就照本檔做，不要臆測內容）。

⚠️ 這是本檔唯一允許指向庫外檔案的地方，代價已知：該檔不隨專案版控，換機器就沒有。
因此**專案作業本身的規則一律留在本檔**（下方 A／B／C 節），全域檔只放通用習慣——
讀不到全域檔時，頂多少掉風格偏好，不會做錯專案的事。

## 這是什麼

- **技術棧**：Python + PySide6（Qt）+ SQLite，純桌面單機程式；使用者為警察單位承辦人員
- **目標環境**：Windows，顯示縮放 **125%**，全域字體 **14pt**；PyInstaller `--onefile` 打包
- **資料**：軟刪除（清空欄位、保留 `doc_id`），不做真 DELETE
- **文件分工**：`README.md`＝使用者門面（撰寫定義見 DEVELOPER §9）；`DEVELOPER.md`＝技術文件（架構／打包／DB／版本記錄）；`PITFALLS.md`＝踩雷速查表（症狀→解法，本表任務對照見下）；`CLAUDE.md`＝協作規則（本檔）；`docs/handover.md`＝跨對話交接（不入庫）
- ⚠️ **入庫文件不得叫人去參照未入庫的檔案**：`CLAUDE.md`／`README.md`／`DEVELOPER.md`／`PITFALLS.md` 內不得指向 `.gitignore` 排除的路徑（`docs/*`、`dbfile.db`、根目錄 `fix_*.py`／`seed_*.py`、`*.spec`、`build/`／`dist/` 等）。**該留的結論直接寫進入庫文件本身**，不要留一個「詳見某某設計文件」的指標——未入庫檔案隨時可能不存在，`git status` 也看不出它被刪，規則會靜默失效（踩過：`docs/superpowers/` 被清掉後，CLAUDE.md 的指路變成死連結）。反向亦然：真正該長期保存的內容就要入庫，不要放在被忽略的路徑

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
**通用習慣（回覆風格、台灣用語、先計畫再寫 code、公版樣板、push 鐵則）見全域設定**，下面只列本專案專屬的部分。

### A. 跟他互動（溝通與節奏）

- **找得到就別問**：文件／code／`dbfile.db` 裡有答案的不要問；但**沒寫進文件的設計決策**一定要問，不要憑空假設

### B. 產出（程式與檔案）

- **README 與 DEVELOPER.md 都不主動改**，他要才改；例外：「發布版本」流程要更新 DEVELOPER 技術章節與 §8 版本記錄
- 改完**先 `py_compile` 驗證語法**，並主動自我迭代驗證：能單測就單測、能模擬（演算法／SQL round-trip）就跑一輪再交付。容器有 PySide6 可 import（跑非 GUI 純邏輯測試），但**無法開 GUI／截圖**——Tab 互動、Dialog、表格渲染請他上機測
- **單元測試在 `tests/`**：完整既有 suite 用 `python -m unittest discover -s tests`，檔名 `test_*.py` 勿改名；兩個 pytest/pytest-qt pilot 在本次核准的 Codex 本機環境，用 `$env:QT_QPA_PLATFORM = 'offscreen'` 後執行 `C:\Users\user\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe -m pytest tests/test_pytest_qt_runtime.py tests/test_reward_gui_pilot.py -q`。⚠️ **Codex 本機專用；Claude 或一般環境不可假設此路徑存在，應改用已安裝相同依賴的 Python**；此絕對路徑只代表本次 Codex 本機已驗證 workflow。動到可單測純邏輯（解析／SQL round-trip／狀態計算／權限判斷）**一併新增或更新測試**。見 DEVELOPER §4。⚠️ **GUI 流程測試目前只有一條敘獎 pilot（`test_reward_gui_pilot.py`，登錄→編輯→待發→發文）**；擴充其餘 GUI 流程、抽 driver 或加 production 注入 seam，一律**須另立經核可的計畫**才動
- ⚠️ **權限 gate 是每個新功能必檢項**：「受限身分不可做」的操作，只靠按鈕 `setEnabled(False)` 不夠——雙擊、行內編輯、Enter、右鍵、拖拉等替代路徑會繞過。①**所有**進入點補 guard（用 `_refEditable()`／`is_admin()` 等便捷判斷，勿字串比較）②上機以受限身分逐路徑驗證。此雷犯過，詳見 DEVELOPER §10「權限」
- ⚠️ **本專案的公版樣板清單**（「有公版就直接套」的通則見全域設定）：全域樣式 `lib/theme.py`（`APPLE_STYLE`／`HINT_COLOR`／`TEXT_COLOR`）、按鈕 `ui_utils/ui_common.py`（`BTN_CONFIRM`／`BTN_CANCEL`／`BTN_DANGER`）、訊息與確認框（`msgInfo`／`msgWarning`／`msgCritical`／`confirmBox`）、表格（`ui_utils/table.py` 的 `setupPreviewTable`）、日期框（`NullableDateEdit`／`setupDateEditToToday`／全域滾輪 guard，見 PITFALLS QTW-10／QTW-13）、設定面板（`ui_utils/settings_panels.py` 的 `_SettingsPanel`／`_save_row`）。在新檔案裡寫死色碼／自訂按鈕樣式＝往後改主題會漏掉這一處（已有前例：對話框自帶一份區域 QSS）

### C. 版本 / Git / 發布（鐵則；完整流程與用語約定見 DEVELOPER §7「發布流程」）

- **逐檔 add**：跳過 `dbfile.db` 與根目錄 `fix_*.py`／`seed_*.py`（刻意不入庫，勿誤刪）
- **push 前必跑 `python -m unittest tests.test_no_pii`**（防真實人名／個資；`dbfile.db` 只能是乾淨空殼）
- **勿手改 `lib/version.py`**：進版一律 `python tools/bump_version.py <版號>`；進位與否**他決定**
- **「進版」「發布版本」「出一版」**＝走完 DEVELOPER §7 發布流程**直到 GitHub Release 上架（5 asset：兩支 exe＋dbfile.db＋PACKED.zip＋速查卡，exe 與速查卡皆帶版號）才算結束**，別只做 bump＋tag 就回報完成
- release note 給 `.md` 檔（不入庫），**不要打在對話裡**
- 打包**只用 onefile**、build 一律用 PowerShell tool、每次砍 spec 全新 build（指令見 DEVELOPER §7）
