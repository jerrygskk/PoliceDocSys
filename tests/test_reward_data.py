# -*- coding: utf-8 -*-
"""敘獎資料層：schema、取號、軟刪除／還原與跨年度重置。"""
import os
import json
import sqlite3
import tempfile
import unittest

from lib import db_schema, db_seed, db_utils


class RewardDbTestCase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.conn = sqlite3.connect(self.db_path)
        db_schema.applySchema(self.conn)

    def tearDown(self):
        self.conn.close()
        os.remove(self.db_path)


class TestRewardSchema(RewardDbTestCase):
    def test_apply_schema_is_idempotent_and_creates_reward_table(self):
        db_schema.applySchema(self.conn)
        columns = [r[1] for r in self.conn.execute(
            "PRAGMA table_info(Document_Reward)")]
        self.assertEqual(columns, [
            "doc_id", "create_date", "register_date", "sender_id", "reason", "recipients",
            "last_modified",
        ])

    def test_sender_id_roundtrips(self):
        self.conn.execute(
            "INSERT INTO Document_Reward"
            "(doc_id,register_date,sender_id,reason,recipients) VALUES(?,?,?,?,?)",
            ("1", "2026-07-18", "P007", "協助偵辦", "甲員"))
        self.conn.commit()
        row = self.conn.execute(
            "SELECT sender_id FROM Document_Reward WHERE doc_id='1'").fetchone()
        self.assertEqual(row[0], "P007")

    def test_unissued_reward_keeps_registration_date_and_null_sender(self):
        # 敘獎登錄一律保留今天的登錄日期；發文頁才補發文日期與發文人員。
        self.conn.execute(
            "INSERT INTO Document_Reward"
            "(doc_id,create_date,register_date,sender_id,reason,recipients) VALUES(?,?,?,?,?,?)",
            ("1", "2026-07-21", "", None, "協助偵辦", "甲員"))
        self.conn.commit()
        row = self.conn.execute(
            "SELECT create_date,register_date,sender_id FROM Document_Reward "
            "WHERE doc_id='1'").fetchone()
        self.assertEqual(row[0], "2026-07-21")
        self.assertEqual(row[1], "")      # 未發文哨兵，非 NULL（NULL＝軟刪除）
        self.assertIsNone(row[2])         # 發文人員待發文頁補填

    def test_reward_insert_and_update_triggers_maintain_last_modified(self):
        names = {r[0] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'")}
        self.assertIn("trg_reward_insert", names)
        self.assertIn("trg_reward_update", names)

        self.conn.execute(
            "INSERT INTO Document_Reward"
            "(doc_id,register_date,reason,recipients) VALUES(?,?,?,?)",
            ("1", "2026-07-17", "協助查緝", "甲員,乙員"))
        inserted = self.conn.execute(
            "SELECT last_modified FROM Document_Reward WHERE doc_id='1'"
        ).fetchone()[0]
        self.assertIsNotNone(inserted)

        self.conn.execute(
            "UPDATE Document_Reward SET last_modified='2000-01-01 00:00:00' "
            "WHERE doc_id='1'")
        self.conn.execute(
            "UPDATE Document_Reward SET reason=? WHERE doc_id='1'",
            ("協助查緝修正",))
        updated = self.conn.execute(
            "SELECT last_modified FROM Document_Reward WHERE doc_id='1'"
        ).fetchone()[0]
        self.assertNotEqual(updated, "2000-01-01 00:00:00")

    def test_seed_contains_reward_sequence(self):
        db_seed.seedFreshDb(self.conn)
        row = self.conn.execute(
            "SELECT last_id FROM Seq_DocId WHERE table_name='Document_Reward'"
        ).fetchone()
        self.assertEqual(row, (0,))


class TestRewardDocId(RewardDbTestCase):
    def test_missing_sequence_row_is_created_then_incremented(self):
        self.assertEqual(db_utils.nextDocId(self.conn, "Document_Reward"), "1")
        self.assertEqual(db_utils.nextDocId(self.conn, "Document_Reward"), "2")
        count = self.conn.execute(
            "SELECT COUNT(*) FROM Seq_DocId WHERE table_name='Document_Reward'"
        ).fetchone()[0]
        self.assertEqual(count, 1)

    def test_existing_sequence_row_keeps_incrementing(self):
        self.conn.execute(
            "INSERT INTO Seq_DocId(table_name,last_id) VALUES(?,?)",
            ("Document_Reward", 8))
        self.assertEqual(db_utils.nextDocId(self.conn, "Document_Reward"), "9")


class TestRewardSoftDelete(RewardDbTestCase):
    def setUp(self):
        super().setUp()
        self.conn.execute(
            "INSERT INTO Document_Reward"
            "(doc_id,create_date,register_date,reason,recipients) VALUES(?,?,?,?,?)",
            ("7", "2026-07-16", "2026-07-17", "協助查緝", "名單外甲,乙員"))
        self.conn.commit()

    def test_insert_and_update_do_not_write_audit(self):
        self.conn.execute(
            "UPDATE Document_Reward SET reason=? WHERE doc_id='7'",
            ("更正事由",))
        count = self.conn.execute("SELECT COUNT(*) FROM Audit_Log").fetchone()[0]
        self.assertEqual(count, 0)

    def test_soft_delete_keeps_id_and_writes_raw_recipient_snapshot(self):
        result = db_utils.softDeleteDoc(
            self.conn, table="Document_Reward", doc_id="7",
            role="user", is_admin=False)
        self.assertEqual(result, "協助查緝")
        row = self.conn.execute(
            "SELECT create_date,register_date,reason,recipients FROM Document_Reward "
            "WHERE doc_id='7'").fetchone()
        self.assertEqual(row, (None, None, None, None))

        trash = self.conn.execute(
            "SELECT subject,doc_person,payload FROM Trash_Documents"
        ).fetchone()
        self.assertEqual(trash[0], "協助查緝")
        self.assertEqual(trash[1], "名單外甲,乙員")
        payload = json.loads(trash[2])
        self.assertEqual(
            {k: payload[k] for k in
             ("doc_id", "create_date", "register_date", "reason", "recipients")},
            {"doc_id": "7", "create_date": "2026-07-16", "register_date": "2026-07-17",
             "reason": "協助查緝", "recipients": "名單外甲,乙員"})

        audit = self.conn.execute(
            "SELECT operator,detail FROM Audit_Log WHERE target_table=?",
            ("Document_Reward",)).fetchone()
        self.assertIsNone(audit[0])
        self.assertIn("登錄日期：2026-07-16", audit[1])
        self.assertIn("發文日期：2026-07-17", audit[1])
        self.assertIn("協助查緝", audit[1])
        self.assertIn("名單外甲,乙員", audit[1])

    def test_restore_recovers_reward_payload(self):
        db_utils.softDeleteDoc(
            self.conn, table="Document_Reward", doc_id="7",
            role="admin", is_admin=True)
        trash_id = self.conn.execute(
            "SELECT trash_id FROM Trash_Documents").fetchone()[0]
        self.assertEqual(
            db_utils.restoreFromTrash(self.conn, trash_id),
            ("Document_Reward", "7"))
        row = self.conn.execute(
            "SELECT create_date,register_date,reason,recipients FROM Document_Reward "
            "WHERE doc_id='7'").fetchone()
        self.assertEqual(
            row, ("2026-07-16", "2026-07-17", "協助查緝", "名單外甲,乙員"))
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM Trash_Documents").fetchone()[0],
            0)


class TestRewardReset(RewardDbTestCase):
    def test_reset_summary_counts_only_active_rows_and_includes_reward(self):
        from tabs.tab_settings import _resetDocCounts, _resetSummary
        self.conn.execute(
            "INSERT INTO Document_Reward"
            "(doc_id,register_date,reason,recipients) VALUES('1','2026-07-17','甲','甲員')")
        self.conn.execute(
            "INSERT INTO Document_Reward(doc_id,register_date) VALUES('2',NULL)")
        counts = _resetDocCounts(self.conn)
        self.assertEqual(counts["reward"], 1)
        self.assertIn("敘獎 1 筆", _resetSummary(counts))

    def test_year_end_reset_clears_reward_and_zeros_sequence(self):
        self.conn.execute(
            "INSERT INTO Document_Reward"
            "(doc_id,register_date,reason,recipients) VALUES(?,?,?,?)",
            ("1", "2026-07-17", "協助查緝", "甲員"))
        self.conn.execute(
            "INSERT INTO Seq_DocId(table_name,last_id) VALUES(?,?)",
            ("Document_Reward", 1))
        self.conn.commit()
        self.conn.close()

        db_utils.performYearEndReset(self.db_path)

        self.conn = sqlite3.connect(self.db_path)
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM Document_Reward").fetchone()[0],
            0)
        self.assertEqual(self.conn.execute(
            "SELECT last_id FROM Seq_DocId WHERE table_name='Document_Reward'"
        ).fetchone(), (0,))


if __name__ == "__main__":
    unittest.main()
