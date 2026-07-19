# -*- coding: utf-8 -*-
"""主要對話框建構 smoke test（offscreen，不開視窗、不呼叫 exec）。

保護對象：對話框建構路徑（載欄位、查 DB、預填）改壞時，跑測試即炸，
不用等上機。只驗「建得起來＋預填正確」；點擊互動、completer 行為仍須上機。
"""
import os
import sqlite3
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
import res.resources_rc
_app = QApplication.instance() or QApplication([])

from lib.db_schema import applySchema


def _make_db_file():
    """實體暫存 DB：正式 schema ＋ 最小參照資料 ＋ 三主表各一筆。

    人名一律虛構（push 前有 test_no_pii 掃真名，禁用真實人名）。
    """
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    conn = sqlite3.connect(path)
    applySchema(conn)        # 正式 DDL（三主表＋參照表＋trigger＋Seq_DocId）
    conn.executescript("""
        INSERT INTO Ref_Personnel(staff_id,staff_name,is_active,sort_order)
            VALUES('P01','王小明',1,1),('P02','陳志豪',1,2);
        UPDATE Ref_Personnel SET alias='小明' WHERE staff_id='P01';
        INSERT INTO Ref_Departments(dept_id,dept_name,is_active,sort_order)
            VALUES('D01','偵查隊',1,1);
        INSERT INTO Ref_CaseTypes(case_type_id,case_type_name,is_active,sort_order)
            VALUES('CT01','竊盜案',1,1);
        INSERT INTO Ref_Case_Status(status_id,status_name) VALUES('CS01','現行');
        INSERT INTO Ref_General_Category(gen_cat_id,gen_cat_name) VALUES('GC01','業務');
        INSERT INTO Seq_DocId(table_name,last_id) VALUES
            ('Document_Task',10),('Document_Criminal',5),('Document_General',20);
        INSERT INTO Document_Task(doc_id,receive_date,receive_id,subject,processor_id)
            VALUES('1','2026-07-01','P01','交辦主旨','P02');
        INSERT INTO Document_Criminal(doc_id,report_date,sender_id,case_type,
            case_status,processor_id,subject_summary,occurrence_date,
            is_reported,is_electronic)
            VALUES('2','2026-07-01','P01','CT01','CS01','P02','刑案主旨',
                   '2026-06-01',0,'');
        INSERT INTO Document_General(doc_id,report_date,sender_id,dept_id,
            gen_cat_id,subject,processor_id,is_reported,is_electronic)
            VALUES('3','2026-07-01','P01','D01','GC01','一般主旨','P02',0,'');
        INSERT INTO Document_Reward(doc_id,register_date,reason,recipients)
            VALUES('4','2026-07-17','協助查緝','王小明, 名單外甲');
    """)
    conn.commit()
    conn.close()
    return path


class _DialogBase(unittest.TestCase):
    def setUp(self):
        self.db = _make_db_file()

    def tearDown(self):
        try:
            os.remove(self.db)
        except OSError:
            pass


class TestRefItemDialog(_DialogBase):
    def test_add_mode_three_configs(self):
        from ui_utils.settings_dialogs import (
            RefItemDialog, REF_PERSONNEL, REF_DEPT, REF_CASETYPE)
        for cfg in (REF_PERSONNEL, REF_DEPT, REF_CASETYPE):
            with self.subTest(category=cfg["category"]):
                dlg = RefItemDialog(cfg, self.db)
                self.assertEqual(dlg.w_name.text(), "")   # 新增模式空欄
                dlg.deleteLater()

    def test_edit_mode_prefills_name(self):
        from ui_utils.settings_dialogs import RefItemDialog, REF_PERSONNEL
        dlg = RefItemDialog(REF_PERSONNEL, self.db,
                            existing=("P01", 1, "王小明", 1))
        self.assertEqual(dlg.w_name.text(), "王小明")
        dlg.deleteLater()


class TestEditDialogs(_DialogBase):
    def test_task_edit_prefills_subject(self):
        from ui_utils.edit_dialog import TaskEditDialog
        dlg = TaskEditDialog(self.db, "1")
        self.assertEqual(dlg.w_subject.text(), "交辦主旨")
        dlg.deleteLater()

    def test_task_edit_restricted_builds(self):
        from ui_utils.edit_dialog import TaskEditDialog
        dlg = TaskEditDialog(self.db, "1", restricted=True)
        self.assertEqual(dlg.w_subject.text(), "交辦主旨")
        dlg.deleteLater()

    def test_criminal_edit_prefills_subject(self):
        from ui_utils.edit_dialog import CriminalEditDialog
        dlg = CriminalEditDialog(self.db, "2")
        self.assertEqual(dlg.w_subject.text(), "刑案主旨")
        dlg.deleteLater()

    def test_general_edit_prefills_subject(self):
        from ui_utils.edit_dialog import GeneralEditDialog
        dlg = GeneralEditDialog(self.db, "3")
        self.assertEqual(dlg.w_subject.text(), "一般主旨")
        dlg.deleteLater()

    def test_reward_edit_builds_for_entry_and_browse(self):
        from ui_utils.reward_dialog import RewardEditDialog
        from ui_utils.edit_dialog import _BaseEditDialog
        # 寬度沿用 _BaseEditDialog 版面常數，與交辦／刑案／一般三彈窗一致
        expected_w = (_BaseEditDialog._LABEL_W + _BaseEditDialog._FIELD_W
                      + _BaseEditDialog._MARGIN)
        for source in ("entry", "browse"):
            with self.subTest(source=source):
                dlg = RewardEditDialog(self.db, "4", source=source)
                self.assertEqual(dlg.minimumWidth(), expected_w)
                self.assertEqual(dlg.w_reason.text(), "協助查緝")
                self.assertEqual(dlg.w_recipients.currentText(), "王小明, 名單外甲")
                self.assertFalse(dlg.btn_save.isDefault())
                self.assertFalse(dlg.btn_save.autoDefault())
                dlg.deleteLater()

    def test_reward_edit_passes_personnel_aliases_to_recipient_controller(self):
        from PySide6.QtCore import Qt, QModelIndex
        from ui_utils.reward_dialog import RewardEditDialog
        dlg = RewardEditDialog(self.db, "4", source="entry")
        # 敘獎人員改為可編輯 QComboBox：controller 掛在其 lineEdit 上
        line = dlg.w_recipients.lineEdit()
        controller = line._recipient_controller
        roles = [controller.model.item(i).data(Qt.UserRole)
                 for i in range(controller.model.rowCount())]
        labels = [controller.model.item(i).text()
                  for i in range(controller.model.rowCount())]
        self.assertIn("小明 → 王小明", labels)
        self.assertEqual(roles[labels.index("小明 → 王小明")], "王小明")
        line.setText("名單外甲, 小明")
        line.setCursorPosition(len(line.text()))
        controller.completer.activated[QModelIndex].emit(
            controller.model.index(labels.index("小明 → 王小明"), 0))
        _app.processEvents()
        self.assertEqual(dlg.w_recipients.currentText(), "名單外甲, 王小明")
        dlg.deleteLater()

    def test_reward_edit_supports_legacy_personnel_table_without_alias(self):
        conn = sqlite3.connect(self.db)
        conn.execute("ALTER TABLE Ref_Personnel DROP COLUMN alias")
        conn.commit()
        conn.close()
        from ui_utils.reward_dialog import RewardEditDialog
        dlg = RewardEditDialog(self.db, "4", source="entry")
        self.assertEqual(dlg.w_reason.text(), "協助查緝")
        dlg.deleteLater()

    def test_reward_edit_open_on_deleted_row_does_not_raise_and_exec_cancels(self):
        """併發刪除：開啟時該列已軟刪除 → 不 raise，exec 彈提示並視同取消。"""
        from unittest.mock import patch
        from PySide6.QtWidgets import QDialog
        from ui_utils.reward_dialog import RewardEditDialog
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE Document_Reward SET register_date=NULL WHERE doc_id='4'")
        conn.commit()
        conn.close()
        # 建構不得 raise（舊版 _load_data 查無列會 raise ValueError）
        dlg = RewardEditDialog(self.db, "4", source="entry")
        self.assertTrue(dlg._row_missing)
        with patch("ui_utils.reward_dialog.msgWarning") as warn:
            self.assertEqual(dlg.exec(), QDialog.Rejected)
            warn.assert_called_once()
        self.assertIsNone(dlg.get_updated())
        dlg.deleteLater()

    def test_reward_edit_save_on_concurrently_deleted_row_is_not_false_success(self):
        """併發刪除：儲存時 0 列受影響 → 彈提示、不 accept、不回傳更新值。"""
        from unittest.mock import patch
        from ui_utils.reward_dialog import RewardEditDialog
        dlg = RewardEditDialog(self.db, "4", source="entry")
        # 開啟後、儲存前，另一端把該列軟刪除
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE Document_Reward SET register_date=NULL WHERE doc_id='4'")
        conn.commit()
        conn.close()
        dlg.w_reason.setText("改後事由")
        # 已發文列（有日期）儲存需發文人員，先選好才走得到併發刪除的 UPDATE
        dlg.w_sender.setCurrentIndex(dlg.w_sender.findData("P01"))
        with patch("ui_utils.reward_dialog.msgWarning") as warn:
            dlg._on_save()
            warn.assert_called_once()
        self.assertIsNone(dlg.get_updated())
        self.assertTrue(dlg._row_missing)
        from PySide6.QtWidgets import QDialog
        self.assertNotEqual(dlg.result(), QDialog.Accepted)
        dlg.deleteLater()


class TestReportDateNullable(_DialogBase):
    """刑案／一般編輯彈窗陳報日期改用 NullableDateEdit 的 round-trip。

    未發文 ⟺ report_date NULL 且 sender_id NULL；填日期＝發文、發文人員必填。
    offscreen 下任何會彈 QMessageBox 的路徑都必須 patch，否則測試永久卡死。
    """

    def _insert_unissued(self, conn, kind):
        if kind == "crim":
            conn.execute(
                "INSERT INTO Document_Criminal(doc_id,report_date,sender_id,"
                "case_type,case_status,processor_id,subject_summary,"
                "occurrence_date,is_reported,is_electronic) "
                "VALUES('6',NULL,NULL,'CT01','CS01','P02','未發文刑案',"
                "'2026-06-01',0,'')")
        else:
            conn.execute(
                "INSERT INTO Document_General(doc_id,report_date,sender_id,"
                "dept_id,gen_cat_id,subject,processor_id,is_reported,is_electronic) "
                "VALUES('7',NULL,NULL,'D01','GC01','未發文一般','P02',0,'')")
        conn.commit()

    def _open_criminal(self, doc_id):
        from ui_utils.edit_dialog import CriminalEditDialog
        return CriminalEditDialog(self.db, doc_id)

    def _open_general(self, doc_id):
        from ui_utils.edit_dialog import GeneralEditDialog
        return GeneralEditDialog(self.db, doc_id)

    def _select_sender(self, dlg, staff_id):
        dlg.w_sender.setCurrentIndex(dlg.w_sender.findData(staff_id))

    # ── 未發文列開啟：日期空白、發文人員空白 ──────────────────
    def test_unissued_opens_blank(self):
        conn = sqlite3.connect(self.db)
        self._insert_unissued(conn, "crim")
        conn.close()
        dlg = self._open_criminal("6")
        self.assertTrue(dlg.w_report_date.isBlank())
        self.assertIsNone(dlg.w_sender.currentData())
        dlg.deleteLater()

    # ── 未發文列留空存回 → report_date NULL 且 sender NULL ───
    def test_unissued_save_blank_keeps_null(self):
        conn = sqlite3.connect(self.db)
        self._insert_unissued(conn, "crim")
        conn.close()
        dlg = self._open_criminal("6")
        dlg._on_save()   # 不填日期直接存
        conn = sqlite3.connect(self.db)
        row = conn.execute("SELECT report_date,sender_id FROM Document_Criminal "
                           "WHERE doc_id='6'").fetchone()
        conn.close()
        self.assertIsNone(row[0])
        self.assertIsNone(row[1])
        from PySide6.QtWidgets import QDialog
        self.assertEqual(dlg.result(), QDialog.Accepted)
        dlg.deleteLater()

    # ── 未發文列填日期＋發文人員 → 補發（寫入日期與 sender）──
    def test_unissued_fill_date_and_sender_issues(self):
        from PySide6.QtCore import QDate
        conn = sqlite3.connect(self.db)
        self._insert_unissued(conn, "crim")
        conn.close()
        dlg = self._open_criminal("6")
        dlg.w_report_date.setDate(QDate(2026, 7, 20))
        self._select_sender(dlg, "P01")
        dlg._on_save()
        conn = sqlite3.connect(self.db)
        row = conn.execute("SELECT report_date,sender_id FROM Document_Criminal "
                           "WHERE doc_id='6'").fetchone()
        conn.close()
        self.assertEqual(row[0], "2026-07-20")
        self.assertEqual(row[1], "P01")
        dlg.deleteLater()

    # ── 已發文列清空日期 → 退回未發文（NULL＋NULL）─────────
    def test_issued_clear_reverts_to_null(self):
        # fixture doc '2' 已發文（report_date 2026-07-01, sender P01）
        dlg = self._open_criminal("2")
        self.assertFalse(dlg.w_report_date.isBlank())
        dlg.w_report_date.clear()
        dlg._on_save()
        conn = sqlite3.connect(self.db)
        row = conn.execute("SELECT report_date,sender_id FROM Document_Criminal "
                           "WHERE doc_id='2'").fetchone()
        conn.close()
        self.assertIsNone(row[0])
        self.assertIsNone(row[1])
        dlg.deleteLater()

    # ── 填日期但缺發文人員 → 必填擋下、不 accept ───────────
    def test_issued_missing_sender_blocked(self):
        from unittest.mock import patch
        from PySide6.QtCore import QDate
        from PySide6.QtWidgets import QDialog
        conn = sqlite3.connect(self.db)
        self._insert_unissued(conn, "crim")
        conn.close()
        dlg = self._open_criminal("6")
        dlg.w_report_date.setDate(QDate(2026, 7, 20))
        dlg.w_sender.setCurrentIndex(0)   # 空白項＝未選發文人員
        with patch("ui_utils.ui_common.msgWarning") as warn:
            dlg._on_save()
            warn.assert_called_once()
        conn = sqlite3.connect(self.db)
        row = conn.execute("SELECT report_date,sender_id FROM Document_Criminal "
                           "WHERE doc_id='6'").fetchone()
        conn.close()
        self.assertIsNone(row[0])   # 被擋下 → DB 未變
        self.assertNotEqual(dlg.result(), QDialog.Accepted)
        dlg.deleteLater()

    # ── 非法日期格式擋下 ─────────────────────────────────────
    def test_invalid_date_blocked(self):
        from unittest.mock import patch
        from PySide6.QtWidgets import QDialog
        conn = sqlite3.connect(self.db)
        self._insert_unissued(conn, "crim")
        conn.close()
        dlg = self._open_criminal("6")
        dlg.w_report_date.setText("2026-13-99")
        with patch("ui_utils.ui_common.msgWarning") as warn:
            dlg._on_save()
            warn.assert_called_once()
        self.assertNotEqual(dlg.result(), QDialog.Accepted)
        dlg.deleteLater()

    # ── 一般彈窗同款 round-trip（挑核心兩情境）──────────────
    def test_general_unissued_blank_and_issue(self):
        from PySide6.QtCore import QDate
        conn = sqlite3.connect(self.db)
        self._insert_unissued(conn, "gen")
        conn.close()
        dlg = self._open_general("7")
        self.assertTrue(dlg.w_report_date.isBlank())
        self.assertIsNone(dlg.w_sender.currentData())
        # 留空存 → NULL＋NULL
        dlg._on_save()
        conn = sqlite3.connect(self.db)
        row = conn.execute("SELECT report_date,sender_id FROM Document_General "
                           "WHERE doc_id='7'").fetchone()
        conn.close()
        self.assertIsNone(row[0])
        self.assertIsNone(row[1])
        dlg.deleteLater()
        # 再開一次填日期＋sender 補發
        dlg2 = self._open_general("7")
        dlg2.w_report_date.setDate(QDate(2026, 7, 20))
        dlg2.w_sender.setCurrentIndex(dlg2.w_sender.findData("P01"))
        dlg2._on_save()
        conn = sqlite3.connect(self.db)
        row = conn.execute("SELECT report_date,sender_id FROM Document_General "
                           "WHERE doc_id='7'").fetchone()
        conn.close()
        self.assertEqual(row[0], "2026-07-20")
        self.assertEqual(row[1], "P01")
        dlg2.deleteLater()

    def test_general_missing_sender_blocked(self):
        from unittest.mock import patch
        from PySide6.QtCore import QDate
        from PySide6.QtWidgets import QDialog
        conn = sqlite3.connect(self.db)
        self._insert_unissued(conn, "gen")
        conn.close()
        dlg = self._open_general("7")
        dlg.w_report_date.setDate(QDate(2026, 7, 20))
        dlg.w_sender.setCurrentIndex(0)
        with patch("ui_utils.ui_common.msgWarning") as warn:
            dlg._on_save()
            warn.assert_called_once()
        self.assertNotEqual(dlg.result(), QDialog.Accepted)
        dlg.deleteLater()


class TestConvertDialog(_DialogBase):
    def test_crim_to_gen_builds(self):
        from ui_utils.convert_dialog import ConvertDialog
        dlg = ConvertDialog(self.db, "crim", "2")
        dlg.deleteLater()

    def test_gen_to_crim_builds(self):
        from ui_utils.convert_dialog import ConvertDialog
        dlg = ConvertDialog(self.db, "gen", "3")
        dlg.deleteLater()


class TestSettleDialog(_DialogBase):
    def test_builds_with_unissued_rows(self):
        # 結算對話框列的是「未發文」（report_date IS NULL）名單，
        # fixture 預設都有日期 → 先把刑案那筆改成 NULL 才有資料可列
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE Document_Criminal SET report_date=NULL, sender_id=NULL "
                     "WHERE doc_id='2'")
        conn.commit()
        conn.close()
        from ui_utils.settle_dialog import SettleDialog
        dlg = SettleDialog(self.db)
        dlg.deleteLater()

    def test_builds_with_empty_list(self):
        # 名單空也要建得起來（現場常態）
        from ui_utils.settle_dialog import SettleDialog
        dlg = SettleDialog(self.db)
        dlg.deleteLater()

    def test_builds_with_reward_unissued_row(self):
        # 敘獎未發文列（register_date='' 哨兵）也要能建起含敘獎列的結算彈窗
        conn = sqlite3.connect(self.db)
        conn.execute("INSERT INTO Document_Reward(doc_id,register_date,reason,recipients) "
                     "VALUES('5','','敘獎事由','王小明')")
        conn.commit()
        conn.close()
        from ui_utils.settle_dialog import SettleDialog
        dlg = SettleDialog(self.db)
        dlg.deleteLater()


if __name__ == "__main__":
    unittest.main()
