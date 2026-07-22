# 2026-07-22 DB 契約矩陣

| 風險／契約 | 現有精確 test ID | 現有 assertion 保護內容 | 缺口 | 處置 |
|---|---|---|---|---|
| schema 建立、冪等與既有資料保存 | `tests.test_db_schema.TestEnsureSchema.test_idempotent`; `tests.test_db_schema.TestEnsureSchema.test_does_not_wipe_existing_data` | 連跑兩次後 `Audit_Log` 僅一張；既有 `Audit_Log` 的一筆資料仍存在。 | 無已知缺口 | 保留既有覆蓋 |
| schema View 建立 | `tests.test_db_schema.TestEnsureSchema.test_idempotent`; `tests.test_db_schema.TestEnsureSchema.test_does_not_wipe_existing_data` | 兩項 assertion 只檢查 `Audit_Log` 的表數與既有資料，未斷言任何正式 View 存在或可查詢。 | 未驗證正式 schema 的 View 建立與可查詢性。 | 候選缺口—等待核准 |
| `doc_id` 配號與碰撞 | `tests.test_db_utils.TestNextDocId.test_increments`; `tests.test_db_utils.TestYearEndReset.test_no_pk_collision_on_shift`; `tests.test_reward_data.TestRewardDocId.test_missing_sequence_row_is_created_then_incremented` | 序號連續遞增；跨年度兩段式重編不觸發 PRIMARY KEY 碰撞；缺少 reward sequence row 時建立一列且後續遞增。 | 無已知缺口 | 保留既有覆蓋 |
| 年度重置 rollback | `tests.test_db_utils.TestYearEndReset.test_rollback_on_failure` | 移除 `Seq_DocId` 注入中途失敗後，`Document_Task` 原列及 `Ref_Personnel` 的原始 `P05` 均仍存在。 | 無已知缺口 | 保留既有覆蓋 |
| audit 共用 transaction rollback | `tests.test_audit.TestWriteAudit.test_shared_transaction_rollback` | 未 commit 的 `writeAudit` 後呼叫端 rollback，`Audit_Log` 筆數為 0。 | 無已知缺口 | 保留既有覆蓋 |
| soft-delete／restore | `tests.test_soft_delete.TestSoftDelete.test_task_delete_by_user_records_receiver`; `tests.test_trash.TestTrash.test_delete_then_restore_round_trip`; `tests.test_trash.TestTrash.test_restore_bumps_last_modified` | 刪除後活動列內容清空並保存 trash 資料；還原後完整欄位值回復、trash 清空，且 `last_modified` 不保留舊快照時間。 | 無已知缺口 | 保留既有覆蓋 |
| conversion rollback | `tests.test_doc_convert.TestConvertRoundTrip.test_rollback_on_pk_clash` | 目標 PRIMARY KEY 衝突時拋出 `sqlite3.IntegrityError`；rollback 後來源一般文的 `subject` 保持原值。 | 未斷言目標表未留下列，亦未斷言目標 `Seq_DocId` 回復。 | 候選缺口—等待核准 |
| reward 三狀態／restore | `tests.test_reward_status.TestRewardStatus.test_reward_register_date_has_three_distinct_states`; `tests.test_reward_data.TestRewardSoftDelete.test_restore_recovers_reward_payload` | `register_date` 的 NULL／空字串／日期分別落入 deleted／pending／issued 集合；restore 回復 reward payload 並清除 trash。 | 無已知缺口 | 改寫已完成 |
| browse 同 timestamp INSERT | `tests.test_dbbrowse_sync.TestDiffUpdateAlignment.test_external_insert_keeps_visible_rows_current` | 新增列的 `last_modified` 與既有 MAX 相同時，呼叫 public `on_activated` 後可見列數加一且包含新主旨。 | 無已知缺口 | 改寫已完成 |
| browse 同秒 soft-delete lifecycle | `tests.test_dbbrowse_sync.TestDiffUpdateAlignment.test_soft_delete_clear_removes_row_and_keeps_alignment`; `tests.test_dbbrowse_sync.TestDiffUpdateAlignment.test_crim_soft_delete_clear_removes_row` | lower-level `_diffUpdate` 可移除清空列並保持內部對齊。 | `(COUNT, MAX(last_modified))` 同秒可能不變，public `on_activated` 可能漏刷新。 | 已知限制—本計畫不修正 |
| backup verification／restore | `tests.test_db_backup.TestListVerifyRestore.test_verify_good_and_reject_corrupt`; `tests.test_db_backup.TestListVerifyRestore.test_restore_roundtrip_with_prerestore` | 驗證可接受正常 backup、拒絕 corrupt backup；restore 後活動資料回復且覆蓋前保護副本存在。 | 無已知缺口 | 保留既有覆蓋 |

## 應用內角色 guard 候選（獨立立案）

| 候選 | 定性 | 處置 |
|---|---|---|
| 跨年度重置 `_doReset()` | 應用內角色 guard 完整性 | 記錄；依可觸發性與影響另案排序；不在本計畫修正 |
| 參照資料／排序儲存 | 應用內角色 guard 完整性 | 記錄；不與 pytest-qt 綁定；不在本計畫修正 |
| 歸檔操作 | 應用內角色 guard 完整性 | 記錄；不在本計畫修正 |
| 管理員開啟特權 Dialog 後角色降級 | stale privilege 的應用內便利性防護 | 記錄；單機情境風險另案評估；不在本計畫修正 |

## 核准關卡

請逐項核准或拒絕所有標為「候選缺口—等待核准」的列；本計畫不新增 DB 測試，也不處理「已知限制—本計畫不修正」。
