# 2026-07-22 測試基線

## 執行環境

- 核准的 Python：BLOCKED — current agent shell has no approved Python executable
- 基線命令：未執行（Python BLOCKED）
- 基線結果：BLOCKED

`python --version` 無法辨識命令；`py -3 --version` 輸出 `No installed Python found!`。依 Global Constraints bootstrap，`$PythonExe` 與 `$PythonPrefix` 均未設定，故未執行 runtime-dependent unittest 命令。

## 逐檔盤點（35/35）

| 測試檔 | 風險／需求 | 層級 | 當前紅綠 | 基線失敗原因 | Git commit 次數 | 耦合 | 處置 |
|---|---|---|---|---|---:|---|---|
| `tests/test_app_lock.py` | 單一執行個體鎖 | unit | BLOCKED | Python runtime unavailable: `python --version` command not found; `py -3 --version`: `No installed Python found!` | 1 | 低 | 保留 |
| `tests/test_archive_text.py` | 歸檔文字解析與內容規則 | unit | BLOCKED | Python runtime unavailable: `python --version` command not found; `py -3 --version`: `No installed Python found!` | 1 | 低 | 保留 |
| `tests/test_audit.py` | Audit trail 寫入與內容 | DB | BLOCKED | Python runtime unavailable: `python --version` command not found; `py -3 --version`: `No installed Python found!` | 1 | 低 | 保留 |
| `tests/test_auth_manager.py` | 身分登入與權限 | DB | BLOCKED | Python runtime unavailable: `python --version` command not found; `py -3 --version`: `No installed Python found!` | 1 | 高 | 階段 1 改寫 |
| `tests/test_base_tab.py` | BaseTab 文件識別與日期格式化 | unit | BLOCKED | Python runtime unavailable: `python --version` command not found; `py -3 --version`: `No installed Python found!` | 1 | 中 | 保留 |
| `tests/test_casetype_alias.py` | 案類別 alias schema migration 與 completer | DB+GUI/offscreen | BLOCKED | Python runtime unavailable: `python --version` command not found; `py -3 --version`: `No installed Python found!` | 1 | 高 | 階段 1 改寫 |
| `tests/test_db_backup.py` | 資料庫備份、驗證與還原 | DB | BLOCKED | Python runtime unavailable: `python --version` command not found; `py -3 --version`: `No installed Python found!` | 2 | 高 | 保留 |
| `tests/test_db_schema.py` | Schema 與 View 結構 | DB | BLOCKED | Python runtime unavailable: `python --version` command not found; `py -3 --version`: `No installed Python found!` | 2 | 低 | 保留 |
| `tests/test_db_utils.py` | 資料庫共用工具公開行為 | DB | BLOCKED | Python runtime unavailable: `python --version` command not found; `py -3 --version`: `No installed Python found!` | 2 | 高 | 保留 |
| `tests/test_dbbrowse_sync.py` | 瀏覽列表外部資料同步 | DB+GUI/offscreen | BLOCKED | Python runtime unavailable: `python --version` command not found; `py -3 --version`: `No installed Python found!` | 2 | 高 | 階段 1 改寫 |
| `tests/test_dialog_smoke.py` | 編輯 Dialog 建立、預填與儲存 | DB+GUI/offscreen | BLOCKED | Python runtime unavailable: `python --version` command not found; `py -3 --version`: `No installed Python found!` | 6 | 高 | pilot 後評估；本輪不刪不併 |
| `tests/test_doc_convert.py` | 文件資料轉換與 round-trip | DB | BLOCKED | Python runtime unavailable: `python --version` command not found; `py -3 --version`: `No installed Python found!` | 1 | 低 | 保留 |
| `tests/test_error_msg.py` | 資料庫錯誤友善訊息分類 | unit | BLOCKED | Python runtime unavailable: `python --version` command not found; `py -3 --version`: `No installed Python found!` | 1 | 高 | 保留 |
| `tests/test_idle_timeouts.py` | 閒置逾時設定解析與換算 | DB | BLOCKED | Python runtime unavailable: `python --version` command not found; `py -3 --version`: `No installed Python found!` | 1 | 低 | 保留 |
| `tests/test_input_lock.py` | 輸入鎖定 resolver 與角色清除 | DB | BLOCKED | Python runtime unavailable: `python --version` command not found; `py -3 --version`: `No installed Python found!` | 1 | 高 | pilot 後評估；本輪不刪不併 |
| `tests/test_no_pii.py` | 版本控管內容個資防護 gate | unit | BLOCKED | Python runtime unavailable: `python --version` command not found; `py -3 --version`: `No installed Python found!` | 1 | 低 | 保留 |
| `tests/test_nullable_date.py` | 可空日期規則與日期輸入 widget | GUI/offscreen | BLOCKED | Python runtime unavailable: `python --version` command not found; `py -3 --version`: `No installed Python found!` | 1 | 低 | pilot 後評估；本輪不刪不併 |
| `tests/test_print_titles.py` | 列印標題資料設定 | DB | BLOCKED | Python runtime unavailable: `python --version` command not found; `py -3 --version`: `No installed Python found!` | 1 | 低 | 保留 |
| `tests/test_ref_sort.py` | 參照資料排序位置解析 | unit | BLOCKED | Python runtime unavailable: `python --version` command not found; `py -3 --version`: `No installed Python found!` | 1 | 高 | 保留 |
| `tests/test_report_input_mode.py` | 陳報輸入模式、結算與歸檔查詢 | DB | BLOCKED | Python runtime unavailable: `python --version` command not found; `py -3 --version`: `No installed Python found!` | 5 | 低 | 保留 |
| `tests/test_reward_browse.py` | 敘獎瀏覽列與同步顯示 | DB+GUI/offscreen | BLOCKED | Python runtime unavailable: `python --version` command not found; `py -3 --version`: `No installed Python found!` | 4 | 高 | 保留 |
| `tests/test_reward_data.py` | 敘獎資料儲存、讀取與軟刪除 | DB | BLOCKED | Python runtime unavailable: `python --version` command not found; `py -3 --version`: `No installed Python found!` | 3 | 低 | 保留 |
| `tests/test_reward_integration.py` | 敘獎功能整合與頁面配置 | GUI/offscreen | BLOCKED | Python runtime unavailable: `python --version` command not found; `py -3 --version`: `No installed Python found!` | 3 | 高 | pilot 後評估；本輪不刪不併 |
| `tests/test_reward_issue.py` | 敘獎待發、發文與刪除流程 | DB+GUI/offscreen | BLOCKED | Python runtime unavailable: `python --version` command not found; `py -3 --version`: `No installed Python found!` | 2 | 高 | pilot 後評估；本輪不刪不併 |
| `tests/test_reward_menu_assets.py` | 敘獎發文選單 icon 資源 | GUI/offscreen | BLOCKED | Python runtime unavailable: `python --version` command not found; `py -3 --version`: `No installed Python found!` | 1 | 低 | pilot 後評估；本輪不刪不併 |
| `tests/test_reward_print.py` | 敘獎列印分段與標題面板 | DB+GUI/offscreen | BLOCKED | Python runtime unavailable: `python --version` command not found; `py -3 --version`: `No installed Python found!` | 2 | 高 | 保留 |
| `tests/test_reward_recipients.py` | 敘獎受獎人姓名與輸入控制 | GUI/offscreen | BLOCKED | Python runtime unavailable: `python --version` command not found; `py -3 --version`: `No installed Python found!` | 1 | 高 | 保留 |
| `tests/test_reward_refresh.py` | 敘獎還原後兄弟頁面刷新 | unit | BLOCKED | Python runtime unavailable: `python --version` command not found; `py -3 --version`: `No installed Python found!` | 1 | 高 | pilot 後評估；本輪不刪不併 |
| `tests/test_reward_status.py` | 敘獎三態 SQL 條件 | unit | BLOCKED | Python runtime unavailable: `python --version` command not found; `py -3 --version`: `No installed Python found!` | 1 | 高 | 階段 1 改寫 |
| `tests/test_reward_summary.py` | 敘獎文件統計摘要與重置 Dialog | GUI/offscreen | BLOCKED | Python runtime unavailable: `python --version` command not found; `py -3 --version`: `No installed Python found!` | 1 | 高 | 保留 |
| `tests/test_reward_tab.py` | 敘獎登錄頁面與受獎人狀態 | DB+GUI/offscreen | BLOCKED | Python runtime unavailable: `python --version` command not found; `py -3 --version`: `No installed Python found!` | 3 | 高 | pilot 後評估；本輪不刪不併 |
| `tests/test_soft_delete.py` | 軟刪除資料不變式 | DB | BLOCKED | Python runtime unavailable: `python --version` command not found; `py -3 --version`: `No installed Python found!` | 3 | 高 | 保留 |
| `tests/test_status.py` | 逾期與文件狀態轉換 | unit | BLOCKED | Python runtime unavailable: `python --version` command not found; `py -3 --version`: `No installed Python found!` | 1 | 低 | 保留 |
| `tests/test_trash.py` | 垃圾桶查詢與還原契約 | DB | BLOCKED | Python runtime unavailable: `python --version` command not found; `py -3 --version`: `No installed Python found!` | 1 | 高 | 保留 |
| `tests/test_ui_load.py` | UI 資源載入與 widget 建立 | GUI/offscreen | BLOCKED | Python runtime unavailable: `python --version` command not found; `py -3 --version`: `No installed Python found!` | 3 | 低 | pilot 後評估；本輪不刪不併 |

## 應用內角色 guard 候選（本計畫只記錄）

| 候選 | 定性 | 本計畫處置 |
|---|---|---|
| 跨年度重置 `_doReset()` | 應用內角色 guard 完整性 | 記錄；依可觸發性與影響另案排序 |
| 參照資料／排序儲存 | 應用內角色 guard 完整性 | 記錄；不與 pytest-qt 綁定 |
| 歸檔操作 | 應用內角色 guard 完整性 | 記錄；不在本計畫修正 |
| 管理員開啟特權 Dialog 後角色降級 | stale privilege 的應用內便利性防護 | 記錄；單機情境風險另案評估 |

真正的資料安全邊界是 Windows／SMB ACL；以上不稱為後端安全漏洞。
