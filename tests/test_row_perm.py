"""`lib/row_perm.py` 的權限矩陣與三態判斷（純邏輯，不開 GUI、不連資料庫）。

對應計畫 `docs/plans/2026-08-04-permission-refresh.md` §5.2。
這支測試釘住的是**規則本身**；各頁有沒有正確呼叫它，由各頁自己的測試負責。
"""

import unittest

from lib.db_utils import INPUT_LOCK_KEYS
from lib import row_perm


# 三種身分的 (is_admin, is_manager)。一般使用者兩者皆否，歸檔管理只有 is_manager，
# admin 兩者皆是（比照 AuthManager.is_admin/is_manager 的實際回傳）。
ROLES = {
    "user":    dict(is_admin=False, is_manager=False),
    "archive": dict(is_admin=False, is_manager=True),
    "admin":   dict(is_admin=True,  is_manager=True),
}


def _edit(page, role, *, dispatched, locked=False):
    return row_perm.canEditRow(page, dispatched=dispatched,
                               input_locked=locked, **ROLES[role])


def _delete(page, role, *, dispatched, locked=False):
    return row_perm.canDeleteRow(page, dispatched=dispatched,
                                 input_locked=locked, **ROLES[role])


class TestPageVocabulary(unittest.TestCase):
    """頁面代號沿用 INPUT_LOCK_KEYS，不得另造第二套詞彙。"""

    def test_pages_match_input_lock_keys(self):
        self.assertEqual(set(row_perm.PAGES), set(INPUT_LOCK_KEYS))

    def test_every_page_has_table_and_columns(self):
        for page in row_perm.PAGES:
            self.assertIn(page, row_perm.PAGE_TABLE)
            self.assertIn(page, row_perm.DATE_COLUMN)
            self.assertIn(page, row_perm.LIVE_COLUMN)

    def test_unknown_page_raises(self):
        with self.assertRaises(ValueError):
            row_perm.canEditRow("browse", is_admin=True, is_manager=True,
                                dispatched=False, input_locked=False)


class TestIsDispatched(unittest.TestCase):
    """三態的邊界：只有『非空日期』算已發文。"""

    def test_none_is_not_dispatched(self):
        # 陳報的未發文、敘獎罰單的軟刪除空殼，都是 None
        self.assertFalse(row_perm.isDispatched(None))

    def test_empty_string_is_not_dispatched(self):
        # 敘獎罰單的未發文哨兵
        self.assertFalse(row_perm.isDispatched(""))

    def test_blank_string_is_not_dispatched(self):
        self.assertFalse(row_perm.isDispatched("   "))

    def test_real_date_is_dispatched(self):
        self.assertTrue(row_perm.isDispatched("2026-08-07"))


class TestIsLiveRow(unittest.TestCase):
    """『這列還在不在』逐頁不同——陳報不可用日期判斷。"""

    def test_entry_pages_use_register_date(self):
        for page in ("reward", "ticket"):
            self.assertEqual(row_perm.LIVE_COLUMN[page], "register_date")
            self.assertFalse(row_perm.isLiveRow(page, None))     # 軟刪除空殼
            self.assertTrue(row_perm.isLiveRow(page, ""))        # 未發文，仍有效
            self.assertTrue(row_perm.isLiveRow(page, "2026-08-07"))

    def test_report_pages_do_not_use_date_column(self):
        """⚠️ 這條是本計畫最初寫錯的地方：陳報未發文存 NULL，
        若拿日期欄判斷存活，所有未發文列都會被誤判成已刪除。"""
        for page in ("crim", "gen"):
            self.assertNotEqual(row_perm.LIVE_COLUMN[page],
                                row_perm.DATE_COLUMN[page])
            # 未發文（report_date 為 None）但主旨還在 → 仍是有效列
            self.assertTrue(row_perm.isLiveRow(page, "某某案件"))
            self.assertFalse(row_perm.isLiveRow(page, None))

    def test_task_pages_do_not_use_date_column(self):
        for page in ("dispatch", "task"):
            self.assertEqual(row_perm.LIVE_COLUMN[page], "subject")
            self.assertTrue(row_perm.isLiveRow(page, "某某交辦"))
            self.assertFalse(row_perm.isLiveRow(page, None))

    def test_live_sql_matches_live_column(self):
        """SQL 片段與 Python 判斷是同一條規則的兩種形態，不可各改各的。"""
        for page in row_perm.PAGES:
            self.assertEqual(row_perm.liveRowSql(page),
                             f"{row_perm.LIVE_COLUMN[page]} IS NOT NULL")


class TestSessionPreviewPrinciple(unittest.TestCase):
    """⚠️⚠️ 凌駕矩陣的原則（2026-08-07 維護者裁示）：

    **不管權限與設定怎麼調整，都不允許擋住「還在預覽列裡、剛登錄完」的資料的
    修改與刪除。唯一例外是交辦單發文。**

    ⚠️ 這是**改回開發初期的行為**，不是新規則。中途曾被改成「降權清空清單」
    與「已發文列鎖住一般使用者」，維護者當時即覺得不合理、事後還得花時間調回。
    本組測試就是為了讓那個改動再也回不來——**這幾條紅了不要改斷言，先問維護者**。
    """

    def test_every_role_can_always_mutate_session_preview_rows(self):
        for page in row_perm.SESSION_PREVIEW_PAGES:
            for role in ROLES:
                for dispatched in (False, True):
                    with self.subTest(page=page, role=role,
                                      dispatched=dispatched):
                        self.assertTrue(
                            _edit(page, role, dispatched=dispatched),
                            "預覽列的修改權限被擋住了")
                        self.assertTrue(
                            _delete(page, role, dispatched=dispatched),
                            "預覽列的刪除權限被擋住了")

    def test_issued_rows_are_not_locked_on_entry_pages(self):
        """送文者輸入模式登錄當下就寫入發文日期，該筆一送出即為「已發文」。

        承辦人打錯字必須當場自己改得掉——這正是原則要保住的情境。
        """
        for page in row_perm.ENTRY_PAGES:
            self.assertTrue(_edit(page, "user", dispatched=True))
            self.assertTrue(_delete(page, "user", dispatched=True))

    def test_readonly_lock_is_the_only_exception_and_freezes_everyone(self):
        """⚠️ 唯讀鎖是原則的**唯一例外**：三種身分一律不准動（含 admin）。

        唯讀的語意是「這個功能停用」，留任何改刪入口都與它衝突；要改資料就先
        到「資料庫設定 → 系統設定」把唯讀關掉（那個入口不受本鎖影響）。
        """
        for page in row_perm.SESSION_PREVIEW_PAGES:
            for role in ROLES:
                for dispatched in (False, True):
                    with self.subTest(page=page, role=role,
                                      dispatched=dispatched):
                        self.assertFalse(
                            _edit(page, role, dispatched=dispatched, locked=True))
                        self.assertFalse(
                            _delete(page, role, dispatched=dispatched, locked=True))

    def test_readonly_lock_also_freezes_dispatch_for_managers(self):
        """交辦單發文同樣一視同仁（原本管理身分不受唯讀影響，2026-08-07 改）。"""
        for role in ROLES:
            self.assertFalse(_edit("dispatch", role, dispatched=False, locked=True))

    def test_dispatch_is_the_only_exception(self):
        """交辦單發文除外——它的預覽列是掃入文號拉出來的**既有**公文，
        不是剛登錄的資料（見 `tab_dispatch.handleQuery`）。"""
        self.assertNotIn("dispatch", row_perm.SESSION_PREVIEW_PAGES)
        self.assertFalse(_edit("dispatch", "user", dispatched=True))

    def test_session_pages_cover_every_page_except_dispatch(self):
        self.assertEqual(set(row_perm.SESSION_PREVIEW_PAGES),
                         set(row_perm.PAGES) - {"dispatch"})


class TestDispatchPage(unittest.TestCase):
    """交辦單發文（計畫 §2.1）：未發文全開、已發文只有 admin。"""

    def test_undispatched_open_to_everyone(self):
        for role in ROLES:
            self.assertTrue(_edit("dispatch", role, dispatched=False))

    def test_dispatched_admin_only(self):
        self.assertTrue(_edit("dispatch", "admin", dispatched=True))
        # ⚠️ 歸檔管理也不能改已發文的交辦單——交辦單不在歸檔業務範圍內
        self.assertFalse(_edit("dispatch", "archive", dispatched=True))
        self.assertFalse(_edit("dispatch", "user", dispatched=True))

    def test_restricted_edit_follows_is_manager_not_is_admin(self):
        """一般使用者只能改承辦人；歸檔管理在未發文的單上可全改。"""
        self.assertTrue(row_perm.dispatchEditIsRestricted(is_manager=False))
        self.assertFalse(row_perm.dispatchEditIsRestricted(is_manager=True))

    def test_delete_is_not_supported(self):
        """✕ 是佇列移除、不碰 DB，恆啟用；接上權限矩陣就拋錯。"""
        with self.assertRaises(ValueError):
            _delete("dispatch", "user", dispatched=False)

    def test_full_matrix(self):
        for role in ROLES:
            for dispatched in (False, True):
                for locked in (False, True):
                    with self.subTest(role=role, dispatched=dispatched,
                                      locked=locked):
                        is_admin = ROLES[role]["is_admin"]
                        is_manager = ROLES[role]["is_manager"]
                        expected = (not locked
                                    and (is_admin or not dispatched))
                        self.assertEqual(
                            _edit("dispatch", role, dispatched=dispatched,
                                  locked=locked),
                            expected)


class TestProfileCoverage(unittest.TestCase):
    """兩支 exe：完整版五頁、獨立版只有敘獎＋罰單（計畫 §2.6）。"""

    def test_standalone_flows_are_covered(self):
        from lib.app_profile import ENTRY_PROFILE, FULL_PROFILE
        for page in ENTRY_PROFILE.input_lock_flows:
            self.assertIn(page, row_perm.PAGES)
        for page in FULL_PROFILE.input_lock_flows:
            self.assertIn(page, row_perm.PAGES)


if __name__ == "__main__":
    unittest.main()
