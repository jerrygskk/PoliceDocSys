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
            case_status,processor_id,subject_summary,is_reported,is_electronic)
            VALUES('2','2026-07-01','P01','CT01','CS01','P02','刑案主旨',0,'');
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
                self.assertEqual(dlg.w_recipients.text(), "王小明, 名單外甲")
                self.assertFalse(dlg.btn_save.isDefault())
                self.assertFalse(dlg.btn_save.autoDefault())
                dlg.deleteLater()

    def test_reward_edit_passes_personnel_aliases_to_recipient_controller(self):
        from PySide6.QtCore import Qt, QModelIndex
        from ui_utils.reward_dialog import RewardEditDialog
        dlg = RewardEditDialog(self.db, "4", source="entry")
        controller = dlg.w_recipients._recipient_controller
        roles = [controller.model.item(i).data(Qt.UserRole)
                 for i in range(controller.model.rowCount())]
        labels = [controller.model.item(i).text()
                  for i in range(controller.model.rowCount())]
        self.assertIn("小明 → 王小明", labels)
        self.assertEqual(roles[labels.index("小明 → 王小明")], "王小明")
        dlg.w_recipients.setText("名單外甲, 小明")
        dlg.w_recipients.setCursorPosition(len(dlg.w_recipients.text()))
        controller.completer.activated[QModelIndex].emit(
            controller.model.index(labels.index("小明 → 王小明"), 0))
        _app.processEvents()
        self.assertEqual(dlg.w_recipients.text(), "名單外甲, 王小明")
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
        with patch("ui_utils.reward_dialog.msgWarning") as warn:
            dlg._on_save()
            warn.assert_called_once()
        self.assertIsNone(dlg.get_updated())
        self.assertTrue(dlg._row_missing)
        from PySide6.QtWidgets import QDialog
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


if __name__ == "__main__":
    unittest.main()
