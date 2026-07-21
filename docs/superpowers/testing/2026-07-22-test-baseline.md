# 2026-07-22 測試基線

## 執行環境

- 核准的 Python：`C:\Users\user\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe`（`$PythonPrefix=@()`；`Python 3.12.13`）
- 基線命令：`& $PythonExe @PythonPrefix -m unittest discover -s tests`
- 基線結果：`FAILED (failures=2, errors=26, skipped=2)`；`Ran 249 tests in 11.782s`

完整 suite 的 26 個 error 均由核准 runtime 缺少 `PySide6` 引起；`test_db_backup` 另有兩個 `verify_admin_password` assertion failure。下表逐檔記錄精確失敗 ID 或 loader ID。

## 逐檔盤點（35/35）

| 測試檔 | 風險／需求 | 層級 | 當前紅綠 | 基線失敗原因 | Git commit 次數 | 耦合 | 處置 |
|---|---|---|---|---|---:|---|---|
| `tests/test_app_lock.py` | 單一執行個體鎖 | unit | 綠 | — | 1 | 低 | 保留 |
| `tests/test_archive_text.py` | 歸檔文字解析與內容規則 | unit | 綠 | — | 1 | 低 | 保留 |
| `tests/test_audit.py` | Audit trail 寫入與內容 | DB | 紅 | `unittest.loader._FailedTest.test_audit`: `ModuleNotFoundError: No module named 'PySide6'` via `tabs.tab_audit` | 1 | 低 | 保留 |
| `tests/test_auth_manager.py` | 身分登入與權限 | DB | 紅 | `unittest.loader._FailedTest.test_auth_manager`: `ModuleNotFoundError: No module named 'PySide6'` via `lib.auth_manager` | 1 | 高 | 階段 1 改寫 |
| `tests/test_base_tab.py` | BaseTab 文件識別與日期格式化 | unit | 紅 | `unittest.loader._FailedTest.test_base_tab`: `ModuleNotFoundError: No module named 'PySide6'` via `lib.base_tab` | 1 | 中 | 保留 |
| `tests/test_casetype_alias.py` | 案類別 alias schema migration 與 completer | DB+GUI/offscreen | 紅 | `unittest.loader._FailedTest.test_casetype_alias`: `ModuleNotFoundError: No module named 'PySide6'` via `ui_utils.settings_dialogs` | 1 | 高 | 階段 1 改寫 |
| `tests/test_db_backup.py` | 資料庫備份、驗證與還原 | DB | 紅 | `TestVerifyAdminPassword.test_correct_password` 與 `test_missing_hash_row_falls_back_to_default`: `AssertionError: False is not true` | 2 | 高 | 保留 |
| `tests/test_db_schema.py` | Schema 與 View 結構 | DB | 綠 | — | 2 | 低 | 保留 |
| `tests/test_db_utils.py` | 資料庫共用工具公開行為 | DB | 綠 | — | 2 | 高 | 保留 |
| `tests/test_dbbrowse_sync.py` | 瀏覽列表外部資料同步 | DB+GUI/offscreen | 紅 | `unittest.loader._FailedTest.test_dbbrowse_sync`: `ModuleNotFoundError: No module named 'PySide6'` | 2 | 高 | 階段 1 改寫 |
| `tests/test_dialog_smoke.py` | 編輯 Dialog 建立、預填與儲存 | DB+GUI/offscreen | 紅 | `unittest.loader._FailedTest.test_dialog_smoke`: `ModuleNotFoundError: No module named 'PySide6'` | 6 | 高 | pilot 後評估；本輪不刪不併 |
| `tests/test_doc_convert.py` | 文件資料轉換與 round-trip | DB | 綠 | — | 1 | 低 | 保留 |
| `tests/test_error_msg.py` | 資料庫錯誤友善訊息分類 | unit | 綠 | — | 1 | 高 | 保留 |
| `tests/test_idle_timeouts.py` | 閒置逾時設定解析與換算 | DB | 綠 | — | 1 | 低 | 保留 |
| `tests/test_input_lock.py` | 輸入鎖定 resolver 與角色清除 | DB | 紅 | `unittest.loader._FailedTest.test_input_lock`: `ModuleNotFoundError: No module named 'PySide6'` via `lib.base_tab` | 1 | 高 | pilot 後評估；本輪不刪不併 |
| `tests/test_no_pii.py` | 版本控管內容個資防護 gate | unit | 綠 | — | 1 | 低 | 保留 |
| `tests/test_nullable_date.py` | 可空日期規則與日期輸入 widget | GUI/offscreen | 紅 | `unittest.loader._FailedTest.test_nullable_date`: `ModuleNotFoundError: No module named 'PySide6'` | 1 | 低 | pilot 後評估；本輪不刪不併 |
| `tests/test_print_titles.py` | 列印標題資料設定 | DB | 綠 | — | 1 | 低 | 保留 |
| `tests/test_ref_sort.py` | 參照資料排序位置解析 | unit | 紅 | `unittest.loader._FailedTest.test_ref_sort`: `ModuleNotFoundError: No module named 'PySide6'` via `ui_utils.settings_dialogs` | 1 | 高 | 保留 |
| `tests/test_report_input_mode.py` | 陳報輸入模式、結算與歸檔查詢 | DB | 紅 | `TestSettleConcurrencyGuard.test_settle_skips_already_issued_crim`, `test_settle_skips_already_issued_gen`, `test_settle_still_updates_unissued`, `TestSettleDocumentTypes.test_settle_registry_and_counts_exclude_reward`: `ModuleNotFoundError: No module named 'PySide6'` via `ui_utils.settle_dialog` | 5 | 低 | 保留 |
| `tests/test_reward_browse.py` | 敘獎瀏覽列與同步顯示 | DB+GUI/offscreen | 紅 | `unittest.loader._FailedTest.test_reward_browse`: `ModuleNotFoundError: No module named 'PySide6'` | 4 | 高 | 保留 |
| `tests/test_reward_data.py` | 敘獎資料儲存、讀取與軟刪除 | DB | 紅 | `TestRewardReset.test_reset_summary_counts_only_active_rows_and_includes_reward`: `ModuleNotFoundError: No module named 'PySide6'` via `tabs.tab_settings` | 3 | 低 | 保留 |
| `tests/test_reward_integration.py` | 敘獎功能整合與頁面配置 | GUI/offscreen | 紅 | `unittest.loader._FailedTest.test_reward_integration`: `ModuleNotFoundError: No module named 'PySide6'` | 3 | 高 | pilot 後評估；本輪不刪不併 |
| `tests/test_reward_issue.py` | 敘獎待發、發文與刪除流程 | DB+GUI/offscreen | 紅 | `unittest.loader._FailedTest.test_reward_issue`: `ModuleNotFoundError: No module named 'PySide6'` | 2 | 高 | pilot 後評估；本輪不刪不併 |
| `tests/test_reward_menu_assets.py` | 敘獎發文選單 icon 資源 | GUI/offscreen | 紅 | `unittest.loader._FailedTest.test_reward_menu_assets`: `ModuleNotFoundError: No module named 'PySide6'` | 1 | 低 | pilot 後評估；本輪不刪不併 |
| `tests/test_reward_print.py` | 敘獎列印分段與標題面板 | DB+GUI/offscreen | 紅 | `unittest.loader._FailedTest.test_reward_print`: `ModuleNotFoundError: No module named 'PySide6'` | 2 | 高 | 保留 |
| `tests/test_reward_recipients.py` | 敘獎受獎人姓名與輸入控制 | GUI/offscreen | 紅 | `unittest.loader._FailedTest.test_reward_recipients`: `ModuleNotFoundError: No module named 'PySide6'` | 1 | 高 | 保留 |
| `tests/test_reward_refresh.py` | 敘獎還原後兄弟頁面刷新 | unit | 紅 | `unittest.loader._FailedTest.test_reward_refresh`: `ModuleNotFoundError: No module named 'PySide6'` via `tabs.tab_settings` | 1 | 高 | pilot 後評估；本輪不刪不併 |
| `tests/test_reward_status.py` | 敘獎三態 SQL 條件 | unit | 綠 | — | 1 | 高 | 階段 1 改寫 |
| `tests/test_reward_summary.py` | 敘獎文件統計摘要與重置 Dialog | GUI/offscreen | 紅 | `unittest.loader._FailedTest.test_reward_summary`: `ModuleNotFoundError: No module named 'PySide6'` | 1 | 高 | 保留 |
| `tests/test_reward_tab.py` | 敘獎登錄頁面與受獎人狀態 | DB+GUI/offscreen | 紅 | `unittest.loader._FailedTest.test_reward_tab`: `ModuleNotFoundError: No module named 'PySide6'` | 3 | 高 | pilot 後評估；本輪不刪不併 |
| `tests/test_soft_delete.py` | 軟刪除資料不變式 | DB | 綠 | — | 3 | 高 | 保留 |
| `tests/test_status.py` | 逾期與文件狀態轉換 | unit | 紅 | `unittest.loader._FailedTest.test_status`: `ModuleNotFoundError: No module named 'PySide6'` via `ui_utils.status` | 1 | 低 | 保留 |
| `tests/test_trash.py` | 垃圾桶查詢與還原契約 | DB | 紅 | `unittest.loader._FailedTest.test_trash`: `ModuleNotFoundError: No module named 'PySide6'` via `ui_utils.trash_panel` | 1 | 高 | 保留 |
| `tests/test_ui_load.py` | UI 資源載入與 widget 建立 | GUI/offscreen | 紅 | `unittest.loader._FailedTest.test_ui_load`: `ModuleNotFoundError: No module named 'PySide6'` | 3 | 低 | pilot 後評估；本輪不刪不併 |

## 應用內角色 guard 候選（本計畫只記錄）

| 候選 | 定性 | 本計畫處置 |
|---|---|---|
| 跨年度重置 `_doReset()` | 應用內角色 guard 完整性 | 記錄；依可觸發性與影響另案排序 |
| 參照資料／排序儲存 | 應用內角色 guard 完整性 | 記錄；不與 pytest-qt 綁定 |
| 歸檔操作 | 應用內角色 guard 完整性 | 記錄；不在本計畫修正 |
| 管理員開啟特權 Dialog 後角色降級 | stale privilege 的應用內便利性防護 | 記錄；單機情境風險另案評估 |

真正的資料安全邊界是 Windows／SMB ACL；以上不稱為後端安全漏洞。
