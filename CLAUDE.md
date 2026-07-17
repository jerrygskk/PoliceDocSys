# 給接手者（Claude 請先讀這節）

## 這是什麼

- **技術棧**：Python + PySide6（Qt）+ SQLite，純桌面單機程式；使用者為警察單位承辦人員
- **目標環境**：Windows，顯示縮放 **125%**，全域字體 **14pt**；PyInstaller `--onefile` 打包
- **資料**：軟刪除（清空欄位、保留 `doc_id`），不做真 DELETE
- **文件分工**：`README.md`＝使用者門面（撰寫定義見 DEVELOPER §9）；`DEVELOPER.md`＝技術文件（架構／踩雷／打包／DB／版本記錄）；`CLAUDE.md`＝協作規則（本檔）；`docs/handover.md`＝跨對話交接（不入庫）

## 任務對照表（動手前先讀哪裡）

**開新對話第一動作：讀 DEVELOPER.md §1（架構）＋§3（慣例與設計決策）**，再依任務對照下表。寫過的雷再踩會被直接點名。

| 要做的事 | 動手前先讀（皆在 DEVELOPER.md） |
|----------|------------------------------|
| 動 `.ui`／新增版面、Tab | §2 踩雷 #1、#4；§5「新增 Tab 標準流程」 |
| Qt 樣式／顏色／表格外觀 | §2 踩雷 #2 |
| Qt 元件行為（combo／completer／日期框／滾輪／彈窗鈕） | §2 踩雷 #3；§5「可空白日期框」 |
| 陳報頁（tab_report）版面／模式切換 | §2 踩雷 #4；§5「tab_report 特殊架構」 |
| Tab 切換／未存攔截 | §2 踩雷 #5 |
| SVG／icon／HELP／速查卡 | §2 踩雷 #6；§5「程式內 HELP」 |
| SQL／查詢／軟刪除／參照表／瀏覽搜尋 | §2 踩雷 #7；§3、§6 |
| 歸檔檔名解析（`archive_text.py`） | §3「歸檔檔名解析的雷」 |
| 打包／重啟／磁碟空間 | §2 踩雷 #9；§7 |
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
- **單元測試在 `tests/`**：`python -m unittest discover -s tests`，檔名 `test_*.py` 勿改名。動到可單測純邏輯（解析／SQL round-trip／狀態計算／權限判斷）**一併新增或更新測試**。見 DEVELOPER §4
- ⚠️ **權限 gate 是每個新功能必檢項**：「受限身分不可做」的操作，只靠按鈕 `setEnabled(False)` 不夠——雙擊、行內編輯、Enter、右鍵、拖拉等替代路徑會繞過。①**所有**進入點補 guard（用 `_refEditable()`／`is_admin()` 等便捷判斷，勿字串比較）②上機以受限身分逐路徑驗證。此雷犯過，詳見 DEVELOPER §3「權限」
- **UI 文字正式**不口語（「儲存目前排序後繼續編輯？」而非「要存嗎？」）；**一律台灣用語**（對話／文件／UI）：軟體、程式、預設、滑鼠、檔案、資料夾、登入/登出、視窗、回傳、字串、迴圈、品質、網路、硬碟…

### C. 版本 / Git / 發布 / 打包

#### 版本號
- 定義於 `lib/version.py`，只進第三碼；進位與否**他決定**。**進版一律跑 `python tools/bump_version.py <版號>`**（同時改 version.py、產 version_info.txt、同步 README 版號），**勿手改 `version.py`**

#### 用語約定（他會用簡稱，要對上）
- **「進版」「發布版本」「出一版」**＝走完整發布流程**直到 GitHub Release 上架（4 asset）才算結束**。別只做 bump＋tag＋§8 就回報完成。其中「bump_version＋git tag `v{版號}`＋DEVELOPER §8 補一列」這組機械動作另稱「**版號進版**」（流程第 4 步）
- **「push上去」「推上去」**＝commit + push。**逐檔 add**（不要一次全加，跳過 `dbfile.db`）；**叫你推才推**，沒說不要問
  - ⚠️ 根目錄 `fix_*.py`／`seed_*.py` 刻意不入庫，add 時跳過、勿誤刪
  - ⚠️ 多行 commit 訊息用 Bash heredoc（`git commit -F - <<'EOF' … EOF`），**不要用 PowerShell here-string**（`@` 會黏進 subject，踩過多次）
- ⚠️ **push 前必確認無真實人名／個資**：含測試 fixture、文件範例、`dbfile.db`（只能是乾淨空殼、提交前 `VACUUM`）。**push 前跑 `python -m unittest tests.test_no_pii`**（比對本機 `tests/pii_denylist.local.txt` 真名清單）；有新進真名補進清單
- **release note**＝給 `.md` 檔（`release_note_v{版號}.md`，不入庫），**不要打在對話裡**；內容寫給使用者看，技術細節留 DEVELOPER.md

#### 發布版本標準流程（照順序做到底）
1. **寫文件內文**：技術章節補進 DEVELOPER.md；使用者有感的改動 README 也同步；HELP／QUICKSTART 對照「跨功能影響對照表」逐列確認（歷來最常漏）
2. **寫 handover**（需跨對話交接才寫）
3. **寫 release note**
4. **版號進版**
5. **推上去** + tag `v{版號}` + push tag
6. **build**：onefile 全新 build（DEVELOPER §7），回報成功/失敗
7. **發 GitHub Release**：4 asset（exe／空殼 `dbfile.db`／`PACKED.zip`／`Quick_Start.pdf`），指令與 asset 取得方式見 DEVELOPER §7「發 GitHub Release」

> ⚠️ **順序鐵則**：文件／release note 要在「版號進版 commit」**之前**寫好，tag 才指向含完整文件的 commit；先打 tag 事後補文件＝退版重做。
> ⚠️ tag 已 push 後要移動：本地 `git tag -f` 後，遠端**先刪再推**（`git push origin :refs/tags/v{版號}` 再 push）。

#### 打包（PyInstaller）
- **只用 onefile**，不要問打包方式；每次砍掉 spec 全新 build（指令見 DEVELOPER §7，開頭含清除步驟）
- **build 一律用 PowerShell tool**：`del /q`／`rmdir /s /q` 是 CMD 語法，Git Bash 不識別會靜默失敗
- 可直接本機執行 build，完成只回報成功/失敗（失敗才貼錯誤末段）
