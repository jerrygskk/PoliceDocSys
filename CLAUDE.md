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
- **文件分工**：`README.md`＝使用者門面（撰寫定義見 DEVELOPER §9）；`DEVELOPER.md`＝技術文件（架構／打包／DB／版本記錄）；`PITFALLS.md`＝踩雷速查表（症狀→解法，本表任務對照見下）；`PRINTING.md`＝簽收單列印專章（引擎／版面／驗收網，自 DEVELOPER §5 拆出）；`CLAUDE.md`＝協作規則（本檔）；`docs/handover.md`＝跨對話交接（不入庫）
- ⚠️ **入庫文件不得叫人去參照未入庫的檔案**（通則與理由見全域設定）：`CLAUDE.md`／`README.md`／`DEVELOPER.md`／`PITFALLS.md` 內不得指向 `.gitignore` 排除的路徑——本專案是 `docs/*`、`dbfile.db`、根目錄 `fix_*.py`／`seed_*.py`、`*.spec`、`build/`／`dist/` 等。踩過：`docs/superpowers/` 被清掉後，CLAUDE.md 的指路變成死連結

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

這是維護者最看重的部分。違反這些會直接消耗他的信任與時間。
**通用習慣（回覆風格、台灣用語、先計畫再寫 code、公版樣板、push 鐵則）見全域設定**，下面只列本專案專屬的部分。

### A. 跟他互動（溝通與節奏）

- **找得到就別問**：文件／code／`dbfile.db` 裡有答案的不要問；但**沒寫進文件的設計決策**一定要問，不要憑空假設

### B. 產出（程式與檔案）

- ⚠️ **產品 runtime 相依是封閉清單，只有 `PySide6`**（全域設計原則「優先用成熟函式庫」在本專案的明確例外）：多一個套件就多一段開機解壓與載入時間，而**開啟速度是本專案刻意付出代價換來的**——PDF 產出因此走 Qt 的 `QPdfWriter`／`QPrinter` 而不引入 reportlab。要往 `requirements.txt` 加東西**一律先問他**；`tools/` 與測試相依（`requirements-dev.txt`）不受此限。分界由 `tests/test_environment_contract.py` 守著

- ⚠️ **完整版與獨立版的差異，一律加在 `AppProfile` 的欄位裡；現場要調的東西，一律做成 `App_Settings` 的 key。不要在程式各處寫「如果是獨立版就……」這種判斷。**
  理由很簡單：差異寫在一個地方，下次要改只改那一處；散在各處，下次就會漏改其中幾處。
  全域設計原則有一條說「不要做臆測性的設定項」，那是指**還沒有人需要**就先做一個開關（例如「以後說不定要換資料庫，先做個抽象層」）。本專案這兩樣**是已經存在的真實需求**（真的有兩支 exe、現場真的要調），不在那條的範圍內，別拿那條當理由改回散落的判斷式

- **README 與 DEVELOPER.md 都不主動改**，他要才改；例外：「發布版本」流程要更新 DEVELOPER 技術章節與 §8 版本記錄
- 改完**先 `py_compile` 驗證語法**，並主動自我迭代驗證：能單測就單測、能模擬（演算法／SQL round-trip）就跑一輪再交付。容器有 PySide6 可 import（跑非 GUI 純邏輯測試），但**無法開 GUI／截圖**——Tab 互動、Dialog、表格渲染請他上機測
- **單元測試在 `tests/`**：⚠️ **完整 gate 一律走 pytest 兩段式**（指令見 DEVELOPER §4／§7），`python -m unittest discover -s tests -t .` 只是無 pytest 環境的備援、不得拿來當發布 gate。⚠️ **`-t .` 不可省**：省略時 `tests` 被當頂層目錄、`tests/__init__.py` 不會載入，日期防呆的遮蔽裝不上，整包會卡在無人可按的確認框（PITFALLS TST-4）。檔名 `test_*.py` 勿改名；`tests/__init__.py` 與 `tests/date_guard_shim.py` 是讓 unittest 跑法也不會卡在日期防呆確認框的必要檔（PITFALLS TST-4），勿刪。單跑 GUI pilot 時先設 `$env:QT_QPA_PLATFORM = 'offscreen'`，再用 `C:\Users\user\AppData\Local\Programs\Python\Python312\python.exe -m pytest <檔案> -q`。⚠️ **這支系統 Python 是正式 gate 的唯一環境**（見 DEVELOPER §4）；**不要用 Codex runtime 那支**（`.cache\codex-runtimes\...`），它沒有 pytest／PySide6／matplotlib，跑不了測試。換機器時絕對路徑會不同，改用已裝齊 `requirements-dev.txt` 的 Python，並先跑 `tests/test_environment_contract.py` 確認版本對得上。動到可單測純邏輯（解析／SQL round-trip／狀態計算／權限判斷）**一併新增或更新測試**。見 DEVELOPER §4。⚠️ **GUI 流程測試為九支 pilot**（清單與寫新 pilot 的四條規則見 DEVELOPER §4「GUI pilot」）；再擴充其餘 GUI 流程、抽 driver 或加 production 注入 seam，一律**須另立經核可的計畫**才動
- ⚠️ **權限 gate 是每個新功能必檢項**（「按鈕反灰擋不住」的通則見全域設定）：本專案用 `_refEditable()`／`is_admin()` 等便捷判斷，勿字串比較；權限矩陣與既有 gate 詳見 DEVELOPER §10「權限」，破壞性或動實體檔案的流程另加「modal 返回後再檢查一次」（§10「執行時權限複核」）
- ⚠️ **視窗開啟時的初始焦點不得停在日期欄位**：任何 Dialog／視窗建好後都要明確
  `setFocus()` 到第一個該填的欄位（通常是必填的文字框或下拉），**不可讓焦點落在
  `QDateEdit`／`NullableDateEdit`**。日期框多半已預設今天，焦點停在上面時使用者
  的鍵盤輸入或滾輪會直接改掉日期，且畫面變化細微不易察覺，等於靜默竄改資料。
  慣例是在 `__init__` 末尾呼叫（既有例：`reward_dialog`／`ticket_dialog`／
  `settle_dialog`）。新增視窗一律照做並上機確認焦點位置。
- ⚠️ **本專案的公版樣板清單**（「有公版就直接套」的通則見全域設定）：全域樣式 `lib/theme.py`（`APPLE_STYLE`／`HINT_COLOR`／`TEXT_COLOR`）、按鈕 `ui_utils/ui_common.py`（`BTN_CONFIRM`／`BTN_CANCEL`／`BTN_DANGER`）、訊息與確認框（`msgInfo`／`msgWarning`／`msgCritical`／`confirmBox`）、表格（`ui_utils/table.py` 的 `setupPreviewTable`）、日期框（`NullableDateEdit`／`setupDateEditToToday`／全域滾輪 guard，見 PITFALLS QTW-10／QTW-13）、設定面板（`ui_utils/settings_panels.py` 的 `_SettingsPanel`／`_save_row`）。在新檔案裡寫死色碼／自訂按鈕樣式＝往後改主題會漏掉這一處。⚠️ **前例已經爆過**：六個編輯彈窗曾自帶一份區域 QSS，把公版的停用反灰整個蓋掉，現場回報「欄位鎖住了卻看不出來」；連帶挖出公版自己的規則順序也寫反。2026-08-07 全部移除、彈窗一律不設 stylesheet，詳見 PITFALLS **QSS-8**（QSS-3 那條「新彈窗必設背景＋文字色」已作廢，照做會再製造同一個 bug）

### C. 版本 / Git / 發布（鐵則；完整流程與用語約定見 DEVELOPER §7「發布流程」）

- **逐檔 add**：跳過 `dbfile.db` 與根目錄 `fix_*.py`／`seed_*.py`（刻意不入庫，勿誤刪）
- **push 前必跑 `python -m unittest tests.test_no_pii`**（防真實人名／個資；`dbfile.db` 只能是乾淨空殼）
- **勿手改 `lib/version.py`**：進版一律 `python tools/bump_version.py <版號>`；進位與否**他決定**
- **「進版」「發布版本」「出一版」**＝走完 DEVELOPER §7 發布流程**直到 GitHub Release 上架（5 asset：兩支 exe＋dbfile.db＋PACKED.zip＋速查卡，exe 與速查卡皆帶版號）才算結束**，別只做 bump＋tag 就回報完成
- release note 給 `.md` 檔（不入庫），**不要打在對話裡**
- 打包**只用 onefile**、build 一律用 PowerShell tool、每次砍 spec 全新 build（指令見 DEVELOPER §7）

#### commit 訊息寫法（本專案補充）

**通用寫法（格式、正文三件事、手動斷行、署名、PowerShell 的正解、禁止的空訊息）見全域設定**，
Codex／其他工具開工前自行讀取全域檔。下面只列本專案專屬的部分：

- commit 訊息是這個專案的**第二層歷史**（第一層是 `HISTORY.md`）——半年後查
  「這行為什麼改成這樣」時 `git log` 就是答案，只寫「修正罰單簽收表」等於沒寫。
- 發版用 `release: v1.2.9 摘要` 當標題。
- ⚠️ **正文手動斷行斷在約 40 個全形字**（≈ 終端機 80 欄），這是全域規則的實際值，
  在此寫死免得又抓錯：踩過斷在 20 個全形字左右，行數平白多一倍，訊息看起來又窄
  又高（v1.2.10-v2 後那兩則）。太窄不是「比較保險」，是把一段話拆得更難讀。
- 踩雷類改動把症狀與根因寫進正文（例：`msjh.ttc` 與 `msjhbd.ttc` family 名相同
  導致靠名字切字重靜默失效），那是往後 `PITFALLS.md` 條目的素材來源。

### D. 派工給 subagent（本專案的環境事實）

**「環境先備妥、實測可用才准派工」與六項準備清單見全域設定**，下面只列本專案要填進 brief 的實際值：

- **直譯器**：`C:\Users\user\AppData\Local\Programs\Python\Python312\python.exe`（正式 gate
  唯一環境，見 DEVELOPER §4）；**不要用 Codex runtime 那支**（`.cache\codex-runtimes\...`），
  它沒有 pytest／PySide6／matplotlib
- **環境變數**：離線 Qt 測試一律 `QT_QPA_PLATFORM=offscreen`
- **工作目錄**：專案根目錄（`getResourcePath` 靠當前工作目錄找 `dbfile.db`，見 DEVELOPER §4）
- **測試指令**：兩段式 pytest（非 shell／shell）＋ `test_no_pii`，指令見 DEVELOPER §4
- 測試一律用**暫存 DB**，絕不搬真實 `dbfile.db`
