# -*- coding: utf-8 -*-
"""資料庫瀏覽頁「近期」篩選（罰單／敘獎子頁）測試（offscreen）。

保護對象：
  - 純邏輯：recentCutoff 的視窗邊界（含今天共 14 天）、isRecentRow 的空白日期退路。
  - 預設啟用：進頁只看得到近兩週登錄的列，舊列被藏起（不是被刪）。
  - 關鍵字優先：打字查詢時一律涵蓋全部期間，避免「明明有卻搜不到」。
  - 適用範圍：只有罰單／敘獎有這顆鈕，其餘三個子頁不受影響。

人名一律虛構（push 前有 test_no_pii 掃真名）。
"""
import os
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QTabWidget, QWidget

import res.resources_rc  # noqa: F401  資源（icon）註冊，_fillRow 會用到 :/icon_pdf.svg
from lib.auth_manager import AuthManager
from lib.db_schema import applySchema
from tabs.tab_dbbrowse import (
    RECENT_DAYS, TABLE_META, TabDBBrowse, isRecentRow, recentCutoff,
)

_app = QApplication.instance() or QApplication([])


def _iso(days_ago):
    return (date.today() - timedelta(days=days_ago)).isoformat()


class TestRecentPureLogic(unittest.TestCase):
    """日期視窗計算與單列判定，不碰 Qt。"""

    def test_cutoff_includes_today_and_spans_14_days(self):
        self.assertEqual(RECENT_DAYS, 14)
        self.assertEqual(recentCutoff("2026-08-14"), "2026-08-01")

    def test_cutoff_crosses_month_boundary(self):
        # 跨月：不可用「同月減 13」這種算法
        self.assertEqual(recentCutoff("2026-03-05"), "2026-02-20")

    def test_boundary_day_is_inside_window(self):
        today = "2026-08-14"
        cut = recentCutoff(today)
        self.assertTrue(isRecentRow({"create_date": "2026-08-01"}, "create_date", cut, today))
        self.assertFalse(isRecentRow({"create_date": "2026-07-31"}, "create_date", cut, today))

    def test_today_is_inside_but_future_dates_are_not(self):
        """登錄日期在編輯彈窗可改且未擋未來日期：誤打成明年的列不得永遠賴在近期。"""
        today = "2026-08-14"
        cut = recentCutoff(today)
        self.assertTrue(isRecentRow({"create_date": today}, "create_date", cut, today))
        for future in ("2026-08-15", "2026-09-01", "2027-01-01"):
            self.assertFalse(
                isRecentRow({"create_date": future}, "create_date", cut, today),
                f"未來日期 {future} 不該算近期")

    def test_blank_date_is_never_hidden(self):
        """舊資料可能缺登錄日期，靜默藏起會讓使用者以為資料不見了。"""
        today = "2026-08-14"
        cut = recentCutoff(today)
        for val in ("", "   ", None):
            self.assertTrue(isRecentRow({"create_date": val}, "create_date", cut, today))
        self.assertTrue(isRecentRow({}, "create_date", cut, today))
        self.assertTrue(isRecentRow(None, "create_date", cut, today))


class _RecentBrowseBase(unittest.TestCase):
    """罰單子頁：一筆近期（今天）、一筆過期（40 天前）。"""

    def setUp(self):
        fd, self.db = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        conn = sqlite3.connect(self.db)
        applySchema(conn)
        conn.execute(
            "INSERT INTO Ref_Personnel(staff_id,staff_name,is_active,sort_order) "
            "VALUES ('P01','測試員甲',1,1)")
        conn.executemany(
            "INSERT INTO Document_Ticket(doc_id,create_date,register_date,"
            "sender_id,issuer_id,ticket_no) VALUES (?,?,?,?,?,?)",
            [("1", _iso(40), _iso(40), "P01", "P01", "OLD111111"),
             ("2", _iso(0),  _iso(0),  "P01", "P01", "NEW222222"),
             # 誤打成未來日期（編輯彈窗沒擋）：不該被當成近期
             ("3", _iso(-5), _iso(-5), "P01", "P01", "FUTURE333")])
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

    def _make_browse(self, role="admin"):
        AuthManager.instance()._role = role
        tabs = QTabWidget()
        tabs.addTab(QWidget(), "瀏覽")
        self._extra_tabs.append(tabs)
        tab = TabDBBrowse(tabs, self.db)
        tab.setup(0)
        tab.buildInitial("ticket")
        return tab

    def _visible_ids(self, tab, key="ticket"):
        table = tab._ui[key]["table"]
        order = tab._docorder[key]
        return [order[r] for r in range(table.rowCount())
                if not table.isRowHidden(r)]


class TestRecentFilterBehaviour(_RecentBrowseBase):

    def test_meta_registers_recent_column(self):
        for key in ("ticket", "reward"):
            self.assertEqual(TABLE_META[key]["recent_date_col"], "create_date")

    def test_default_on_shows_only_rows_inside_the_window(self):
        tab = self._make_browse()
        self.assertTrue(tab._ui["ticket"]["recent"].isChecked())
        self.assertEqual(self._visible_ids(tab), ["2"])   # 舊的與未來的都不算近期
        # 只是被藏起、不是被移除（關掉就該回來）
        self.assertEqual(tab._ui["ticket"]["table"].rowCount(), 3)

    def test_toggle_off_shows_everything(self):
        tab = self._make_browse()
        tab._ui["ticket"]["recent"].setChecked(False)
        self.assertEqual(self._visible_ids(tab), ["1", "2", "3"])

    def test_keyword_search_ignores_recent_window(self):
        """打字查詢必須查得到兩週前的罰單，否則使用者會以為資料不存在。"""
        tab = self._make_browse()
        tab._ui["ticket"]["kw"].setText("OLD111111")
        tab._applyFilter("ticket")
        self.assertTrue(tab._ui["ticket"]["recent"].isChecked())
        self.assertEqual(self._visible_ids(tab), ["1"])

    def test_window_uses_current_date_not_a_stale_cache(self):
        """程式常整天開著：跨過午夜後仍用昨天的視窗算，今天登錄的反而被當成未來。

        以「上次載入時留下的昨日快取」模擬跨午夜，今天登錄的列必須仍看得到。"""
        tab = self._make_browse()
        tab._today_cache = _iso(1)          # 昨天（跨午夜後的殘留值）
        tab._applyRowVisibility("ticket")
        self.assertIn("2", self._visible_ids(tab))

    def test_footer_marks_the_window(self):
        tab = self._make_browse()
        self.assertIn("近兩週", tab._ui["ticket"]["count"].text())
        tab._ui["ticket"]["recent"].setChecked(False)
        self.assertNotIn("近兩週", tab._ui["ticket"]["count"].text())

    def test_recent_and_unissued_are_intersected(self):
        tab = self._make_browse()
        tab._ui["ticket"]["overdue"].setChecked(True)   # 兩筆皆已發文
        self.assertEqual(self._visible_ids(tab), [])

    def test_only_registration_pages_have_the_button(self):
        tab = self._make_browse()
        for key in ("ticket", "reward"):
            self.assertIsNotNone(tab._ui[key]["recent"])
            self.assertIn(key, tab._sticky)      # 黏底捲動同樣只套這兩頁
        for key in ("task", "crim", "gen"):
            self.assertIsNone(tab._ui[key]["recent"])
            self.assertNotIn(key, tab._sticky)


if __name__ == "__main__":
    unittest.main()
