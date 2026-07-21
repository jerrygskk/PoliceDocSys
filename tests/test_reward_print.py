# -*- coding: utf-8 -*-
import os
import sqlite3
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PySide6.QtWidgets import QApplication, QLabel

from lib import db_schema, db_seed, db_utils
from tabs import tab_print
from ui_utils.settings_panels import PrintTitlePanel


class TestRewardPrint(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        fd, self.db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.conn = sqlite3.connect(self.db)
        db_schema.applySchema(self.conn)
        db_seed.seedFreshDb(self.conn)
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        os.remove(self.db)

    def test_reward_section_is_active_only_one_reason_per_row(self):
        self.conn.executemany(
            "INSERT INTO Document_Reward(doc_id,create_date,register_date,reason,recipients) "
            "VALUES(?,?,?,?,?)",
            [
                ("1", "2026-07-16", "2026-07-17", "協助查緝", "王小明、李小華"),
                ("2", None, None, None, None),
                ("3", "2026-07-17", "2026-07-18", "不同日期", "陳小美"),
            ],
        )
        self.conn.commit()

        sections = tab_print._build_sections(self.db, "2026-07-17")
        reward = next(s for s in sections if s["key"] == "reward")

        self.assertEqual(reward["scheme"], "reward")
        self.assertEqual(reward["rows"], [
            ("1", "2026/07/17", "王小明、李小華", "協助查緝", ""),
        ])
        self.assertEqual(
            [c["role"] for c in reward["columns"]],
            ["id", "date", "recipients", "subject", "signature"],
        )
        self.assertEqual(reward["columns"][1]["header"], "發文日期")

    def test_reward_columns_have_stretch_reason_and_signature_minimum(self):
        columns = tab_print.REWARD_COLUMNS
        self.assertEqual(len(columns), 5)
        reason = next(c for c in columns if c["role"] == "subject")
        signature = next(c for c in columns if c["role"] == "signature")
        self.assertTrue(reason["stretch"])
        self.assertGreaterEqual(signature["ratio"], 0.27)
        self.assertAlmostEqual(sum(c["ratio"] for c in columns), 1.0)

    def test_unissued_counter_only_includes_criminal_and_general(self):
        fake = SimpleNamespace(db_path=self.db, lbl_unissued=QLabel())
        with patch("ui_utils.settle_dialog.count_unissued",
                   return_value={"crim": 2, "gen": 3, "reward": 99}):
            tab_print.TabPrint._refresh_unissued(fake)
        self.assertEqual(fake.lbl_unissued.text(),
                         "未發文：5 筆（刑案 2／一般 3）")

    def test_settle_success_does_not_mark_reward_tab_dirty(self):
        reward_tab = SimpleNamespace(reward_data_dirty=False)
        fake = SimpleNamespace(
            db_path=self.db, tab_widget=None, date_edit=None,
            _manager=SimpleNamespace(tabs={"reward": reward_tab}),
            _refresh_unissued=Mock(), _on_generate=Mock())
        dialog = Mock()
        dialog.settled.return_value = True
        with patch("ui_utils.settle_dialog.SettleDialog", return_value=dialog):
            tab_print.TabPrint._on_settle(fake)
        self.assertFalse(reward_tab.reward_data_dirty)
        fake._on_generate.assert_called_once_with()

    def _insert_print_rows(self, *, task=True, criminal=True, general=True,
                           reward=True):
        if task:
            self.conn.execute(
                "INSERT INTO Document_Task"
                "(doc_id,receive_date,receive_id,subject,processor_id,"
                "dispatch_date,sender_id,timestamp) VALUES(?,?,?,?,?,?,?,?)",
                ("11", "2026-07-16", "P01", "交辦", "P01",
                 "2026-07-17", "P01", "2026-07-16 08:00:00"),
            )
        if criminal:
            self.conn.execute(
                "INSERT INTO Document_Criminal"
                "(doc_id,report_date,sender_id,case_type,case_status,"
                "processor_id,subject_summary) VALUES(?,?,?,?,?,?,?)",
                ("12", "2026-07-17", "P01", "CT01", "CS02", "P01", "刑案"),
            )
        if general:
            self.conn.execute(
                "INSERT INTO Document_General"
                "(doc_id,report_date,sender_id,dept_id,gen_cat_id,subject,processor_id) "
                "VALUES(?,?,?,?,?,?,?)",
                ("13", "2026-07-17", "P01", "D01", "GC01", "一般", "P01"),
            )
        if reward:
            self.conn.execute(
                "INSERT INTO Document_Reward"
                "(doc_id,create_date,register_date,reason,recipients) "
                "VALUES(?,?,?,?,?)",
                ("14", "2026-07-16", "2026-07-17", "敘獎事由", "甲、乙"),
            )
        self.conn.commit()

    def test_four_real_sections_keep_fixed_order_and_own_schemes(self):
        self._insert_print_rows()
        sections = tab_print._build_sections(self.db, "2026-07-17")
        self.assertEqual(
            [(s["key"], s["scheme"]) for s in sections],
            [("task", "task"), ("criminal", "criminal"),
             ("general", "general"), ("reward", "reward")],
        )

    def test_missing_middle_real_sections_do_not_shift_scheme(self):
        self._insert_print_rows(task=False, general=False)
        sections = tab_print._build_sections(self.db, "2026-07-17")
        self.assertEqual(
            [(s["key"], s["scheme"]) for s in sections],
            [("criminal", "criminal"), ("reward", "reward")],
        )
        self.assertEqual(
            tab_print.SCHEMES["reward"],
            ("#9B8BB8", "#C4B7D7", "#F1EDF6", "#66547F", "#2E2238"),
        )

    def test_generate_pages_only_reward_adds_duplex_blank_page(self):
        self._insert_print_rows(task=False, criminal=False, general=False)
        preview, pdf_bytes, print_pages = tab_print.generate_pages(
            self.db, "2026-07-17")
        self.assertEqual(len(preview), 2)
        self.assertEqual(len(print_pages), 2)
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

    def test_reward_title_seed_fallback_unset_and_panel_field(self):
        self.assertIn(("print_title_reward", ""), db_seed.APP_SETTINGS)
        self.assertEqual(db_utils.PRINT_TITLE_KEYS["reward"], "print_title_reward")
        self.assertEqual(
            db_utils.printTitle(self.db, "reward"),
            "○○派出所敘獎簽收表",
        )
        self.assertTrue(db_utils.printTitlesUnset(self.db))

        panel = PrintTitlePanel(self.db)
        self.assertIn("print_title_reward", panel._edits)
        panel._edits["print_title_reward"].setText("自訂敘獎簽收表")
        self.assertTrue(panel.isDirty())


if __name__ == "__main__":
    unittest.main()
