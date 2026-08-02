# 給接手者（Codex 請先讀這節）

**讀取中文文字檔一律明確指定 UTF-8。**

- PowerShell 執行前先將 `$OutputEncoding` 與 `[Console]::OutputEncoding` 設為 UTF-8，不依賴系統預設編碼
- 若出現亂碼，立即改用 UTF-8 重新讀取；不得依據亂碼內容判斷

**開始工作前先讀取 `CLAUDE.md`。**


**commit 訊息不得只寫一行標題帶過。**

- 已知 Codex 習慣一行結案，本專案不接受：訊息要交代**為什麼改、改成什麼、影響哪些地方**
- 完整格式、分行寬度、類型前綴與範例見 `CLAUDE.md` C 節「commit 訊息寫法」，動手前先讀

**跑測試一律用正式 gate 那支 Python，不要用你自己的 runtime。**

- 正式環境：`C:\Users\user\AppData\Local\Programs\Python\Python312\python.exe`（3.12.10，已裝齊 `requirements-dev.txt`），指令與兩段式規則見 `DEVELOPER.md` §4
- ⚠️ **Codex runtime 那支跑不了測試**：`C:\Users\user\.cache\codex-runtimes\...\python.exe` 沒有 pytest／PySide6／matplotlib，`-m pytest` 會直接 `No module named pytest`。2026-08-03 前的文件曾指向它，已作廢
- **回報測試結果前先跑 `tests/test_environment_contract.py`**：它比對實際安裝版本與 `requirements-dev.txt`，不符即紅。這支紅著的時候，其餘測試的綠燈都不算數
- 換了直譯器就等於換了環境：**不得**因為「我這支跑得動」而改用別的 Python 交差，也不得為了讓環境契約測試變綠而去改 `requirements-dev.txt`——那份清單是正式 gate 環境的快照，要動先問維護者

以下不再鏡像：專案背景、任務對照表、協作偏好、版本／Git／發布鐵則**一律以 `CLAUDE.md` 為唯一來源**，本檔不維護副本。
