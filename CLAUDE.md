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
| **簽收單列印／繪圖層／簽收表版面** | **`PRINTING.md` 全檔**（引擎、三個出口、罰單 renderer、三層驗收網與基準重建）；改繪圖前基準必須是綠的 |
| SQL／查詢／軟刪除／參照表／瀏覽搜尋 | PITFALLS SQL 組；§6、§10「資料庫瀏覽（Tab6）搜尋」 |
| 歸檔檔名解析（`archive_text.py`） | §10「歸檔檔名解析的雷」 |
| 備份／異地備份／任何在網路路徑上建資料夾 | PITFALLS **NET 組**（`exist_ok=True` 吞不掉 UNC 分享根目錄的 WinError 50、錯誤碼不可比字串）；§10「平時自動備份」 |
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

- ⚠️ **產品 runtime 相依是封閉清單，只有 `PySide6`**（全域設計原則「優先用成熟函式庫」在本專案的明確例外）：多一個套件就多一段開機解壓與載入時間，而**開啟速度是本專案刻意付出代價換來的**——PDF 產出因此走 Qt 的 `QPdfWriter`／`QPrinter` 而不引入 reportlab。要往 `requirements.txt` 加東西**一律先問他**；`tools/` 與測試相依（`requirements-dev.txt`）不受此限。分界由 `tests/test_environment_contract.py` 守著

- ⚠️ **完整版與獨立版的差異，一律加在 `AppProfile` 的欄位裡；現場要調的東西，一律做成 `App_Settings` 的 key。不要在程式各處寫「如果是獨立版就……」這種判斷。**
  理由很簡單：差異寫在一個地方，下次要改只改那一處；散在各處，下次就會漏改其中幾處。
  全域設計原則有一條說「不要做臆測性的設定項」，那是指**還沒有人需要**就先做一個開關（例如「以後說不定要換資料庫，先做個抽象層」）。本專案這兩樣**是已經存在的真實需求**（真的有兩支 exe、現場真的要調），不在那條的範圍內，別拿那條當理由改回散落的判斷式

- **README 與 DEVELOPER.md 都不主動改**，他要才改；例外：「發布版本」流程要更新 DEVELOPER 技術章節與 §8 版本記錄
- 改完**先 `py_compile` 驗證語法**，並主動自我迭代驗證：能單測就單測、能模擬（演算法／SQL round-trip）就跑一輪再交付。容器有 PySide6 可 import（跑非 GUI 純邏輯測試），但**無法開 GUI／截圖**——Tab 互動、Dialog、表格渲染請他上機測
- **單元測試在 `tests/`**：完整既有 suite 用 `python -m unittest discover -s tests`，檔名 `test_*.py` 勿改名；兩個 pytest/pytest-qt pilot 用 `$env:QT_QPA_PLATFORM = 'offscreen'` 後執行 `C:\Users\user\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/test_pytest_qt_runtime.py tests/test_reward_gui_pilot.py -q`。⚠️ **這支系統 Python 是正式 gate 的唯一環境**（見 DEVELOPER §4）；**不要用 Codex runtime 那支**（`.cache\codex-runtimes\...`），它沒有 pytest／PySide6／matplotlib，跑不了測試。換機器時絕對路徑會不同，改用已裝齊 `requirements-dev.txt` 的 Python，並先跑 `tests/test_environment_contract.py` 確認版本對得上。動到可單測純邏輯（解析／SQL round-trip／狀態計算／權限判斷）**一併新增或更新測試**。見 DEVELOPER §4。⚠️ **GUI 流程測試目前只有一條敘獎 pilot（`test_reward_gui_pilot.py`，登錄→編輯→待發→發文）**；擴充其餘 GUI 流程、抽 driver 或加 production 注入 seam，一律**須另立經核可的計畫**才動
- ⚠️ **權限 gate 是每個新功能必檢項**：「受限身分不可做」的操作，只靠按鈕 `setEnabled(False)` 不夠——雙擊、行內編輯、Enter、右鍵、拖拉等替代路徑會繞過。①**所有**進入點補 guard（用 `_refEditable()`／`is_admin()` 等便捷判斷，勿字串比較）②上機以受限身分逐路徑驗證。此雷犯過，詳見 DEVELOPER §10「權限」
- ⚠️ **視窗開啟時的初始焦點不得停在日期欄位**：任何 Dialog／視窗建好後都要明確
  `setFocus()` 到第一個該填的欄位（通常是必填的文字框或下拉），**不可讓焦點落在
  `QDateEdit`／`NullableDateEdit`**。日期框多半已預設今天，焦點停在上面時使用者
  的鍵盤輸入或滾輪會直接改掉日期，且畫面變化細微不易察覺，等於靜默竄改資料。
  慣例是在 `__init__` 末尾呼叫（既有例：`reward_dialog`／`ticket_dialog`／
  `settle_dialog`）。新增視窗一律照做並上機確認焦點位置。
- ⚠️ **本專案的公版樣板清單**（「有公版就直接套」的通則見全域設定）：全域樣式 `lib/theme.py`（`APPLE_STYLE`／`HINT_COLOR`／`TEXT_COLOR`）、按鈕 `ui_utils/ui_common.py`（`BTN_CONFIRM`／`BTN_CANCEL`／`BTN_DANGER`）、訊息與確認框（`msgInfo`／`msgWarning`／`msgCritical`／`confirmBox`）、表格（`ui_utils/table.py` 的 `setupPreviewTable`）、日期框（`NullableDateEdit`／`setupDateEditToToday`／全域滾輪 guard，見 PITFALLS QTW-10／QTW-13）、設定面板（`ui_utils/settings_panels.py` 的 `_SettingsPanel`／`_save_row`）。在新檔案裡寫死色碼／自訂按鈕樣式＝往後改主題會漏掉這一處（已有前例：對話框自帶一份區域 QSS）

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
- 踩雷類改動把症狀與根因寫進正文（例：`msjh.ttc` 與 `msjhbd.ttc` family 名相同
  導致靠名字切字重靜默失效），那是往後 `PITFALLS.md` 條目的素材來源。

### D. 派工給 subagent（主程序的準備責任）

- ⚠️ **環境由主程序先備妥、實測可用，才准派工**：不得把「環境長怎樣」丟給 agent 自己摸索。
  agent 是冷啟動、沒有本次對話脈絡，環境沒備好就會一路試錯（跑到沒有 PySide6 的直譯器、
  找不到輸出資料夾、測試指令寫錯、在別人正在改的檔案上動手），時間全花在重試上。
- **派工前主程序要先自己跑一遍確認、再把結論寫進 brief**（是「已驗證的事實」，不是「請你自己查」）：
  1. **Python 直譯器**：確定要用哪一支絕對路徑，並實際 import 過 `PySide6`、確認 `pytest` 可用
     （本專案測試環境與兩段式 pytest 規則見 DEVELOPER §4）
  2. **執行環境變數**：離線 Qt 測試一律 `QT_QPA_PLATFORM=offscreen`
  3. **工作目錄**：絕對路徑；程式須從專案根目錄啟動（見 DEVELOPER §4 路徑解析）
  4. **輸出／暫存資料夾**：需要寫檔的先建好並在 brief 給絕對路徑，不讓 agent 臨時決定位置
  5. **可直接貼上執行的測試指令**：連同該 Task 該跑哪幾支測試一起給，不讓 agent 自行拼湊
  6. **工作區狀態**：先確認 git 乾淨或已知的未提交範圍、該 agent 的獨佔檔案範圍，
     避免與主程序或其他 agent 撞檔
- **未入庫的資料由 brief 直接提供**（計畫、規格、路徑約定等）：那些檔案 agent 可能根本看不到。
- 測試一律用**暫存 DB**，絕不搬真實 `dbfile.db`。
