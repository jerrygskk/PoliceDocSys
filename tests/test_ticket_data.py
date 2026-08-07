# -*- coding: utf-8 -*-
"""罰單登錄資料層：schema、View、外鍵、流水號與 domain helper。"""
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

from lib import ticket_utils

from lib import db_schema, db_seed
from lib.ticket_utils import (
    TicketConflictError, TicketDuplicateError, TicketNotFoundError,
    TicketValidationError,
    createTicket, deleteTicket, normalizeTicketNo, ticketExists,
    ticketSortKey, updateTicket, updateTicketFromBrowse,
)
from ui_utils.settle_dialog import load_unissued


class TicketDbTestCase(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.conn = sqlite3.connect(self.db_path)
        # raw sqlite3 連線預設關閉外鍵；不在此明確開啟，FK 測試會假綠。
        self.conn.execute("PRAGMA foreign_keys=ON")
        db_schema.applySchema(self.conn)
        db_seed.seedFreshDb(self.conn)
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        os.remove(self.db_path)

    def _insert_person(self, staff_id, staff_name, sort_order=1):
        self.conn.execute(
            "INSERT OR REPLACE INTO Ref_Personnel"
            "(staff_id,staff_name,is_active,sort_order) VALUES(?,?,1,?)",
            (staff_id, staff_name, sort_order))
        self.conn.commit()

    def _lastModified(self, doc_id="1"):
        """開窗快照：樂觀鎖比對用的 `last_modified` 現值。

        ⚠️ 2026-08-07 起罰單改用 `last_modified` 樂觀鎖，取代原本比對五欄原值
        的做法（全專案五個編輯彈窗統一，見 db_utils.LAST_MODIFIED_CAS_SQL）。
        """
        row = self.conn.execute(
            "SELECT last_modified FROM Document_Ticket WHERE doc_id=?",
            (doc_id,)).fetchone()
        return row[0] if row is not None else None

    def _touch(self, doc_id="1", last_modified="2099-01-01 00:00:00"):
        """模擬他機異動：把 `last_modified` 換成與快照不同的值。

        ⚠️ 必須明寫而不能只靠 trigger——`last_modified` 只有秒精度，測試裡的
        兩次寫入落在同一秒會拿到相同字串，那正是這套機制的已知窄縫
        （見 db_utils.LAST_MODIFIED_CAS_SQL 與 PITFALLS SQL-7）。
        """
        self.conn.execute(
            "UPDATE Document_Ticket SET last_modified=? WHERE doc_id=?",
            (last_modified, doc_id))


class TestTicketNaturalSort(TicketDbTestCase):
    def test_ticket_sort_key_preserves_full_hand_checked_tuple_order(self):
        rows = [
            (2, "王小明", "A1"),
            (1, "李大華", "A10"),
            (1, "李大華", "A2"),
            (1, None, "B1"),
            (1, "王小明", "A1"),
        ]

        self.assertEqual(
            sorted(rows, key=lambda row: ticketSortKey(*row)),
            [
                (1, None, "B1"),
                (1, "李大華", "A2"),
                (1, "李大華", "A10"),
                (1, "王小明", "A1"),
                (2, "王小明", "A1"),
            ],
        )

    def test_natural_key_sorts_numeric_segments_case_insensitively(self):
        natural_key = getattr(ticket_utils, "ticketNoNaturalKey", None)
        self.assertIsNotNone(natural_key, "ticket_utils 應提供罰單自然排序單一來源")

        ticket_nos = [
            "A10B10", "a2", "A01", "a1", "A10B2", "A10", "b1",
        ]
        self.assertEqual(
            sorted(ticket_nos, key=natural_key),
            ["a1", "A01", "a2", "A10", "A10B2", "A10B10", "b1"],
        )

    def test_natural_key_handles_real_ticket_number_format(self):
        natural_key = getattr(ticket_utils, "ticketNoNaturalKey", None)
        self.assertIsNotNone(natural_key, "ticket_utils 應提供罰單自然排序單一來源")

        ticket_nos = ["D5RJ84426", "D4RD12450", "D5RJ84425"]
        self.assertEqual(
            sorted(ticket_nos, key=natural_key),
            ["D4RD12450", "D5RJ84425", "D5RJ84426"],
        )

    def test_settlement_ticket_rows_use_natural_order_after_query(self):
        self._insert_person("P001", "王小明", sort_order=1)
        for doc_id, ticket_no in enumerate(
                ("A10B10", "A2", "A01", "A1", "A10B2"), start=1):
            self.conn.execute(
                "INSERT INTO Document_Ticket"
                "(doc_id,create_date,register_date,sender_id,issuer_id,ticket_no) "
                "VALUES(?, '2026-07-29', '', NULL, 'P001', ?)",
                (str(doc_id), ticket_no),
            )
        self.conn.commit()

        rows = load_unissued(self.db_path)["ticket"]
        self.assertEqual(
            [row["subject"] for row in rows],
            ["A1", "A01", "A2", "A10B2", "A10B10"],
        )

    def test_settlement_sort_accepts_legacy_missing_issuer_names(self):
        self.conn.execute("PRAGMA foreign_keys=OFF")
        self.conn.execute("PRAGMA ignore_check_constraints=ON")
        self.conn.execute(
            "INSERT INTO Document_Ticket"
            "(doc_id,create_date,register_date,issuer_id,ticket_no) "
            "VALUES('1','2026-07-29','',NULL,'A10')")
        self.conn.execute(
            "INSERT INTO Document_Ticket"
            "(doc_id,create_date,register_date,issuer_id,ticket_no) "
            "VALUES('2','2026-07-29','','P404','A2')")
        self.conn.execute("PRAGMA ignore_check_constraints=OFF")
        self.conn.commit()

        rows = load_unissued(self.db_path)["ticket"]
        self.assertEqual([row["subject"] for row in rows], ["A10", "A2"])


class TestTicketSchema(TicketDbTestCase):
    def test_ticket_schema_view_and_seed_exist(self):
        conn = self.conn
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
        views = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='view'"
        )}
        self.assertIn("Document_Ticket", tables)
        self.assertIn("Document_Ticket_Full", views)
        self.assertEqual(
            conn.execute(
                "SELECT last_id FROM Seq_DocId WHERE table_name='Document_Ticket'"
            ).fetchone()[0],
            0,
        )

    def test_ticket_foreign_keys_are_enforced(self):
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.assertEqual(
            self.conn.execute("PRAGMA foreign_keys").fetchone()[0],
            1,
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                """INSERT INTO Document_Ticket
                   (doc_id, create_date, register_date, sender_id, issuer_id, ticket_no)
                   VALUES ('1', '2026-07-23', '', NULL, 'P999', 'D4RD15263')"""
            )

    def test_apply_schema_is_idempotent_and_columns_match(self):
        db_schema.applySchema(self.conn)
        columns = [r[1] for r in self.conn.execute(
            "PRAGMA table_info(Document_Ticket)")]
        self.assertEqual(columns, [
            "doc_id", "create_date", "register_date", "sender_id",
            "issuer_id", "ticket_no", "last_modified",
        ])

    def test_ticket_last_modified_trigger_exists_and_fires(self):
        names = {r[0] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'")}
        self.assertIn("trg_ticket_insert", names)
        self.assertIn("trg_ticket_update", names)

        self._insert_person("P001", "王小明")
        self.conn.execute(
            "INSERT INTO Document_Ticket"
            "(doc_id,create_date,register_date,sender_id,issuer_id,ticket_no) "
            "VALUES('1','2026-07-23','',NULL,'P001','D4RD15263')")
        self.assertIsNotNone(self.conn.execute(
            "SELECT last_modified FROM Document_Ticket WHERE doc_id='1'"
        ).fetchone()[0])

        self.conn.execute(
            "UPDATE Document_Ticket SET last_modified='2000-01-01 00:00:00' "
            "WHERE doc_id='1'")
        self.conn.execute(
            "UPDATE Document_Ticket SET ticket_no='D4RD15264' WHERE doc_id='1'")
        self.assertNotEqual(
            self.conn.execute(
                "SELECT last_modified FROM Document_Ticket WHERE doc_id='1'"
            ).fetchone()[0],
            "2000-01-01 00:00:00")

    def test_ticket_indexes_exist(self):
        names = {r[0] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'")}
        self.assertIn("ux_ticket_no_active", names)
        self.assertIn("idx_ticket_lastmod", names)

    def test_deleted_shell_row_is_allowed_and_index_ignores_null(self):
        # 軟刪除空殼（全欄 NULL）必須通過 CHECK，且多筆空殼不受唯一索引限制。
        self.conn.execute("INSERT INTO Document_Ticket(doc_id) VALUES('1')")
        self.conn.execute("INSERT INTO Document_Ticket(doc_id) VALUES('2')")
        self.conn.commit()
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM Document_Ticket").fetchone()[0], 2)

    def test_check_rejects_invalid_ticket_no(self):
        self._insert_person("P001", "王小明")
        for bad in ("d4rd15263", "D4-RD15263", "D4 RD", ""):
            with self.subTest(bad=bad):
                with self.assertRaises(sqlite3.IntegrityError):
                    self.conn.execute(
                        "INSERT INTO Document_Ticket"
                        "(doc_id,create_date,register_date,issuer_id,ticket_no) "
                        "VALUES('9','2026-07-23','','P001',?)", (bad,))

    def test_view_joins_personnel_names(self):
        self._insert_person("P001", "王小明", sort_order=3)
        self._insert_person("P002", "李大華", sort_order=5)
        self.conn.execute(
            "INSERT INTO Document_Ticket"
            "(doc_id,create_date,register_date,sender_id,issuer_id,ticket_no) "
            "VALUES('1','2026-07-23','2026-07-23','P002','P001','D4RD15263')")
        self.conn.commit()
        row = self.conn.execute(
            "SELECT sender_name, issuer_name, issuer_sort_order, ticket_no "
            "FROM Document_Ticket_Full WHERE doc_id='1'").fetchone()
        self.assertEqual(row, ("李大華", "王小明", 3, "D4RD15263"))


class TestProductionConnEnablesForeignKeys(TicketDbTestCase):
    def test_get_conn_turns_foreign_keys_on(self):
        # 正式連線必須真的啟用外鍵，否則 Document_Ticket 的 FK 宣告形同虛設。
        from lib.db_utils import getConn
        conn = getConn(self.db_path)
        try:
            self.assertEqual(
                conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            self.assertEqual(
                conn.execute("PRAGMA busy_timeout").fetchone()[0], 3000)
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO Document_Ticket"
                    "(doc_id,create_date,register_date,issuer_id,ticket_no) "
                    "VALUES('1','2026-07-23','','P999','D4RD15263')")
        finally:
            conn.close()


class TestTicketNormalize(unittest.TestCase):
    def test_normalize_ticket_no(self):
        self.assertEqual(normalizeTicketNo(" d4rd15263 "), "D4RD15263")
        for invalid in ("", "   ", "D4-RD", "D4 RD", "Ｄ４ＲＤ"):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    normalizeTicketNo(invalid)

    def test_normalize_ticket_no_length_limit(self):
        ok = "A" * 20
        self.assertEqual(normalizeTicketNo(ok), ok)
        too_long = "A" * 21
        with self.assertRaises(TicketValidationError):
            normalizeTicketNo(too_long)

    def test_validation_errors_are_value_errors(self):
        self.assertTrue(issubclass(TicketValidationError, ValueError))
        self.assertTrue(issubclass(TicketDuplicateError, TicketValidationError))
        self.assertTrue(issubclass(TicketNotFoundError, LookupError))


class TestTicketCreate(TicketDbTestCase):
    def test_create_ticket_modes_and_sequence(self):
        self._insert_person("P001", "王小明")
        self._insert_person("P002", "李大華")
        first = createTicket(
            self.conn, issuer_id="P001", ticket_no=" d4rd15263 ",
            self_service=True, sender_id=None, create_date="2026-07-23", role="user",
        )
        second = createTicket(
            self.conn, issuer_id="P001", ticket_no="d4rd15264",
            self_service=False, sender_id="P002",
            create_date="2026-07-23", role="user",
        )
        self.assertEqual((first, second), ("1", "2"))
        self.assertEqual(
            self.conn.execute(
                "SELECT register_date, sender_id, ticket_no "
                "FROM Document_Ticket WHERE doc_id='1'"
            ).fetchone(),
            ("", None, "D4RD15263"),
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT register_date, sender_id FROM Document_Ticket WHERE doc_id='2'"
            ).fetchone(),
            ("2026-07-23", "P002"),
        )

    def test_duplicate_is_case_insensitive(self):
        self._insert_person("P001", "王小明")
        createTicket(
            self.conn, issuer_id="P001", ticket_no="D4RD15263",
            self_service=True, sender_id=None, create_date="2026-07-23", role="user",
        )
        with self.assertRaises(TicketDuplicateError):
            createTicket(
                self.conn, issuer_id="P001", ticket_no="d4rd15263",
                self_service=True, sender_id=None,
                create_date="2026-07-23", role="user",
            )

    def test_self_service_ignores_leftover_sender(self):
        # 發文結算模式的發文者欄反灰但仍有殘留值，提交時不得採用。
        self._insert_person("P001", "王小明")
        self._insert_person("P002", "李大華")
        createTicket(
            self.conn, issuer_id="P001", ticket_no="D4RD15263",
            self_service=True, sender_id="P002",
            create_date="2026-07-23", role="user",
        )
        self.assertEqual(
            self.conn.execute(
                "SELECT register_date, sender_id FROM Document_Ticket WHERE doc_id='1'"
            ).fetchone(),
            ("", None),
        )

    def test_unknown_issuer_or_sender_is_rejected(self):
        self._insert_person("P001", "王小明")
        with self.assertRaises(TicketValidationError):
            createTicket(
                self.conn, issuer_id="P999", ticket_no="D4RD15263",
                self_service=True, sender_id=None,
                create_date="2026-07-23", role="user")
        with self.assertRaises(TicketValidationError):
            createTicket(
                self.conn, issuer_id="P001", ticket_no="D4RD15263",
                self_service=False, sender_id="P999",
                create_date="2026-07-23", role="user")
        with self.assertRaises(TicketValidationError):
            createTicket(
                self.conn, issuer_id="P001", ticket_no="D4RD15263",
                self_service=False, sender_id=None,
                create_date="2026-07-23", role="user")
        with self.assertRaises(TicketValidationError):
            createTicket(
                self.conn, issuer_id="P001", ticket_no="D4RD15263",
                self_service=True, sender_id=None,
                create_date="", role="user")
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM Document_Ticket").fetchone()[0], 0)

    def test_create_writes_no_audit(self):
        """罰單新增不寫操作紀錄（維護者決定：高頻操作，只保留刪除紀錄）。"""
        self._insert_person("P001", "王小明")
        createTicket(
            self.conn, issuer_id="P001", ticket_no="D4RD15263",
            self_service=True, sender_id=None,
            create_date="2026-07-23", role="user")
        self.assertEqual(
            self.conn.execute("SELECT COUNT(*) FROM Audit_Log").fetchone()[0],
            0)

    def test_deleted_ticket_no_can_be_reused(self):
        self._insert_person("P001", "王小明")
        createTicket(
            self.conn, issuer_id="P001", ticket_no="D4RD15263",
            self_service=True, sender_id=None,
            create_date="2026-07-23", role="user")
        deleteTicket(self.conn, doc_id="1", role="user")
        second = createTicket(
            self.conn, issuer_id="P001", ticket_no="D4RD15263",
            self_service=True, sender_id=None,
            create_date="2026-07-23", role="user")
        self.assertEqual(second, "2")


class TestTicketExists(TicketDbTestCase):
    def setUp(self):
        super().setUp()
        self._insert_person("P001", "王小明")
        createTicket(
            self.conn, issuer_id="P001", ticket_no="D4RD15263",
            self_service=True, sender_id=None,
            create_date="2026-07-23", role="user")

    def test_exists_is_case_insensitive_and_trimmed(self):
        self.assertTrue(ticketExists(self.conn, " d4rd15263 "))
        self.assertFalse(ticketExists(self.conn, "D4RD99999"))
        self.assertFalse(ticketExists(self.conn, ""))

    def test_exclude_doc_id_skips_self(self):
        self.assertFalse(
            ticketExists(self.conn, "D4RD15263", exclude_doc_id="1"))
        self.assertTrue(
            ticketExists(self.conn, "D4RD15263", exclude_doc_id="2"))

    def test_deleted_shell_is_not_counted(self):
        deleteTicket(self.conn, doc_id="1", role="user")
        self.assertFalse(ticketExists(self.conn, "D4RD15263"))


class TestTicketUpdate(TicketDbTestCase):
    def setUp(self):
        super().setUp()
        self._insert_person("P001", "王小明")
        self._insert_person("P002", "李大華")
        createTicket(
            self.conn, issuer_id="P001", ticket_no="D4RD15263",
            self_service=False, sender_id="P002",
            create_date="2026-07-20", role="user")

    def test_update_keeps_dates_and_sender(self):
        updateTicket(self.conn, doc_id="1", issuer_id="P002",
                     ticket_no=" d4rd19999 ", role="user",
                     last_modified=self._lastModified())
        self.assertEqual(
            self.conn.execute(
                "SELECT create_date, register_date, sender_id, issuer_id, ticket_no "
                "FROM Document_Ticket WHERE doc_id='1'").fetchone(),
            ("2026-07-20", "2026-07-20", "P002", "P002", "D4RD19999"))
        # 新增與修改都不寫稽核（只有刪除寫）
        actions = [r[0] for r in self.conn.execute(
            "SELECT action FROM Audit_Log ORDER BY log_id")]
        self.assertEqual(actions, [])

    def test_update_requires_load_time_snapshot(self):
        """漏傳開窗快照直接 TypeError——不可在儲存時重查（重查等於沒有鎖）。"""
        with self.assertRaises(TypeError):
            updateTicket(
                self.conn, doc_id="1", issuer_id="P002",
                ticket_no="D4RD19999", role="user")

    def test_update_rejects_duplicate_and_unknown_issuer(self):
        createTicket(
            self.conn, issuer_id="P001", ticket_no="D4RD15264",
            self_service=True, sender_id=None,
            create_date="2026-07-21", role="user")
        with self.assertRaises(TicketDuplicateError):
            updateTicket(self.conn, doc_id="1", issuer_id="P001",
                         ticket_no="d4rd15264", role="user",
                         last_modified=self._lastModified())
        with self.assertRaises(TicketValidationError):
            updateTicket(self.conn, doc_id="1", issuer_id="P999",
                         ticket_no="D4RD15263", role="user",
                         last_modified=self._lastModified())

    def test_update_same_number_is_allowed(self):
        updateTicket(self.conn, doc_id="1", issuer_id="P001",
                     ticket_no="d4rd15263", role="user",
                     last_modified=self._lastModified())
        self.assertEqual(
            self.conn.execute(
                "SELECT ticket_no FROM Document_Ticket WHERE doc_id='1'"
            ).fetchone()[0], "D4RD15263")

    def test_update_missing_or_deleted_raises_not_found(self):
        snapshot = self._lastModified()
        with self.assertRaises(TicketNotFoundError):
            updateTicket(self.conn, doc_id="99", issuer_id="P001",
                         ticket_no="MISSING99", role="user",
                         last_modified=snapshot)
        deleteTicket(self.conn, doc_id="1", role="user")
        with self.assertRaises(TicketNotFoundError):
            updateTicket(self.conn, doc_id="1", issuer_id="P001",
                         ticket_no="D4RD15263", role="user",
                         last_modified=snapshot)

    def test_update_preserves_other_computer_change(self):
        """他機改過這筆 → 快照對不上 → 整筆擋下，不覆蓋對方的值。"""
        snapshot = self._lastModified()
        self.conn.execute(
            "UPDATE Document_Ticket SET issuer_id='P002',ticket_no='REMOTE99' "
            "WHERE doc_id='1'")
        self._touch()
        self.conn.commit()

        with self.assertRaises(LookupError) as ctx:
            updateTicket(
                self.conn, doc_id="1", issuer_id="P001", ticket_no="LOCAL88",
                role="user", last_modified=snapshot)

        self.assertIn("其他電腦修改", str(ctx.exception))
        self.assertEqual(
            self.conn.execute(
                "SELECT issuer_id,ticket_no FROM Document_Ticket WHERE doc_id='1'"
            ).fetchone(),
            ("P002", "REMOTE99"))

    def test_update_reports_deleted_separately(self):
        """被刪與被改要分開報：前者收掉視窗，後者留著讓使用者重開。"""
        snapshot = self._lastModified()
        deleteTicket(self.conn, doc_id="1", role="user")
        self.conn.commit()

        with self.assertRaises(TicketNotFoundError) as ctx:
            updateTicket(
                self.conn, doc_id="1", issuer_id="P001", ticket_no="LOCAL88",
                role="user", last_modified=snapshot)

        self.assertIn("刪除", str(ctx.exception))

    def test_update_blocked_by_any_column_change(self):
        """任一欄被他機動過都擋得下——`last_modified` 涵蓋整列。

        ⚠️ 舊做法是逐一比對五個業務欄位，改不到的欄位（例如只動
        `last_modified` 本身）就漏掉；這裡改為驗「動哪一欄都擋」。
        """
        for column, remote_value in (
                ("create_date", "2026-07-21"),
                ("register_date", "2026-07-21"),
                ("sender_id", "P001"),
                ("issuer_id", "P002"),
                ("ticket_no", "REMOTE99"),
        ):
            with self.subTest(column=column):
                self.conn.execute(
                    "UPDATE Document_Ticket SET create_date='2026-07-20',"
                    "register_date='2026-07-20',sender_id='P002',"
                    "issuer_id='P001',ticket_no='D4RD15263' WHERE doc_id='1'")
                self._touch(last_modified="2026-08-07 09:00:00")
                self.conn.commit()
                snapshot = self._lastModified()

                self.conn.execute(
                    f"UPDATE Document_Ticket SET {column}=? WHERE doc_id='1'",
                    (remote_value,))
                self._touch(last_modified="2026-08-07 09:00:30")
                self.conn.commit()

                with self.assertRaises(TicketConflictError):
                    updateTicket(
                        self.conn, doc_id="1", issuer_id="P002",
                        ticket_no="LOCAL88", role="user",
                        last_modified=snapshot)
                self.conn.rollback()

                self.assertEqual(
                    self.conn.execute(
                        f"SELECT {column} FROM Document_Ticket WHERE doc_id='1'"
                    ).fetchone()[0],
                    remote_value)

    def test_update_blocked_when_values_were_changed_back(self):
        """⚠️ 換成 `last_modified` 才擋得住：他機把值改成 B 又改回 A。

        舊的五欄比對只看「值一不一樣」，改回來就形同沒改過、照樣放行。
        """
        self._touch(last_modified="2026-08-07 09:00:00")
        self.conn.commit()
        snapshot = self._lastModified()

        self.conn.execute(
            "UPDATE Document_Ticket SET ticket_no='REMOTE99' WHERE doc_id='1'")
        self.conn.execute(
            "UPDATE Document_Ticket SET ticket_no='D4RD15263' WHERE doc_id='1'")
        self._touch(last_modified="2026-08-07 09:00:30")
        self.conn.commit()

        with self.assertRaises(TicketConflictError):
            updateTicket(
                self.conn, doc_id="1", issuer_id="P002", ticket_no="LOCAL88",
                role="user", last_modified=snapshot)


class TestTicketUpdateFromBrowse(TicketDbTestCase):
    def setUp(self):
        super().setUp()
        self._insert_person("P001", "王小明")
        self._insert_person("P002", "李大華")
        createTicket(
            self.conn, issuer_id="P001", ticket_no="D4RD15263",
            self_service=True, sender_id=None,
            create_date="2026-07-20", role="admin")

    def test_browse_update_can_issue_a_pending_ticket(self):
        updateTicketFromBrowse(
            self.conn, doc_id="1", create_date="2026-07-20",
            register_date="2026-07-22", sender_id="P002",
            issuer_id="P002", ticket_no=" d4rd15263 ", role="admin",
            last_modified=self._lastModified())
        self.assertEqual(
            self.conn.execute(
                "SELECT create_date, register_date, sender_id, issuer_id, ticket_no "
                "FROM Document_Ticket WHERE doc_id='1'").fetchone(),
            ("2026-07-20", "2026-07-22", "P002", "P002", "D4RD15263"))

    def test_browse_update_requires_load_time_snapshot(self):
        with self.assertRaises(TypeError):
            updateTicketFromBrowse(
                self.conn, doc_id="1", create_date="2026-07-20",
                register_date="", sender_id=None,
                issuer_id="P001", ticket_no="D4RD15263", role="admin")

    def test_browse_update_keeps_pending_sentinel(self):
        updateTicketFromBrowse(
            self.conn, doc_id="1", create_date="2026-07-20",
            register_date="", sender_id=None,
            issuer_id="P001", ticket_no="D4RD15263", role="admin",
            last_modified=self._lastModified())
        self.assertEqual(
            self.conn.execute(
                "SELECT register_date, sender_id FROM Document_Ticket "
                "WHERE doc_id='1'").fetchone(),
            ("", None))

    def test_browse_update_rejects_null_register_date(self):
        # NULL 是刪除狀態，不得經由編輯寫入。
        with self.assertRaises(TicketValidationError) as ctx:
            updateTicketFromBrowse(
                self.conn, doc_id="1", create_date="2026-07-20",
                register_date=None, sender_id=None,
                issuer_id="P001", ticket_no="D4RD15263", role="admin",
                last_modified=self._lastModified())
        # 使用者可見訊息不得外露內部哨兵語彙。
        self.assertNotIn("NULL", str(ctx.exception).upper())

    def test_browse_update_requires_sender_when_issued(self):
        # 有發文日期就必然有發文者，缺發文者必須被擋下且不得寫入。
        for missing in (None, "", "   "):
            with self.subTest(sender_id=missing):
                with self.assertRaises(TicketValidationError) as ctx:
                    updateTicketFromBrowse(
                        self.conn, doc_id="1", create_date="2026-07-20",
                        register_date="2026-07-25", sender_id=missing,
                        issuer_id="P001", ticket_no="D4RD15263", role="admin",
                        last_modified=self._lastModified())
                message = str(ctx.exception)
                for leak in ("SQL", "Document_Ticket", "CHECK", "constraint",
                             "sender_id", "NULL"):
                    self.assertNotIn(leak, message)
        self.assertEqual(
            self.conn.execute(
                "SELECT register_date, sender_id FROM Document_Ticket "
                "WHERE doc_id='1'").fetchone(),
            ("", None))

    def test_browse_update_allows_no_sender_when_pending(self):
        updateTicketFromBrowse(
            self.conn, doc_id="1", create_date="2026-07-20",
            register_date="", sender_id="   ",
            issuer_id="P001", ticket_no="D4RD15263", role="admin",
            last_modified=self._lastModified())
        self.assertEqual(
            self.conn.execute(
                "SELECT register_date, sender_id FROM Document_Ticket "
                "WHERE doc_id='1'").fetchone(),
            ("", None))

    def test_browse_update_validates_dependencies(self):
        with self.assertRaises(TicketValidationError):
            updateTicketFromBrowse(
                self.conn, doc_id="1", create_date="",
                register_date="", sender_id=None,
                issuer_id="P001", ticket_no="D4RD15263", role="admin",
                last_modified=self._lastModified())
        with self.assertRaises(TicketValidationError):
            updateTicketFromBrowse(
                self.conn, doc_id="1", create_date="2026-07-20",
                register_date="", sender_id="P999",
                issuer_id="P001", ticket_no="D4RD15263", role="admin",
                last_modified=self._lastModified())
        with self.assertRaises(TicketNotFoundError):
            updateTicketFromBrowse(
                self.conn, doc_id="99", create_date="2026-07-20",
                register_date="", sender_id=None,
                issuer_id="P001", ticket_no="D4RD19999", role="admin",
                last_modified=self._lastModified())

    def test_browse_preserves_other_computer_change(self):
        snapshot = self._lastModified()
        self.conn.execute(
            "UPDATE Document_Ticket SET create_date='2026-07-21',"
            "issuer_id='P002',ticket_no='REMOTE99' WHERE doc_id='1'")
        self._touch()
        self.conn.commit()

        with self.assertRaises(LookupError) as ctx:
            updateTicketFromBrowse(
                self.conn, doc_id="1", create_date="2026-07-22",
                register_date="2026-07-22", sender_id="P002",
                issuer_id="P001", ticket_no="LOCAL88", role="admin",
                last_modified=snapshot)

        self.assertIn("其他電腦修改", str(ctx.exception))
        self.assertEqual(
            self.conn.execute(
                "SELECT create_date,register_date,sender_id,issuer_id,ticket_no "
                "FROM Document_Ticket WHERE doc_id='1'"
            ).fetchone(),
            ("2026-07-21", "", None, "P002", "REMOTE99"))

    def test_browse_reports_deleted_separately(self):
        snapshot = self._lastModified()
        deleteTicket(self.conn, doc_id="1", role="admin")
        self.conn.commit()

        with self.assertRaises(TicketNotFoundError) as ctx:
            updateTicketFromBrowse(
                self.conn, doc_id="1", create_date="2026-07-22",
                register_date="", sender_id=None,
                issuer_id="P001", ticket_no="LOCAL88", role="admin",
                last_modified=snapshot)

        self.assertIn("刪除", str(ctx.exception))

    def test_browse_blocked_by_any_column_change(self):
        for column, remote_value in (
                ("create_date", "2026-07-21"),
                ("register_date", "2026-07-21"),
                ("sender_id", "P001"),
                ("issuer_id", "P002"),
                ("ticket_no", "REMOTE99"),
        ):
            with self.subTest(column=column):
                self.conn.execute(
                    "UPDATE Document_Ticket SET create_date='2026-07-20',"
                    "register_date='2026-07-20',sender_id='P002',"
                    "issuer_id='P001',ticket_no='D4RD15263' WHERE doc_id='1'")
                self._touch(last_modified="2026-08-07 09:00:00")
                self.conn.commit()
                snapshot = self._lastModified()

                self.conn.execute(
                    f"UPDATE Document_Ticket SET {column}=? WHERE doc_id='1'",
                    (remote_value,))
                self._touch(last_modified="2026-08-07 09:00:30")
                self.conn.commit()

                with self.assertRaises(TicketConflictError):
                    updateTicketFromBrowse(
                        self.conn, doc_id="1", create_date="2026-07-22",
                        register_date="2026-07-22", sender_id="P002",
                        issuer_id="P001", ticket_no="LOCAL88", role="admin",
                        last_modified=snapshot)
                self.conn.rollback()

                self.assertEqual(
                    self.conn.execute(
                        f"SELECT {column} FROM Document_Ticket WHERE doc_id='1'"
                    ).fetchone()[0],
                    remote_value)


class TestIntegrityErrorIsNotAlwaysDuplicate(TicketDbTestCase):
    """FK／其他 IntegrityError 不得被誤報成「罰單編號重複」。

    正常流程有 `_requirePerson()` 擋在前面，只有「檢查通過後人員才被移除」的
    併發情境會讓 FK 違規真的打到 SQL 層；以 patch 略過前置檢查來重現該情境。
    """

    def setUp(self):
        super().setUp()
        self._insert_person("P001", "王小明")

    @staticmethod
    def _passthrough(conn, staff_id, label):
        return (staff_id or "").strip() or None

    def test_create_fk_violation_is_not_reported_as_duplicate(self):
        with mock.patch.object(ticket_utils, "_requirePerson",
                               self._passthrough):
            with self.assertRaises(sqlite3.IntegrityError) as ctx:
                createTicket(
                    self.conn, issuer_id="P999", ticket_no="D4RD15263",
                    self_service=True, sender_id=None,
                    create_date="2026-07-23", role="user")
        self.assertNotIsInstance(ctx.exception, TicketDuplicateError)
        self.assertIn("FOREIGN KEY", str(ctx.exception))

    def test_update_fk_violation_is_not_reported_as_duplicate(self):
        createTicket(
            self.conn, issuer_id="P001", ticket_no="D4RD15263",
            self_service=True, sender_id=None,
            create_date="2026-07-23", role="user")
        with mock.patch.object(ticket_utils, "_requirePerson",
                               self._passthrough):
            with self.assertRaises(sqlite3.IntegrityError) as ctx:
                updateTicket(self.conn, doc_id="1", issuer_id="P999",
                             ticket_no="D4RD15263", role="user",
                             last_modified=self._lastModified())
        self.assertNotIsInstance(ctx.exception, TicketDuplicateError)
        self.assertIn("FOREIGN KEY", str(ctx.exception))

    def test_browse_update_fk_violation_is_not_reported_as_duplicate(self):
        createTicket(
            self.conn, issuer_id="P001", ticket_no="D4RD15263",
            self_service=True, sender_id=None,
            create_date="2026-07-23", role="user")
        with mock.patch.object(ticket_utils, "_requirePerson",
                               self._passthrough):
            with self.assertRaises(sqlite3.IntegrityError) as ctx:
                updateTicketFromBrowse(
                    self.conn, doc_id="1", create_date="2026-07-20",
                    register_date="2026-07-22", sender_id="P999",
                    issuer_id="P001", ticket_no="D4RD15263", role="admin",
                    last_modified=self._lastModified())
        self.assertNotIsInstance(ctx.exception, TicketDuplicateError)
        self.assertIn("FOREIGN KEY", str(ctx.exception))

    def test_real_unique_violation_from_sql_layer_is_still_duplicate(self):
        # 唯一性違規（模擬併發搶登錄：略過前置的 ticketExists 檢查）仍須轉譯。
        createTicket(
            self.conn, issuer_id="P001", ticket_no="D4RD15263",
            self_service=True, sender_id=None,
            create_date="2026-07-23", role="user")
        with mock.patch.object(ticket_utils, "_requireUnique",
                               lambda *a, **k: None):
            with self.assertRaises(TicketDuplicateError):
                createTicket(
                    self.conn, issuer_id="P001", ticket_no="D4RD15263",
                    self_service=True, sender_id=None,
                    create_date="2026-07-23", role="user")

    def test_doc_id_collision_is_not_reported_as_duplicate_number(self):
        # SQLite 把主鍵衝突也寫成 "UNIQUE constraint failed: ...doc_id"，
        # 若靠訊息字串判別，流水號失準（還原舊備份／手改 DB）配到已存在的
        # doc_id 時，會把全新的罰單編號誤報成「編號重複」。
        createTicket(
            self.conn, issuer_id="P001", ticket_no="D4RD15263",
            self_service=True, sender_id=None,
            create_date="2026-07-23", role="user")
        # 讓流水號倒退，下一次配號必然撞上已存在的 doc_id='1'。
        self.conn.execute(
            "UPDATE Seq_DocId SET last_id=0 WHERE table_name='Document_Ticket'")
        with self.assertRaises(sqlite3.IntegrityError) as ctx:
            createTicket(
                self.conn, issuer_id="P001", ticket_no="ZZ99",
                self_service=True, sender_id=None,
                create_date="2026-07-23", role="user")
        self.assertNotIsInstance(ctx.exception, TicketDuplicateError)


class TestTicketDelete(TicketDbTestCase):
    def setUp(self):
        super().setUp()
        self._insert_person("P001", "王小明")
        createTicket(
            self.conn, issuer_id="P001", ticket_no="D4RD15263",
            self_service=True, sender_id=None,
            create_date="2026-07-20", role="user")

    def test_delete_clears_columns_and_keeps_shell(self):
        deleteTicket(self.conn, doc_id="1", role="user")
        self.assertEqual(
            self.conn.execute(
                "SELECT create_date, register_date, sender_id, issuer_id, ticket_no "
                "FROM Document_Ticket WHERE doc_id='1'").fetchone(),
            (None, None, None, None, None))
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM Document_Ticket").fetchone()[0], 1)

    def test_delete_does_not_write_trash(self):
        deleteTicket(self.conn, doc_id="1", role="user")
        self.assertEqual(
            self.conn.execute(
                "SELECT COUNT(*) FROM Trash_Documents").fetchone()[0], 0)

    def test_delete_writes_audit(self):
        deleteTicket(self.conn, doc_id="1", role="user")
        row = self.conn.execute(
            "SELECT action, target_id, detail FROM Audit_Log "
            "ORDER BY log_id DESC").fetchone()
        self.assertEqual(row[0], "DELETE")
        self.assertEqual(row[1], "1")
        self.assertIn("[罰單][刪除]", row[2])
        self.assertIn("D4RD15263", row[2])

    def test_delete_twice_raises_not_found(self):
        deleteTicket(self.conn, doc_id="1", role="user")
        with self.assertRaises(TicketNotFoundError):
            deleteTicket(self.conn, doc_id="1", role="user")
        with self.assertRaises(TicketNotFoundError):
            deleteTicket(self.conn, doc_id="99", role="user")


class TestTicketAfterYearEndReset(TicketDbTestCase):
    """罰單編號唯一性只限目前年度 DB：重置後新年度可重用舊年度編號。"""

    @staticmethod
    def _first_active_person_id(conn):
        return conn.execute(
            "SELECT staff_id FROM Ref_Personnel WHERE is_active=1 "
            "ORDER BY sort_order, staff_id").fetchone()[0]

    def test_reset_preview_counts_only_active_ticket_rows(self):
        from tabs.tab_settings import _resetDocCounts, _resetSummary
        self._insert_person("P001", "王小明")
        self.conn.execute(
            "INSERT INTO Document_Ticket"
            "(doc_id,create_date,register_date,sender_id,issuer_id,ticket_no) "
            "VALUES('1','2026-07-23','',NULL,'P001','D4RD15263')")
        self.conn.execute("INSERT INTO Document_Ticket(doc_id) VALUES('2')")
        counts = _resetDocCounts(self.conn)
        self.assertEqual(counts["ticket"], 1)   # 軟刪除空殼不計入
        self.assertIn("罰單 1 筆", _resetSummary(counts))

    def test_ticket_number_can_be_reused_after_year_end_reset(self):
        from lib.db_utils import getConn, performYearEndReset
        self._insert_person("P001", "王小明")
        self.conn.execute(
            "INSERT INTO Document_Ticket"
            "(doc_id,create_date,register_date,sender_id,issuer_id,ticket_no) "
            "VALUES('1','2026-07-23','',NULL,'P001','D4RD15263')")
        self.conn.commit()
        performYearEndReset(self.db_path)
        conn = getConn(self.db_path)
        try:
            doc_id = createTicket(
                conn,
                issuer_id=self._first_active_person_id(conn),
                ticket_no="D4RD15263",
                self_service=True,
                sender_id=None,
                create_date="2027-01-01",
                role="admin",
            )
            conn.commit()
            self.assertEqual(doc_id, "1")   # Seq_DocId 已歸零，重新從 1 配號
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
