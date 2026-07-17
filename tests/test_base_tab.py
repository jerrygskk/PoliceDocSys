"""BaseTab 共用 helper 的回歸測試。

重點：_trimName 已收斂至 archive_text._trimName（單一來源），
原本 base_tab 只處理半形 -，不處理全形 －，導致全形破折號的人名去尾失敗。
"""
import unittest

from lib.base_tab import BaseTab
from lib.archive_text import _trimName as archive_trimName


class TestBaseTabTrimName(unittest.TestCase):

    def test_half_width_suffix(self):
        self.assertEqual(BaseTab._trimName("王小明-01"), "王小明")

    def test_full_width_suffix(self):
        # 修正前的 base_tab 版本只切半形 -，全形 － 會原樣留下
        self.assertEqual(BaseTab._trimName("李美華－19.06"), "李美華")

    def test_no_suffix(self):
        self.assertEqual(BaseTab._trimName("陳志明"), "陳志明")

    def test_empty_and_none(self):
        self.assertEqual(BaseTab._trimName(""), "")
        self.assertEqual(BaseTab._trimName(None), "")

    def test_delegates_to_archive_text(self):
        # 單一來源：兩者行為一致
        for s in ("王小明-01", "李美華－19.06", "陳志明", " 王小明 -01", "", None):
            self.assertEqual(BaseTab._trimName(s), archive_trimName(s))


class TestBaseTabFmtDate(unittest.TestCase):
    """_fmtDate：YYYY-MM-DD → MM-DD-YYYY（僅預覽顯示用）。"""

    def test_normal(self):
        self.assertEqual(BaseTab._fmtDate("2026-06-28"), "06-28-2026")

    def test_empty_and_none(self):
        self.assertEqual(BaseTab._fmtDate(""), "")
        self.assertEqual(BaseTab._fmtDate(None), "")

    def test_bad_format_returns_original(self):
        # 解析不了就原樣回傳字串，不拋例外
        self.assertEqual(BaseTab._fmtDate("2026/06/28"), "2026/06/28")
        self.assertEqual(BaseTab._fmtDate("abc"), "abc")


class _FakeLabel:
    def __init__(self, html):
        self._html = html
    def text(self):
        return self._html


class TestBaseTabDocIdFromLabel(unittest.TestCase):
    """_docIdFromLabel：從 QLabel 的 HTML 取 href 中的 doc_id。"""

    def test_extracts_href(self):
        lbl = _FakeLabel('<a href="765" style="color:#000">765</a>')
        self.assertEqual(BaseTab._docIdFromLabel(lbl), "765")

    def test_no_href_returns_none(self):
        self.assertIsNone(BaseTab._docIdFromLabel(_FakeLabel("純文字 765")))

    def test_none_label_returns_none(self):
        self.assertIsNone(BaseTab._docIdFromLabel(None))


if __name__ == "__main__":
    unittest.main()
