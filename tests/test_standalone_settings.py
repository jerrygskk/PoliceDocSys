# -*- coding: utf-8 -*-
"""獨立版（公文快速登錄系統）精簡設定頁測試（offscreen）。

保護對象：
  - `TabSettings(profile=...)` 只組裝 profile 核准的設定頁與系統設定面板；
    保留 .ui 六個 stack page 與固定索引，不刪頁、不重排。
  - 未核准頁（部門／案類／回收筒／備份還原）不建立物件，屬性明確為 None，
    對應 nav button 隱藏；跨年度重置鈕隱藏且不連接 `_doReset`。
  - `_applyRolePermissions()` 每次角色變動都重新檢查 profile：未核准的
    trash／backup nav button 不得被再次 `setVisible(True)`。
  - `InputLockPanel`／`InputModePanel` 的 `flow_keys` 只建立、只讀寫白名單
    內的流程，不動其他流程既有 App_Settings 值。
  - 完整版（預設 profile=FULL_PROFILE）行為零變化：六頁六面板全部建立。

人名一律虛構（push 前有 test_no_pii 掃真名）。
"""
import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QTabWidget, QWidget

from lib.app_profile import ENTRY_PROFILE, FULL_PROFILE
from lib.auth_manager import AuthManager
from lib.db_schema import applySchema
from lib.db_utils import getSetting, setSetting
from tabs.tab_settings import TabSettings
from ui_utils.settings_panels import InputLockPanel, InputModePanel

_app = QApplication.instance() or QApplication([])


class _SettingsBase(unittest.TestCase):
    def setUp(self):
        fd, self.db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        conn = sqlite3.connect(self.db)
        applySchema(conn)
        conn.commit()
        conn.close()
        self._extra_tabs = []
        self._settings_tabs = []
        AuthManager.instance()._role = "user"

    def tearDown(self):
        AuthManager.instance()._role = "user"
        # ⚠️ TabSettings.setup 會把 _onRoleChanged 接到 AuthManager 單例上，
        # 而單例活過整個 test session：只 deleteLater 容器的話，widget 被銷毀、
        # 但連線還在，之後別的測試 emit role_changed 就會打到已刪除的
        # _outer_stack（`RuntimeError: ... QStackedWidget already deleted`）。
        # 這是跨檔汙染，只有特定執行順序才會炸（實際踩過：pytest 全跑時
        # test_ticket_tab 的降權測試被牽連）。務必在這裡斷開。
        for tab in self._settings_tabs:
            try:
                AuthManager.instance().role_changed.disconnect(tab._onRoleChanged)
            except (RuntimeError, TypeError):
                pass
        for t in self._extra_tabs:
            t.deleteLater()
        try:
            os.remove(self.db)
        except OSError:
            pass

    def _make_settings(self, profile=None):
        tabs = QTabWidget()
        tabs.addTab(QWidget(), "設定")
        self._extra_tabs.append(tabs)
        if profile is None:
            tab = TabSettings(tabs, self.db)
        else:
            tab = TabSettings(tabs, self.db, profile=profile)
        tab.setup(0)
        self._settings_tabs.append(tab)
        return tab

    def _login_as(self, settings, role):
        """略過密碼驗證，直接模擬登入後的畫面狀態（比照 _onRoleChanged 成功分支）。"""
        AuthManager.instance()._role = role
        settings._applyRolePermissions()
        settings._outer_stack.setCurrentIndex(1)
        settings._switchPage(settings._PAGE_PERSONNEL)


class TestEntrySettingsAssembly(_SettingsBase):
    """獨立版：只組裝人員與系統設定，系統設定只留三個核准面板。"""

    def test_entry_settings_only_has_personnel_and_system(self):
        s = self._make_settings(profile=ENTRY_PROFILE)
        self.assertEqual(s.enabled_page_keys, ("personnel", "system"))
        self.assertEqual(s.enabled_system_panel_keys,
                          ("idle", "input_lock", "input_mode"))
        self.assertIsNone(s._trash_panel)
        self.assertIsNone(s._panel_restore)
        self.assertIsNone(s._panel_archive_root)
        self.assertIsNone(s._panel_print_title)
        self.assertIsNone(s._panel_backup)
        self.assertTrue(s._btn_year_reset.isHidden())

    def test_entry_hides_dept_casetype_trash_backup_nav_buttons(self):
        s = self._make_settings(profile=ENTRY_PROFILE)
        self.assertFalse(s._nav_btns[s._PAGE_PERSONNEL].isHidden())
        self.assertFalse(s._nav_btns[s._PAGE_SYSTEM].isHidden())
        self.assertTrue(s._nav_btns[s._PAGE_DEPT].isHidden())
        self.assertTrue(s._nav_btns[s._PAGE_CASETYPE].isHidden())
        self.assertTrue(s._nav_btns[s._PAGE_TRASH].isHidden())
        self.assertTrue(s._nav_btns[s._PAGE_BACKUP].isHidden())

    def test_entry_switch_page_rejects_forbidden_indices(self):
        s = self._make_settings(profile=ENTRY_PROFILE)
        AuthManager.instance()._role = "admin"
        s._applyRolePermissions()
        s._outer_stack.setCurrentIndex(1)
        s._switchPage(s._PAGE_DEPT)     # 不得切頁、不得拋例外（無 _sort_state["dept"]）
        self.assertNotEqual(s._inner_stack.currentIndex(), s._PAGE_DEPT)
        s._switchPage(s._PAGE_TRASH)
        self.assertNotEqual(s._inner_stack.currentIndex(), s._PAGE_TRASH)
        s._switchPage(s._PAGE_BACKUP)
        self.assertNotEqual(s._inner_stack.currentIndex(), s._PAGE_BACKUP)

    def test_entry_year_reset_button_not_connected(self):
        # ⚠️ 不可用 patch.object(TabSettings, "_doReset") 驗證：signal 連的是
        # setup() 當下取得的 bound method，事後換掉類別屬性不影響既有連線，
        # 反而會讓「真的被連上」的情況靜默通過。改攔 _doReset 內部會開的
        # ResetDialog：真的連上就會被建構，沒連上就完全不會出現。
        s = self._make_settings(profile=ENTRY_PROFILE)
        self.assertTrue(s._btn_year_reset.isHidden())
        with patch("tabs.tab_settings.ResetDialog") as mock_dlg:
            s._btn_year_reset.click()      # 隱藏鈕仍可被程式觸發，等同替代路徑
            mock_dlg.assert_not_called()

    def test_entry_input_panels_only_show_approved_flows(self):
        s = self._make_settings(profile=ENTRY_PROFILE)
        self.assertEqual(s._panel_input_lock.flow_keys, ("reward", "ticket"))
        self.assertEqual(s._panel_input_mode.flow_keys, ("reward", "ticket"))


class TestEntryHasNoRestoreEntryButSharedMechanismIntact(_SettingsBase):
    """獨立版設定頁沒有回收筒／還原入口（`_trash_panel`／`_panel_restore` 皆
    None，見上一個 TestCase），但這只是「沒有 UI 入口」，不是「資料不能還原」：
    共用 `lib.db_utils.restoreFromTrash()` 與大程式 `TrashPanel` 完全沒被本案
    動過。敘獎軟刪除後仍可還原的實際 round-trip 證據見
    tests/test_standalone_browse.py::TestSharedDeleteSemantics
    .test_shared_reward_trash_entry_is_restorable；此處只驗證獨立版沒有另建
    一套還原機制或入口。"""

    def test_entry_settings_builds_no_trash_or_restore_widgets(self):
        s = self._make_settings(profile=ENTRY_PROFILE)
        self.assertIsNone(s._trash_panel)
        self.assertIsNone(s._panel_restore)
        self.assertFalse(hasattr(s, "_doRestore"))

    def test_shared_restore_function_is_untouched_by_entry_profile(self):
        from lib.db_utils import restoreFromTrash
        from ui_utils.trash_panel import TrashPanel
        # 只確認獨立版沒有另建同名或替代實作；還原邏輯仍是大程式那一套。
        import tabs.tab_settings as tab_settings_module
        self.assertIs(tab_settings_module.TrashPanel, TrashPanel)
        self.assertTrue(callable(restoreFromTrash))


class TestRoleRefreshCannotReshowForbiddenPages(_SettingsBase):
    def test_role_refresh_cannot_reshow_forbidden_pages(self):
        s = self._make_settings(profile=ENTRY_PROFILE)
        AuthManager.instance()._role = "admin"
        s._applyRolePermissions()
        self.assertTrue(s._nav_btns[s._PAGE_TRASH].isHidden())
        self.assertTrue(s._nav_btns[s._PAGE_BACKUP].isHidden())
        # 反覆呼叫（模擬多次角色變動）仍不得再顯示
        AuthManager.instance()._role = "archive"
        s._applyRolePermissions()
        AuthManager.instance()._role = "admin"
        s._applyRolePermissions()
        self.assertTrue(s._nav_btns[s._PAGE_TRASH].isHidden())
        self.assertTrue(s._nav_btns[s._PAGE_BACKUP].isHidden())


class TestEntryRoleBaseline(_SettingsBase):
    """三角色 baseline：人員與系統設定（idle/input_lock/input_mode）。"""

    def test_admin_can_edit_personnel_and_system_settings(self):
        s = self._make_settings(profile=ENTRY_PROFILE)
        self._login_as(s, "admin")
        self.assertTrue(s.btn_add_personnel.isEnabled())
        self.assertTrue(s._panel_input_lock.isEnabled())
        self.assertTrue(s._panel_input_mode.isEnabled())
        self.assertTrue(s._panel_idle.isEnabled())

    def test_archive_is_readonly_like_full_app(self):
        s = self._make_settings(profile=ENTRY_PROFILE)
        self._login_as(s, "archive")
        self.assertFalse(s.btn_add_personnel.isEnabled())
        self.assertFalse(s._panel_input_lock.isEnabled())
        self.assertFalse(s._panel_input_mode.isEnabled())
        self.assertFalse(s._panel_idle.isEnabled())

    def test_user_stays_on_login_page(self):
        s = self._make_settings(profile=ENTRY_PROFILE)
        self.assertEqual(s._outer_stack.currentIndex(), 0)

    def test_change_password_and_logout_still_use_auth_manager(self):
        s = self._make_settings(profile=ENTRY_PROFILE)
        self._login_as(s, "admin")
        with patch("tabs.tab_settings.confirmBox", return_value=True):
            s._doLogout()
        self.assertEqual(AuthManager.instance().current_role, "user")


class TestFullSettingsUnchanged(_SettingsBase):
    """完整版（預設 profile）：六頁六面板全部建立，行為零變化。"""

    def test_full_profile_default_builds_all_six_pages_and_panels(self):
        s = self._make_settings()   # 不傳 profile → 預設 FULL_PROFILE
        self.assertEqual(s.enabled_page_keys,
                          ("personnel", "dept", "casetype", "system",
                           "trash", "backup"))
        self.assertEqual(s.enabled_system_panel_keys,
                          ("archive_root", "print_title", "idle",
                           "input_lock", "backup", "input_mode"))
        self.assertIsNotNone(s._trash_panel)
        self.assertIsNotNone(s._panel_restore)
        for i in range(6):
            self.assertFalse(s._nav_btns[i].isHidden())
        self.assertFalse(s._btn_year_reset.isHidden())

    def test_full_profile_explicit_matches_default(self):
        s = self._make_settings(profile=FULL_PROFILE)
        self.assertEqual(s.enabled_page_keys,
                          ("personnel", "dept", "casetype", "system",
                           "trash", "backup"))

    def test_full_input_lock_panel_keeps_all_six_rows(self):
        # 敘獎發文頁移除後唯讀鎖剩六把；陳報模式加入敘獎後為四列。
        s = self._make_settings()
        self.assertEqual(len(s._panel_input_lock._checks), 6)
        self.assertEqual(len(s._panel_input_mode._radios), 4)

    def test_full_admin_can_reach_year_reset(self):
        # ⚠️ 不可讓 click() 真的跑進 _doReset：那會開 modal ResetDialog，
        # offscreen 測試沒有人按，整支測試會永遠卡住（本檔踩過）。
        # 改成攔 ResetDialog（回傳取消），驗證按鈕確實通到重置流程即可。
        s = self._make_settings()
        self._login_as(s, "admin")
        self.assertTrue(s._btn_year_reset.isEnabled())
        self.assertFalse(s._btn_year_reset.isHidden())
        with patch("tabs.tab_settings.ResetDialog") as mock_dlg:
            mock_dlg.return_value.exec.return_value = 0   # 使用者取消
            s._btn_year_reset.click()
            mock_dlg.assert_called_once()


class TestResetRuntimeGuards(_SettingsBase):
    """重置流程在 modal 巢狀事件迴圈中降權後不得繼續副作用。"""

    def test_direct_call_as_non_admin_stops_before_read_or_dialog(self):
        s = self._make_settings()
        AuthManager.instance()._role = "archive"

        with patch("tabs.tab_settings.getConn") as get_conn, \
                patch("tabs.tab_settings.ResetDialog") as dialog:
            dialog.return_value.exec.return_value = 0
            s._doReset()

        get_conn.assert_not_called()
        dialog.assert_not_called()

    def test_downgrade_inside_reset_dialog_stops_before_audit_or_backup(self):
        s = self._make_settings()
        self._login_as(s, "admin")

        class DowngradeDialog:
            def __init__(self, *args, **kwargs):
                pass

            def exec(self):
                AuthManager.instance()._role = "archive"
                return 1

        with patch("tabs.tab_settings.ResetDialog", DowngradeDialog), \
                patch("tabs.tab_settings.writeAudit") as write_audit, \
                patch("tabs.tab_settings.shutil.copy2") as copy_backup, \
                patch("tabs.tab_settings.confirmBox", return_value=False), \
                patch("tabs.tab_settings.performYearEndReset") as reset, \
                patch("tabs.tab_settings.msgInfo"), \
                patch.object(s, "_restartApp"):
            s._doReset()

        write_audit.assert_not_called()
        copy_backup.assert_not_called()
        reset.assert_not_called()

    def test_downgrade_in_final_backup_prompt_stops_before_reset(self):
        s = self._make_settings()
        self._login_as(s, "admin")

        def downgrade_and_skip(*args, **kwargs):
            AuthManager.instance()._role = "archive"
            return False

        with patch("tabs.tab_settings.ResetDialog") as dialog, \
                patch("tabs.tab_settings.confirmBox", side_effect=downgrade_and_skip), \
                patch("tabs.tab_settings.shutil.copy2"), \
                patch("tabs.tab_settings.performYearEndReset") as reset, \
                patch("tabs.tab_settings.msgInfo"), \
                patch.object(s, "_restartApp"):
            dialog.return_value.exec.return_value = 1
            s._doReset()

        reset.assert_not_called()


class TestSortDowngradeGuards(_SettingsBase):
    def _seed_personnel(self):
        conn = sqlite3.connect(self.db)
        conn.executemany(
            "INSERT INTO Ref_Personnel("
            "staff_id,staff_name,is_active,sort_order) VALUES(?,?,1,?)",
            (("P001", "甲員", 1), ("P002", "乙員", 2)),
        )
        conn.commit()
        conn.close()

    def _admin_with_rows(self):
        self._seed_personnel()
        s = self._make_settings()
        self._login_as(s, "admin")
        return s

    def _db_order(self):
        conn = sqlite3.connect(self.db)
        try:
            return [row[0] for row in conn.execute(
                "SELECT staff_id FROM Ref_Personnel ORDER BY sort_order")]
        finally:
            conn.close()

    def test_move_row_direct_call_after_downgrade_does_not_mutate_memory(self):
        s = self._admin_with_rows()
        before = [row[0] for row in s._sort_state["personnel"]["rows"]]
        AuthManager.instance()._role = "archive"

        s._moveRow("personnel", 0, 1)

        state = s._sort_state["personnel"]
        self.assertEqual([row[0] for row in state["rows"]], before)
        self.assertFalse(state["dirty"])

    def test_drop_callback_after_downgrade_does_not_mutate_memory(self):
        s = self._admin_with_rows()
        before = [row[0] for row in s._sort_state["personnel"]["rows"]]
        AuthManager.instance()._role = "archive"

        s._onDragDrop("personnel", 0, 1)

        state = s._sort_state["personnel"]
        self.assertEqual([row[0] for row in state["rows"]], before)
        self.assertFalse(state["dirty"])

    def test_save_sort_after_downgrade_returns_false_without_db_write(self):
        s = self._admin_with_rows()
        state = s._sort_state["personnel"]
        state["rows"].reverse()
        state["dirty"] = True
        AuthManager.instance()._role = "archive"

        self.assertFalse(s._saveSort("personnel"))
        self.assertEqual(self._db_order(), ["P001", "P002"])
        self.assertTrue(state["dirty"])

    def test_save_sort_as_admin_returns_true_and_persists(self):
        s = self._admin_with_rows()
        state = s._sort_state["personnel"]
        state["rows"].reverse()
        state["dirty"] = True

        self.assertTrue(s._saveSort("personnel"))
        self.assertEqual(self._db_order(), ["P002", "P001"])
        self.assertFalse(state["dirty"])

    def test_prompt_does_not_continue_when_confirm_downgrades_and_save_fails(self):
        s = self._admin_with_rows()
        state = s._sort_state["personnel"]
        s._moveRow("personnel", 0, 1)

        def downgrade(*args, **kwargs):
            AuthManager.instance()._role = "archive"
            return True

        with patch("tabs.tab_settings.confirmBox", side_effect=downgrade):
            self.assertFalse(s._promptUnsaved(context="switch"))

        self.assertTrue(state["dirty"])
        self.assertEqual(self._db_order(), ["P001", "P002"])

    def test_logout_discards_dirty_sort_without_prompt_and_reloads_db_order(self):
        s = self._admin_with_rows()
        s._moveRow("personnel", 0, 1)

        with patch("tabs.tab_settings.confirmBox") as confirm:
            AuthManager.instance().logout()

        state = s._sort_state["personnel"]
        confirm.assert_not_called()
        self.assertEqual([row[0] for row in state["rows"]], ["P001", "P002"])
        self.assertFalse(state["dirty"])
        self.assertFalse(state["save_btn"].isEnabled())

    def test_switch_to_archive_discards_dirty_sort_without_prompt(self):
        s = self._admin_with_rows()
        s._moveRow("personnel", 0, 1)
        AuthManager.instance()._role = "archive"

        with patch("tabs.tab_settings.confirmBox") as confirm:
            s._onRoleChanged("archive")

        state = s._sort_state["personnel"]
        confirm.assert_not_called()
        self.assertEqual([row[0] for row in state["rows"]], ["P001", "P002"])
        self.assertFalse(state["dirty"])

class TestInputLockPanelFlowIsolation(unittest.TestCase):
    """InputLockPanel(flow_keys=...) 存檔不得動未列出流程的既有值。"""

    def setUp(self):
        fd, self.db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        conn = sqlite3.connect(self.db)
        applySchema(conn)
        conn.commit()
        conn.close()
        AuthManager.instance()._role = "admin"

    def tearDown(self):
        AuthManager.instance()._role = "user"
        try:
            os.remove(self.db)
        except OSError:
            pass

    def test_entry_input_lock_save_does_not_touch_unlisted_flows(self):
        # 先在 DB 內設定一個不在白名單內的流程（task）為鎖定
        setSetting(self.db, "input_lock_task", "1")

        panel = InputLockPanel(self.db, flow_keys=("reward", "ticket"))
        self.assertEqual(set(panel._checks.keys()), {"reward", "ticket"})
        panel._checks["reward"].setChecked(True)
        panel._checks["ticket"].setChecked(False)
        self.assertTrue(panel._save())

        # 白名單外的 task 唯讀設定必須維持原值不被清掉或覆寫
        self.assertEqual(
            (getSetting(self.db, "input_lock_task", "") or "").strip(), "1")
        self.assertEqual(
            (getSetting(self.db, "input_lock_reward", "") or "").strip(), "1")
        panel.deleteLater()

    def test_entry_input_mode_save_does_not_touch_unlisted_flows(self):
        setSetting(self.db, "report_mode_crim", "1")

        panel = InputModePanel(self.db, flow_keys=("ticket",))
        self.assertEqual(set(panel._radios.keys()), {"ticket"})
        panel._radios["ticket"][1].setChecked(True)   # 自助取號
        self.assertTrue(panel._save())

        self.assertEqual(
            (getSetting(self.db, "report_mode_crim", "") or "").strip(), "1")
        self.assertEqual(
            (getSetting(self.db, "report_mode_ticket", "") or "").strip(), "1")
        panel.deleteLater()


if __name__ == "__main__":
    unittest.main()
