# 給接手者（Claude／Codex 請先讀這節）

## 通則在維護者的全域設定

跨專案共通的規則（回覆風格、編碼、正式 Python、測試兩階、Qt 慣例、Git／commit／發版通則等）
放在維護者的全域設定 **`C:\Users\user\.claude\CLAUDE.md`**（Claude 與 Codex 皆自動載入），本檔不重複，只寫本專案的事。

⚠️ 這是本檔唯一允許指向庫外檔案的地方，代價已知：該檔不隨專案版控，換機器就沒有。
因此**專案作業本身的規則一律留在本檔**——讀不到全域檔時，頂多少掉通用習慣，不會做錯專案的事。

## 測試環境

- 正式 gate 環境：全域設定的那支 Python 3.12（本機為 3.12.10，已裝齊 `requirements-dev.txt`），指令與兩段式規則見 `DEVELOPER.md` §4
- ⚠️ Codex runtime 那支沒有 pytest／PySide6／matplotlib，`-m pytest` 會直接 `No module named pytest`。2026-08-03 前的文件曾指向它，已作廢
- **回報測試結果前先跑 `tests/test_environment_contract.py`**：它比對實際安裝版本與 `requirements-dev.txt`，不符即紅。這支紅著的時候，其餘測試的綠燈都不算數
- **不得**為了讓環境契約測試變綠而去改 `requirements-dev.txt`——那份清單是正式 gate 環境的快照，要動先問維護者

## 這是什麼

- **技術棧**：Python + PySide6（Qt）+ SQLite，純桌面單機程式；使用者為警察單位承辦人員
- **目標環境**：Windows，顯示縮放 **125%**，全域字體 **14pt**；PyInstaller `--onefile` 打包
- **資料**：軟刪除（清空欄位、保留 `doc_id`），不做真 DELETE
- **文件分工**：`README.md`＝使用者門面（撰寫定義見 DEVELOPER §9）；`DEVELOPER.md`＝技術文件（架構／打包／DB／版本記錄）；`PITFALLS.md`＝踩雷速查表（症狀→解法，本表任務對照見下）；`PRINTING.md`＝簽收單列印專章（引擎／版面／驗收網，自 DEVELOPER §5 拆出）；`AGENTS.md`＝協作規則（本檔）；`docs/handover.md`＝跨對話交接（不入庫）
- ⚠️ 入庫文件不得指向的未入庫路徑（通則見全域設定），本專案是 `docs/*`、`dbfile.db`、根目錄 `fix_*.py`／`seed_*.py`、`*.spec`、`build/`／`dist/` 等。踩過：`docs/superpowers/` 被清掉後，協作規則檔的指路變成死連結

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
| **簽收單列印／繪圖層／簽收表版面** | **`PRINTING.md` 全檔**（引擎、三個出口、罰單 renderer、三層驗收網與基準重建）；改繪圖前基準必須是綠的 |
| SQL／查詢／軟刪除／參照表／瀏覽搜尋 | PITFALLS SQL 組；§6、§10「資料庫瀏覽（Tab6）搜尋」 |
| 歸檔檔名解析（`archive_text.py`） | §10「歸檔檔名解析的雷」 |
| 備份／異地備份／任何在網路路徑上建資料夾 | PITFALLS **NET 組**（`exist_ok=True` 吞不掉 UNC 分享根目錄的 WinError 50、錯誤碼不可比字串）；§10「平時自動備份」 |
| 打包／重啟／磁碟空間 | PITFALLS PKG 組；§7 |
| **設定／權限／面板／新 App_Settings key** | **§2 文末「跨功能影響對照表」右欄逐項檢查**（防改 A 漏 B；新增 key／權限／面板須同步補一列）；PITFALLS **CFG 組**（開機讀一次就快取的設定，存檔後要有人重新套用） |
| 預覽列的可改／可刪、降權行為 | PITFALLS **PRM 組**；§10「權限」的「預覽列權限」分界表（三種頁面三套規則，規則單一來源 `lib/row_perm.py`） |
| 編輯彈窗的併發防護（樂觀鎖） | §10「編輯彈窗的 `last_modified` 樂觀鎖」（五個彈窗統一；秒精度窄縫是已知並接受的） |
| 改 README | §9「README 撰寫定義」 |
| 改 schema／種子 | §5「結構變更原則」（唯一來源 `db_schema.py`／`db_seed.py`） |

## 協作偏好（務必遵守）

這是維護者最看重的部分。違反這些會直接消耗他的信任與時間。下面只列本專案專屬的部分。

### B. 產出（程式與檔案）

- ⚠️ **產品 runtime 相依是封閉清單，只有 `PySide6`**（全域「優先用成熟函式庫」在本專案的明確例外）：**開啟速度是本專案刻意付出代價換來的**——PDF 產出因此走 Qt 的 `QPdfWriter`／`QPrinter` 而不引入 reportlab。`tools/` 與測試相依（`requirements-dev.txt`）不受此限。分界由 `tests/test_environment_contract.py` 守著

- ⚠️ **完整版與獨立版的差異，一律加在 `AppProfile` 的欄位裡；現場要調的東西，一律做成 `App_Settings` 的 key。不要在程式各處寫「如果是獨立版就……」這種判斷。**
  理由很簡單：差異寫在一個地方，下次要改只改那一處；散在各處，下次就會漏改其中幾處。
  全域設計原則有一條說「不要做臆測性的設定項」，那是指**還沒有人需要**就先做一個開關（例如「以後說不定要換資料庫，先做個抽象層」）。本專案這兩樣**是已經存在的真實需求**（真的有兩支 exe、現場真的要調），不在那條的範圍內，別拿那條當理由改回散落的判斷式

- 語法用 `py_compile` 驗證。容器有 PySide6 可 import（跑非 GUI 純邏輯測試），但**無法開 GUI／截圖**——Tab 互動、Dialog、表格渲染請他上機測
- **單元測試在 `tests/`**：⚠️ **完整 gate 一律走 pytest 兩段式**（指令見 DEVELOPER §4／§7），`python -m unittest discover -s tests -t .` 只是無 pytest 環境的備援、不得拿來當發布 gate。⚠️ **`-t .` 不可省**：省略時 `tests` 被當頂層目錄、`tests/__init__.py` 不會載入，日期防呆的遮蔽裝不上，整包會卡在無人可按的確認框（PITFALLS TST-4）。檔名 `test_*.py` 勿改名；`tests/__init__.py` 與 `tests/date_guard_shim.py` 是讓 unittest 跑法也不會卡在日期防呆確認框的必要檔（PITFALLS TST-4），勿刪。單跑 GUI pilot：`$env:QT_QPA_PLATFORM = 'offscreen'` 後 `python -m pytest <檔案> -q`。⚠️ **GUI 流程測試為九支 pilot**（清單與寫新 pilot 的四條規則見 DEVELOPER §4「GUI pilot」）；再擴充其餘 GUI 流程、抽 driver 或加 production 注入 seam，一律**須另立經核可的計畫**才動
- ⚠️ **測試分兩階跑**（通則見全域設定）：本專案的「② 完整 gate」＝DEVELOPER §4 的環境契約＋兩段 pytest＋`test_no_pii`，約 5 分鐘。
  改完當下就直接跑 ② 的範圍：`lib/theme.py`、`tests/schema_template.py`、根 `conftest.py`、`lib/db_schema.py`／`lib/db_seed.py`、列印繪圖層（另有基準比對，見 `PRINTING.md`）
- ⚠️ **權限 gate 是每個新功能必檢項**（通則見全域設定）：本專案用 `_refEditable()`／`is_admin()` 等便捷判斷；權限矩陣與既有 gate 詳見 DEVELOPER §10「權限」，破壞性或動實體檔案的流程另加「modal 返回後再檢查一次」（§10「執行時權限複核」）
- 初始焦點規則（通則見全域設定）的既有例：`reward_dialog`／`ticket_dialog`／`settle_dialog`，焦點不可落在 `QDateEdit`／`NullableDateEdit`
- ⚠️ **本專案的公版樣板清單**（通則見全域設定）：全域樣式 `lib/theme.py`（`APPLE_STYLE`／`HINT_COLOR`／`TEXT_COLOR`）、按鈕 `ui_utils/ui_common.py`（`BTN_CONFIRM`／`BTN_CANCEL`／`BTN_DANGER`）、訊息與確認框（`msgInfo`／`msgWarning`／`msgCritical`／`confirmBox`）、表格（`ui_utils/table.py` 的 `setupPreviewTable`）、日期框（`NullableDateEdit`／`setupDateEditToToday`／全域滾輪 guard，見 PITFALLS QTW-10／QTW-13）、設定面板（`ui_utils/settings_panels.py` 的 `_SettingsPanel`／`_save_row`）。彈窗不設 stylesheet 的來由與公版規則順序見 PITFALLS **QSS-8**（QSS-3 那條「新彈窗必設背景＋文字色」已作廢，照做會再製造同一個 bug）

### C. 版本 / Git / 發布（完整流程與用語約定見 DEVELOPER §7「發布流程」）

- **逐檔 add 的跳過清單**：`dbfile.db` 與根目錄 `fix_*.py`／`seed_*.py`（刻意不入庫，勿誤刪）
- **push 前必跑 `python -m unittest tests.test_no_pii`**（防真實人名／個資；`dbfile.db` 只能是乾淨空殼）
- **進版工具**：`python tools/bump_version.py <版號>`，勿手改 `lib/version.py`
- **發版完成的標準**：GitHub Release 上架 5 個 asset——兩支 exe＋dbfile.db＋PACKED.zip＋速查卡，exe 與速查卡皆帶版號
- build 一律用 PowerShell tool、每次砍 spec 全新 build（指令見 DEVELOPER §7）
- commit 訊息是本專案的**第二層歷史**（第一層是 `HISTORY.md`）；發版用 `release: v1.2.9 摘要` 當標題

### D. 派工給 subagent（本專案的環境事實）

準備清單見全域設定，本專案要填進 brief 的實際值：

- **工作目錄**：專案根目錄（`getResourcePath` 靠當前工作目錄找 `dbfile.db`，見 DEVELOPER §4）
- **測試指令**：兩段式 pytest（非 shell／shell）＋ `test_no_pii`，指令見 DEVELOPER §4
- 暫存 DB，絕不搬真實 `dbfile.db`；直譯器與環境變數照全域設定
