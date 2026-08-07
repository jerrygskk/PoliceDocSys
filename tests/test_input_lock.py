# -*- coding: utf-8 -*-
"""輸入流程唯讀設定純邏輯測試。

兩層：
  1. db_utils 讀取層：INPUT_LOCK_KEYS／isInputLocked（App_Settings round-trip）
  2. InputLockMixin 行為層（各輸入／發文頁共用的唯讀鎖定）：
     鎖種類解析（str / callable）、依身分＋isInputLocked 決定反灰/橫幅、
     dict 版（陳報頁依模式取用當前那組）、登出清單。
     以 stub 元件＋monkeypatch AuthManager／isInputLocked，不需真的開 Qt 視窗。
"""
import os, sqlite3, tempfile, unittest
from unittest import mock

from lib.db_utils import INPUT_LOCK_KEYS, isInputLocked, setSetting
from lib.base_tab import InputLockMixin


class TestInputLock(unittest.TestCase):
    def setUp(self):
        fd, self.db = tempfile.mkstemp(suffix=".db"); os.close(fd)
        conn = sqlite3.connect(self.db)
        conn.execute("CREATE TABLE App_Settings (key TEXT PRIMARY KEY, value TEXT)")
        conn.commit(); conn.close()

    def tearDown(self):
        os.remove(self.db)

    def test_keys_present(self):
        self.assertEqual(set(INPUT_LOCK_KEYS),
                         {"dispatch", "task", "crim", "gen", "ticket",
                          "reward"})

    def test_ticket_and_reward_lock_keys_present(self):
        self.assertEqual(INPUT_LOCK_KEYS["ticket"], "input_lock_ticket")
        self.assertEqual(INPUT_LOCK_KEYS["reward"], "input_lock_reward")

    def test_ticket_and_reward_round_trip(self):
        # 走正式設定 API（無 setInputLocked helper，設定面板本身以 setSetting 寫入）。
        setSetting(self.db, INPUT_LOCK_KEYS["ticket"], "1")
        setSetting(self.db, INPUT_LOCK_KEYS["reward"], "1")
        self.assertTrue(isInputLocked(self.db, "ticket"))
        self.assertTrue(isInputLocked(self.db, "reward"))
        # 兩把鎖互相獨立
        setSetting(self.db, INPUT_LOCK_KEYS["ticket"], "")
        self.assertFalse(isInputLocked(self.db, "ticket"))
        self.assertTrue(isInputLocked(self.db, "reward"))

    def test_removed_reward_issue_kind_is_unknown(self):
        """敘獎發文頁已移除：舊 key 殘留在資料庫也不得再被視為一把鎖。"""
        self.assertNotIn("reward_issue", INPUT_LOCK_KEYS)
        setSetting(self.db, "input_lock_reward_issue", "1")
        self.assertFalse(isInputLocked(self.db, "reward_issue"))
        self.assertFalse(isInputLocked(self.db, "reward"))

    def test_ticket_and_reward_zero_and_junk_are_unlocked(self):
        for kind in ("ticket", "reward"):
            setSetting(self.db, INPUT_LOCK_KEYS[kind], "0")
            self.assertFalse(isInputLocked(self.db, kind))
            setSetting(self.db, INPUT_LOCK_KEYS[kind], "x")
            self.assertFalse(isInputLocked(self.db, kind))

    def test_dispatch_key_independent(self):
        setSetting(self.db, INPUT_LOCK_KEYS["dispatch"], "1")
        self.assertTrue(isInputLocked(self.db, "dispatch"))
        self.assertFalse(isInputLocked(self.db, "task"))

    def test_default_unlocked(self):
        for kind in INPUT_LOCK_KEYS:
            self.assertFalse(isInputLocked(self.db, kind))

    def test_locked_when_one(self):
        setSetting(self.db, INPUT_LOCK_KEYS["task"], "1")
        self.assertTrue(isInputLocked(self.db, "task"))
        self.assertFalse(isInputLocked(self.db, "crim"))

    def test_zero_and_junk_are_unlocked(self):
        setSetting(self.db, INPUT_LOCK_KEYS["gen"], "0")
        self.assertFalse(isInputLocked(self.db, "gen"))
        setSetting(self.db, INPUT_LOCK_KEYS["gen"], "x")
        self.assertFalse(isInputLocked(self.db, "gen"))

    def test_unknown_kind_is_false(self):
        self.assertFalse(isInputLocked(self.db, "nope"))


# ── InputLockMixin 行為層 ────────────────────────────────────────────

class _W:
    """假可反灰元件。"""
    def __init__(self):
        self.enabled = True

    def setEnabled(self, v):
        self.enabled = v


class _Banner:
    def __init__(self):
        self.visible = None

    def setVisible(self, v):
        self.visible = v


class _Table:
    def __init__(self):
        self.rows = 5

    def setRowCount(self, n):
        self.rows = n


class _Panel(InputLockMixin):
    """裸持有 mixin 需要的屬性，不繼承 BaseTab（避免要 Qt）。"""
    def __init__(self, kind, widgets, banner=None, refresh=None):
        self.db_path = "dummy.db"
        self._tab_index = 3
        self._lock_kind = kind
        self._lock_widgets = widgets
        self._readonly_banner = banner
        self._lock_refresh_tables = refresh or []
        self.refreshed_with = None

    def _refreshRowPermissions(self, tables):
        """記下 hook 有沒有被呼叫、拿到哪些表（不動列數）。"""
        self.refreshed_with = tables


def _apply(panel, *, is_manager, locked_kinds):
    fake_am = mock.Mock()
    fake_am.instance.return_value.is_manager.return_value = is_manager
    with mock.patch("lib.auth_manager.AuthManager", fake_am), \
         mock.patch("lib.db_utils.isInputLocked",
                    lambda db, k: k in locked_kinds):
        panel._applyInputLock()


class TestResolveLockKind(unittest.TestCase):
    def test_str_kind(self):
        p = _Panel("task", [])
        self.assertEqual(p._resolveLockKind(), "task")

    def test_callable_kind(self):
        p = _Panel(lambda: "gen", [])
        self.assertEqual(p._resolveLockKind(), "gen")


class TestApplyInputLockList(unittest.TestCase):
    """list 版（收文/發文）。"""

    def test_locked_general_user_disables_and_shows_banner(self):
        w1, w2, banner = _W(), _W(), _Banner()
        p = _Panel("task", [w1, w2], banner)
        _apply(p, is_manager=False, locked_kinds={"task"})
        self.assertFalse(w1.enabled)
        self.assertFalse(w2.enabled)
        self.assertTrue(banner.visible)

    def test_manager_is_locked_too(self):
        """⚠️ 2026-08-07 起唯讀對**三種身分**一律生效（原本管理身分豁免）。

        唯讀＝這個功能停用，不分身分；要改資料就先到「資料庫設定 → 系統設定」
        把唯讀關掉（那個入口不受本鎖影響）。全專案六支硬 gate 同步改。
        """
        w1, banner = _W(), _Banner()
        p = _Panel("task", [w1], banner)
        _apply(p, is_manager=True, locked_kinds={"task"})
        self.assertFalse(w1.enabled)
        self.assertTrue(banner.visible)

    def test_unlocked_kind_stays_editable(self):
        w1, banner = _W(), _Banner()
        p = _Panel("task", [w1], banner)
        _apply(p, is_manager=False, locked_kinds={"crim"})  # 別的表鎖、task 沒鎖
        self.assertTrue(w1.enabled)
        self.assertFalse(banner.visible)


class TestApplyInputLockDict(unittest.TestCase):
    """dict 版（陳報頁依當前模式只鎖對應那組）。"""

    def test_only_current_kind_widgets_toggled(self):
        crim_w, gen_w, banner = _W(), _W(), _Banner()
        widgets = {"crim": [crim_w], "gen": [gen_w]}
        # 當前模式＝crim，且 crim 被鎖
        p = _Panel(lambda: "crim", widgets, banner)
        _apply(p, is_manager=False, locked_kinds={"crim"})
        self.assertFalse(crim_w.enabled)     # 當前模式反灰
        self.assertTrue(gen_w.enabled)       # 另一模式不受影響
        self.assertTrue(banner.visible)

    def test_switch_to_unlocked_mode_reenables(self):
        crim_w, gen_w, banner = _W(), _W(), _Banner()
        widgets = {"crim": [crim_w], "gen": [gen_w]}
        # 當前模式＝gen，只有 crim 被鎖 → gen 可填、橫幅隱藏
        p = _Panel(lambda: "gen", widgets, banner)
        _apply(p, is_manager=False, locked_kinds={"crim"})
        self.assertTrue(gen_w.enabled)
        self.assertFalse(banner.visible)


class TestRoleRefresh(unittest.TestCase):
    """⚠️ 2026-08-07 起降權**不再清空預覽清單**，改為呼叫逐列重刷 hook。

    原本的斷言是「降權把表清成 0 列」，那是把資料庫瀏覽頁的規則錯套到登錄／
    收發文頁上——這些頁對三種身分都開放刪改，清空等於讓一般使用者失去他本來
    就有的入口。
    """

    def _refresh(self, panel, is_manager):
        fake_am = mock.Mock()
        fake_am.instance.return_value.is_manager.return_value = is_manager
        with mock.patch("lib.auth_manager.AuthManager", fake_am):
            panel._onRoleRefresh()

    def test_general_user_triggers_refresh_without_touching_rows(self):
        t1, t2 = _Table(), _Table()
        p = _Panel("task", [], refresh=[t1, t2])
        self._refresh(p, is_manager=False)
        self.assertEqual(p.refreshed_with, [t1, t2])
        self.assertEqual(t1.rows, 5)     # 列數不動
        self.assertEqual(t2.rows, 5)

    def test_manager_skips_refresh(self):
        """管理身分 early return：升權由 on_activated 整份重刷，
        唯讀凍結又只鎖一般使用者，故不會漏鎖任何情境。"""
        t1 = _Table()
        p = _Panel("task", [], refresh=[t1])
        self._refresh(p, is_manager=True)
        self.assertIsNone(p.refreshed_with)
        self.assertEqual(t1.rows, 5)

    def test_default_hook_is_a_noop(self):
        """沒實作 hook 的頁不會壞（預設 no-op）。"""
        panel = InputLockMixin()
        self.assertIsNone(panel._refreshRowPermissions([]))


if __name__ == "__main__":
    unittest.main()
