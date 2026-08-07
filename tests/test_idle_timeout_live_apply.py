"""閒置逾時「存檔即時生效」的接線測試（暫存 sqlite，offscreen Qt）。

背景（踩雷）：分鐘數只在程式啟動時讀一次存進記憶體，設定頁存檔只寫 DB。
現場把自動登出從 1 分改成 10 分並按儲存後，正在跑的那支仍拿著舊的 1 分，
照樣一分鐘把人登出，看起來像存檔完全沒作用。

本檔釘住三件事：
  1. 面板存檔且值有變 → emit timeouts_changed；值沒變 → 不 emit
  2. DocumentManager.applyIdleTimeouts() 會重讀 DB 並重新起算兩個計時器
  3. 設為 0（停用）時計時器要停掉，且倒數橫幅要收掉
執行：專案根目錄下 `python -m unittest tests.test_idle_timeout_live_apply`
"""
import os
import sys
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from lib import db_schema
from lib.auth_manager import AuthManager
from lib.db_utils import setSetting, IDLE_TIMEOUT_KEYS
from ui_utils.settings_panels import IdleTimeoutPanel


def _app():
    return QApplication.instance() or QApplication([])


class _TimerStub:
    """只記錄被要求做什麼，不真的計時（測試不等真實逾時）。"""

    def __init__(self):
        self.started_with = None
        self.stopped = False

    def start(self, ms=None):
        self.started_with = ms
        self.stopped = False

    def stop(self):
        self.stopped = True


class _BannerStub:
    def __init__(self):
        self.visible = True

    def setVisible(self, v):
        self.visible = v


class _IdleTimeoutLiveBase(unittest.TestCase):
    def setUp(self):
        _app()
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        conn = sqlite3.connect(self.db_path)
        db_schema.applySchema(conn)
        conn.commit()
        conn.close()
        self._role = AuthManager.instance().current_role
        AuthManager.instance()._role = "admin"

    def tearDown(self):
        AuthManager.instance()._role = self._role
        if os.path.exists(self.db_path):
            os.remove(self.db_path)


class TestPanelEmits(_IdleTimeoutLiveBase):
    def _panel(self):
        p = IdleTimeoutPanel(self.db_path)
        self.addCleanup(p.deleteLater)
        return p

    def test_save_with_changed_values_emits(self):
        setSetting(self.db_path, IDLE_TIMEOUT_KEYS["logout"], "1")
        setSetting(self.db_path, IDLE_TIMEOUT_KEYS["close"], "5")
        p = self._panel()
        seen = []
        p.timeouts_changed.connect(lambda: seen.append(1))
        p.sp_logout.setValue(10)
        p.sp_close.setValue(14.5)
        self.assertTrue(p._save())
        self.assertEqual(len(seen), 1)

    def test_save_without_change_does_not_emit(self):
        setSetting(self.db_path, IDLE_TIMEOUT_KEYS["logout"], "10")
        setSetting(self.db_path, IDLE_TIMEOUT_KEYS["close"], "14.5")
        p = self._panel()
        seen = []
        p.timeouts_changed.connect(lambda: seen.append(1))
        self.assertTrue(p._save())
        self.assertEqual(seen, [])

    def test_rejected_save_does_not_emit(self):
        # 強制關閉須大於自動登出：擋下時不得 emit（否則主視窗會套到沒存進去的值）
        p = self._panel()
        seen = []
        p.timeouts_changed.connect(lambda: seen.append(1))
        p.sp_logout.setValue(10)
        p.sp_close.setValue(5.0)
        # 驗證失敗會跳提示框，測試環境不得真的開 modal（會卡住整包，PITFALLS TST-7）
        with patch("ui_utils.settings_panels.msgWarning") as warn:
            self.assertFalse(p._save())
        self.assertTrue(warn.called)
        self.assertEqual(seen, [])


class TestApplyIdleTimeouts(_IdleTimeoutLiveBase):
    def _mgr(self):
        from main import DocumentManager
        mgr = DocumentManager.__new__(DocumentManager)
        mgr.db_path = self.db_path
        mgr._IDLE_TIMEOUT_MS = 60 * 1000
        mgr._CLOSE_TIMEOUT_MS = 5 * 60 * 1000
        mgr._idle_timer = _TimerStub()
        mgr._close_timer = _TimerStub()
        mgr._countdown_timer = _TimerStub()
        mgr._idle_banner = _BannerStub()
        return mgr

    def test_new_values_restart_both_timers(self):
        setSetting(self.db_path, IDLE_TIMEOUT_KEYS["logout"], "10")
        setSetting(self.db_path, IDLE_TIMEOUT_KEYS["close"], "14.5")
        mgr = self._mgr()
        mgr.applyIdleTimeouts()
        self.assertEqual(mgr._IDLE_TIMEOUT_MS, 10 * 60000)
        self.assertEqual(mgr._CLOSE_TIMEOUT_MS, int(14.5 * 60000))
        # 自動登出：管理者身分 → 以新值重新起算，不是沿用舊的 1 分
        self.assertEqual(mgr._idle_timer.started_with, 10 * 60000)
        # 自動關閉：重設到「警示點」（總時限減警示段），並收掉倒數與橫幅
        self.assertEqual(mgr._close_timer.started_with,
                         int(14.5 * 60000) - mgr._CLOSE_WARN_MS)
        self.assertTrue(mgr._countdown_timer.stopped)
        self.assertFalse(mgr._idle_banner.visible)

    def test_zero_disables_and_hides_banner(self):
        setSetting(self.db_path, IDLE_TIMEOUT_KEYS["logout"], "0")
        setSetting(self.db_path, IDLE_TIMEOUT_KEYS["close"], "0")
        mgr = self._mgr()
        mgr.applyIdleTimeouts()
        self.assertTrue(mgr._idle_timer.stopped)
        self.assertTrue(mgr._close_timer.stopped)
        self.assertTrue(mgr._countdown_timer.stopped)
        self.assertFalse(mgr._idle_banner.visible)

    def test_general_user_never_gets_logout_timer(self):
        # 自動登出僅管理者／歸檔管理計時（與事件過濾器同一條件）
        setSetting(self.db_path, IDLE_TIMEOUT_KEYS["logout"], "10")
        AuthManager.instance()._role = "user"
        mgr = self._mgr()
        mgr.applyIdleTimeouts()
        self.assertTrue(mgr._idle_timer.stopped)
        self.assertIsNone(mgr._idle_timer.started_with)


if __name__ == "__main__":
    unittest.main()
