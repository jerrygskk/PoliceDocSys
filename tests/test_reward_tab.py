# -*- coding: utf-8 -*-
import os
import sqlite3
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QApplication, QTabWidget, QWidget

from lib.db_schema import applySchema

_app = QApplication.instance() or QApplication([])


class TestRewardTab(unittest.TestCase):
    def setUp(self):
        fd, self.db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        conn = sqlite3.connect(self.db)
        applySchema(conn)
        conn.executescript("""
            INSERT INTO Ref_Personnel(staff_id,staff_name,is_active,sort_order)
                VALUES('P01','測試甲',1,1),('P02','測試乙',1,2);
            UPDATE Ref_Personnel SET alias='甲員' WHERE staff_id='P01';
        """)
        conn.commit()
        conn.close()
        self.tabs = QTabWidget()
        self.tabs.addTab(QWidget(), "敘獎登錄")

    def tearDown(self):
        self.tabs.deleteLater()
        try:
            os.remove(self.db)
        except OSError:
            pass

    def _make_tab(self):
        from tabs.tab_reward import TabReward
        tab = TabReward(self.tabs, self.db)
        tab.setup(0)
        return tab

    def test_setup_initializes_form_and_does_not_define_clear_tables(self):
        tab = self._make_tab()
        self.assertEqual(tab.reward_date.date(), QDate.currentDate())
        self.assertEqual(tab.reward_reason.placeholderText(), "請輸入敘獎事由")
        self.assertFalse(hasattr(tab, "clear_tables"))
        self.assertEqual(tab.reward_table.columnCount(), 5)

    def test_preview_uses_shared_preview_table_format(self):
        tab = self._make_tab()
        table = tab.reward_table
        css = table.styleSheet().lower()

        self.assertEqual(table.property("stretch_col"), 3)
        self.assertEqual(table.property("fixed_overrides"), {
            "編號": 70,
            "發文日期": 120,
            "敘獎人員": 320,
        })
        # 首欄為空表頭刪除欄（比照其他預覽頁），不顯示「刪除」二字
        self.assertEqual(table.horizontalHeaderItem(0).text(), "")
        self.assertFalse(table.showGrid())
        self.assertIn("alternate-background-color: #f2f2f7", css)
        self.assertIn("qheaderview::section", css)
        self.assertIn("border-bottom: 1px solid #e5e5ea", css)

    def test_setup_passes_personnel_aliases_to_recipient_controller(self):
        from PySide6.QtCore import Qt, QModelIndex
        tab = self._make_tab()
        controller = tab.reward_recipients._recipient_controller
        labels = [controller.model.item(i).text()
                  for i in range(controller.model.rowCount())]
        roles = [controller.model.item(i).data(Qt.UserRole)
                 for i in range(controller.model.rowCount())]
        self.assertIn("甲員 → 測試甲", labels)
        self.assertEqual(roles[labels.index("甲員 → 測試甲")], "測試甲")
        tab.reward_recipients.setText("名單外姓名, 甲員")
        tab.reward_recipients.setCursorPosition(len(tab.reward_recipients.text()))
        controller.completer.activated[QModelIndex].emit(
            controller.model.index(labels.index("甲員 → 測試甲"), 0))
        _app.processEvents()
        self.assertEqual(tab.reward_recipients.text(), "名單外姓名, 測試甲")

    def test_setup_supports_legacy_personnel_table_without_alias(self):
        conn = sqlite3.connect(self.db)
        conn.execute("ALTER TABLE Ref_Personnel DROP COLUMN alias")
        conn.commit()
        conn.close()
        tab = self._make_tab()
        self.assertEqual(tab.reward_personnel_list.count(), 2)

    def test_repeated_activation_updates_existing_recipient_controller(self):
        tab = self._make_tab()
        controller = tab.reward_recipients._recipient_controller
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE Ref_Personnel SET staff_name='測試甲更名',alias='新別名' "
                     "WHERE staff_id='P01'")
        conn.commit()
        conn.close()
        # 參照表改過：設定頁切走時 main 會對各 tab 設 _ref_changed=True。
        # 第一次 on_activated 依旗標重載並清旗標，第二次自然 no-op（不重複重建）。
        tab._ref_changed = True
        tab.on_activated()
        self.assertFalse(getattr(tab, "_ref_changed", False))
        tab.on_activated()
        self.assertIs(tab.reward_recipients._recipient_controller, controller)
        labels = [controller.model.item(i).text()
                  for i in range(controller.model.rowCount())]
        self.assertIn("新別名 → 測試甲更名", labels)
        self.assertNotIn("甲員 → 測試甲", labels)

    def test_submit_commits_then_tracks_session_and_clears_non_date_fields(self):
        tab = self._make_tab()
        tab.reward_reason.setText("  協助查緝  ")
        tab.reward_recipients.setText("測試甲、測試乙，測試甲")
        tab.reward_sender.setCurrentIndex(tab.reward_sender.findData("P01"))
        tab._submit()
        conn = sqlite3.connect(self.db)
        row = conn.execute(
            "SELECT doc_id,register_date,sender_id,reason,recipients FROM Document_Reward"
        ).fetchone()
        conn.close()
        self.assertEqual(row[2:], ("P01", "協助查緝", "測試甲,測試乙"))
        self.assertEqual(tab._session_doc_ids, [row[0]])
        self.assertEqual(tab.reward_table.rowCount(), 1)
        self.assertEqual(tab.reward_reason.text(), "")
        self.assertEqual(tab.reward_recipients.text(), "")

    def test_submit_requires_sender_in_sender_mode(self):
        tab = self._make_tab()
        tab.reward_reason.setText("協助查緝")
        tab.reward_recipients.setText("測試甲")
        # 未選發文人員 → 送文者模式必填擋下，不寫入
        from unittest.mock import patch
        with patch("tabs.tab_reward.msgWarning") as warn:
            tab._submit()
            warn.assert_called_once()
        conn = sqlite3.connect(self.db)
        count = conn.execute("SELECT COUNT(*) FROM Document_Reward").fetchone()[0]
        conn.close()
        self.assertEqual(count, 0)

    def test_self_service_submit_omits_sender_and_leaves_empty_date(self):
        tab = self._make_tab()
        conn = sqlite3.connect(self.db)
        conn.execute("INSERT OR REPLACE INTO App_Settings(key,value) "
                     "VALUES('report_input_mode','1')")
        conn.commit()
        conn.close()
        tab._applySelfServiceMode()
        # 自助模式：日期與發文人員兩欄反灰
        self.assertFalse(tab.reward_date.isEnabled())
        self.assertFalse(tab.reward_sender.isEnabled())
        tab.reward_reason.setText("協助查緝")
        tab.reward_recipients.setText("測試甲")
        tab._submit()
        conn = sqlite3.connect(self.db)
        row = conn.execute(
            "SELECT register_date,sender_id FROM Document_Reward").fetchone()
        conn.close()
        self.assertEqual(row[0], "")       # 未發文哨兵
        self.assertIsNone(row[1])          # 送文者待結算補填

    def test_dirty_refresh_updates_active_rows_and_removes_deleted_rows(self):
        tab = self._make_tab()
        conn = sqlite3.connect(self.db)
        conn.execute("INSERT INTO Document_Reward(doc_id,register_date,reason,recipients) "
                     "VALUES('7','2026-07-17','原事由','測試甲')")
        conn.commit()
        conn.close()
        tab._session_doc_ids = ["7"]
        tab.reward_data_dirty = True
        tab.on_activated()
        self.assertEqual(tab.reward_table.item(0, 3).text(), "原事由")

        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE Document_Reward SET reason='新事由' WHERE doc_id='7'")
        conn.commit()
        conn.close()
        tab.reward_data_dirty = True
        tab.on_activated()
        self.assertEqual(tab.reward_table.item(0, 3).text(), "新事由")

        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE Document_Reward SET register_date=NULL WHERE doc_id='7'")
        conn.commit()
        conn.close()
        tab.reward_data_dirty = True
        tab.on_activated()
        self.assertEqual(tab._session_doc_ids, [])
        self.assertEqual(tab.reward_table.rowCount(), 0)

    def test_activation_without_flags_does_not_reload_personnel(self):
        tab = self._make_tab()
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE Ref_Personnel SET staff_name='測試甲更名' WHERE staff_id='P01'")
        conn.commit()
        conn.close()
        # 未設任何旗標：切頁不應全表重讀人員（效率修復）
        tab.on_activated()
        names = [p[1] for p in tab._personnel]
        self.assertIn("測試甲", names)
        self.assertNotIn("測試甲更名", names)

    def test_submit_then_delete_maintain_counts_in_memory(self):
        tab = self._make_tab()
        tab.reward_reason.setText("協助查緝")
        tab.reward_recipients.setText("測試甲、測試乙")
        tab.reward_sender.setCurrentIndex(tab.reward_sender.findData("P01"))
        tab._submit()
        self.assertEqual(tab._name_counts.get("測試甲"), 1)
        self.assertEqual(tab._name_counts.get("測試乙"), 1)
        doc_id = tab._session_doc_ids[0]
        with_confirm = "tabs.tab_reward.confirmBox"
        from unittest.mock import patch
        with patch(with_confirm, return_value=True):
            tab._deleteByDocId(doc_id)
        self.assertNotIn("測試甲", tab._name_counts)
        self.assertNotIn("測試乙", tab._name_counts)

    def test_marks_browse_reward_cache_dirty(self):
        tab = self._make_tab()

        class Browse:
            _pending_reload_keys = None

            def _forceReload(self, _key):
                pass

        browse = Browse()
        tab._manager = type("Manager", (), {"tabs": {"browse": browse}})()
        tab._flag_browse_dirty()
        self.assertEqual(browse._pending_reload_keys, {"reward"})


if __name__ == "__main__":
    unittest.main()
