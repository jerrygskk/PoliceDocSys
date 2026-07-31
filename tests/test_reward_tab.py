# -*- coding: utf-8 -*-
import os
import sqlite3
import tempfile
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from unittest.mock import patch

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QApplication, QPushButton, QTabWidget, QWidget

from lib.auth_manager import AuthManager
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

    def test_setup_initializes_form_with_issue_fields(self):
        tab = self._make_tab()
        # 未設定 report_mode_reward＝送文者輸入模式：兩欄可填、日期預設今天
        self.assertIsNotNone(tab.reward_date)
        self.assertIsNotNone(tab.reward_sender)
        self.assertTrue(tab.reward_date.isEnabled())
        self.assertTrue(tab.reward_sender.isEnabled())
        self.assertEqual(tab.reward_date.date(), QDate.currentDate())
        # 送文者模式不顯示自助提示條（比照罰單登錄頁的可見 QLabel 提示）
        self.assertTrue(tab.reward_sender_hint.isHidden())
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
        le = tab.reward_recipients.lineEdit()   # 可編輯下拉：controller 掛在 lineEdit
        le.setText("名單外姓名, 甲員")
        le.setCursorPosition(len(le.text()))
        controller.completer.activated[QModelIndex].emit(
            controller.model.index(labels.index("甲員 → 測試甲"), 0))
        _app.processEvents()
        self.assertEqual(le.text(), "名單外姓名, 測試甲")

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

    def _set_mode(self, self_service):
        conn = sqlite3.connect(self.db)
        conn.execute("INSERT OR REPLACE INTO App_Settings(key,value) "
                     "VALUES('report_mode_reward',?)",
                     ("1" if self_service else "0",))
        conn.commit()
        conn.close()

    def _rows(self):
        conn = sqlite3.connect(self.db)
        try:
            return conn.execute(
                "SELECT doc_id,create_date,register_date,sender_id,reason,"
                "recipients FROM Document_Reward "
                "ORDER BY CAST(doc_id AS INTEGER)").fetchall()
        finally:
            conn.close()

    def test_self_service_submit_creates_unissued_reward(self):
        self._set_mode(True)
        tab = self._make_tab()
        self.assertFalse(tab.reward_date.isEnabled())
        self.assertFalse(tab.reward_sender.isEnabled())
        # 自助模式：以可見提示條說明兩欄免填（tooltip 在深色模式看不到，QSS-7）
        self.assertFalse(tab.reward_sender_hint.isHidden())
        self.assertEqual(tab.reward_sender_hint.text(),
                         "自助取號模式：發文日期與發文人員免填")
        for _ in range(2):
            tab.reward_reason.setText("  協助查緝  ")
            tab.reward_recipients.setCurrentText("測試甲、測試乙，測試甲")
            tab._submit()
        rows = self._rows()
        today = QDate.currentDate().toString("yyyy-MM-dd")
        self.assertEqual([row[1:] for row in rows], [
            (today, "", None, "協助查緝", "測試甲,測試乙"),
            (today, "", None, "協助查緝", "測試甲,測試乙"),
        ])
        self.assertEqual(tab._session_doc_ids, [row[0] for row in rows])
        self.assertEqual(tab.reward_table.rowCount(), 2)
        self.assertEqual(tab.reward_table.item(0, 2).text(), "未發文")
        self.assertEqual(tab.reward_reason.text(), "")
        self.assertEqual(tab.reward_recipients.currentText(), "")

    def test_sender_mode_submit_issues_immediately(self):
        """送文者輸入模式：登錄即發文，帶所填發文日期與發文人員。"""
        tab = self._make_tab()
        tab.reward_date.setDate(QDate(2026, 7, 24))
        tab.reward_sender.setCurrentIndex(tab.reward_sender.findData("P01"))
        tab.reward_reason.setText("協助查緝")
        tab.reward_recipients.setCurrentText("測試甲")
        tab._submit()
        today = QDate.currentDate().toString("yyyy-MM-dd")
        self.assertEqual([row[1:] for row in self._rows()],
                         [(today, "2026-07-24", "P01", "協助查緝", "測試甲")])
        self.assertEqual(tab.reward_table.item(0, 2).text(), "2026-07-24")

    def test_sender_mode_requires_sender(self):
        """送文者模式未選發文人員時擋下，不得寫入。"""
        tab = self._make_tab()
        tab.reward_reason.setText("協助查緝")
        tab.reward_recipients.setCurrentText("測試甲")
        with patch("tabs.tab_reward.msgWarning") as warn:
            tab._submit()
        warn.assert_called_once()
        self.assertEqual(self._rows(), [])

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

    def _candidate_names(self, tab):
        return [tab.reward_personnel_list.item(i).text()
                for i in range(tab.reward_personnel_list.count())]

    def test_candidate_order_follows_personnel_sort_order_not_usage(self):
        """候選名條一律照 Ref_Personnel 的 sort_order，不受敘獎次數影響。"""
        conn = sqlite3.connect(self.db)
        # 測試乙（sort_order 2）被敘獎兩次，仍不得被提到測試甲前面
        conn.executescript("""
            INSERT INTO Document_Reward
                (doc_id,create_date,register_date,sender_id,reason,recipients)
            VALUES ('90','2026-07-20','2026-07-20','P01','甲案','測試乙'),
                   ('91','2026-07-20','2026-07-20','P01','乙案','測試乙');
        """)
        conn.commit()
        conn.close()
        tab = self._make_tab()
        self.assertEqual(self._candidate_names(tab), ["測試甲", "測試乙"])

    def test_submit_and_delete_do_not_reorder_candidates(self):
        tab = self._make_tab()
        before = self._candidate_names(tab)
        tab.reward_sender.setCurrentIndex(tab.reward_sender.findData("P01"))
        tab.reward_reason.setText("協助查緝")
        tab.reward_recipients.setCurrentText("測試乙")
        tab._submit()
        self.assertEqual(self._candidate_names(tab), before)
        doc_id = tab._session_doc_ids[0]
        from unittest.mock import patch
        with patch("tabs.tab_reward.confirmBox", return_value=True):
            tab._deleteByDocId(doc_id)
        self.assertEqual(self._candidate_names(tab), before)

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


class TestRewardInputLock(unittest.TestCase):
    """跨年度唯讀鎖（input_lock_reward）：只擋一般使用者新增，
    不擋 admin／archive，不擋既有資料 edit／delete。"""

    def setUp(self):
        fd, self.db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        conn = sqlite3.connect(self.db)
        applySchema(conn)
        conn.executescript("""
            INSERT INTO Ref_Personnel(staff_id,staff_name,is_active,sort_order)
                VALUES('P01','測試甲',1,1),('P02','測試乙',1,2);
        """)
        conn.commit()
        conn.close()
        self._extra_tabs = []
        AuthManager.instance()._role = "user"

    def tearDown(self):
        AuthManager.instance()._role = "user"   # 還原單例（不 emit）
        for t in self._extra_tabs:
            t.deleteLater()
        try:
            os.remove(self.db)
        except OSError:
            pass

    def _make_tab(self):
        # 每個 tab 自帶 QTabWidget，避免同一測試建多個 tab 撞到同一 widget(0)。
        from tabs.tab_reward import TabReward
        tabs = QTabWidget()
        tabs.addTab(QWidget(), "敘獎登錄")
        self._extra_tabs.append(tabs)
        tab = TabReward(tabs, self.db)
        tab.setup(0)
        return tab

    def _make_multi_tab(self):
        """兩個分頁的 QTabWidget（本頁在 index 1），供真的 emit currentChanged
        做切頁往返；單一分頁的 widget 切不動、測不出切回頁時的復活。"""
        from tabs.tab_reward import TabReward
        tabs = QTabWidget()
        tabs.addTab(QWidget(), "其他頁")
        tabs.addTab(QWidget(), "敘獎登錄")
        self._extra_tabs.append(tabs)
        tab = TabReward(tabs, self.db)
        tab.setup(1)
        return tabs, tab

    def _set_lock(self, on):
        conn = sqlite3.connect(self.db)
        conn.execute("INSERT OR REPLACE INTO App_Settings(key,value) "
                     "VALUES('input_lock_reward',?)", ("1" if on else "",))
        conn.commit()
        conn.close()

    def _set_role(self, role, *, emit=False):
        am = AuthManager.instance()
        am._role = role
        if emit:
            am.role_changed.emit(role)

    def _reward_count(self):
        conn = sqlite3.connect(self.db)
        try:
            return conn.execute("SELECT COUNT(*) FROM Document_Reward "
                                "WHERE recipients IS NOT NULL").fetchone()[0]
        finally:
            conn.close()

    def _fill(self, tab, reason="協助查緝", recipients="測試甲"):
        # 預設送文者輸入模式：發文人員必填，不選會先被欄位檢查擋下。
        tab.reward_sender.setCurrentIndex(tab.reward_sender.findData("P01"))
        tab.reward_reason.setText(reason)
        tab.reward_recipients.setCurrentText(recipients)

    def test_locked_blocks_regular_but_allows_admin_and_archive(self):
        self._set_lock(True)
        self._set_role("user")
        regular = self._make_tab()
        self._fill(regular)
        with patch("tabs.tab_reward.msgWarning"):
            regular._submit()
        self.assertEqual(self._reward_count(), 0)
        for role in ("admin", "archive"):
            with self.subTest(role=role):
                self._set_role(role)
                manager = self._make_tab()
                self._fill(manager)
                manager._submit()
        self.assertEqual(self._reward_count(), 2)

    def test_locked_regular_user_disables_inputs_and_shows_banner(self):
        self._set_role("user")
        tab = self._make_tab()
        self._set_lock(True)
        tab.on_activated()   # 切回本頁重套
        self.assertFalse(tab.btn_submit.isEnabled())
        self.assertFalse(tab.reward_reason.isEnabled())
        self.assertFalse(tab.reward_recipients.isEnabled())
        self.assertFalse(tab.reward_date.isEnabled())
        self.assertFalse(tab.reward_sender.isEnabled())
        # offscreen 無 show()：以 isHidden 判斷本身可見旗標（isVisible 受祖鏈影響）
        self.assertFalse(tab._readonly_banner.isHidden())

    def test_manager_never_locked_and_banner_hidden(self):
        self._set_lock(True)
        self._set_role("admin")
        tab = self._make_tab()
        self.assertTrue(tab.btn_submit.isEnabled())
        self.assertTrue(tab._readonly_banner.isHidden())

    def test_submit_hard_guard_blocks_even_when_inputs_bypassed(self):
        # 移除 _submit 的 hard guard 此測試須轉紅。
        self._set_lock(True)
        self._set_role("user")
        tab = self._make_tab()
        self._fill(tab)
        with patch("tabs.tab_reward.msgWarning") as warn, \
             patch("tabs.tab_reward.nextDocId") as nx:
            tab._submit()
            warn.assert_called_once()
            nx.assert_not_called()
        self.assertEqual(self._reward_count(), 0)

    def test_manager_downgrade_clears_preview(self):
        self._set_role("admin")
        tab = self._make_tab()
        self._fill(tab)
        tab._submit()
        self.assertEqual(tab.reward_table.rowCount(), 1)
        self._set_role("user", emit=True)
        self.assertEqual(tab.reward_table.rowCount(), 0)

    def test_manager_downgrade_clears_preview_persistently_across_tab_switch(self):
        """降權清空必須具持續性：切頁往返後仍是 0 列。

        ⚠️ 只斷言降權當下 `rowCount()==0` 是假保證：`_onRoleClearList` 若只清
        表格 widget、不清 `self._session_doc_ids`，本頁 `on_activated` 的
        dirty-flag 守衛只是掩蓋——`reward_data_dirty` 會被不設角色 gate 的
        路徑（如列印頁結算發文，一般使用者走得到）設為 True，旗標一開，切回本頁就 `_refresh_session_rows()` 把整份
        清單從 DB 重建，降權後的一般使用者即取得「編輯／刪除管理身分建立之
        敘獎」的入口（同一筆在瀏覽頁是僅 admin 可改）。故本測試必須真的
        `logout()`、真的設 dirty 旗標、真的 emit `currentChanged`。
        """
        self._set_role("admin")
        tabs, tab = self._make_multi_tab()
        self._fill(tab)
        tab._submit()
        doc_id = tab._session_doc_ids[0]
        self.assertEqual(tab.reward_table.rowCount(), 1)

        # 真實降權路徑（非直接改 _role）：admin → logout() → user
        am = AuthManager.instance()
        am.logout()
        self.assertEqual(am.current_role, "user")
        self.assertEqual(tab.reward_table.rowCount(), 0)

        # 列印頁結算發文完成時對所有 tab 設的旗標（tab_print._flagRewardReload）
        tab.reward_data_dirty = True
        # 真的切走再切回（emit currentChanged→_onShown→on_activated）
        tabs.setCurrentIndex(0)
        tabs.setCurrentIndex(1)

        self.assertEqual(tab.reward_table.rowCount(), 0)
        self.assertEqual(tab._session_doc_ids, [])
        # 取不到列＝編輯（_onEditRow）／刪除（_deleteByDocId）進入點取不到 doc_id
        self.assertEqual(tab._row_for_doc_id(doc_id), -1)
        # 清的是入口不是資料：該筆敘獎仍在 DB
        conn = sqlite3.connect(self.db)
        row = conn.execute(
            "SELECT doc_id,reason,recipients FROM Document_Reward "
            "WHERE doc_id=?", (doc_id,)).fetchone()
        conn.close()
        self.assertEqual(row, (doc_id, "協助查緝", "測試甲"))

    def test_lock_does_not_block_delete_of_existing(self):
        self._set_role("user")
        tab = self._make_tab()
        self._fill(tab)
        tab._submit()
        self.assertEqual(self._reward_count(), 1)
        doc_id = tab._session_doc_ids[0]
        self._set_lock(True)
        tab.on_activated()
        with patch("tabs.tab_reward.confirmBox", return_value=True):
            tab._deleteByDocId(doc_id)
        self.assertEqual(self._reward_count(), 0)   # 已軟刪除（recipients 清空）


if __name__ == "__main__":
    unittest.main()
