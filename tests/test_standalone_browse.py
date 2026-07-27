# -*- coding: utf-8 -*-
"""獨立版（警政快速登錄系統）資料庫瀏覽白名單測試（offscreen）。

保護對象：
  - `TabDBBrowse(allowed_keys=...)` 限縮瀏覽範圍為敘獎與罰單，未知 key 拒絕建構。
  - 子頁籤以 `subtabs.setTabData()` 保存公文類型 key（不得用 currentIndex()/
    BROWSE_KEYS 做位置映射），獨立版恰為 ("reward", "ticket")。
  - 獨立版不出現交辦單／刑案／一般陳報子頁，因此案類互轉、開啟歸檔 PDF 等
    敘獎/罰單用不到的入口自然不存在。
  - 完整版（預設 allowed_keys=BROWSE_KEYS）行為零變化。

人名一律虛構（push 前有 test_no_pii 掃真名）。
"""
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QTabWidget, QWidget

import res.resources_rc  # noqa: F401  資源（icon）註冊，_fillRow 會用到 :/icon_pdf.svg
from lib.auth_manager import AuthManager
from lib.db_schema import applySchema
from lib.db_utils import restoreFromTrash, softDeleteDoc
from lib.ticket_utils import deleteTicket
from tabs.tab_dbbrowse import BROWSE_KEYS, TABLE_META, TabDBBrowse, queryBrowseRows
from tabs.tab_reward import TabReward
from tabs.tab_ticket import TabTicket
from ui_utils.reward_dialog import RewardEditDialog
from ui_utils.ticket_dialog import TicketEditDialog

_app = QApplication.instance() or QApplication([])

ENTRY_BROWSE_KEYS = ("reward", "ticket")


class _StandaloneBrowseBase(unittest.TestCase):
    def setUp(self):
        fd, self.db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        conn = sqlite3.connect(self.db)
        applySchema(conn)
        conn.executescript("""
            INSERT INTO Ref_Personnel(staff_id,staff_name,is_active,sort_order) VALUES
                ('P01','測試員甲',1,1),('P02','測試員乙',1,2);
            INSERT INTO Ref_Departments(dept_id,dept_name,is_active,sort_order) VALUES
                ('D01','偵查隊',1,1);
            INSERT INTO Ref_CaseTypes(case_type_id,case_type_name,is_active,sort_order)
                VALUES('CT01','竊盜案',1,1);
        """)
        conn.executemany(
            "INSERT INTO Document_Task"
            "(doc_id,receive_date,receive_id,dept_id,subject,processor_id,"
            " deadline,dispatch_date,sender_id,timestamp) VALUES(?,?,?,?,?,?,?,?,?,?)",
            [("1", "2026-07-01", "P02", "D01", "甲案交辦事由", "P01",
              "2026-07-20", "2026-07-05", "P02", "2026-07-01 09:00:00")])
        conn.executemany(
            "INSERT INTO Document_Criminal"
            "(doc_id,report_date,sender_id,case_type,case_status,processor_id,"
            " subject_summary,is_reported,is_electronic) VALUES(?,?,?,?,?,?,?,?,?)",
            [("1", "2026-07-01", "P02", "CT01", "", "P01", "甲嫌竊盜案", 0, "")])
        conn.executemany(
            "INSERT INTO Document_Reward"
            "(doc_id,create_date,register_date,reason,recipients) VALUES(?,?,?,?,?)",
            [("1", "2026-07-16", "2026-07-17", "專案有功", "測試甲")])
        conn.executemany(
            "INSERT INTO Document_Ticket"
            "(doc_id,create_date,register_date,sender_id,issuer_id,ticket_no) "
            "VALUES(?,?,?,?,?,?)",
            [("1", "2026-07-01", "2026-07-02", "P01", "P02", "AB1234")])
        conn.commit()
        conn.close()
        self._extra_tabs = []
        AuthManager.instance()._role = "user"

    def tearDown(self):
        AuthManager.instance()._role = "user"
        for t in self._extra_tabs:
            t.deleteLater()
        try:
            os.remove(self.db)
        except OSError:
            pass

    def _make_browse(self, allowed_keys=None):
        tabs = QTabWidget()
        tabs.addTab(QWidget(), "瀏覽")
        self._extra_tabs.append(tabs)
        if allowed_keys is None:
            tab = TabDBBrowse(tabs, self.db)
        else:
            tab = TabDBBrowse(tabs, self.db, allowed_keys=allowed_keys)
        tab.setup(0)
        return tab


class TestFullBrowseUnchanged(_StandaloneBrowseBase):
    """完整版預設 allowed_keys=BROWSE_KEYS，行為必須零變化。"""

    def test_default_allowed_keys_is_full_browse_keys(self):
        tab = self._make_browse()
        self.assertEqual(tab.allowed_keys, BROWSE_KEYS)

    def test_full_subtabs_tab_data_matches_browse_keys_order(self):
        tab = self._make_browse()
        keys = [tab.subtabs.tabBar().tabData(i) for i in range(tab.subtabs.count())]
        self.assertEqual(keys, list(BROWSE_KEYS))
        self.assertEqual(tab.subtabs.count(), len(BROWSE_KEYS))


class TestEntryBrowseWhitelist(_StandaloneBrowseBase):
    """獨立版：allowed_keys=("reward","ticket")。"""

    def test_entry_allowed_keys_is_reward_and_ticket(self):
        tab = self._make_browse(allowed_keys=ENTRY_BROWSE_KEYS)
        self.assertEqual(tab.allowed_keys, ENTRY_BROWSE_KEYS)

    def test_entry_subtabs_tab_data_is_reward_and_ticket_only(self):
        tab = self._make_browse(allowed_keys=ENTRY_BROWSE_KEYS)
        keys = [tab.subtabs.tabBar().tabData(i) for i in range(tab.subtabs.count())]
        self.assertEqual(keys, list(ENTRY_BROWSE_KEYS))
        self.assertEqual(tab.subtabs.count(), 2)

    def test_entry_browse_has_no_task_crim_gen_subtabs(self):
        tab = self._make_browse(allowed_keys=ENTRY_BROWSE_KEYS)
        keys = {tab.subtabs.tabBar().tabData(i) for i in range(tab.subtabs.count())}
        self.assertNotIn("task", keys)
        self.assertNotIn("crim", keys)
        self.assertNotIn("gen", keys)
        # crim/gen 才有案類互轉、開啟歸檔 PDF 的入口；沒有這兩個子頁，
        # 這些操作在獨立版自然不存在，不需另外隱藏。
        self.assertNotIn("archive", TABLE_META["reward"])
        self.assertNotIn("archive", TABLE_META["ticket"])

    def test_entry_browse_only_builds_ui_for_allowed_keys(self):
        tab = self._make_browse(allowed_keys=ENTRY_BROWSE_KEYS)
        self.assertEqual(set(tab._ui.keys()), set(ENTRY_BROWSE_KEYS))

    def test_entry_all_rows_only_contains_allowed_keys(self):
        tab = self._make_browse(allowed_keys=ENTRY_BROWSE_KEYS)
        for key in ENTRY_BROWSE_KEYS:
            tab.buildInitial(key)
        self.assertLessEqual(set(tab._allRows), set(ENTRY_BROWSE_KEYS))
        self.assertEqual(set(tab._allRows), set(ENTRY_BROWSE_KEYS))

    def test_entry_get_tables_only_returns_allowed_keys_tables(self):
        tab = self._make_browse(allowed_keys=ENTRY_BROWSE_KEYS)
        self.assertEqual(len(tab.get_tables()), 2)

    def test_entry_reuses_table_meta_edit_and_delete_handlers(self):
        # 獨立版不得另寫 handler：修改／刪除仍走 TABLE_META 既有定義。
        tab = self._make_browse(allowed_keys=ENTRY_BROWSE_KEYS)
        self.assertIs(TABLE_META["reward"]["dialog"], RewardEditDialog)
        self.assertIs(TABLE_META["ticket"]["dialog"], TicketEditDialog)
        self.assertIn("delete_handler", TABLE_META["ticket"])
        self.assertNotIn("delete_handler", TABLE_META["reward"])
        del tab  # 僅需確認建構成功，不需額外互動


class TestUnknownBrowseKeyRejected(_StandaloneBrowseBase):
    def test_unknown_key_raises_value_error(self):
        tabs = QTabWidget()
        tabs.addTab(QWidget(), "瀏覽")
        self._extra_tabs.append(tabs)
        with self.assertRaises(ValueError):
            TabDBBrowse(tabs, self.db, allowed_keys=("reward", "bogus"))


# ── Task 6：純 DB round-trip 驗證兩種刪除語意 ───────────────────────────
class TestSharedDeleteSemantics(unittest.TestCase):
    """直接呼叫既有 production 函式 softDeleteDoc()／deleteTicket()，不建立
    insert_reward_through_entry() 等包裝 helper。敘獎走共用回收筒可還原；
    罰單清空式軟刪除、保留 doc_id 空殼、不進回收筒。"""

    def setUp(self):
        fd, self.db = tempfile.mkstemp(suffix=".db")
        os.close(fd)

    def tearDown(self):
        try:
            os.remove(self.db)
        except OSError:
            pass

    def test_shared_reward_delete_stays_restorable(self):
        with sqlite3.connect(self.db) as conn:
            applySchema(conn)
            conn.execute(
                "INSERT INTO Document_Reward "
                "(doc_id, create_date, register_date, reason, recipients) "
                "VALUES ('1', '2026-07-27', '', '測試事由', '測試人員')")
            softDeleteDoc(
                conn,
                table="Document_Reward",
                doc_id="1",
                role="admin",
                is_admin=True,
            )
            conn.commit()
            self.assertEqual(queryBrowseRows(conn, "reward"), [])
            trash_count = conn.execute(
                "SELECT COUNT(*) FROM Trash_Documents WHERE doc_id = ?",
                ("1",),
            ).fetchone()[0]
        self.assertEqual(trash_count, 1)

    def test_shared_reward_trash_entry_is_restorable(self):
        # 補證獨立版設定頁沒有還原入口這件事不影響「資料可還原」：軟刪除紀錄
        # 本身仍可由大程式既有 restoreFromTrash() 還原（泛用機制已由
        # tests/test_trash.py 驗證，這裡專測敘獎表）。
        with sqlite3.connect(self.db) as conn:
            applySchema(conn)
            conn.execute(
                "INSERT INTO Document_Reward "
                "(doc_id, create_date, register_date, reason, recipients) "
                "VALUES ('1', '2026-07-27', '', '測試事由', '測試人員')")
            softDeleteDoc(
                conn, table="Document_Reward", doc_id="1",
                role="admin", is_admin=True)
            conn.commit()
            trash_id = conn.execute(
                "SELECT trash_id FROM Trash_Documents WHERE doc_id=?", ("1",)
            ).fetchone()[0]
            result = restoreFromTrash(conn, trash_id)
            conn.commit()
            self.assertEqual(result, ("Document_Reward", "1"))
            rows = queryBrowseRows(conn, "reward")
        self.assertEqual([r["doc_id"] for r in rows], ["1"])
        self.assertEqual(rows[0]["reason"], "測試事由")

    def test_shared_ticket_delete_keeps_shell_without_trash(self):
        with sqlite3.connect(self.db) as conn:
            applySchema(conn)
            conn.execute(
                "INSERT INTO Ref_Personnel (staff_id, staff_name) "
                "VALUES ('P1', '測試人員')")
            conn.execute(
                "INSERT INTO Document_Ticket "
                "(doc_id, create_date, register_date, issuer_id, ticket_no) "
                "VALUES ('1', '2026-07-27', '', 'P1', 'A001')")
            deleteTicket(conn, doc_id="1", role="admin")
            conn.commit()
            row = conn.execute(
                "SELECT doc_id, ticket_no FROM Document_Ticket WHERE doc_id = ?",
                ("1",),
            ).fetchone()
            trash_count = conn.execute(
                "SELECT COUNT(*) FROM Trash_Documents WHERE doc_id = ?",
                ("1",),
            ).fetchone()[0]
        self.assertEqual(row, ("1", None))
        self.assertEqual(trash_count, 0)


# ── Task 6：資料庫瀏覽三角色 baseline（entry allowed_keys=("reward","ticket")）──
class TestEntryBrowseMutateBaseline(_StandaloneBrowseBase):
    """BROWSE_CAN_MUTATE：admin 可、archive/user 不可。權限判斷與大程式共用
    （_canEditKey／AuthManager.is_admin），不另寫角色字串比較。逐一走替代路徑：
    刪除鈕（_onDeleteCell）、編號連結點擊（_onLinkCell→_onEdit→dialog）、
    直接呼叫 _onDelete（實際 delete_handler／confirmBox 是否被呼叫）。"""

    BROWSE_CAN_MUTATE = {"admin": True, "archive": False, "user": False}

    def _browse(self, role):
        AuthManager.instance()._role = role
        tab = self._make_browse(allowed_keys=ENTRY_BROWSE_KEYS)
        tab.buildInitial("reward")
        tab.buildInitial("ticket")
        return tab

    def test_reward_delete_handler_baseline(self):
        for role, allowed in self.BROWSE_CAN_MUTATE.items():
            with self.subTest(role=role):
                tab = self._browse(role)
                with patch("tabs.tab_dbbrowse.confirmBox",
                           return_value=True) as confirm, \
                     patch("tabs.tab_dbbrowse.softDeleteDoc") as soft_delete:
                    tab._onDelete("reward", "1")
                if allowed:
                    confirm.assert_called_once()
                    soft_delete.assert_called_once()
                else:
                    confirm.assert_not_called()
                    soft_delete.assert_not_called()

    def test_reward_delete_button_cell_click_baseline(self):
        for role, allowed in self.BROWSE_CAN_MUTATE.items():
            with self.subTest(role=role):
                tab = self._browse(role)
                del_col = next(i for i, c in enumerate(TABLE_META["reward"]["cols"])
                               if c.get("delete"))
                tab._docorder["reward"] = ["1"]
                with patch.object(tab, "_onDelete") as on_delete:
                    tab._onDeleteCell("reward", 0, del_col, del_col)
                if allowed:
                    on_delete.assert_called_once_with("reward", "1")
                else:
                    on_delete.assert_not_called()

    def test_reward_dialog_save_baseline_via_link_cell(self):
        # ⚠️ TABLE_META["reward"]["dialog"] 是模組載入時就存好的類別參考，
        # patch("tabs.tab_dbbrowse.RewardEditDialog") 只換掉模組屬性、換不掉
        # dict 裡已存的舊參考——若真的 allowed，_onEdit 會開到「真的」對話框、
        # exec() 進 modal 導致 offscreen 測試永久卡住（本檔踩過）。改成
        # patch.dict 直接換 TABLE_META 裡的 dialog 物件才攔得到。
        for role, allowed in self.BROWSE_CAN_MUTATE.items():
            with self.subTest(role=role):
                tab = self._browse(role)
                link_col = next(i for i, c in enumerate(TABLE_META["reward"]["cols"])
                                if c.get("link"))
                tab._docorder["reward"] = ["1"]
                dialog_factory = MagicMock()
                dialog_factory.return_value.exec.return_value = False
                with patch.dict(TABLE_META["reward"], {"dialog": dialog_factory}):
                    tab._onLinkCell("reward", 0, link_col, link_col)
                if allowed:
                    dialog_factory.assert_called_once()
                else:
                    dialog_factory.assert_not_called()

    def test_ticket_delete_handler_baseline(self):
        for role, allowed in self.BROWSE_CAN_MUTATE.items():
            with self.subTest(role=role):
                tab = self._browse(role)
                handler = MagicMock()
                with patch("tabs.tab_dbbrowse.confirmBox",
                           return_value=True) as confirm, \
                     patch.dict(TABLE_META["ticket"], {"delete_handler": handler}):
                    tab._onDelete("ticket", "1")
                if allowed:
                    confirm.assert_called_once()
                    handler.assert_called_once()
                else:
                    confirm.assert_not_called()
                    handler.assert_not_called()

    def test_ticket_delete_button_cell_click_baseline(self):
        for role, allowed in self.BROWSE_CAN_MUTATE.items():
            with self.subTest(role=role):
                tab = self._browse(role)
                del_col = next(i for i, c in enumerate(TABLE_META["ticket"]["cols"])
                               if c.get("delete"))
                tab._docorder["ticket"] = ["1"]
                with patch.object(tab, "_onDelete") as on_delete:
                    tab._onDeleteCell("ticket", 0, del_col, del_col)
                if allowed:
                    on_delete.assert_called_once_with("ticket", "1")
                else:
                    on_delete.assert_not_called()

    def test_ticket_dialog_save_baseline_via_link_cell(self):
        # 同上：直接換 TABLE_META["ticket"]["dialog"]，不 patch 模組屬性。
        for role, allowed in self.BROWSE_CAN_MUTATE.items():
            with self.subTest(role=role):
                tab = self._browse(role)
                link_col = next(i for i, c in enumerate(TABLE_META["ticket"]["cols"])
                                if c.get("link"))
                tab._docorder["ticket"] = ["1"]
                dialog_factory = MagicMock()
                dialog_factory.return_value.exec.return_value = False
                with patch.dict(TABLE_META["ticket"], {"dialog": dialog_factory}):
                    tab._onLinkCell("ticket", 0, link_col, link_col)
                if allowed:
                    dialog_factory.assert_called_once()
                else:
                    dialog_factory.assert_not_called()


# ── Task 6：登錄頁本次預覽三角色 baseline（共用敘獎登錄／罰單登錄頁）──────
class _EntryPreviewBase(unittest.TestCase):
    def setUp(self):
        fd, self.db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        conn = sqlite3.connect(self.db)
        applySchema(conn)
        conn.executescript("""
            INSERT INTO Ref_Personnel(staff_id,staff_name,is_active,sort_order) VALUES
                ('P01','測試員甲',1,1),('P02','測試員乙',1,2);
        """)
        conn.commit()
        conn.close()
        self._extra_tabs = []
        AuthManager.instance()._role = "user"

    def tearDown(self):
        AuthManager.instance()._role = "user"
        for t in self._extra_tabs:
            t.deleteLater()
        try:
            os.remove(self.db)
        except OSError:
            pass

    def _reward_tab(self, role):
        AuthManager.instance()._role = role
        tabs = QTabWidget()
        tabs.addTab(QWidget(), "敘獎登錄")
        self._extra_tabs.append(tabs)
        tab = TabReward(tabs, self.db)
        tab.setup(0)
        return tab

    def _ticket_tab(self, role):
        AuthManager.instance()._role = role
        tabs = QTabWidget()
        tabs.addTab(QWidget(), "罰單登錄")
        self._extra_tabs.append(tabs)
        tab = TabTicket(tabs, self.db)
        tab.setup(0)
        return tab


class TestEntryPreviewMutateBaseline(_EntryPreviewBase):
    """ENTRY_PREVIEW_CAN_MUTATE：本次登錄預覽的修改／刪除三角色皆可——這條
    路徑本身沒有角色 gate（僅新增受輸入鎖限制，見下一個 TestCase），
    admin／archive／user 都應能修改與刪除自己剛送出的那筆。"""

    ENTRY_PREVIEW_CAN_MUTATE = {"admin": True, "archive": True, "user": True}

    def test_reward_preview_edit_and_delete_allowed_for_all_roles(self):
        for role in self.ENTRY_PREVIEW_CAN_MUTATE:
            with self.subTest(role=role):
                tab = self._reward_tab(role)
                tab.reward_reason.setText("協助查緝")
                tab.reward_recipients.setCurrentText("測試員甲")
                tab._submit()
                doc_id = tab._session_doc_ids[0]
                with patch("tabs.tab_reward.RewardEditDialog") as dialog_factory:
                    dialog_factory.return_value.exec.return_value = False
                    tab._onEditRow(0, doc_id)
                    dialog_factory.assert_called_once()
                with patch("tabs.tab_reward.confirmBox", return_value=True):
                    tab._deleteByDocId(doc_id)
                conn = sqlite3.connect(self.db)
                row = conn.execute(
                    "SELECT recipients FROM Document_Reward WHERE doc_id=?",
                    (doc_id,)).fetchone()
                conn.close()
                self.assertIsNone(row[0])

    def test_ticket_preview_edit_and_delete_allowed_for_all_roles(self):
        for role in self.ENTRY_PREVIEW_CAN_MUTATE:
            with self.subTest(role=role):
                tab = self._ticket_tab(role)
                tab.ticket_sender.setCurrentIndex(tab.ticket_sender.findData("P01"))
                tab.ticket_issuer.setCurrentIndex(tab.ticket_issuer.findData("P02"))
                tab.ticket_no.setText("D4RD00001")
                tab._submit()
                doc_id = tab._session_doc_ids[0]
                with patch("tabs.tab_ticket.TicketEditDialog") as dialog_factory:
                    dialog_factory.return_value.exec.return_value = False
                    tab._onEditRow(0, doc_id)
                    dialog_factory.assert_called_once()
                with patch("tabs.tab_ticket.confirmBox", return_value=True):
                    tab._deleteByDocId(doc_id)
                conn = sqlite3.connect(self.db)
                row = conn.execute(
                    "SELECT ticket_no FROM Document_Ticket WHERE doc_id=?",
                    (doc_id,)).fetchone()
                conn.close()
                self.assertIsNone(row[0])


class TestEntryPreviewInputLockOnlyBlocksNewAdd(_EntryPreviewBase):
    """一般使用者的輸入鎖只擋新增，不得把既有資料的刪改一併鎖死。沿用
    tests/test_reward_tab.py／tests/test_ticket_tab.py 已驗證的機制，這裡只
    用 entry 會實際共用的敘獎/罰單登錄頁再次確認，不新建 GUI 測試基礎設施。"""

    def test_reward_lock_blocks_new_but_allows_delete_of_existing(self):
        tab = self._reward_tab("user")
        tab.reward_reason.setText("協助查緝")
        tab.reward_recipients.setCurrentText("測試員甲")
        tab._submit()
        doc_id = tab._session_doc_ids[0]

        conn = sqlite3.connect(self.db)
        conn.execute("INSERT OR REPLACE INTO App_Settings(key,value) "
                     "VALUES('input_lock_reward','1')")
        conn.commit()
        conn.close()
        tab.on_activated()

        with patch("tabs.tab_reward.msgWarning"):
            tab.reward_reason.setText("新事由")
            tab.reward_recipients.setCurrentText("測試員乙")
            tab._submit()
        conn = sqlite3.connect(self.db)
        count = conn.execute(
            "SELECT COUNT(*) FROM Document_Reward "
            "WHERE recipients IS NOT NULL").fetchone()[0]
        conn.close()
        self.assertEqual(count, 1)   # 新增被擋

        with patch("tabs.tab_reward.confirmBox", return_value=True):
            tab._deleteByDocId(doc_id)
        conn = sqlite3.connect(self.db)
        row = conn.execute(
            "SELECT recipients FROM Document_Reward WHERE doc_id=?",
            (doc_id,)).fetchone()
        conn.close()
        self.assertIsNone(row[0])   # 既有資料仍可刪

    def test_ticket_lock_blocks_new_but_allows_delete_of_existing(self):
        tab = self._ticket_tab("user")
        tab.ticket_sender.setCurrentIndex(tab.ticket_sender.findData("P01"))
        tab.ticket_issuer.setCurrentIndex(tab.ticket_issuer.findData("P02"))
        tab.ticket_no.setText("D4RD00001")
        tab._submit()
        doc_id = tab._session_doc_ids[0]

        conn = sqlite3.connect(self.db)
        conn.execute("INSERT OR REPLACE INTO App_Settings(key,value) "
                     "VALUES('input_lock_ticket','1')")
        conn.commit()
        conn.close()
        tab.on_activated()

        with patch("tabs.tab_ticket.msgWarning"):
            tab.ticket_no.setText("D4RD00002")
            tab._submit()
        conn = sqlite3.connect(self.db)
        count = conn.execute(
            "SELECT COUNT(*) FROM Document_Ticket "
            "WHERE ticket_no IS NOT NULL").fetchone()[0]
        conn.close()
        self.assertEqual(count, 1)   # 新增被擋

        with patch("tabs.tab_ticket.confirmBox", return_value=True):
            tab._deleteByDocId(doc_id)
        conn = sqlite3.connect(self.db)
        row = conn.execute(
            "SELECT ticket_no FROM Document_Ticket WHERE doc_id=?",
            (doc_id,)).fetchone()
        conn.close()
        self.assertIsNone(row[0])   # 既有資料仍可刪


if __name__ == "__main__":
    unittest.main()
