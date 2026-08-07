# -*- coding: utf-8 -*-
"""主要對話框建構 smoke test（offscreen，不開視窗、不呼叫 exec）。

保護對象：對話框建構路徑（載欄位、查 DB、預填）改壞時，跑測試即炸，
不用等上機。只驗「建得起來＋預填正確」；點擊互動、completer 行為仍須上機。
"""
import os
import sqlite3
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QDateEdit, QLabel, QTableWidget
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
        INSERT INTO Document_Criminal(doc_id,create_date,report_date,sender_id,case_type,
            case_status,processor_id,subject_summary,occurrence_date,
            is_reported,is_electronic)
            VALUES('2','2026-07-16','2026-07-01','P01','CT01','CS01','P02','刑案主旨',
                   '2026-06-01',0,'');
        INSERT INTO Document_General(doc_id,create_date,report_date,sender_id,dept_id,
            gen_cat_id,subject,processor_id,is_reported,is_electronic)
            VALUES('3','2026-07-16','2026-07-01','P01','D01','GC01','一般主旨','P02',0,'');
        INSERT INTO Document_Reward(doc_id,create_date,register_date,reason,recipients)
            VALUES('4','2026-07-16','2026-07-17','協助查緝','王小明, 名單外甲');
        INSERT INTO Document_Ticket(doc_id,create_date,register_date,sender_id,
            issuer_id,ticket_no)
            VALUES('5','2026-07-16','2026-07-17','P01','P02','D4RD15263');
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

    def test_report_page_hides_convert_button_and_archive_group(self):
        """⚠️ 陳報頁的修改視窗**不建立**類別轉換鈕與歸檔狀態區塊。

        現場回報：歸檔管理與管理者在陳報頁看得到這兩樣，但那一頁根本不能轉換
        （只能在歸檔頁或資料庫瀏覽頁做），容易誤會成自己權限不夠。
        2026-08-08 前是「建出來再反灰」，而唯一的說明掛在 tooltip 上、tooltip
        在深色模式整塊黑（QSS-7），等於沒有說明；那段 tooltip 文字也是錯的
        （結算模式下未發文的列一樣被反灰）。故改為不建立。
        """
        from PySide6.QtWidgets import QGroupBox, QPushButton
        from lib.auth_manager import AuthManager
        from ui_utils.edit_dialog import CriminalEditDialog, GeneralEditDialog
        AuthManager.instance()._role = "admin"
        self.addCleanup(lambda: setattr(AuthManager.instance(), "_role", "user"))
        for cls, doc in ((CriminalEditDialog, "2"), (GeneralEditDialog, "3")):
            with self.subTest(cls=cls.__name__):
                dlg = cls(self.db, doc, hide_manager_tools=True)
                self.addCleanup(dlg.deleteLater)
                labels = [b.text() for b in dlg.findChildren(QPushButton)]
                self.assertNotIn("⇄ 轉換類別", labels,
                                 "陳報頁不該出現類別轉換鈕")
                self.assertIsNone(dlg.w_arch_reported,
                                  "陳報頁不該建立歸檔狀態區塊")
                titles = [g.title() for g in dlg.findChildren(QGroupBox)]
                self.assertNotIn("歸檔狀態", titles)

    def test_other_pages_still_offer_convert_and_archive(self):
        """歸檔頁與資料庫瀏覽頁照常提供（它們不傳 hide_manager_tools）。

        少了這條，上面那條可能只是「管理身分根本沒建過這兩樣」而假綠。
        """
        from PySide6.QtWidgets import QGroupBox, QPushButton
        from lib.auth_manager import AuthManager
        from ui_utils.edit_dialog import CriminalEditDialog, GeneralEditDialog
        AuthManager.instance()._role = "admin"
        self.addCleanup(lambda: setattr(AuthManager.instance(), "_role", "user"))
        for cls, doc in ((CriminalEditDialog, "2"), (GeneralEditDialog, "3")):
            with self.subTest(cls=cls.__name__):
                dlg = cls(self.db, doc)
                self.addCleanup(dlg.deleteLater)
                labels = [b.text() for b in dlg.findChildren(QPushButton)]
                self.assertIn("⇄ 轉換類別", labels)
                self.assertIsNotNone(dlg.w_arch_reported)
                titles = [g.title() for g in dlg.findChildren(QGroupBox)]
                self.assertIn("歸檔狀態", titles)

    def test_report_edits_show_and_preserve_readonly_create_date(self):
        from ui_utils.edit_dialog import CriminalEditDialog, GeneralEditDialog
        for cls, doc, subject_attr, changed_subject, table in (
                (CriminalEditDialog, "2", "w_subject", "刑案主旨更新",
                 "Document_Criminal"),
                (GeneralEditDialog, "3", "w_subject", "一般主旨更新",
                 "Document_General")):
            with self.subTest(dialog=cls.__name__):
                dlg = cls(self.db, doc)
                self.assertIsInstance(dlg.w_create_date, QLabel)
                self.assertEqual(dlg.w_create_date.text(), "2026-07-16")
                getattr(dlg, subject_attr).setText(changed_subject)
                dlg._on_save()
                conn = sqlite3.connect(self.db)
                create_date = conn.execute(
                    f"SELECT create_date FROM {table} WHERE doc_id=?",
                    (doc,)).fetchone()[0]
                conn.close()
                self.assertEqual(create_date, "2026-07-16")
                dlg.deleteLater()

    def _set_self_service(self, on):
        conn = sqlite3.connect(self.db)
        for key in ("report_mode_crim", "report_mode_gen"):
            conn.execute("INSERT OR REPLACE INTO App_Settings(key,value) "
                         "VALUES(?,?)", (key, "1" if on else "0"))
        conn.commit()
        conn.close()

    def test_report_edit_locks_fields_for_regular_user_in_self_service(self):
        # 發文結算模式＋一般使用者：陳報日期／發文人員反灰（避免繞過結算）。
        from unittest.mock import patch
        from ui_utils.edit_dialog import CriminalEditDialog, GeneralEditDialog
        self._set_self_service(True)
        for cls, doc in ((CriminalEditDialog, "2"), (GeneralEditDialog, "3")):
            with self.subTest(dialog=cls.__name__):
                with patch("ui_utils.edit_dialog.AuthManager.instance") as inst:
                    inst.return_value.is_manager.return_value = False
                    dlg = cls(self.db, doc)
                self.assertFalse(dlg.w_report_date.isEnabled())
                self.assertFalse(dlg.w_sender.isEnabled())
                dlg.deleteLater()

    def test_report_edit_manager_not_locked_in_self_service(self):
        # 發文結算模式＋管理者／歸檔管理者：不擋，仍可手動補正。
        from unittest.mock import patch
        from ui_utils.edit_dialog import CriminalEditDialog, GeneralEditDialog
        self._set_self_service(True)
        for cls, doc in ((CriminalEditDialog, "2"), (GeneralEditDialog, "3")):
            with self.subTest(dialog=cls.__name__):
                with patch("ui_utils.edit_dialog.AuthManager.instance") as inst:
                    inst.return_value.is_manager.return_value = True
                    dlg = cls(self.db, doc)
                self.assertTrue(dlg.w_report_date.isEnabled())
                self.assertTrue(dlg.w_sender.isEnabled())
                dlg.deleteLater()

    def test_report_edit_fields_editable_when_not_self_service(self):
        # 非發文結算模式：任何身分皆可編輯。
        from unittest.mock import patch
        from ui_utils.edit_dialog import CriminalEditDialog, GeneralEditDialog
        self._set_self_service(False)
        for cls, doc in ((CriminalEditDialog, "2"), (GeneralEditDialog, "3")):
            with self.subTest(dialog=cls.__name__):
                with patch("ui_utils.edit_dialog.AuthManager.instance") as inst:
                    inst.return_value.is_manager.return_value = False
                    dlg = cls(self.db, doc)
                self.assertTrue(dlg.w_report_date.isEnabled())
                self.assertTrue(dlg.w_sender.isEnabled())
                dlg.deleteLater()

    def test_report_edit_self_service_locked_save_preserves_date_and_sender(self):
        # 一般使用者反灰欄位儲存時讀回原值寫回，report_date／sender 不變、其他欄照改。
        from unittest.mock import patch
        from ui_utils.edit_dialog import CriminalEditDialog
        self._set_self_service(True)
        with patch("ui_utils.edit_dialog.AuthManager.instance") as inst:
            inst.return_value.is_manager.return_value = False
            dlg = CriminalEditDialog(self.db, "2")   # 建構時套用反灰
        dlg.w_subject.setText("改後主旨")
        dlg._on_save()                                # 儲存走真實環境
        conn = sqlite3.connect(self.db)
        row = conn.execute(
            "SELECT report_date,sender_id,subject_summary "
            "FROM Document_Criminal WHERE doc_id='2'").fetchone()
        conn.close()
        self.assertEqual(row, ("2026-07-01", "P01", "改後主旨"))
        dlg.deleteLater()

    def test_general_edit_prefills_subject(self):
        from ui_utils.edit_dialog import GeneralEditDialog
        dlg = GeneralEditDialog(self.db, "3")
        self.assertEqual(dlg.w_subject.text(), "一般主旨")
        dlg.deleteLater()

    def test_reward_edit_builds_for_entry_and_browse(self):
        from PySide6.QtWidgets import QLabel
        from ui_utils.reward_dialog import RewardEditDialog
        from ui_utils.edit_dialog import _BaseEditDialog
        # 寬度沿用 _BaseEditDialog 版面常數，與交辦／刑案／一般三彈窗一致
        expected_w = (_BaseEditDialog._LABEL_W + _BaseEditDialog._FIELD_W
                      + _BaseEditDialog._MARGIN)
        for source in ("entry", "browse"):
            with self.subTest(source=source):
                dlg = RewardEditDialog(self.db, "4", source=source)
                self.assertEqual(dlg.minimumWidth(), expected_w)
                self.assertIsInstance(dlg.w_create_date, QLabel)
                self.assertEqual(dlg.w_create_date.text(), "2026-07-16")
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

    def test_reward_edit_save_preserves_create_date(self):
        # 瀏覽頁改發文欄位為最高權限管理者專屬，故 patch 身分為 admin。
        from unittest.mock import patch
        from ui_utils.reward_dialog import RewardEditDialog
        dlg = RewardEditDialog(self.db, "4", source="browse")
        dlg.w_sender.setCurrentIndex(dlg.w_sender.findData("P01"))
        dlg.w_reason.setText("更新後事由")
        with patch("ui_utils.reward_dialog.AuthManager.instance") as inst:
            inst.return_value.is_admin.return_value = True
            dlg._on_save()
        conn = sqlite3.connect(self.db)
        row = conn.execute(
            "SELECT create_date,register_date,sender_id,reason "
            "FROM Document_Reward WHERE doc_id='4'").fetchone()
        conn.close()
        self.assertEqual(row, ("2026-07-16", "2026-07-17", "P01", "更新後事由"))
        dlg.deleteLater()

    def test_reward_entry_save_only_touches_reason_and_recipients(self):
        # 敘獎登錄頁（entry）：發文日期／發文人員為唯讀 QLabel（比照罰單登錄修改），
        # 儲存只改事由與人員，register_date／sender_id 一律不動。
        from PySide6.QtWidgets import QLabel
        from ui_utils.reward_dialog import RewardEditDialog
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE Document_Reward SET sender_id='P02' WHERE doc_id='4'")
        conn.commit()
        conn.close()
        dlg = RewardEditDialog(self.db, "4", source="entry")
        self.assertFalse(hasattr(dlg, "w_date"))
        self.assertFalse(hasattr(dlg, "w_sender"))
        self.assertIsInstance(dlg.w_register_date, QLabel)
        self.assertEqual(dlg.w_register_date.text(), "2026-07-17")
        self.assertIsInstance(dlg.w_sender_name, QLabel)
        self.assertEqual(dlg.w_sender_name.text(), "陳志豪")
        dlg.w_reason.setText("登錄者改事由")
        dlg._on_save()
        conn = sqlite3.connect(self.db)
        row = conn.execute(
            "SELECT create_date,register_date,sender_id,reason "
            "FROM Document_Reward WHERE doc_id='4'").fetchone()
        conn.close()
        # 發文日期／發文人員原封不動，只有事由更新
        self.assertEqual(row, ("2026-07-16", "2026-07-17", "P02", "登錄者改事由"))
        dlg.deleteLater()

    def test_reward_entry_shows_unissued_placeholders(self):
        # 未結算列（register_date=''、sender_id 為 NULL）：登錄頁唯讀欄顯示
        # 「未發文」／「－」，不留空白讓人以為系統沒記。
        from ui_utils.reward_dialog import RewardEditDialog
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE Document_Reward SET register_date='', sender_id=NULL "
                     "WHERE doc_id='4'")
        conn.commit()
        conn.close()
        dlg = RewardEditDialog(self.db, "4", source="entry")
        self.assertEqual(dlg.w_register_date.text(), "未發文")
        self.assertEqual(dlg.w_sender_name.text(), "－")
        dlg.deleteLater()

    def test_reward_edit_shows_blank_label_for_missing_create_date(self):
        from PySide6.QtWidgets import QLabel
        from ui_utils.reward_dialog import RewardEditDialog
        conn = sqlite3.connect(self.db)
        conn.execute(
            "UPDATE Document_Reward SET create_date=NULL WHERE doc_id='4'")
        conn.commit()
        conn.close()

        dlg = RewardEditDialog(self.db, "4", source="entry")
        self.assertIsInstance(dlg.w_create_date, QLabel)
        self.assertEqual(dlg.w_create_date.text(), "")
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


class TestTicketEditDialog(_DialogBase):
    """罰單登錄修改彈窗：建構、預填、只改開立人員與罰單編號。"""

    def test_builds_and_prefills(self):
        from PySide6.QtWidgets import QLabel
        from ui_utils.ticket_dialog import TicketEditDialog
        from ui_utils.edit_dialog import _BaseEditDialog
        expected_w = (_BaseEditDialog._LABEL_W + _BaseEditDialog._FIELD_W
                      + _BaseEditDialog._MARGIN)
        dlg = TicketEditDialog(self.db, "5")
        self.assertEqual(dlg.minimumWidth(), expected_w)
        self.assertIsInstance(dlg.w_create_date, QLabel)
        self.assertEqual(dlg.w_create_date.text(), "2026-07-16")
        self.assertEqual(dlg.w_register_date.text(), "2026-07-17")
        self.assertEqual(dlg.w_ticket_no.text(), "D4RD15263")
        self.assertEqual(dlg.w_issuer.currentData(), "P02")
        # Enter 不誤觸儲存（比照敘獎修改彈窗）
        self.assertFalse(dlg.btn_save.isDefault())
        self.assertFalse(dlg.btn_save.autoDefault())
        dlg.deleteLater()

    def test_unissued_row_shows_pending_label(self):
        # register_date=''＝發文結算登錄未發文（NULL 才是刪除哨兵）
        from ui_utils.ticket_dialog import TicketEditDialog
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE Document_Ticket SET register_date='',sender_id=NULL "
                     "WHERE doc_id='5'")
        conn.commit()
        conn.close()
        dlg = TicketEditDialog(self.db, "5")
        self.assertEqual(dlg.w_register_date.text(), "未發文")
        dlg.deleteLater()

    def test_save_only_touches_issuer_and_ticket_no(self):
        from ui_utils.ticket_dialog import TicketEditDialog
        dlg = TicketEditDialog(self.db, "5")
        dlg.w_issuer.setCurrentIndex(dlg.w_issuer.findData("P01"))
        dlg.w_ticket_no.setText(" ab99 ")
        dlg._on_save()
        conn = sqlite3.connect(self.db)
        row = conn.execute(
            "SELECT create_date,register_date,sender_id,issuer_id,ticket_no "
            "FROM Document_Ticket WHERE doc_id='5'").fetchone()
        conn.close()
        self.assertEqual(row, ("2026-07-16", "2026-07-17", "P01", "P01", "AB99"))
        dlg.deleteLater()

    def test_open_on_deleted_row_does_not_raise_and_exec_cancels(self):
        from unittest.mock import patch
        from PySide6.QtWidgets import QDialog
        from ui_utils.ticket_dialog import TicketEditDialog
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE Document_Ticket SET create_date=NULL,"
                     "register_date=NULL,sender_id=NULL,issuer_id=NULL,"
                     "ticket_no=NULL WHERE doc_id='5'")
        conn.commit()
        conn.close()
        dlg = TicketEditDialog(self.db, "5")
        self.assertTrue(dlg._row_missing)
        with patch("ui_utils.ticket_dialog.msgWarning") as warn:
            self.assertEqual(dlg.exec(), QDialog.Rejected)
            warn.assert_called_once()
        self.assertIsNone(dlg.get_updated())
        dlg.deleteLater()

    def test_invalid_source_raises(self):
        from ui_utils.ticket_dialog import TicketEditDialog
        # 傳錯／漏傳 source 必須明確失敗，不得靜默降級成唯讀版本
        with self.assertRaises(ValueError):
            TicketEditDialog(self.db, "5", source="bogus")

    def test_browse_source_builds_editable_fields(self):
        from ui_utils.ticket_dialog import TicketEditDialog
        from ui_utils.widgets import NullableDateEdit
        from PySide6.QtWidgets import QComboBox
        dlg = TicketEditDialog(self.db, "5", source="browse")
        # 瀏覽來源：登錄／發文日期為可空白日期框、發文者為可選下拉（皆可改）
        self.assertIsInstance(dlg.w_create_date, NullableDateEdit)
        self.assertIsInstance(dlg.w_register_date, NullableDateEdit)
        self.assertIsInstance(dlg.w_sender, QComboBox)
        self.assertEqual(dlg.w_ticket_no.text(), "D4RD15263")
        dlg.deleteLater()

    def test_browse_source_blocks_non_admin_save(self):
        from unittest.mock import patch
        from ui_utils.ticket_dialog import TicketEditDialog
        dlg = TicketEditDialog(self.db, "5", source="browse")
        dlg.w_ticket_no.setText("AB99")
        with patch("lib.auth_manager.AuthManager.instance") as inst:
            inst.return_value.is_admin.return_value = False
            with patch("ui_utils.ticket_dialog.msgWarning") as warn:
                dlg._on_save()
                warn.assert_called_once()
        conn = sqlite3.connect(self.db)
        row = conn.execute(
            "SELECT ticket_no FROM Document_Ticket WHERE doc_id='5'").fetchone()
        conn.close()
        self.assertEqual(row[0], "D4RD15263")   # 非 admin 未寫入
        dlg.deleteLater()

    def test_browse_source_admin_edits_all_fields(self):
        from unittest.mock import patch
        from PySide6.QtCore import QDate
        from ui_utils.ticket_dialog import TicketEditDialog
        dlg = TicketEditDialog(self.db, "5", source="browse")
        dlg.w_issuer.setCurrentIndex(dlg.w_issuer.findData("P01"))
        dlg.w_register_date.setDate(QDate(2026, 8, 1))
        dlg.w_sender.setCurrentIndex(dlg.w_sender.findData("P01"))
        dlg.w_ticket_no.setText("cd88")
        with patch("lib.auth_manager.AuthManager.instance") as inst:
            inst.return_value.is_admin.return_value = True
            inst.return_value.current_role = "admin"
            dlg._on_save()
        conn = sqlite3.connect(self.db)
        row = conn.execute(
            "SELECT register_date,sender_id,issuer_id,ticket_no "
            "FROM Document_Ticket WHERE doc_id='5'").fetchone()
        conn.close()
        self.assertEqual(row, ("2026-08-01", "P01", "P01", "CD88"))
        dlg.deleteLater()

    def test_save_on_concurrently_deleted_row_is_not_false_success(self):
        from unittest.mock import patch
        from PySide6.QtWidgets import QDialog
        from ui_utils.ticket_dialog import TicketEditDialog
        dlg = TicketEditDialog(self.db, "5")
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE Document_Ticket SET create_date=NULL,"
                     "register_date=NULL,sender_id=NULL,issuer_id=NULL,"
                     "ticket_no=NULL WHERE doc_id='5'")
        conn.commit()
        conn.close()
        dlg.w_ticket_no.setText("AB99")
        with patch("ui_utils.ticket_dialog.msgWarning") as warn:
            dlg._on_save()
            warn.assert_called_once()
        self.assertIsNone(dlg.get_updated())
        self.assertTrue(dlg._row_missing)
        self.assertNotEqual(dlg.result(), QDialog.Accepted)
        dlg.deleteLater()

    def test_duplicate_ticket_no_is_blocked(self):
        from unittest.mock import patch
        from ui_utils.ticket_dialog import TicketEditDialog
        conn = sqlite3.connect(self.db)
        conn.execute("INSERT INTO Document_Ticket(doc_id,create_date,"
                     "register_date,sender_id,issuer_id,ticket_no) "
                     "VALUES('6','2026-07-16','','P01','P02','ZZ9')")
        conn.commit()
        conn.close()
        dlg = TicketEditDialog(self.db, "5")
        dlg.w_ticket_no.setText("zz9")
        with patch("ui_utils.ticket_dialog.msgWarning") as warn:
            dlg._on_save()
            warn.assert_called_once()
        conn = sqlite3.connect(self.db)
        row = conn.execute("SELECT ticket_no FROM Document_Ticket "
                           "WHERE doc_id='5'").fetchone()
        conn.close()
        self.assertEqual(row[0], "D4RD15263")   # 被擋下 → 未更動
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


class TestReportPreviewCreateDate(_DialogBase):
    def test_preview_headers_put_create_date_after_doc_id(self):
        from tabs.tab_report import CRIM_HEADERS, GEN_HEADERS
        # 標題用兩字「登錄」，欄寬才壓得到 5 半形（見 _fmtDateShort）
        self.assertEqual(CRIM_HEADERS[1:3], ["編號", "登錄"])
        self.assertEqual(GEN_HEADERS[1:3], ["編號", "登錄"])
        self.assertEqual(CRIM_HEADERS[8], "陳報")

    def test_subject_is_the_stretch_column(self):
        """伸縮欄＝陳報主旨：其餘欄固定寬，剩餘寬度全部給主旨。

        原本是「末端空標題欄吃掉剩餘寬度、主旨固定 184」，導致固定欄總和
        超出可用寬而冒水平捲軸；改由主旨吸收剩餘後，主旨不需要固定數字。
        """
        import ast
        import pathlib
        from tabs.tab_report import CRIM_HEADERS, GEN_HEADERS
        for headers, name in ((CRIM_HEADERS, "刑案"), (GEN_HEADERS, "一般")):
            self.assertNotIn("", headers[1:], f"{name}不應再有末端空標題欄")
        src = pathlib.Path("tabs/tab_report.py").read_text(encoding="utf-8")
        calls = [n for n in ast.walk(ast.parse(src))
                 if isinstance(n, ast.Call)
                 and getattr(n.func, "id", "") == "setupPreviewTable"]
        self.assertEqual(len(calls), 2)
        for call in calls:
            kw = {k.arg: k.value for k in call.keywords}
            # stretch_col=<HEADERS>.index("陳報主旨")
            self.assertEqual(kw["stretch_col"].args[0].value, "陳報主旨")

    def test_autoresize_never_overflows_when_sections_have_large_minimum(self):
        """欄寬總和不得超過 viewport，否則一開啟就冒水平捲軸（實機踩過）。

        Qt 會把每一欄夾到 header 的 `minimumSectionSize`（隨字型／DPI 而變，
        實機 125%＋14pt 時比刪除欄的 32 大），實際總寬因此比算出來的多幾 px。
        ⚠️ offscreen 的 minimumSectionSize 只有 23、夾不到，所以這裡**刻意調大**
        來重現實機條件；不要因為「本機測不出來」就把 autoResizeTable 末尾的
        校正拿掉。
        """
        from ui_utils.table import setupPreviewTable, autoResizeTable
        table = QTableWidget()
        setupPreviewTable(table, ["", "編號", "登錄", "陳報主旨", "承辦人"],
                          stretch_col=3, cap_mode=False,
                          fixed_overrides={"陳報主旨": 92})
        table.horizontalHeader().setMinimumSectionSize(46)   # 模擬實機夾寬
        table.show()
        table.resize(600, 300)
        QApplication.processEvents()
        autoResizeTable(table)
        total = sum(table.columnWidth(c) for c in range(table.columnCount()))
        self.assertLessEqual(total, table.viewport().width(),
                             "欄寬總和超出 viewport，會冒水平捲軸")
        table.deleteLater()

    def test_preview_layout_splits_three_to_two(self):
        """previewLayout 3:2＝兩塊扣掉主旨後的固定欄比值，兩邊主旨才等寬。"""
        import pathlib
        ui = pathlib.Path("layouts/Layout3.ui").read_text(encoding="utf-8")
        block = ui.split('name="previewLayout"', 1)[1][:800]
        self.assertIn('<string notr="true">3,2</string>', block)

    def test_report_preview_column_widths_match_agreed_baseline(self):
        """陳報預覽欄寬＝維護者定的字數基準（全形 17px、半形 8px、PAD 24）。

        改這些數字前先回頭看 DEVELOPER §5「陳報預覽欄寬基準」，那裡記了
        字數、換算式與預算上限；只改數字不改基準會再次跑掉。
        """
        from ui_utils.table import FIXED_COL_WIDTHS as W
        full = lambda n: n * 17 + 24      # noqa: E731
        half = lambda n: n * 8 + 24       # noqa: E731
        self.assertEqual(W["編號"], half(4))
        self.assertEqual(W["狀態"], full(2))
        self.assertEqual(W["承辦人"], full(4))
        self.assertEqual(W["受理人"], full(4))
        self.assertEqual(W["報案人"], full(4))
        self.assertEqual(W["業務單位"], full(4))
        self.assertEqual(W["分類"], full(2))
        # 兩個日期欄固定 5 半形＝只顯示 MM-DD；標題取兩字才不會被切
        for key in ("登錄", "陳報"):
            self.assertEqual(W[key], half(5))
            self.assertGreaterEqual(W[key], full(2), f"標題「{key}」會被切")

    def test_preview_dates_show_month_day_only_with_full_date_tooltip(self):
        """預覽日期欄只顯示 MM-DD，完整日期掛 tooltip。"""
        from tabs.tab_report import _fmtDateShort
        self.assertEqual(_fmtDateShort("2026-07-31"), "07/31")
        self.assertEqual(_fmtDateShort(""), "")
        self.assertEqual(_fmtDateShort(None), "")
        self.assertEqual(_fmtDateShort("非日期"), "非日期")

    def test_short_date_does_not_touch_shared_fmtDate(self):
        """⚠️ 不可改 BaseTab._fmtDate：交辦單／罰單／敘獎預覽共用它。"""
        from lib.base_tab import BaseTab
        self.assertEqual(BaseTab._fmtDate("2026-07-31"), "07-31-2026")

    def test_report_previews_disable_ellipsis_except_subject(self):
        """除「陳報主旨」外不顯示省略號：切斷就切斷。

        省略號會再吃掉一個字元寬，欄寬是照字數算好的（日期欄踩過：64px
        本該剛好顯示 07-16，加省略號變成 07-1…）。
        """
        from PySide6.QtCore import Qt
        from ui_utils import applyNoElide
        from ui_utils.table import _ElideRightDelegate
        from tabs.tab_report import CRIM_HEADERS, GEN_HEADERS

        for headers in (CRIM_HEADERS, GEN_HEADERS):
            subject = headers.index("陳報主旨")
            table = QTableWidget(0, len(headers))
            applyNoElide(table, elide_cols=(subject,))
            self.assertEqual(table.textElideMode(), Qt.ElideNone)
            self.assertIsInstance(table.itemDelegateForColumn(subject),
                                  _ElideRightDelegate)
            other = 1 if subject != 1 else 2
            self.assertNotIsInstance(table.itemDelegateForColumn(other),
                                     _ElideRightDelegate)
            table.deleteLater()

    def test_report_previews_wire_no_elide_for_subject_column_only(self):
        """陳報頁確實有呼叫 applyNoElide，且只把主旨欄列為例外。"""
        import ast
        import pathlib
        src = pathlib.Path("tabs/tab_report.py").read_text(encoding="utf-8")
        calls = [n for n in ast.walk(ast.parse(src))
                 if isinstance(n, ast.Call)
                 and getattr(n.func, "id", "") == "applyNoElide"]
        self.assertEqual(len(calls), 2, "兩張預覽表都要關省略號")
        for call in calls:
            kw = {k.arg: k.value for k in call.keywords}
            self.assertIn("elide_cols", kw)
            self.assertEqual(len(kw["elide_cols"].elts), 1,
                             "只有主旨欄可保留省略號")

    def test_report_previews_use_fixed_widths_not_caps(self):
        """陳報兩張預覽表一律固定寬：內容再長不加寬、內容短也不縮。

        `cap_mode=False` 才是「固定值」；True 會變成上限（短內容縮、長內容
        撐到上限），維護者要求除主旨外都不自動變寬。
        """
        import ast
        import pathlib
        src = pathlib.Path("tabs/tab_report.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call)
                 and getattr(n.func, "id", "") == "setupPreviewTable"]
        self.assertEqual(len(calls), 2, "陳報頁應只建立兩張預覽表")
        for call in calls:
            kw = {k.arg: k.value for k in call.keywords}
            self.assertIn("cap_mode", kw)
            self.assertIs(kw["cap_mode"].value, False)

    def test_preview_rows_show_create_date_without_shifting_existing_values(self):
        from tabs.tab_report import CRIM_HEADERS, GEN_HEADERS, TabReport
        tab = TabReport(None, self.db)
        tab.crim_table = QTableWidget(0, len(CRIM_HEADERS))
        tab.gen_table = QTableWidget(0, len(GEN_HEADERS))

        tab._insertCrimRow(
            "2", "2026-07-16", "現行", "竊盜案", "刑案主旨",
            "陳志豪", "", "", "2026-06-01")
        self.assertEqual(
            [tab.crim_table.item(0, col).text() for col in range(2, 10)],
            ["07/16", "現行", "竊盜案", "刑案主旨",
             "陳志豪", "", "06/01", ""])
        # 完整日期仍掛在 tooltip
        self.assertEqual(tab.crim_table.item(0, 2).toolTip(), "2026-07-16")
        self.assertEqual(tab.crim_table.item(0, 8).toolTip(), "2026-06-01")

        tab._insertGenRow(
            "3", "2026-07-16", "偵查隊", "一般主旨", "陳志豪", "業務")
        self.assertEqual(
            [tab.gen_table.item(0, col).text() for col in range(2, 7)],
            ["07/16", "偵查隊", "一般主旨", "陳志豪", "業務"])
        self.assertEqual(tab.gen_table.item(0, 2).toolTip(), "2026-07-16")
        tab.crim_table.deleteLater()
        tab.gen_table.deleteLater()


class TestSettleDialog(_DialogBase):
    def test_theme_contract_uses_global_controls_and_shared_buttons(self):
        """結算視窗只保留專用狀態樣式，其餘控制項繼承全域 theme。"""
        from lib.theme import APPLE_STYLE
        from ui_utils.ui_common import BTN_CANCEL, BTN_CONFIRM
        from ui_utils.settle_dialog import SettleDialog

        # 比照 main.runApplication：字型與樣式表都由 QApplication 提供，
        # 彈窗本身不得再自行 setFont（會被全域樣式表的 `*` 規則蓋掉＝死碼，
        # 又把字體名稱抄成第二份來源）。
        old_style = _app.styleSheet()
        old_font = _app.font()
        _app.setFont(QFont("Microsoft JhengHei", 14))
        _app.setStyleSheet(APPLE_STYLE)
        try:
            dlg = SettleDialog(self.db)
            self.assertEqual(dlg.font().family(), "Microsoft JhengHei")
            for widget in (
                dlg.issue_date, dlg.issue_date.lineEdit(), dlg.cmb_sender,
                dlg.edit_kw, dlg._tbl,
            ):
                self.assertEqual(widget.font().pointSize(), 14)
            for label in dlg.findChildren(QLabel):
                self.assertEqual(label.font().pointSize(), 14)
            for chip in dlg._chips.values():
                self.assertEqual(chip.font().pointSize(), 14)
            # 表頭字級由共用表格樣式提供，不得在元件上再寫死字體／字級
            self.assertEqual(dlg._tbl.horizontalHeader().styleSheet(), "")
            self.assertIn("font-size: 13pt", dlg._tbl.styleSheet())
            self.assertNotIn("font-family", dlg._tbl.styleSheet())
            self.assertEqual(dlg.btn_confirm.styleSheet(), BTN_CONFIRM)
            self.assertEqual(dlg.btn_cancel.styleSheet(), BTN_CANCEL)
            self.assertIn("QDialog", dlg.styleSheet())
            self.assertIn("QWidget", dlg.styleSheet())
            self.assertIn("background-color: #ffffff", dlg.styleSheet().lower())
            self.assertIn("color: #000000", dlg.styleSheet().lower())
            self.assertNotIn("QLineEdit", dlg.styleSheet())
            self.assertNotIn("QComboBox", dlg.styleSheet())
            self.assertNotIn("QDateEdit", dlg.styleSheet())
            self.assertIn("QTableWidget::item:hover", dlg._tbl.styleSheet())
            self.assertIn("QCheckBox::indicator:indeterminate", dlg._tbl.styleSheet())
            self.assertIn("QPushButton#chip:checked", dlg._chips["all"].styleSheet())
        finally:
            dlg.deleteLater()
            _app.setStyleSheet(old_style)
            _app.setFont(old_font)

    def test_issue_date_is_required_calendar_date_and_exposed_after_settlement(self):
        """發文日期可選，但尚未成功結算時不得暴露成功日期。"""
        from ui_utils.settle_dialog import SettleDialog
        dlg = SettleDialog(self.db)

        self.assertIsInstance(dlg.issue_date, QDateEdit)
        self.assertTrue(dlg.issue_date.calendarPopup())
        self.assertEqual(dlg.issue_date.displayFormat(), "yyyy-MM-dd")
        self.assertEqual(dlg.issue_date.date(), QDate.currentDate())
        self.assertEqual(dlg.issue_date.minimumWidth(), 220)
        self.assertIsNone(dlg.settledDate())
        dlg.deleteLater()

    def test_confirm_uses_selected_issue_date_for_settlement(self):
        """確認結算時必須把使用者選定的過去日期寫入，而非重新取今天。"""
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE Document_Criminal SET report_date=NULL, sender_id=NULL "
                     "WHERE doc_id='2'")
        conn.commit()
        conn.close()
        from ui_utils.settle_dialog import SettleDialog
        dlg = SettleDialog(self.db)
        dlg.issue_date.setDate(QDate(2026, 7, 9))
        dlg.cmb_sender.setCurrentIndex(1)

        # 本例刻意選過去日期會觸發日期防呆的確認框；遮蔽由 tests/date_guard_shim
        # 統一處置（PITFALLS TST-4），這裡不再自己 patch 第二份。
        with mock.patch("ui_utils.settle_dialog.confirmBox", return_value=True), \
             mock.patch("ui_utils.settle_dialog.settle_selected", return_value=1) as settle:
            dlg._on_confirm()

        self.assertEqual(settle.call_args.args[2], "2026-07-09")
        self.assertTrue(dlg.settled())
        self.assertEqual(dlg.settledDate(), QDate(2026, 7, 9))
        dlg.issue_date.setDate(QDate(2026, 7, 10))
        self.assertEqual(dlg.settledDate(), QDate(2026, 7, 9))
        dlg.deleteLater()

    def test_cancel_confirmation_keeps_settled_date_empty(self):
        """取消確認不建立結算成功日期快照。"""
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE Document_Criminal SET report_date=NULL, sender_id=NULL "
                     "WHERE doc_id='2'")
        conn.commit()
        conn.close()
        from ui_utils.settle_dialog import SettleDialog
        dlg = SettleDialog(self.db)
        dlg.cmb_sender.setCurrentIndex(1)

        with mock.patch("ui_utils.settle_dialog.confirmBox", return_value=False):
            dlg._on_confirm()

        self.assertFalse(dlg.settled())
        self.assertIsNone(dlg.settledDate())
        dlg.deleteLater()

    def test_zero_updated_rows_warns_reloads_and_keeps_dialog_open(self):
        """全部列於確認前失效時，不得誤報成功或關閉對話框。"""
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE Document_Criminal SET report_date=NULL, sender_id=NULL "
                     "WHERE doc_id='2'")
        conn.commit()
        conn.close()
        from ui_utils.settle_dialog import SettleDialog
        dlg = SettleDialog(self.db)
        dlg.issue_date.setDate(QDate(2026, 7, 9))
        dlg.cmb_sender.setCurrentIndex(1)

        with mock.patch("ui_utils.settle_dialog.confirmBox", return_value=True), \
             mock.patch("ui_utils.settle_dialog.settle_selected", return_value=0), \
             mock.patch("ui_utils.settle_dialog.msgWarning") as warning, \
             mock.patch("ui_utils.settle_dialog.msgInfo"), \
             mock.patch.object(SettleDialog, "_load", autospec=True) as load, \
             mock.patch.object(dlg, "accept") as accept:
            dlg._on_confirm()

        warning.assert_called_once()
        self.assertIn("沒有任何公文完成結算", warning.call_args.args[1])
        load.assert_called_once_with(dlg)
        accept.assert_not_called()
        self.assertFalse(dlg.settled())
        self.assertIsNone(dlg.settledDate())
        dlg.deleteLater()

    def test_partial_success_accepts_and_snapshots_selected_date(self):
        """非 strict 部分成功仍完成流程，快照使用實際寫入日期。"""
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE Document_Criminal SET report_date=NULL, sender_id=NULL "
                     "WHERE doc_id='2'")
        conn.execute("UPDATE Document_General SET report_date=NULL, sender_id=NULL "
                     "WHERE doc_id='3'")
        conn.commit()
        conn.close()
        from ui_utils.settle_dialog import SettleDialog
        dlg = SettleDialog(self.db)
        dlg.issue_date.setDate(QDate(2026, 7, 9))
        dlg.cmb_sender.setCurrentIndex(1)

        with mock.patch("ui_utils.settle_dialog.confirmBox", return_value=True), \
             mock.patch("ui_utils.settle_dialog.settle_selected", return_value=1), \
             mock.patch("ui_utils.settle_dialog.msgInfo") as info, \
             mock.patch.object(dlg, "accept") as accept:
            dlg._on_confirm()

        info.assert_called_once()
        accept.assert_called_once()
        self.assertTrue(dlg.settled())
        self.assertEqual(dlg.settledDate(), QDate(2026, 7, 9))
        dlg.deleteLater()

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

    def test_conflict_shows_warning_not_generic_error_and_reloads(self):
        """C1：SettlementConflict 須走 msgWarning 顯示白話訊息並重載清單，
        絕不能落到 reportError（泛用當機訊息＋寫 error.log）。"""
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE Document_Criminal SET report_date=NULL, sender_id=NULL "
                     "WHERE doc_id='2'")
        conn.commit()
        conn.close()
        from ui_utils.settle_dialog import SettleDialog, SettlementConflict
        dlg = SettleDialog(self.db)
        dlg.cmb_sender.setCurrentIndex(1)  # 送文者（現行三型態皆需必填）

        conflict_msg = ("刑案（編號 2）已由其他電腦發文或刪除，"
                         "本次結算已全部取消，請重新開啟結算視窗。")
        with mock.patch("ui_utils.settle_dialog.settle_selected",
                         side_effect=SettlementConflict(conflict_msg)), \
             mock.patch("ui_utils.settle_dialog.confirmBox", return_value=True), \
             mock.patch("ui_utils.settle_dialog.msgWarning") as m_warn, \
             mock.patch("ui_utils.settle_dialog.reportError") as m_report, \
             mock.patch.object(SettleDialog, "_load", autospec=True) as m_load:
            dlg._on_confirm()

        m_report.assert_not_called()
        m_warn.assert_called_once()
        warn_text = m_warn.call_args[0][1]
        self.assertIn("編號 2", warn_text)
        m_load.assert_called_once()
        self.assertFalse(dlg.settled())
        self.assertIsNone(dlg.settledDate())
        dlg.deleteLater()

    def test_processor_name_trimmed_and_search_matches_display(self):
        """維護者裁決：結算彈窗承辦人姓名比照敘獎去 `-NN` 後綴顯示，
        搜尋亦須比對「顯示值」而非原始值，避免「畫面顯示 A、搜尋要打 B」。"""
        conn = sqlite3.connect(self.db)
        conn.execute("INSERT INTO Ref_Personnel(staff_id,staff_name,is_active,sort_order) "
                     "VALUES('P03','測試員-19.06',1,3)")
        conn.execute("UPDATE Document_Criminal SET report_date=NULL, sender_id=NULL, "
                     "processor_id='P03' WHERE doc_id='2'")
        conn.commit()
        conn.close()

        from ui_utils.settle_dialog import load_unissued
        data = load_unissued(self.db)
        self.assertEqual(data["crim"][0]["processor"], "測試員")

        from ui_utils.settle_dialog import SettleDialog
        dlg = SettleDialog(self.db)

        # 顯示值即去後綴後的姓名
        proc_texts = [dlg._tbl.item(r, dlg._tbl.COL_PROC).text()
                      for r in range(dlg._tbl.rowCount())]
        self.assertIn("測試員", proc_texts)
        self.assertNotIn("測試員-19.06", proc_texts)

        # 搜尋顯示值找得到
        dlg.edit_kw.setText("測試員")
        self.assertTrue(len(dlg._tbl.visible_rows()) >= 1)

        # 搜尋原始（含後綴）值找不到——證明搜尋比對的是顯示值，不是原始值
        dlg.edit_kw.setText("測試員-19.06")
        self.assertEqual(dlg._tbl.visible_rows(), [])
        dlg.deleteLater()

class TestHelpPageMapping(unittest.TestCase):
    """HELP 頁碼須依分頁 key 換算，獨立版才不會開到別頁的說明。"""

    def test_entry_profile_pages_match_their_tabs(self):
        from ui_utils.help_dialog import helpPageIndex
        from ui_utils.help_content import HELP_TITLES
        from lib.app_profile import ENTRY_PROFILE, FULL_PROFILE

        expected = {
            "reward": "敘獎登錄",
            "ticket": "罰單登錄",
            "browse": "資料庫瀏覽",
            "settings": "資料庫設定",
        }
        for pos, key in enumerate(ENTRY_PROFILE.tab_keys):
            idx = helpPageIndex(pos, ENTRY_PROFILE.tab_keys)
            self.assertEqual(HELP_TITLES[idx], expected[key],
                             f"獨立版第 {pos} 頁（{key}）開到錯的說明")

        # 完整版：位置即頁碼，行為不得改變
        for pos in range(len(FULL_PROFILE.tab_keys)):
            self.assertEqual(helpPageIndex(pos, FULL_PROFILE.tab_keys), pos)
            self.assertEqual(helpPageIndex(pos, None), pos)

    def test_help_mapping_keeps_full_profile_index_for_each_role(self):
        from lib.app_profile import FULL_PROFILE, visibleTabKeys
        from ui_utils.help_dialog import helpPageIndex

        for role in ("user", "archive", "admin"):
            for key in visibleTabKeys(role, FULL_PROFILE):
                fixed_index = FULL_PROFILE.tab_keys.index(key)
                self.assertEqual(
                    helpPageIndex(fixed_index, FULL_PROFILE.tab_keys),
                    fixed_index,
                )


if __name__ == "__main__":
    unittest.main()
