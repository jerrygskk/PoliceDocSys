# -*- coding: utf-8 -*-
"""三表新增鎖（唯讀設定）純邏輯測試。

兩層：
  1. db_utils 讀取層：INPUT_LOCK_KEYS／isInputLocked（App_Settings round-trip）
  2. InputLockMixin 行為層（收文/發文/陳報三頁共用的唯讀鎖定）：
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
        self.assertEqual(set(INPUT_LOCK_KEYS), {"dispatch", "task", "crim", "gen"})

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
    def __init__(self, kind, widgets, banner=None, clear=None):
        self.db_path = "dummy.db"
        self._tab_index = 3
        self._lock_kind = kind
        self._lock_widgets = widgets
        self._readonly_banner = banner
        self._lock_clear_tables = clear or []


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

    def test_manager_never_locked(self):
        w1, banner = _W(), _Banner()
        p = _Panel("task", [w1], banner)
        _apply(p, is_manager=True, locked_kinds={"task"})
        self.assertTrue(w1.enabled)
        self.assertFalse(banner.visible)

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


class TestRoleClearList(unittest.TestCase):
    def _clear(self, panel, is_manager):
        fake_am = mock.Mock()
        fake_am.instance.return_value.is_manager.return_value = is_manager
        with mock.patch("lib.auth_manager.AuthManager", fake_am):
            panel._onRoleClearList()

    def test_general_user_clears_tables(self):
        t1, t2 = _Table(), _Table()
        p = _Panel("task", [], clear=[t1, t2])
        self._clear(p, is_manager=False)
        self.assertEqual(t1.rows, 0)
        self.assertEqual(t2.rows, 0)

    def test_manager_keeps_tables(self):
        t1 = _Table()
        p = _Panel("task", [], clear=[t1])
        self._clear(p, is_manager=True)
        self.assertEqual(t1.rows, 5)


if __name__ == "__main__":
    unittest.main()
